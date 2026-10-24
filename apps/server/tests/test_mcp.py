import asyncio
import json
from pathlib import Path
from typing import Any

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
        "propose_change",
        "list_proposals",
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
