import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError
from typer.testing import CliRunner

from openpipeline.api import create_app
from openpipeline.cli import app as cli_app
from openpipeline.mcp_server import create_mcp_server

LOCAL = "http://127.0.0.1"

runner = CliRunner()


def _client(project_dir: Path) -> TestClient:
    return TestClient(create_app(project_dir, serve_ui=False), base_url=LOCAL)


def _call(server: Any, tool: str, args: dict[str, Any]) -> Any:
    result = asyncio.run(server.call_tool(tool, args))
    assert not result.is_error, result
    structured = result.structured_content
    if structured is not None:
        return structured.get("result", structured)
    return json.loads(result.content[0].text)


def test_search_endpoint(project_dir: Path) -> None:
    client = _client(project_dir)
    hits = client.get("/api/search", params={"q": "lifetime", "limit": 5}).json()
    assert hits[0]["kind"] == "column"
    assert hits[0]["name"] == "customers"
    assert hits[0]["column"] == "lifetime_value"
    assert hits[0]["node_id"] == "model.jaffle_shop.customers"
    assert client.get("/api/search", params={"q": ""}).json() == []
    assert len(client.get("/api/search", params={"q": "order", "limit": 2}).json()) == 2
    assert client.get("/api/search", params={"q": "x", "limit": 0}).status_code == 422


def test_columns_endpoint(project_dir: Path) -> None:
    client = _client(project_dir)
    cols = client.get("/api/models/customers/columns").json()
    assert [c["name"] for c in cols][-1] == "lifetime_value"
    ltv = cols[-1]
    assert ltv["description"].startswith("Total amount")
    assert ltv["upstream"] == [
        {
            "node_id": "model.jaffle_shop.orders",
            "node": "orders",
            "kind": "model",
            "column": "amount",
        }
    ]
    assert client.get("/api/models/nope/columns").status_code == 404
    # Sources work too, with columns learned from the models that read them.
    assert "amount" in [c["name"] for c in client.get("/api/models/raw.payments/columns").json()]


def test_column_lineage_endpoint(project_dir: Path) -> None:
    client = _client(project_dir)
    body = client.get("/api/models/orders/columns/amount/lineage").json()
    assert [(r["node"], r["column"]) for r in body["upstream"]] == [
        ("stg_payments", "amount"),
        ("raw.payments", "amount"),
    ]
    assert [(r["node"], r["column"]) for r in body["downstream"]] == [
        ("customers", "lifetime_value")
    ]
    assert client.get("/api/models/orders/columns/nope/lineage").status_code == 404
    assert client.get("/api/models/nope/columns/x/lineage").status_code == 404


def test_lineage_index_is_rebuilt_when_files_change(project_dir: Path) -> None:
    client = _client(project_dir)
    assert client.get("/api/models/orders/columns/amount/lineage").status_code == 200
    time.sleep(0.01)
    path = project_dir / "models" / "marts" / "orders.sql"
    path.write_text(path.read_text().replace("0) as amount", "0) as paid"))
    assert client.get("/api/models/orders/columns/amount/lineage").status_code == 404
    assert client.get("/api/models/orders/columns/paid/lineage").status_code == 200


def test_mcp_search_and_column_lineage(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    hits = _call(server, "search", {"query": "lifetime"})
    assert hits[0]["column"] == "lifetime_value"
    body = _call(server, "column_lineage", {"model": "customers", "column": "lifetime_value"})
    assert [(r["node"], r["column"]) for r in body["upstream"]] == [
        ("orders", "amount"),
        ("stg_payments", "amount"),
        ("raw.payments", "amount"),
    ]
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert "before you rename" in (tools["column_lineage"].description or "").lower()
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("column_lineage", {"model": "customers", "column": "x"}))
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("column_lineage", {"model": "nope", "column": "x"}))


def test_cli_lineage(project_dir: Path) -> None:
    result = runner.invoke(cli_app, ["lineage", "customers", "lifetime_value", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "customers.lifetime_value" in result.stdout
    assert "orders.amount" in result.stdout
    assert "raw.payments.amount" in result.stdout

    result = runner.invoke(cli_app, ["lineage", "orders", "amount", str(project_dir)])
    assert "Used by:\n  customers.lifetime_value" in result.stdout

    as_json = runner.invoke(cli_app, ["lineage", "orders", "amount", str(project_dir), "--json"])
    assert json.loads(as_json.stdout)["downstream"][0]["column"] == "lifetime_value"

    assert runner.invoke(cli_app, ["lineage", "nope", "x", str(project_dir)]).exit_code == 1
    assert runner.invoke(cli_app, ["lineage", "orders", "x", str(project_dir)]).exit_code == 1
