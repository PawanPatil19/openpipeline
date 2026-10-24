"""HTTP API used by the web UI. Also serves the built UI itself."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openpipeline import __version__
from openpipeline.proposals import Proposal, ProposalStore, Status
from openpipeline.state import ProjectState
from openpipeline_core import ModelStory, Node, explain_model

STATIC_DIR = Path(__file__).parent / "static"


class ProjectInfo(BaseModel):
    name: str
    root: str
    loaded_from: str
    model_count: int
    source_count: int
    warnings: list[str]


class Impact(BaseModel):
    model: str
    upstream: list[str]
    downstream: list[str]


class StatusUpdate(BaseModel):
    status: Status


def create_app(project_dir: str | Path, *, serve_ui: bool = True) -> FastAPI:
    state = ProjectState(project_dir)
    proposals = ProposalStore(state.root)
    app = FastAPI(title="OpenPipeline", version=__version__, docs_url="/api/docs")

    def node_or_404(name: str) -> Node:
        node = state.project().get(name)
        if node is None:
            raise HTTPException(status_code=404, detail=f"No model named {name!r}")
        return node

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/project")
    def project_info() -> ProjectInfo:
        p = state.project()
        return ProjectInfo(
            name=p.name,
            root=p.root,
            loaded_from=p.loaded_from,
            model_count=len(p.models()),
            source_count=sum(1 for n in p.nodes.values() if n.kind.value == "source"),
            warnings=p.warnings,
        )

    @app.get("/api/graph")
    def graph() -> dict[str, Any]:
        return state.graph().to_dict()

    @app.get("/api/models/{name}")
    def model(name: str) -> Node:
        return node_or_404(name)

    @app.get("/api/models/{name}/story")
    def story(name: str) -> ModelStory:
        node = node_or_404(name)
        return explain_model(state.project(), node.unique_id)

    @app.get("/api/models/{name}/impact")
    def impact(name: str) -> Impact:
        node = node_or_404(name)
        g, p = state.graph(), state.project()
        return Impact(
            model=node.name,
            upstream=[p.nodes[u].name for u in g.upstream(node.unique_id)],
            downstream=[p.nodes[u].name for u in g.downstream(node.unique_id)],
        )

    @app.get("/api/proposals")
    def list_proposals(status: Status | None = None) -> list[Proposal]:
        return proposals.list(status)

    @app.post("/api/proposals/{proposal_id}")
    def update_proposal(proposal_id: str, body: StatusUpdate) -> Proposal:
        try:
            return proposals.set_status(proposal_id, body.status)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Proposal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    if serve_ui and (STATIC_DIR / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (STATIC_DIR / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR):
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app
