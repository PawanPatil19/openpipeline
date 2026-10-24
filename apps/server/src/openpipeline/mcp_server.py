"""MCP server so AI agents can read the project and propose changes.

Agents can look at everything, but they can only *propose* edits. A person
reviews each proposal in the web UI before anything touches the dbt files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from openpipeline import __version__
from openpipeline.lineage_views import column_lineage_view
from openpipeline.proposals import FileChange, Proposal, ProposalStore
from openpipeline.sample import SampleEngine
from openpipeline.state import ProjectState
from openpipeline_core import (
    DocsUpdate,
    explain_model,
    preview_changes,
    search_project,
    update_docs,
)


def create_mcp_server(
    project_dir: str | Path,
    *,
    sample_data: str | Path | None = None,
    dialect: str | None = None,
) -> MCPServer:
    state = ProjectState(project_dir)
    sampler = SampleEngine(state, sample_data=sample_data, dialect=dialect)
    store = ProposalStore(state.root)
    server = MCPServer(
        "openpipeline",
        instructions=(
            "Read a dbt project and propose changes to it. You cannot change files "
            "directly: a person reviews every proposal on the graph and accepts or "
            "rejects it. Work in this loop. 1) explain (and list_models, get_model, "
            "search) to understand the models you will touch (propose_docs files a "
            "description-only change). 2) impact_of to see what depends on them, and "
            "column_lineage before you rename or remove a column. 3) preview_change "
            "with the full new file contents to check the effect without saving "
            "anything, and fix new warnings and SQL errors. "
            "4) propose_change with the same files, a clear title, and a rationale in plain "
            "English. 5) Poll get_proposal to see whether it was accepted or rejected, and "
            "to read the person's comments. 6) If they ask for changes, call "
            "propose_change again with revises set to the old proposal id; the old one is "
            "marked superseded. Models can carry business rules (see list_rules and the "
            "rules field of get_model and explain). If a change touches a rule, say so in "
            "the rationale and name the rule."
        ),
        version=__version__,
    )

    def _rules_for(model: str) -> list[dict[str, Any]]:
        return [
            {
                "id": m.rule.id,
                "name": m.rule.name,
                "description": m.rule.description,
                "owner": m.rule.owner,
                "columns": m.columns,
            }
            for m in state.rules().applied_to(model)
        ]

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
        data = node.model_dump(mode="json")
        data["rules"] = _rules_for(node.name)
        return data

    @server.tool()
    def explain(name: str) -> dict[str, Any]:
        """Explain in plain English what a model does, step by step."""
        data = explain_model(state.project(), name).model_dump(mode="json")
        data["rules"] = _rules_for(data["model"])
        return data

    @server.tool()
    def list_rules() -> dict[str, Any]:
        """List business rules with their owner and the models and columns they apply to.

        Changes that touch a rule must say so in the rationale.
        """
        registry = state.rules()
        return {
            "rules": [r.model_dump(mode="json") for r in registry.rules],
            "warnings": registry.warnings,
        }

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
    def preview_change(files: list[dict[str, str]]) -> dict[str, Any]:
        """Dry run: see what a change would do, without saving a proposal.

        ``files`` is a list of ``{"path": ..., "content": ...}`` with the full new
        content of each file. Empty content deletes the file. Returns a plain-English
        summary, models added, changed, and removed, models affected downstream, new
        warnings (such as a ref to a missing model), and SQL that could not be read.
        Nothing is written. Use it to check your work before propose_change.
        """
        changes = [FileChange.model_validate(f) for f in files]
        try:
            store.check_paths([c.path for c in changes])
            preview = preview_changes(state.root, [(c.path, c.content) for c in changes])
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return {
            "summary": preview.summary,
            "added": preview.names_with_status("added"),
            "modified": preview.names_with_status("modified"),
            "removed": preview.names_with_status("removed"),
            "affected": preview.names_with_status("affected"),
            "new_warnings": preview.new_warnings,
            "parse_errors": [e.model_dump() for e in preview.parse_errors],
            "details": [c.model_dump(mode="json") for c in preview.diff.changes],
            "ok": not preview.new_warnings and not preview.parse_errors,
        }

    @server.tool()
    def sample_rows(name: str, limit: int = 10) -> dict[str, Any]:
        """Run a model on small local sample data and return a few rows.

        Use it to sanity-check logic. It runs in memory and never touches the
        warehouse. If sample data is missing, ``error`` names the model and the
        table to add.
        """
        try:
            return sampler.sample(name, limit).model_dump(mode="json")
        except KeyError as exc:
            raise ValueError(f"No model named {name!r}") from exc

    @server.tool()
    def search(query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Find models, sources, seeds, and columns by name or description.

        Best matches come first. Each hit has a kind, node name, optional column,
        and a short snippet.
        """
        hits = search_project(state.project(), state.lineage(), query, limit)
        return [h.model_dump(mode="json", exclude={"score"}) for h in hits]

    @server.tool()
    def column_lineage(model: str, column: str) -> dict[str, Any]:
        """Show which columns a column is built from and which columns use it.

        Call this before you rename, remove, or change the meaning of a column.
        Everything under ``downstream`` may break. Upstream and downstream lists
        are nearest first and cover every hop, not just the direct neighbours.
        """
        node = state.project().get(model)
        if node is None:
            raise ToolError(f"No model named {model!r}")
        try:
            view = column_lineage_view(state.project(), state.lineage(), node, column)
        except KeyError as exc:
            raise ToolError(exc.args[0]) from exc
        return view.model_dump(mode="json")

    @server.tool()
    def propose_change(
        title: str,
        rationale: str,
        files: list[dict[str, str]],
        author: str = "agent",
        revises: str | None = None,
    ) -> dict[str, Any]:
        """Propose edits to the dbt project for a person to review.

        ``files`` is a list of ``{"path": ..., "content": ...}`` with the full new
        content of each file, relative to the project root. Empty content deletes
        the file. Set ``revises`` to the id of an earlier proposal to replace it after
        feedback; that proposal is marked superseded. Returns the proposal id.
        """
        proposal = store.create(
            Proposal(
                title=title,
                rationale=rationale,
                author=author,
                changes=[FileChange.model_validate(f) for f in files],
                revises=revises,
            )
        )
        return {"id": proposal.id, "status": proposal.status}

    @server.tool()
    def propose_docs(
        model: str,
        description: str | None = None,
        columns: dict[str, str] | None = None,
        rationale: str = "",
        author: str = "agent",
    ) -> dict[str, Any]:
        """Propose a new description and/or column descriptions for a model.

        ``columns`` maps column name to description. Leave out anything that should
        stay as it is. This files a normal proposal containing the updated YAML file,
        so a person still reviews it before anything is written.
        """
        if description is None and not columns:
            raise ToolError("Give a description, column descriptions, or both.")
        try:
            edit = update_docs(
                state.project(), model, DocsUpdate(description=description, columns=columns or {})
            )
        except KeyError as exc:
            raise ToolError(f"No model named {model!r}") from exc
        proposal = store.create(
            Proposal(
                title=f"Update docs for {model}",
                rationale=rationale,
                author=author,
                changes=[FileChange(path=edit.path, content=edit.content)],
            )
        )
        return {"id": proposal.id, "status": proposal.status, "path": edit.path}

    @server.tool()
    def get_proposal(id: str) -> dict[str, Any]:
        """Return a proposal's status and the comments people left on it.

        Poll this after propose_change. Status is pending, accepted, rejected, or
        superseded. Comments include the reason for a rejection.
        """
        proposal = store.get(id)
        if proposal is None:
            raise ToolError(f"No proposal with id {id!r}")
        return {
            "id": proposal.id,
            "title": proposal.title,
            "status": proposal.status,
            "revises": proposal.revises,
            "superseded_by": proposal.superseded_by,
            "files": [c.path for c in proposal.changes],
            "comments": [c.model_dump(mode="json") for c in proposal.comments],
        }

    @server.tool()
    def list_proposals() -> list[dict[str, Any]]:
        """List proposals and whether each is pending, accepted, rejected, or superseded."""
        return [
            {"id": p.id, "title": p.title, "status": p.status, "author": p.author}
            for p in store.list()
        ]

    return server
