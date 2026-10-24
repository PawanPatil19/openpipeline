"""Business rules through the API, the MCP server, and the CLI."""

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openpipeline.api import create_app
from openpipeline.cli import app as cli_app
from openpipeline.mcp_server import create_mcp_server

runner = CliRunner()


def _client(project_dir: Path) -> TestClient:
    return TestClient(create_app(project_dir, serve_ui=False))


def _call(server: Any, tool: str, args: dict[str, Any]) -> Any:
    result = asyncio.run(server.call_tool(tool, args))
    assert not result.is_error, result
    structured = result.structured_content
    if structured is not None:
        return structured.get("result", structured)
    return json.loads(result.content[0].text)


def test_api_rules(project_dir: Path) -> None:
    client = _client(project_dir)
    body = client.get("/api/rules").json()
    assert body["warnings"] == []
    by_id = {r["id"]: r for r in body["rules"]}
    assert set(by_id) == {"no-test-orders", "lifetime-value", "amounts-in-dollars"}
    assert by_id["lifetime-value"]["owner"] == "growth-team"
    assert {link["model"] for link in by_id["lifetime-value"]["applies_to"]} == {
        "customers",
        "orders",
    }


def test_api_model_rules(project_dir: Path) -> None:
    client = _client(project_dir)
    rules = client.get("/api/models/orders/rules").json()
    assert [r["rule"]["id"] for r in rules] == ["lifetime-value"]
    assert rules[0]["columns"] == ["amount"]
    assert client.get("/api/models/stg_customers/rules").json() == []
    assert client.get("/api/models/nope/rules").status_code == 404


def test_rule_warnings_show_in_project_info(project_dir: Path) -> None:
    (project_dir / "openpipeline.yml").write_text(
        "rules:\n  - id: a\n    name: A\n    applies_to: [{model: ghost}]\n"
    )
    warnings = _client(project_dir).get("/api/project").json()["warnings"]
    assert any("unknown model 'ghost'" in w for w in warnings)


def test_reloads_when_openpipeline_yml_changes(project_dir: Path) -> None:
    client = _client(project_dir)
    assert len(client.get("/api/rules").json()["rules"]) == 3
    time.sleep(0.01)
    rules_file = project_dir / "openpipeline.yml"
    rules_file.write_text(
        rules_file.read_text()
        + "\n  - id: extra\n    name: Extra\n    applies_to:\n      - model: orders\n"
    )
    assert len(client.get("/api/rules").json()["rules"]) == 4
    assert "extra" in {r["rule"]["id"] for r in client.get("/api/models/orders/rules").json()}


def test_mcp_list_rules_and_model_rules(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    rules = _call(server, "list_rules", {})
    assert {r["id"] for r in rules["rules"]} == {
        "no-test-orders",
        "lifetime-value",
        "amounts-in-dollars",
    }
    model = _call(server, "get_model", {"name": "customers"})
    assert [r["id"] for r in model["rules"]] == ["lifetime-value"]
    assert model["rules"][0]["columns"] == ["lifetime_value"]
    story = _call(server, "explain", {"name": "stg_orders"})
    assert [r["id"] for r in story["rules"]] == ["no-test-orders"]
    instructions = server.instructions or ""
    assert "rationale" in instructions
    assert "rule" in instructions


def test_cli_rules_grouped_by_owner(project_dir: Path) -> None:
    result = runner.invoke(cli_app, ["rules", str(project_dir)])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines.index("data-platform") < lines.index("finance-team") < lines.index("growth-team")
    assert "  Lifetime value is what a customer has paid (lifetime-value)" in lines
    assert "    applies to customers [lifetime_value]" in lines

    as_json = runner.invoke(cli_app, ["rules", str(project_dir), "--json"])
    assert len(json.loads(as_json.stdout)["rules"]) == 3


def test_cli_rules_without_a_file(project_dir: Path) -> None:
    (project_dir / "openpipeline.yml").unlink()
    result = runner.invoke(cli_app, ["rules", str(project_dir)])
    assert result.exit_code == 0
    assert "No business rules found" in result.stdout


def test_review_mentions_rules(project_dir: Path, tmp_path: Path) -> None:
    head = tmp_path / "head"
    shutil.copytree(project_dir, head)
    stg = head / "models" / "staging" / "stg_orders.sql"
    stg.write_text(stg.read_text().replace("!= 'test'", "= 'shipped'"))
    result = runner.invoke(cli_app, ["review", str(project_dir), str(head)])
    assert result.exit_code == 0
    assert "#### Business rules touched" in result.stdout
    assert "Test orders are never real orders" in result.stdout
