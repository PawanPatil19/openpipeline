"""Turn a model's SQL into a plain-English story.

This is deterministic: it reads the SQL structure with sqlglot and describes
it. It needs no network access and no AI model, so it is fast, free, and gives
the same answer every time. An optional AI rewrite can be layered on top later.
"""

from __future__ import annotations

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp

from openpipeline_core import jinja
from openpipeline_core.models import NodeKind, Project

_AGG_WORDS: dict[type[exp.Expr], str] = {
    exp.Sum: "total",
    exp.Count: "number",
    exp.Min: "smallest",
    exp.Max: "largest",
    exp.Avg: "average",
}


class ColumnStory(BaseModel):
    name: str
    how: str


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


def explain_model(project: Project, name_or_id: str, *, dialect: str | None = None) -> ModelStory:
    node = project.get(name_or_id)
    if node is None:
        raise KeyError(f"No model named {name_or_id!r}")

    reads_from = [project.nodes[d].name for d in node.depends_on if d in project.nodes]
    if node.kind != NodeKind.MODEL or not node.raw_sql.strip():
        what = "source table" if node.kind == NodeKind.SOURCE else node.kind.value
        return ModelStory(
            model=node.name,
            description=node.description,
            summary=node.description or f"{node.name} is a {what}.",
            reads_from=reads_from,
        )

    try:
        tree = sqlglot.parse_one(jinja.to_plain_sql(node.raw_sql), read=dialect)
    except sqlglot.errors.ParseError as exc:
        return ModelStory(
            model=node.name,
            description=node.description,
            summary=node.description or f"{node.name} reads from {_join(reads_from)}.",
            reads_from=reads_from,
            parse_error=str(exc).splitlines()[0],
        )

    steps: list[str] = []
    with_ = _arg(tree, "with")
    if with_ is not None:
        for cte in with_.expressions:
            inner = cte.this
            if isinstance(inner, exp.Select):
                steps.append(f"Builds a step called {cte.alias}: {_describe_select(inner)}")

    final = _first_select(tree)
    columns: list[ColumnStory] = []
    filters: list[str] = []
    grain: list[str] = []
    if final is not None:
        steps.append(f"Final result: {_describe_select(final)}")
        columns = [_column_story(e) for e in final.expressions]
        where = final.args.get("where")
        if where is not None:
            filters = [where.this.sql(dialect=dialect)]
        group = final.args.get("group")
        if group is not None:
            grain = [_short(e) for e in group.expressions]

    summary = _summary(node.name, reads_from, grain, columns)
    return ModelStory(
        model=node.name,
        description=node.description,
        summary=summary,
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


def _first_select(tree: exp.Expr) -> exp.Select | None:
    if isinstance(tree, exp.Select):
        return tree
    if isinstance(tree, exp.Union):
        return _first_select(tree.left)
    return tree.find(exp.Select)


def _table_name(node: exp.Expr | None) -> str:
    if isinstance(node, exp.Table):
        return ".".join(p for p in (node.db, node.name) if p)
    if isinstance(node, exp.Subquery):
        return "a subquery"
    return node.sql() if node is not None else "nothing"


def _describe_select(sel: exp.Select) -> str:
    from_ = _arg(sel, "from")
    parts = [f"takes rows from {_table_name(from_.this if from_ else None)}"]
    for join in sel.args.get("joins") or []:
        side = (join.side or join.kind or "inner").lower()
        how = {
            "left": "keeping every row even without a match",
            "inner": "keeping only rows that match",
            "full": "keeping unmatched rows from both sides",
            "right": "keeping every row from the joined table",
            "cross": "pairing every row with every row",
        }.get(side, side)
        parts.append(f"adds {_table_name(join.this)} ({how})")
    where = sel.args.get("where")
    if where is not None:
        parts.append(f"keeps only rows where {where.this.sql()}")
    group = sel.args.get("group")
    if group is not None:
        parts.append(f"rolls up to one row per {_join([_short(e) for e in group.expressions])}")
    return ", ".join(parts) + "."


def _column_story(e: exp.Expr) -> ColumnStory:
    name = e.alias_or_name
    inner = e.this if isinstance(e, exp.Alias) else e
    agg = inner.find(exp.AggFunc)
    if agg is not None:
        word = next((w for t, w in _AGG_WORDS.items() if isinstance(agg, t)), agg.key)
        arg = agg.this
        target = _short(arg) if arg is not None and not isinstance(arg, exp.Star) else "rows"
        return ColumnStory(name=name, how=f"the {word} of {target}")
    if isinstance(inner, exp.Column):
        if inner.name == name:
            return ColumnStory(name=name, how="passed through unchanged")
        return ColumnStory(name=name, how=f"renamed from {inner.name}")
    if isinstance(inner, exp.Star):
        return ColumnStory(name="*", how="every column from the input")
    return ColumnStory(name=name, how=f"calculated as {inner.sql()}")


def _short(e: exp.Expr) -> str:
    return e.name if isinstance(e, exp.Column) else e.sql()


def _join(items: list[str]) -> str:
    if not items:
        return "nothing"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _summary(name: str, reads_from: list[str], grain: list[str], cols: list[ColumnStory]) -> str:
    out = (
        f"{name} combines {_join(reads_from)}"
        if len(reads_from) > 1
        else (f"{name} is built from {_join(reads_from)}")
    )
    if grain:
        out += f" into one row per {_join(grain)}"
    out += "."
    calculated = [c for c in cols if not c.how.startswith(("passed", "renamed", "every"))]
    if calculated:
        out += " It works out " + _join([f"{c.name} ({c.how})" for c in calculated]) + "."
    return out
