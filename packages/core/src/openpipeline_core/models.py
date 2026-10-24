"""Data types shared by every part of OpenPipeline.

They are pydantic models so the API server and MCP server can send them as
JSON without extra conversion code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class NodeKind(StrEnum):
    MODEL = "model"
    SOURCE = "source"
    SEED = "seed"
    SNAPSHOT = "snapshot"


class Column(BaseModel):
    name: str
    description: str = ""
    tests: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class Node(BaseModel):
    """One box in the graph: a model, a source table, a seed, or a snapshot."""

    unique_id: str
    """Stable id, matching dbt's format, e.g. ``model.jaffle_shop.customers``."""
    name: str
    kind: NodeKind
    description: str = ""
    path: str | None = None
    """File path relative to the project root, when the node comes from a file."""
    raw_sql: str = ""
    materialized: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    """``unique_id`` of every node this one reads from."""
    columns: list[Column] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def owner(self) -> str | None:
        owner = self.meta.get("owner")
        return str(owner) if owner is not None else None


class Project(BaseModel):
    name: str
    root: str
    loaded_from: str
    """How the project was read: ``"manifest"`` or ``"files"``."""
    nodes: dict[str, Node] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    """Problems found while loading, such as a ``ref()`` to a missing model."""

    def get(self, name_or_id: str) -> Node | None:
        """Find a node by ``unique_id`` or, failing that, by short name."""
        if name_or_id in self.nodes:
            return self.nodes[name_or_id]
        matches = [n for n in self.nodes.values() if n.name == name_or_id]
        # Prefer a model over a source that happens to share the name.
        matches.sort(key=lambda n: n.kind != NodeKind.MODEL)
        return matches[0] if matches else None

    def models(self) -> list[Node]:
        return sorted(
            (n for n in self.nodes.values() if n.kind == NodeKind.MODEL), key=lambda n: n.name
        )
