"""Turn a model's SQL into a plain-English story.

This is deterministic: it reads the SQL structure with sqlglot and describes
it. It needs no network access and no AI model, so it is fast, free, and gives
the same answer every time. An optional AI rewrite can be layered on top later.

The SQL comes from ``sql_source.readable_sql``: dbt's compiled code when the
project was loaded from a manifest, otherwise the raw file with its Jinja
simplified. Columns are followed through CTEs, subqueries and ``select *``, so
every output column says where it was actually worked out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlglot import exp

from openpipeline_core.describe import describe, describe_expr, is_predicate, join_words
from openpipeline_core.models import Node, NodeKind, Project
from openpipeline_core.sql_source import ReadableSQL, RelationIndex, readable_sql

if TYPE_CHECKING:
    from openpipeline_core.lineage import ColumnLineage

_MAX_SUBQUERY_DEPTH = 5
_PASSED = "passed through"
_MAX_CALCULATED_IN_SUMMARY = 4


class ColumnStory(BaseModel):
    name: str
    how: str
    from_step: str | None = None
    """The CTE where this column was worked out. ``None`` for the final select or a pass-through."""


class ModelStory(BaseModel):
    model: str
    description: str = ""
    summary: str
    steps: list[str] = Field(default_factory=list)
    reads_from: list[str] = Field(default_factory=list)
    columns: list[ColumnStory] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    grain: list[str] = Field(default_factory=list)
    """Columns that make a row unique, when the model groups its data."""
    parse_error: str | None = None


def explain_model(
    project: Project,
    name_or_id: str,
    *,
    dialect: str | None = None,
    lineage: ColumnLineage | None = None,
) -> ModelStory:
    """Explain one model. ``lineage`` (optional) supplies upstream columns for ``select *``."""
    node = project.get(name_or_id)
    if node is None:
        raise KeyError(f"No model named {name_or_id!r}")

    reads_from = [project.nodes[d].name for d in node.depends_on if d in project.nodes]
    if node.kind != NodeKind.MODEL or not (node.raw_sql.strip() or node.compiled_sql.strip()):
        what = "source table" if node.kind == NodeKind.SOURCE else node.kind.value
        return ModelStory(
            model=node.name,
            description=node.description,
            summary=node.description or f"{node.name} is a {what}.",
            reads_from=reads_from,
        )

    ctx = _Ctx(project, dialect, lineage)
    readable = _read(ctx, node)
    if readable.tree is None:
        return ModelStory(
            model=node.name,
            description=node.description,
            summary=node.description or f"{node.name} reads from {_join(reads_from)}.",
            reads_from=reads_from,
            parse_error=readable.error or "Could not read the SQL",
        )

    steps, final, filters = _analyze(ctx, readable.tree)
    columns = final.columns if final is not None else []
    grain = final.grain if final is not None else []
    return ModelStory(
        model=node.name,
        description=node.description,
        summary=_summary(node.name, reads_from, grain, columns),
        steps=steps,
        reads_from=reads_from,
        columns=columns,
        filters=filters,
        grain=grain,
    )


def _arg(e: exp.Expr, key: str) -> exp.Expr | None:
    """Read ``from``/``with``. sqlglot 30 renamed these keys with a trailing underscore."""
    value = e.args.get(f"{key}_", e.args.get(key))
    return value if isinstance(value, exp.Expr) else None


# --- Context and intermediate results ------------------------------------------


class _Ctx:
    def __init__(
        self,
        project: Project,
        dialect: str | None,
        lineage: ColumnLineage | None,
        *,
        shallow: bool = False,
    ) -> None:
        self.project = project
        self.dialect = dialect
        self.lineage = lineage
        self.shallow = shallow
        """Shallow contexts take upstream columns from lineage or docs only, never by reading
        the upstream SQL, so reading upstream models goes one level deep at most."""
        self.index = RelationIndex(project)
        self.by_table: dict[str, str] = {}
        self.by_source: dict[str, str] = {}
        for uid, node in project.nodes.items():
            if node.kind == NodeKind.SOURCE:
                self.by_source.setdefault(node.name, uid)
            else:
                self.by_table.setdefault(node.name, uid)
        self.memo: dict[str, list[str] | None] = {}

    def shallow_copy(self) -> _Ctx:
        other = _Ctx.__new__(_Ctx)
        other.__dict__.update(self.__dict__)
        other.shallow = True
        other.memo = {}
        return other

    def resolve(self, table: exp.Table) -> str | None:
        """Same rules as ``ColumnLineage._resolve_table``."""
        if table.catalog:
            return None
        if table.db:
            return self.by_source.get(f"{table.db}.{table.name}")
        return self.by_table.get(table.name)


@dataclass
class _Source:
    """One thing a select reads from: a CTE, a node's table, or a subquery."""

    alias: str
    label: str
    columns: list[ColumnStory] | None
    """Known columns (may hold a ``*`` entry when only some are known), or ``None``."""
    origin: str
    """Name to use in "passed through from ...", e.g. the upstream model."""
    star_origins: list[str] = field(default_factory=list)


@dataclass
class _Result:
    columns: list[ColumnStory] = field(default_factory=list)
    star_origins: list[str] = field(default_factory=list)
    grain: list[str] = field(default_factory=list)
    desc: str = ""
    filters: list[str] = field(default_factory=list)
    plain_star_from: str | None = None
    """Set when the select is just ``select * from X`` with nothing else."""
    reads_table: bool = False
    """Whether ``plain_star_from`` is a table (not a subquery)."""


class _Cols:
    """Output columns in order, with star handling and name de-duplication."""

    def __init__(self) -> None:
        self.items: list[ColumnStory] = []
        self.index: dict[str, int] = {}
        self.star_origins: list[str] = []

    def add_star(self, origins: list[str]) -> None:
        for o in origins:
            if o not in self.star_origins:
                self.star_origins.append(o)
        if "*" not in self.index:
            self.index["*"] = len(self.items)
            self.items.append(ColumnStory(name="*", how=""))

    def add(self, col: ColumnStory, *, from_star: bool = False) -> None:
        key = col.name.lower()
        if key in self.index:
            if not from_star:
                self.items[self.index[key]] = col
            return
        self.index[key] = len(self.items)
        self.items.append(col)

    def finish(self) -> list[ColumnStory]:
        if "*" in self.index:
            self.items[self.index["*"]].how = "every column from " + join_words(self.star_origins)
        return self.items


# --- Walking the query ------------------------------------------------------------


def _analyze(ctx: _Ctx, tree: exp.Expr) -> tuple[list[str], _Result | None, list[str]]:
    env: dict[str, _Result] = {}
    steps: list[str] = []
    filters: list[str] = []
    with_ = _arg(tree, "with")
    if with_ is not None:
        for cte in with_.expressions:
            if not isinstance(cte, exp.CTE):
                continue
            name = cte.alias or "step"
            res = _body(ctx, cte.this, env, name, 0)
            env[name.lower()] = res
            if res.plain_star_from is not None and res.reads_table:
                steps.append(f"Reads {res.plain_star_from}.")
            else:
                shown = f"{_pretty(name)} (an ephemeral model)" if name != _pretty(name) else name
                steps.append(f"Builds a step called {shown}: {res.desc}")
            filters.extend(res.filters)
    final = _body(ctx, tree, env, None, 0)
    if final.plain_star_from is not None:
        steps.append(f"Final result: everything from {final.plain_star_from}.")
    else:
        steps.append(f"Final result: {final.desc}")
    filters.extend(final.filters)
    return steps, final, list(dict.fromkeys(filters))


def _with_env(ctx: _Ctx, q: exp.Expr, env: dict[str, _Result], depth: int) -> dict[str, _Result]:
    """``env`` extended with the CTEs declared on ``q`` (for subqueries)."""
    with_ = _arg(q, "with")
    if with_ is None:
        return env
    out = dict(env)
    for cte in with_.expressions:
        if isinstance(cte, exp.CTE) and cte.alias:
            out[cte.alias.lower()] = _body(ctx, cte.this, out, cte.alias, depth)
    return out


def _body(ctx: _Ctx, q: exp.Expr, env: dict[str, _Result], step: str | None, depth: int) -> _Result:
    """Analyse a SELECT, a set operation or a parenthesised query."""
    while isinstance(q, (exp.Subquery, exp.Paren)):
        q = q.this
    set_op = getattr(exp, "SetOperation", exp.Union)
    if isinstance(q, set_op):
        branches = _branches(q)
        first = _body(ctx, branches[0], env, step, depth)
        word = {"Union": "stacks", "Intersect": "keeps rows found in all of", "Except": "removes"}
        verb = word.get(type(q).__name__, "combines")
        first.desc = f"{verb} the results of {len(branches)} queries."
        first.grain = []
        first.plain_star_from = None
        return first
    if not isinstance(q, exp.Select):
        inner = q.find(exp.Select)
        if inner is None:
            return _Result(desc="runs a statement we cannot describe.")
        q = inner
    return _select(ctx, q, env, step, depth)


def _branches(q: exp.Expr) -> list[exp.Expr]:
    set_op = getattr(exp, "SetOperation", exp.Union)
    if isinstance(q, set_op):
        return [*_branches(q.left), *_branches(q.right)]
    return [q]


def _select(
    ctx: _Ctx, sel: exp.Select, env: dict[str, _Result], step: str | None, depth: int
) -> _Result:
    env = _with_env(ctx, sel, env, depth)
    from_ = _arg(sel, "from")
    joins = list(sel.args.get("joins") or [])
    items: list[exp.Expr] = ([from_.this] if from_ is not None else []) + [j.this for j in joins]
    sources = [_source(ctx, item, env, depth) for item in items]

    group_keys = _group_keys(sel)
    cols = _Cols()
    for position, e in enumerate(sel.expressions):
        inner = e.this if isinstance(e, exp.Alias) else e
        if isinstance(inner, exp.Star) or (
            isinstance(inner, exp.Column) and isinstance(inner.this, exp.Star)
        ):
            _expand_star(inner, sources, cols)
            continue
        name = e.alias_or_name or _sql_name(inner, position)
        cols.add(_column_story(name, inner, sources, step, group_keys))
    columns = cols.finish()

    result = _Result(columns=columns, star_origins=cols.star_origins)
    result.grain = group_keys or _inherited_grain(sel, sources, env, columns)
    result.desc = _describe_select(sel, items, group_keys)
    where = sel.args.get("where")
    if where is not None:
        result.filters.append(describe(where.this))
    having = sel.args.get("having")
    if having is not None:
        result.filters.append(f"{describe(having.this)} (after grouping)")
    if _is_plain_star(sel, from_, joins) and from_ is not None:
        result.plain_star_from = _item_label(from_.this)
        result.reads_table = isinstance(from_.this, exp.Table)
    return result


_EPHEMERAL_PREFIX = "__dbt__cte__"
"""dbt inlines an ephemeral model as a CTE with this prefix."""


def _pretty(name: str) -> str:
    return name.removeprefix(_EPHEMERAL_PREFIX)


def _item_label(item: exp.Expr) -> str:
    if isinstance(item, exp.Table):
        return _pretty(".".join(p for p in (item.db, item.name) if p))
    if isinstance(item, exp.Subquery):
        return "a subquery"
    return describe(item)


def _is_plain_star(sel: exp.Select, from_: exp.Expr | None, joins: list[exp.Expr]) -> bool:
    if from_ is None or joins or len(sel.expressions) != 1:
        return False
    only = sel.expressions[0]
    if not (isinstance(only, exp.Star) or (isinstance(only, exp.Column) and only.is_star)):
        return False
    if isinstance(only, exp.Star) and (only.args.get("except_") or only.args.get("replace")):
        return False
    return not any(
        sel.args.get(k)
        for k in ("where", "group", "having", "qualify", "distinct", "limit", "order", "windows")
    )


def _source(ctx: _Ctx, item: exp.Expr, env: dict[str, _Result], depth: int) -> _Source:
    if isinstance(item, exp.Table) and isinstance(item.this, exp.Identifier):
        low = item.name.lower()
        if not item.db and not item.catalog and low in env:
            res = env[low]
            origin = join_words(res.star_origins) if res.star_origins else item.name
            return _Source(
                item.alias_or_name, item.name, list(res.columns), origin, list(res.star_origins)
            )
        uid = ctx.resolve(item)
        label = _item_label(item)
        if uid is not None:
            node = ctx.project.nodes[uid]
            names = _node_columns(ctx, uid)
            columns = (
                [ColumnStory(name=c, how=f"{_PASSED} from {node.name}") for c in names]
                if names
                else None
            )
            return _Source(item.alias_or_name, label, columns, node.name, [node.name])
        return _Source(item.alias_or_name, label, None, label, [label])
    if isinstance(item, exp.Subquery) and depth < _MAX_SUBQUERY_DEPTH:
        res = _body(ctx, item.this, env, None, depth + 1)
        return _Source(
            item.alias_or_name, "a subquery", list(res.columns), "a subquery", res.star_origins
        )
    label = _item_label(item)
    return _Source(getattr(item, "alias_or_name", "") or label, label, None, label, [label])


def _fingerprint(project: Project, node: Node, dialect: str | None) -> int:
    return hash((node.compiled_sql, node.raw_sql, project.adapter, dialect))


def _read(ctx: _Ctx, node: Node) -> ReadableSQL:
    """``readable_sql`` with the parsed tree kept on the project. Stories never edit it."""
    cache = ctx.project.scratch()
    key = f"read:{node.unique_id}"
    stamp = _fingerprint(ctx.project, node, ctx.dialect)
    hit = cache.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]  # type: ignore[no-any-return]
    readable = readable_sql(ctx.project, node, ctx.dialect, index=ctx.index)
    cache[key] = (stamp, readable)
    return readable


def _node_columns(ctx: _Ctx, uid: str) -> list[str] | None:
    """Column names of an upstream node: lineage, else its own story, else its docs."""
    if uid in ctx.memo:
        return ctx.memo[uid]
    node = ctx.project.nodes.get(uid)
    result: list[str] | None = None
    if ctx.lineage is not None:
        known = ctx.lineage.columns(uid)
        if known:
            result = known
    if (
        result is None
        and not ctx.shallow
        and node is not None
        and node.kind in (NodeKind.MODEL, NodeKind.SNAPSHOT)
        and (node.raw_sql.strip() or node.compiled_sql.strip())
    ):
        result = _story_column_names(ctx, node)
    if result is None and node is not None and node.columns:
        result = [c.name for c in node.columns]
    ctx.memo[uid] = result
    return result


def _story_column_names(ctx: _Ctx, node: Node) -> list[str] | None:
    """Output columns of ``node`` read from its own SQL (its parents via lineage or docs)."""
    cache = ctx.project.scratch()
    key = f"names:{node.unique_id}"
    stamp = _fingerprint(ctx.project, node, ctx.dialect)
    hit = cache.get(key) if ctx.lineage is None else None
    if hit is not None and hit[0] == stamp:
        return hit[1]  # type: ignore[no-any-return]
    names: list[str] | None = None
    readable = _read(ctx, node)
    if readable.tree is not None:
        try:
            _, final, _ = _analyze(ctx.shallow_copy(), readable.tree)
        except Exception:
            final = None
        if final is not None and not any(c.name == "*" for c in final.columns):
            names = [c.name for c in final.columns] or None
    if ctx.lineage is None:
        cache[key] = (stamp, names)
    return names


def _expand_star(star: exp.Expr, sources: list[_Source], cols: _Cols) -> None:
    table = star.table.lower() if isinstance(star, exp.Column) and star.table else None
    excluded = {
        c.name.lower()
        for c in (star.args.get("except_") or star.args.get("except") or [])
        if isinstance(c, exp.Expr)
    }
    for s in sources:
        if table is not None and table not in (s.alias.lower(), s.label.lower()):
            continue
        if s.columns is None:
            cols.add_star(s.star_origins or [s.label])
            continue
        for c in s.columns:
            if c.name == "*":
                cols.add_star(s.star_origins or [s.label])
            elif c.name.lower() not in excluded:
                cols.add(c.model_copy(), from_star=True)


def _sql_name(e: exp.Expr, position: int) -> str:
    text = " ".join(e.sql().split())
    return text if len(text) <= 40 else f"column_{position + 1}"


# --- Column stories -------------------------------------------------------------------


def _resolve(sources: list[_Source], col: exp.Column) -> tuple[ColumnStory | None, _Source | None]:
    """Find the story of the source column ``col`` refers to, or at least its source."""
    name = col.name.lower()
    table = col.table.lower() if col.table else ""
    candidates = [s for s in sources if not table or table in (s.alias.lower(), s.label.lower())]
    for s in candidates:
        for c in s.columns or []:
            if c.name != "*" and c.name.lower() == name:
                return c, s
    maybe = [s for s in candidates if s.columns is None or any(c.name == "*" for c in s.columns)]
    if len(maybe) == 1 or (maybe and table):
        return None, maybe[0]
    if len(candidates) == 1:
        return None, candidates[0]
    return None, None


def _column_story(
    name: str,
    inner: exp.Expr,
    sources: list[_Source],
    step: str | None,
    group_keys: list[str],
) -> ColumnStory:
    if isinstance(inner, exp.Column):
        return _passed_or_renamed(name, inner, sources, step)

    described = describe_expr(inner)
    how = described.text if described.exact else f"calculated as {described.text}"
    if described.exact and is_predicate(inner):
        how = f"true when {how}"
    aggregates = [a for a in inner.find_all(exp.AggFunc) if a.find_ancestor(exp.Window) is None]
    if aggregates and 1 <= len(group_keys) <= 2:
        how += f" per {join_words(group_keys)}"
    return ColumnStory(name=name, how=how, from_step=step)


def _passed_or_renamed(
    name: str, col: exp.Column, sources: list[_Source], step: str | None
) -> ColumnStory:
    base, source = _resolve(sources, col)
    same = name.lower() == col.name.lower()
    if base is None:
        if same:
            how = (
                f"{_PASSED} from {source.origin}" if source is not None else f"{_PASSED} unchanged"
            )
            return ColumnStory(name=name, how=how)
        return ColumnStory(name=name, how=f"renamed from {col.name}", from_step=step)
    if same:
        return ColumnStory(name=name, how=base.how, from_step=base.from_step)
    if base.from_step is None and base.how.startswith((_PASSED, "renamed from")):
        return ColumnStory(name=name, how=f"renamed from {col.name}", from_step=step)
    return ColumnStory(name=name, how=base.how, from_step=base.from_step)


# --- Grain and step text -----------------------------------------------------------------


def _group_keys(sel: exp.Select) -> list[str]:
    group = sel.args.get("group")
    if group is None:
        return []
    if group.args.get("all"):
        return [
            e.alias_or_name or describe(e)
            for e in sel.expressions
            if not isinstance(e, exp.Star)
            and not any(a.find_ancestor(exp.Window) is None for a in e.find_all(exp.AggFunc))
        ]
    keys: list[str] = []
    for key in group.expressions:
        while isinstance(key, exp.Paren):
            key = key.this
        if isinstance(key, exp.Literal) and not key.is_string:
            try:
                target = sel.expressions[int(str(key.this)) - 1]
            except (ValueError, IndexError):
                keys.append(describe(key))
                continue
            keys.append(_name_of(target))
        elif isinstance(key, exp.Column):
            keys.append(key.name)
        else:
            keys.append(describe(key))
    return keys


def _name_of(target: exp.Expr) -> str:
    inner = target.this if isinstance(target, exp.Alias) else target
    return target.alias_or_name or (
        inner.name if isinstance(inner, exp.Column) else describe(inner)
    )


def _inherited_grain(
    sel: exp.Select, sources: list[_Source], env: dict[str, _Result], columns: list[ColumnStory]
) -> list[str]:
    """A plain filter or projection of a grouped step keeps that step's grain."""
    if len(sources) != 1 or sel.args.get("joins") or sel.args.get("distinct"):
        return []
    res = env.get(sources[0].label.lower())
    if res is None or not res.grain:
        return []
    names = {c.name.lower() for c in columns}
    renamed = {c.how.lower().removeprefix("renamed from "): c.name for c in columns}
    out: list[str] = []
    for g in res.grain:
        if g.lower() in names or "*" in names:
            out.append(g)
        elif g.lower() in renamed:
            out.append(renamed[g.lower()])
        else:
            return []
    return out


def _describe_select(sel: exp.Select, items: list[exp.Expr], group_keys: list[str]) -> str:
    joins = list(sel.args.get("joins") or [])
    parts = [f"takes rows from {_item_label(items[0]) if items else 'nothing'}"]
    for join in joins:
        side = (join.side or join.kind or "inner").lower()
        how = {
            "left": "keeping every row even without a match",
            "inner": "keeping only rows that match",
            "full": "keeping unmatched rows from both sides",
            "right": "keeping every row from the joined table",
            "cross": "pairing every row with every row",
        }.get(side, side)
        parts.append(f"adds {_item_label(join.this)} ({how})")
    where = sel.args.get("where")
    if where is not None:
        parts.append(f"keeps only rows where {describe(where.this)}")
    if sel.args.get("group") is not None:
        parts.append(f"rolls up to one row per {_join(group_keys)}")
    having = sel.args.get("having")
    if having is not None:
        parts.append(f"then keeps only groups where {describe(having.this)}")
    if sel.args.get("distinct"):
        parts.append("removes duplicate rows")
    return ", ".join(parts) + "."


def _join(items: list[str]) -> str:
    return join_words(items)


def _summary(name: str, reads_from: list[str], grain: list[str], cols: list[ColumnStory]) -> str:
    out = (
        f"{name} combines {_join(reads_from)}"
        if len(reads_from) > 1
        else (f"{name} is built from {_join(reads_from)}")
    )
    if grain:
        out += f" into one row per {_join(grain)}"
    out += "."
    calculated = [c for c in cols if not c.how.startswith((_PASSED, "renamed", "every"))]
    if calculated:
        shown = [f"{c.name} ({c.how})" for c in calculated[:_MAX_CALCULATED_IN_SUMMARY]]
        extra = len(calculated) - _MAX_CALCULATED_IN_SUMMARY
        if extra > 0:
            shown.append(f"{extra} more")
        out += " It works out " + _join(shown) + "."
    return out
