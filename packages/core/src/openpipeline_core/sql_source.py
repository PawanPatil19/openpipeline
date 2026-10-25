"""One place that turns a node into SQL we can read.

The story and the column lineage both need a parsed query whose tables are the
short names people use (``stg_orders``, ``ecom.raw_orders``). Two inputs give us
that:

* the manifest's ``compiled_code``, where dbt has already resolved every macro,
  ``if`` and ``var``. Its tables are physical names such as
  ``"dev"."main"."stg_orders"``, so we map them back to nodes with each node's
  ``relation_name`` and rewrite them to the short names;
* otherwise the raw file, run through ``jinja.to_plain_sql``.

Either way, everything downstream sees the same table naming.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from openpipeline_core import jinja
from openpipeline_core.models import Node, NodeKind, Project

_ADAPTER_DIALECTS = {
    "duckdb": "duckdb",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "postgres": "postgres",
    "redshift": "redshift",
    "databricks": "databricks",
    "spark": "spark",
    "trino": "trino",
    "athena": "trino",
    "sqlserver": "tsql",
    "fabric": "tsql",
}


def dialect_for_adapter(adapter: str | None) -> str | None:
    """The sqlglot dialect for a dbt adapter name, or ``None`` when unknown."""
    return _ADAPTER_DIALECTS.get(adapter.lower()) if adapter else None


@dataclass(frozen=True)
class ReadableSQL:
    tree: exp.Expr | None
    """The parsed query, or ``None`` when nothing could be parsed."""
    error: str | None
    from_compiled: bool
    """True when the tree came from dbt's compiled SQL rather than the raw file."""


_QUOTES = re.compile(r"[\"`\[\]]")


def _parts(relation: str) -> list[str]:
    return [p for p in _QUOTES.sub("", relation).lower().split(".") if p]


class RelationIndex:
    """Maps physical table names (from ``relation_name``) back to nodes."""

    def __init__(self, project: Project) -> None:
        self._full: dict[str, Node] = {}
        self._last2: dict[str, Node] = {}
        self._last1: dict[str, list[Node]] = {}
        for node in project.nodes.values():
            if not node.relation_name:
                continue
            parts = _parts(node.relation_name)
            if not parts:
                continue
            self._full.setdefault(".".join(parts), node)
            if len(parts) >= 2:
                self._last2.setdefault(".".join(parts[-2:]), node)
            self._last1.setdefault(parts[-1], []).append(node)

    def __bool__(self) -> bool:
        return bool(self._full)

    def resolve(self, parts: list[str]) -> Node | None:
        """Match by the full dotted name, then the last two parts, then a unique last part."""
        parts = [p.lower() for p in parts]
        if not parts:
            return None
        found = self._full.get(".".join(parts))
        if found is None and len(parts) >= 2:
            found = self._last2.get(".".join(parts[-2:]))
        if found is None:
            candidates = self._last1.get(parts[-1], [])
            if len(candidates) == 1:
                found = candidates[0]
        return found


def readable_sql(
    project: Project,
    node: Node,
    dialect: str | None = None,
    *,
    index: RelationIndex | None = None,
) -> ReadableSQL:
    """Parse ``node``'s SQL, preferring dbt's compiled code. Never raises.

    ``dialect`` wins when given; otherwise the project's adapter picks one.
    Compiled SQL that does not parse falls back to the raw file.
    """
    dialect = dialect or dialect_for_adapter(project.adapter)
    if node.compiled_sql.strip():
        try:
            tree = sqlglot.parse_one(node.compiled_sql, read=dialect)
        except Exception:  # any parse or tokenize failure: fall back to the raw file
            tree = None
        if tree is not None:
            try:
                rewrite_relations(tree, index or RelationIndex(project))
            except Exception:
                tree = None
            else:
                return ReadableSQL(tree, None, True)
    try:
        tree = sqlglot.parse_one(jinja.to_plain_sql(node.raw_sql), read=dialect)
        tree = _macros_as_tables(tree)
    except Exception as exc:
        return ReadableSQL(None, str(exc).splitlines()[0] if str(exc) else "Could not parse", False)
    return ReadableSQL(tree, None, False)


def _macro_table(e: exp.Expr | None) -> exp.Table | None:
    """A table named after the macro, when ``e`` is a bare ``__macro__name(...)`` call."""
    if isinstance(e, exp.Anonymous) and str(e.this).lower().startswith(jinja.MACRO_PREFIX):
        return exp.to_table(str(e.this)[len(jinja.MACRO_PREFIX) :])
    return None


def _macros_as_tables(tree: exp.Expr) -> exp.Expr:
    """Where a macro stands in for a whole query or table, use a table of the same name.

    ``{{ dbt.date_spine(...) }}`` inside a CTE reads like a table. Left as a function
    call it would not be a valid place for one, and column tracing would trip on it.
    """
    for node in list(tree.find_all(exp.CTE, exp.Subquery, exp.From, exp.Join)):
        table = _macro_table(node.this)
        if table is None:
            continue
        if isinstance(node, (exp.CTE, exp.Subquery)):
            node.set("this", exp.select("*").from_(table))
        else:
            node.set("this", table)
    if tree.__class__ is exp.Anonymous:
        table = _macro_table(tree)
        if table is not None:
            return exp.select("*").from_(table)
    return tree


def rewrite_relations(tree: exp.Expr, index: RelationIndex) -> None:
    """Point physical tables at the short names ``to_plain_sql`` would produce, in place.

    Models, seeds and snapshots become their bare name. A source becomes
    ``source_name.table``. Names of CTEs are never touched.
    """
    if not index:
        return
    ctes = {c.alias.lower() for c in tree.find_all(exp.CTE) if c.alias}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            continue
        parts = [p.name for p in (table.args.get("catalog"), table.args.get("db"), table.this) if p]
        if len(parts) == 1 and parts[0].lower() in ctes:
            continue
        node = index.resolve(parts)
        if node is None:
            continue
        if node.kind == NodeKind.SOURCE:
            source, _, name = node.name.partition(".")
            if not name:
                continue
            table.set("this", exp.to_identifier(name))
            table.set("db", exp.to_identifier(source))
        else:
            table.set("this", exp.to_identifier(node.name))
            table.set("db", None)
        table.set("catalog", None)
