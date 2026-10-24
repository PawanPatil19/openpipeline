"""Column lineage and search as plain JSON-ready views, shared by the API, MCP, and CLI."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from openpipeline.state import ProjectState
from openpipeline_core import ColumnLineage, ColumnRef, Node, Project, SearchHit, search_project


class ColumnRefView(BaseModel):
    node_id: str
    node: str
    """The node's name."""
    kind: str
    column: str


class ColumnInfo(BaseModel):
    name: str
    description: str = ""
    tests: list[str] = Field(default_factory=list)
    upstream: list[ColumnRefView] = Field(default_factory=list)
    """The columns this one is computed from, one step back."""


class ColumnLineageView(BaseModel):
    model: str
    column: str
    upstream: list[ColumnRefView]
    downstream: list[ColumnRefView]


def _view(project: Project, ref: ColumnRef) -> ColumnRefView:
    node = project.nodes[ref.node_id]
    return ColumnRefView(
        node_id=ref.node_id, node=node.name, kind=node.kind.value, column=ref.column
    )


def _views(project: Project, refs: list[ColumnRef]) -> list[ColumnRefView]:
    return [_view(project, r) for r in refs if r.node_id in project.nodes]


def column_infos(project: Project, lineage: ColumnLineage, node: Node) -> list[ColumnInfo]:
    """Output columns of a node with their descriptions and direct upstream columns."""
    documented = {c.name.lower(): c for c in node.columns}
    out: list[ColumnInfo] = []
    for name in lineage.columns(node.unique_id):
        doc = documented.get(name.lower())
        out.append(
            ColumnInfo(
                name=name,
                description=doc.description if doc else "",
                tests=list(doc.tests) if doc else [],
                upstream=_views(project, lineage.direct_upstream(node.unique_id, name)),
            )
        )
    return out


def column_lineage_view(
    project: Project, lineage: ColumnLineage, node: Node, column: str
) -> ColumnLineageView:
    """Everything upstream and downstream of one column. Raises ``KeyError`` if unknown."""
    name = lineage.canonical(node.unique_id, column)
    if name is None:
        raise KeyError(f"{node.name} has no column named {column!r}")
    return ColumnLineageView(
        model=node.name,
        column=name,
        upstream=_views(project, lineage.upstream(node.unique_id, name)),
        downstream=_views(project, lineage.downstream(node.unique_id, name)),
    )


def lineage_router(state: ProjectState) -> APIRouter:
    router = APIRouter()

    def node_or_404(name: str) -> Node:
        node = state.project().get(name)
        if node is None:
            raise HTTPException(status_code=404, detail=f"No model named {name!r}")
        return node

    @router.get("/api/search")
    def search(q: str = "", limit: int = Query(20, ge=1, le=100)) -> list[SearchHit]:
        return search_project(state.project(), state.lineage(), q, limit)

    @router.get("/api/models/{name}/columns")
    def columns(name: str) -> list[ColumnInfo]:
        node = node_or_404(name)
        return column_infos(state.project(), state.lineage(), node)

    @router.get("/api/models/{name}/columns/{column}/lineage")
    def column_lineage(name: str, column: str) -> ColumnLineageView:
        node = node_or_404(name)
        try:
            return column_lineage_view(state.project(), state.lineage(), node, column)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=exc.args[0]) from exc

    return router
