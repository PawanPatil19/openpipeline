"""Column-level lineage: which upstream columns each output column comes from.

Like the rest of the core this reads SQL structure only. It never runs
anything. For each model it rewrites table names to the nodes they refer to,
asks sqlglot to qualify the query and trace every output column, and records
the upstream ``(node, column)`` pairs it finds.

Reading SQL without a warehouse is best effort, so this module never raises.
When a query cannot be read, or a column cannot be traced, that column simply
has no known upstream columns.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from typing import NamedTuple

from sqlglot import exp
from sqlglot.lineage import lineage as sqlglot_lineage
from sqlglot.optimizer import build_scope, qualify
from sqlglot.optimizer.scope import Scope, traverse_scope

from openpipeline_core.graph import ModelGraph
from openpipeline_core.models import Node, NodeKind, Project
from openpipeline_core.sql_source import RelationIndex, readable_sql

_log = logging.getLogger(__name__)


class ColumnRef(NamedTuple):
    """One column of one node, e.g. ``("model.shop.orders", "amount")``."""

    node_id: str
    column: str


class ColumnLineage:
    """Column lineage for a whole project, with fast lookups in both directions."""

    def __init__(
        self, project: Project, graph: ModelGraph | None = None, *, dialect: str | None = None
    ) -> None:
        self.project = project
        self._dialect = dialect
        self._columns: dict[str, list[str]] = {}
        self._direct_up: dict[str, dict[str, list[ColumnRef]]] = {}
        self._direct_down: dict[ColumnRef, list[ColumnRef]] = {}
        self._relations = RelationIndex(project)
        self._by_table: dict[str, str] = {}
        for uid, node in project.nodes.items():
            if node.kind != NodeKind.SOURCE:
                self._by_table.setdefault(node.name, uid)
        self._by_source = {
            n.name: uid for uid, n in project.nodes.items() if n.kind == NodeKind.SOURCE
        }
        self._build(graph or ModelGraph(project))

    # --- Questions you can ask ---------------------------------------------

    def columns(self, node_id: str) -> list[str]:
        """Output columns of a node, in query order. Empty when unknown."""
        return list(self._columns.get(node_id, []))

    def has_column(self, node_id: str, column: str) -> bool:
        return self.canonical(node_id, column) is not None

    def canonical(self, node_id: str, column: str) -> str | None:
        """The column's name as this node spells it, ignoring case. ``None`` if unknown."""
        wanted = column.lower()
        for c in self._columns.get(node_id, []):
            if c.lower() == wanted:
                return c
        return None

    def direct_upstream(self, node_id: str, column: str) -> list[ColumnRef]:
        """The columns this column is computed from, one step back."""
        name = self.canonical(node_id, column)
        return list(self._direct_up.get(node_id, {}).get(name or column, []))

    def direct_downstream(self, node_id: str, column: str) -> list[ColumnRef]:
        name = self.canonical(node_id, column) or column
        return list(self._direct_down.get(ColumnRef(node_id, name), []))

    def upstream(self, node_id: str, column: str, recursive: bool = True) -> list[ColumnRef]:
        """Columns this column is derived from, nearest first."""
        start = ColumnRef(node_id, self.canonical(node_id, column) or column)
        return self._walk(start, self.direct_upstream, recursive)

    def downstream(self, node_id: str, column: str, recursive: bool = True) -> list[ColumnRef]:
        """Columns computed from this column, nearest first."""
        start = ColumnRef(node_id, self.canonical(node_id, column) or column)
        return self._walk(start, self.direct_downstream, recursive)

    def lineage_nodes(self, node_id: str, column: str) -> set[str]:
        """Ids of every node on this column's lineage, including its own node."""
        out = {node_id}
        for ref in self.upstream(node_id, column) + self.downstream(node_id, column):
            out.add(ref.node_id)
        return out

    # --- Building ------------------------------------------------------------

    def _build(self, graph: ModelGraph) -> None:
        try:
            order = graph.topological_order()
        except ValueError:
            order = list(self.project.nodes)
        for uid in order:
            node = self.project.nodes[uid]
            documented = [c.name for c in node.columns]
            self._columns[uid] = documented
            self._direct_up[uid] = {}
            if node.kind in (NodeKind.MODEL, NodeKind.SNAPSHOT) and (
                node.raw_sql.strip() or node.compiled_sql.strip()
            ):
                try:
                    self._read_model(node, documented)
                except Exception:  # best effort: never let one model break the project
                    _log.debug("column lineage failed for %s", uid, exc_info=True)

        for uid, per_column in self._direct_up.items():
            for column, refs in per_column.items():
                for ref in refs:
                    self._direct_down.setdefault(ref, [])
                    if ColumnRef(uid, column) not in self._direct_down[ref]:
                        self._direct_down[ref].append(ColumnRef(uid, column))

        # Sources and seeds often have no documented columns. Learn them from use.
        for used in list(self._direct_down):
            owner = self.project.nodes.get(used.node_id)
            if owner is not None and owner.kind != NodeKind.MODEL:
                known = self._columns.setdefault(used.node_id, [])
                if used.column.lower() not in {c.lower() for c in known}:
                    known.append(used.column)

    def _resolve_table(self, table: exp.Table) -> str | None:
        if table.catalog:
            return None
        if table.db:
            return self._by_source.get(f"{table.db}.{table.name}")
        return self._by_table.get(table.name)

    def _schema_for(self, uid: str) -> dict[str, str]:
        return dict.fromkeys(self._columns.get(uid, []), "unknown")

    def _read_model(self, node: Node, documented: list[str]) -> None:
        tree = readable_sql(self.project, node, self._dialect, index=self._relations).tree
        if not isinstance(tree, exp.Query):
            return

        # Point every real table at a short alias that maps back to a node id.
        # CTEs are left alone. Scopes tell the two apart, even when a CTE has
        # the same name as the model it reads.
        aliases: dict[str, str] = {}
        schema: dict[str, dict[str, str]] = {}
        for scope in traverse_scope(tree):
            for table in scope.tables:
                source = scope.sources.get(table.alias_or_name)
                if not isinstance(source, exp.Table):
                    continue
                uid = self._resolve_table(table)
                if uid is None:
                    continue
                key = f"t{len(aliases)}"
                aliases[key] = uid
                original = table.alias_or_name
                table.set("this", exp.to_identifier(key))
                table.set("db", None)
                table.set("catalog", None)
                table.set("alias", exp.TableAlias(this=exp.to_identifier(original)))
                if self._columns.get(uid):
                    schema[key] = self._schema_for(uid)

        qualified = qualify.qualify(
            tree, schema=dict[str, object](schema), validate_qualify_columns=False, identify=False
        )
        root_scope = build_scope(qualified)
        if root_scope is None:
            return
        query = root_scope.expression
        if not isinstance(query, exp.Query):
            return
        scope = root_scope

        outputs: list[str] = []
        refs: dict[str, list[ColumnRef]] = {}
        saw_star = False
        for select in query.selects:
            name = select.alias_or_name
            if _is_star(select):
                saw_star = True
                self._expand_star(select, scope, aliases, outputs, refs)
                continue
            if not name or name in refs:
                continue
            outputs.append(name)
            refs[name] = self._trace(name, qualified, schema, scope, aliases)

        if saw_star:
            have = {o.lower() for o in outputs}
            outputs.extend(c for c in documented if c.lower() not in have)
        self._columns[node.unique_id] = outputs or documented
        self._direct_up[node.unique_id] = {k: v for k, v in refs.items() if v}

    def _trace(
        self,
        name: str,
        qualified: exp.Expr,
        schema: dict[str, dict[str, str]],
        scope: Scope,
        aliases: dict[str, str],
    ) -> list[ColumnRef]:
        try:
            # trim_selects=False skips a deep copy per step. It changes nothing we
            # read (only leaf tables), and makes large projects about 5x faster.
            root = sqlglot_lineage(
                name, qualified, schema, scope=scope, copy=False, trim_selects=False
            )
        except Exception:
            return []
        found: list[ColumnRef] = []
        for leaf in root.walk():
            if leaf.downstream or not isinstance(leaf.expression, exp.Table):
                continue
            uid = aliases.get(leaf.expression.name)
            if uid is None:
                continue
            column = leaf.name.rsplit(".", 1)[-1]
            ref = ColumnRef(uid, self.canonical(uid, column) or column)
            if ref not in found:
                found.append(ref)
        return found

    def _expand_star(
        self,
        select: exp.Expr,
        scope: Scope,
        aliases: dict[str, str],
        outputs: list[str],
        refs: dict[str, list[ColumnRef]],
    ) -> None:
        """Pass a ``*`` through from plain tables whose columns are known."""
        wanted = [select.table] if isinstance(select, exp.Column) and select.table else None
        for alias, source in scope.sources.items():
            if wanted is not None and alias != wanted[0]:
                continue
            if not isinstance(source, exp.Table):
                continue
            uid = aliases.get(source.name)
            if uid is None:
                continue
            for column in self._columns.get(uid, []):
                if column.lower() not in {o.lower() for o in outputs}:
                    outputs.append(column)
                    refs[column] = [ColumnRef(uid, column)]

    @staticmethod
    def _walk(
        start: ColumnRef, step: Callable[[str, str], list[ColumnRef]], recursive: bool
    ) -> list[ColumnRef]:
        seen = {start}
        out: list[ColumnRef] = []
        queue: deque[ColumnRef] = deque([start])
        while queue:
            cur = queue.popleft()
            for ref in step(cur.node_id, cur.column):
                if ref not in seen:
                    seen.add(ref)
                    out.append(ref)
                    if recursive:
                        queue.append(ref)
        return out


def _is_star(select: exp.Expr) -> bool:
    return isinstance(select, exp.Star) or (
        isinstance(select, exp.Column) and isinstance(select.this, exp.Star)
    )
