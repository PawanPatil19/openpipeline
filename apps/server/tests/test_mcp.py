import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from openpipeline.mcp_server import create_mcp_server
from openpipeline.proposals import ProposalStore


def _call(server: Any, tool: str, args: dict[str, Any]) -> Any:
    result = asyncio.run(server.call_tool(tool, args))
    assert not result.is_error, result
    structured = result.structured_content
    if structured is not None:
        # Non-object return values are wrapped as {"result": ...}.
        return structured.get("result", structured)
    return json.loads(result.content[0].text)


def test_tools_are_registered(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {
        "list_models",
        "get_model",
        "explain",
        "impact_of",
        "preview_change",
        "list_rules",
        "search",
        "column_lineage",
        "propose_change",
        "get_proposal",
        "propose_docs",
        "propose_glossary_term",
        "list_glossary",
        "list_proposals",
        "sample_rows",
    }


def test_read_tools(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    models = _call(server, "list_models", {})
    assert {m["name"] for m in models} >= {"customers", "orders"}
    assert _call(server, "explain", {"name": "customers"})["model"] == "customers"
    assert "customers" in _call(server, "impact_of", {"name": "orders"})["downstream"]


def test_propose_change_creates_pending_proposal(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    result = _call(
        server,
        "propose_change",
        {
            "title": "Add revenue model",
            "rationale": "Finance asked for daily revenue",
            "files": [{"path": "models/marts/revenue.sql", "content": "select 1"}],
        },
    )
    assert result["status"] == "pending"
    stored = ProposalStore(project_dir).get(result["id"])
    assert stored is not None
    assert stored.changes[0].path == "models/marts/revenue.sql"
    # Nothing is written until a person accepts it.
    assert not (project_dir / "models" / "marts" / "revenue.sql").exists()


def test_propose_docs_files_a_yaml_proposal(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    assert "propose_docs" in {t.name for t in asyncio.run(server.list_tools())}
    schema = project_dir / "models" / "marts" / "schema.yml"
    before = schema.read_text()
    result = _call(
        server,
        "propose_docs",
        {
            "model": "customers",
            "description": "Everyone who ordered.",
            "columns": {"first_name": "Given name."},
            "rationale": "Finance asked.",
        },
    )
    assert result["status"] == "pending"
    assert result["path"] == "models/marts/schema.yml"
    stored = ProposalStore(project_dir).get(result["id"])
    assert stored is not None
    assert stored.rationale == "Finance asked."
    assert "Everyone who ordered." in stored.changes[0].content
    # Agents only propose: the file is untouched until a person accepts.
    assert schema.read_text() == before
    ProposalStore(project_dir).set_status(stored.id, "accepted")
    assert "Everyone who ordered." in schema.read_text()


def test_propose_docs_needs_something_to_change(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    with pytest.raises(ToolError, match="Give a description"):
        asyncio.run(server.call_tool("propose_docs", {"model": "customers"}))


def test_sample_rows(project_dir: Path) -> None:
    pytest.importorskip("duckdb")
    server = create_mcp_server(project_dir)
    result = _call(server, "sample_rows", {"name": "customers", "limit": 3})
    assert result["error"] is None
    assert len(result["rows"]) == 3
    (project_dir / "sample_data" / "raw.customers.csv").unlink()
    missing = _call(server, "sample_rows", {"name": "customers"})
    assert missing["error"]["missing_table"] == "raw.customers"
