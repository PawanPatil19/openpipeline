"""HTTP API used by the web UI. Also serves the built UI itself."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from openpipeline import __version__
from openpipeline.ai import AIClient, AIError, AIExplanation, AIService, AIStatus, default_client
from openpipeline.files import write_file
from openpipeline.proposals import Proposal, ProposalStore, StaleProposalError, Status
from openpipeline.state import ProjectState
from openpipeline_core import (
    ChangePreview,
    DocsUpdate,
    ModelRule,
    ModelStory,
    Node,
    NodeKind,
    Rule,
    explain_model,
    preview_changes,
    update_docs,
)

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


class RulesResponse(BaseModel):
    rules: list[Rule]
    warnings: list[str]


class StatusUpdate(BaseModel):
    status: Literal["accepted", "rejected"]
    reason: str | None = None
    """Why the proposal was rejected. Saved as a comment."""
    force: bool = False
    """Accept even if files changed since the proposal was made."""


class CommentCreate(BaseModel):
    text: str = Field(min_length=1)
    author: str = "reviewer"


def create_app(
    project_dir: str | Path, *, serve_ui: bool = True, ai_client: AIClient | None = None
) -> FastAPI:
    state = ProjectState(project_dir)
    proposals = ProposalStore(state.root)
    ai = AIService(state.root, ai_client if ai_client is not None else default_client())
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
            warnings=[*p.warnings, *state.rules().warnings],
        )

    @app.get("/api/graph")
    def graph() -> dict[str, Any]:
        return state.graph().to_dict()

    @app.get("/api/models/{name}")
    def model(name: str) -> Node:
        return node_or_404(name)

    def model_or_404(name: str) -> Node:
        node = node_or_404(name)
        if node.kind != NodeKind.MODEL:
            raise HTTPException(status_code=404, detail=f"No model named {name!r}")
        return node

    @app.put("/api/models/{name}/docs")
    def save_docs(name: str, body: DocsUpdate) -> Node:
        """A person saving descriptions from the UI. Writes the YAML file directly."""
        node = model_or_404(name)
        try:
            edit = update_docs(state.project(), node.unique_id, body)
            write_file(state.root, edit.path, edit.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return model_or_404(name)

    @app.get("/api/ai")
    def ai_status() -> AIStatus:
        return ai.status()

    @app.post("/api/models/{name}/ai-explanation")
    def ai_explanation(name: str, refresh: bool = False) -> AIExplanation:
        node = model_or_404(name)
        status = ai.status()
        if not status.available:
            raise HTTPException(status_code=503, detail=status.reason or "AI is not available.")
        try:
            return ai.explain(state.project(), state.graph(), node, refresh=refresh)
        except AIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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

    @app.get("/api/rules")
    def rules() -> RulesResponse:
        registry = state.rules()
        return RulesResponse(rules=registry.rules, warnings=registry.warnings)

    @app.get("/api/models/{name}/rules")
    def model_rules(name: str) -> list[ModelRule]:
        node = node_or_404(name)
        return state.rules().applied_to(node.name)

    @app.get("/api/proposals")
    def list_proposals(status: Status | None = None) -> list[Proposal]:
        return proposals.list(status)

    @app.post("/api/proposals/{proposal_id}")
    def update_proposal(proposal_id: str, body: StatusUpdate) -> Proposal:
        try:
            return proposals.set_status(
                proposal_id, body.status, reason=body.reason, force=body.force
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Proposal not found") from exc
        except StaleProposalError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "stale", "message": str(exc), "changed_files": exc.files},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/proposals/{proposal_id}/comments")
    def comment_on_proposal(proposal_id: str, body: CommentCreate) -> Proposal:
        try:
            return proposals.add_comment(proposal_id, body.author, body.text)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Proposal not found") from exc

    @app.get("/api/proposals/{proposal_id}/preview")
    def preview_proposal(proposal_id: str) -> ChangePreview:
        """What the proposal would do to the project as it is on disk now.

        For an accepted proposal the files are already written, so the preview shows
        little or nothing. It is only meaningful while a proposal is pending.
        """
        proposal = proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        try:
            return preview_changes(state.root, [(c.path, c.content) for c in proposal.changes])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
