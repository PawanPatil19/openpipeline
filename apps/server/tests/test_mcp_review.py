import asyncio
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from openpipeline.mcp_server import create_mcp_server
from openpipeline.proposals import ProposalStore

from .test_mcp import _call


def test_preview_change_is_a_dry_run(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    result = _call(
        server,
        "preview_change",
        {
            "files": [
                {"path": "models/marts/revenue.sql", "content": "select * from {{ ref('orders') }}"}
            ]
        },
    )
    assert result["added"] == ["revenue"]
    assert result["ok"] is True
    assert ProposalStore(project_dir).list() == []
    assert not (project_dir / "models" / "marts" / "revenue.sql").exists()


def test_preview_change_reports_problems_and_affected(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    bad = _call(
        server,
        "preview_change",
        {"files": [{"path": "models/marts/x.sql", "content": "select * from {{ ref('ghost') }}"}]},
    )
    assert bad["ok"] is False
    assert any("ghost" in w for w in bad["new_warnings"])
    gone = _call(
        server,
        "preview_change",
        {"files": [{"path": "models/staging/stg_orders.sql", "content": ""}]},
    )
    assert gone["removed"] == ["stg_orders"]
    assert "orders" in gone["modified"]
    assert "customers" in gone["affected"]


def test_preview_change_refuses_unsafe_paths(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    with pytest.raises(ToolError, match="outside the project"):
        asyncio.run(
            server.call_tool("preview_change", {"files": [{"path": "../x.sql", "content": "x"}]})
        )


def test_get_proposal_and_revise_loop(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    files = [{"path": "models/marts/revenue.sql", "content": "select 1 as revenue"}]
    first = _call(server, "propose_change", {"title": "v1", "rationale": "r", "files": files})
    ProposalStore(project_dir).set_status(first["id"], "rejected", reason="Use orders as input")

    seen = _call(server, "get_proposal", {"id": first["id"]})
    assert seen["status"] == "rejected"
    assert seen["comments"][0]["text"] == "Use orders as input"

    second = _call(
        server,
        "propose_change",
        {"title": "v2", "rationale": "r", "files": files, "revises": first["id"]},
    )
    assert _call(server, "get_proposal", {"id": second["id"]})["revises"] == first["id"]
    # A rejected proposal keeps its status; only pending ones become superseded.
    assert _call(server, "get_proposal", {"id": first["id"]})["status"] == "rejected"

    third = _call(
        server,
        "propose_change",
        {"title": "v3", "rationale": "r", "files": files, "revises": second["id"]},
    )
    old = _call(server, "get_proposal", {"id": second["id"]})
    assert old["status"] == "superseded"
    assert old["superseded_by"] == third["id"]


def test_get_proposal_unknown_id_errors(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    with pytest.raises(ToolError, match="No proposal"):
        asyncio.run(server.call_tool("get_proposal", {"id": "000000000000"}))
