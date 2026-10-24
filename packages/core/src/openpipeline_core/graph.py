"""The dependency graph between nodes, and questions you can ask of it."""

from __future__ import annotations

from collections import deque
from typing import Any

from openpipeline_core.models import Project


class ModelGraph:
    """A directed graph where an edge ``a -> b`` means ``b`` reads from ``a``."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self._parents: dict[str, list[str]] = {}
        self._children: dict[str, list[str]] = {uid: [] for uid in project.nodes}
        for uid, node in project.nodes.items():
            self._parents[uid] = [d for d in node.depends_on if d in project.nodes]
            for dep in self._parents[uid]:
                self._children[dep].append(uid)

    def parents(self, uid: str) -> list[str]:
        return list(self._parents.get(uid, []))

    def children(self, uid: str) -> list[str]:
        return list(self._children.get(uid, []))

    def upstream(self, uid: str, depth: int | None = None) -> list[str]:
        """Every node ``uid`` reads from, directly or indirectly, nearest first."""
        return self._walk(uid, self._parents, depth)

    def downstream(self, uid: str, depth: int | None = None) -> list[str]:
        """Every node that would be affected by a change to ``uid``, nearest first."""
        return self._walk(uid, self._children, depth)

    def topological_order(self) -> list[str]:
        """Nodes ordered so each one comes after everything it reads from.

        Raises ``ValueError`` if the graph has a cycle.
        """
        indegree = {uid: len(p) for uid, p in self._parents.items()}
        queue = deque(sorted(uid for uid, d in indegree.items() if d == 0))
        order: list[str] = []
        while queue:
            uid = queue.popleft()
            order.append(uid)
            for child in sorted(self._children[uid]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if len(order) != len(indegree):
            stuck = sorted(uid for uid, d in indegree.items() if d > 0)
            raise ValueError(f"Cycle detected involving: {', '.join(stuck)}")
        return order

    def to_dict(self) -> dict[str, Any]:
        """Nodes and edges in the shape the web UI expects."""
        return {
            "nodes": [
                {
                    "id": n.unique_id,
                    "name": n.name,
                    "kind": n.kind.value,
                    "description": n.description,
                    "materialized": n.materialized,
                    "path": n.path,
                    "owner": n.owner,
                }
                for n in sorted(self.project.nodes.values(), key=lambda n: n.unique_id)
            ],
            "edges": [
                {"source": parent, "target": uid}
                for uid in sorted(self._parents)
                for parent in self._parents[uid]
            ],
        }

    @staticmethod
    def _walk(start: str, adjacency: dict[str, list[str]], depth: int | None) -> list[str]:
        seen: set[str] = {start}
        out: list[str] = []
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        while queue:
            uid, d = queue.popleft()
            if depth is not None and d >= depth:
                continue
            for nxt in adjacency.get(uid, []):
                if nxt not in seen:
                    seen.add(nxt)
                    out.append(nxt)
                    queue.append((nxt, d + 1))
        return out
