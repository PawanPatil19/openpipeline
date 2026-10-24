"""MCP server so AI agents can read the project and propose changes.

Agents can look at everything, but they can only *propose* edits. A person
reviews each proposal in the web UI before anything touches the dbt files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from openpipeline import __version__
from openpipeline.proposals import FileChange, Proposal, ProposalStore
from openpipeline.state import ProjectState
from openpipeline_core import explain_model


def create_mcp_server(project_dir: str | Path) -> MCPServer:
    state = ProjectState(project_dir)
    store = ProposalStore(state.root)
    server = MCPServer(
        "openpipeline",
        instructions=(
            "Read a dbt project and propose changes to it. Use list_models and "
            "explain to understand the project, impact_of before changing a model, "
            "and propose_change to suggest edits. Proposals are reviewed by a person; "
            "you cannot change files directly."
        ),
        version=__version__,
    )

    @server.tool()
    def list_models() -> list[dict[str, Any]]:
        """List every dbt model with its description, owner, and file path."""
        return [
            {"name": n.name, "description": n.description, "owner": n.owner, "path": n.path}
            for n in state.project().models()
        ]

    @server.tool()
    def get_model(name: str) -> dict[str, Any]:
        """Return a model's SQL, columns, config, and direct dependencies."""
        node = state.project().get(name)
        if node is None:
            raise ValueError(f"No model named {name!r}")
        return node.model_dump(mode="json")

    @server.tool()
    def explain(name: str) -> dict[str, Any]:
        """Explain in plain English what a model does, step by step."""
        return explain_model(state.project(), name).model_dump(mode="json")

    @server.tool()
    def impact_of(name: str) -> dict[str, list[str]]:
        """List the models upstream of, and affected downstream by, a model."""
        p, g = state.project(), state.graph()
        node = p.get(name)
        if node is None:
            raise ValueError(f"No model named {name!r}")
        return {
            "upstream": [p.nodes[u].name for u in g.upstream(node.unique_id)],
            "downstream": [p.nodes[u].name for u in g.downstream(node.unique_id)],
        }

    @server.tool()
    def propose_change(
        title: str, rationale: str, files: list[dict[str, str]], author: str = "agent"
    ) -> dict[str, Any]:
        """Propose edits to the dbt project for a person to review.

        ``files`` is a list of ``{"path": ..., "content": ...}`` with the full new
        content of each file, relative to the project root. Empty content deletes
        the file. Returns the proposal id.
        """
        proposal = store.create(
            Proposal(
                title=title,
                rationale=rationale,
                author=author,
                changes=[FileChange.model_validate(f) for f in files],
            )
        )
        return {"id": proposal.id, "status": proposal.status}

    @server.tool()
    def list_proposals() -> list[dict[str, Any]]:
        """List proposals and whether each is pending, accepted, or rejected."""
        return [
            {"id": p.id, "title": p.title, "status": p.status, "author": p.author}
            for p in store.list()
        ]

    return server
