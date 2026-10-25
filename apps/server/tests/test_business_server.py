"""Business words through the API, the MCP server, and the CLI."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError
from typer.testing import CliRunner

from openpipeline.api import create_app
from openpipeline.cli import app as cli_app
from openpipeline.mcp_server import create_mcp_server
from openpipeline.proposals import ProposalStore

runner = CliRunner()


def _client(project_dir: Path) -> TestClient:
    return TestClient(create_app(project_dir, serve_ui=False), base_url="http://127.0.0.1")


def _call(server: Any, tool: str, args: dict[str, Any]) -> Any:
    result = asyncio.run(server.call_tool(tool, args))
    assert not result.is_error, result
    structured = result.structured_content
    if structured is not None:
        return structured.get("result", structured)
    return json.loads(result.content[0].text)


# --- API ---------------------------------------------------------------------------------


def test_api_glossary(project_dir: Path) -> None:
    body = _client(project_dir).get("/api/glossary").json()
    assert body["warnings"] == []
    by_name = {t["name"]: t for t in body["terms"]}
    assert by_name["customer_id"]["label"] == "Customer"
    assert by_name["customer_id"]["aliases"] == ["user_id"]
    assert by_name["orders"]["definition"].startswith("One row per order")


def test_api_business_story(project_dir: Path) -> None:
    client = _client(project_dir)
    body = client.get("/api/models/customers/business-story").json()
    assert body["title"] == "Customers"
    assert body["summary"].startswith("Customers brings together Cleaned customer list")
    assert body["technical"]["summary"].startswith("customers combines")
    assert {c["name"]: c["label"] for c in body["columns"]}["lifetime_value"] == "Lifetime value"
    assert any(t["name"] == "amount" for t in body["terms_used"])
    # The technical story endpoint is unchanged.
    assert client.get("/api/models/customers/story").json() == body["technical"]
    # Lookups work by unique id too, and unknown names are a 404.
    assert client.get("/api/models/model.jaffle_shop.customers/business-story").status_code == 200
    assert client.get("/api/models/nope/business-story").status_code == 404


def test_api_business_story_for_a_source(project_dir: Path) -> None:
    body = _client(project_dir).get("/api/models/raw.orders/business-story").json()
    assert body["title"] == "Raw orders"
    assert body["steps"] == []


def test_glossary_follows_file_changes_and_warns(project_dir: Path) -> None:
    client = _client(project_dir)
    assert client.get("/api/models/orders/business-story").json()["title"] == "Orders"
    path = project_dir / "openpipeline.yml"
    path.write_text(path.read_text().replace("label: Orders\n", "label: Sales\n", 1) + "\n# end\n")
    assert client.get("/api/models/orders/business-story").json()["title"] == "Sales"

    path.write_text("glossary:\n  - name: a\n  - name: a\n    label: A\n")
    warnings = client.get("/api/project").json()["warnings"]
    assert any("entry 'a' has no label" in w for w in warnings)
    assert client.get("/api/glossary").json()["warnings"]


# --- MCP ---------------------------------------------------------------------------------


def test_propose_glossary_term_files_a_proposal_and_writes_nothing(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    path = project_dir / "openpipeline.yml"
    before = path.read_text()

    made = _call(
        server,
        "propose_glossary_term",
        {
            "name": "refund_id",
            "label": "Refund",
            "definition": "Money handed back to a customer.",
            "rationale": "Finance asked for it.",
        },
    )
    assert made["status"] == "pending"
    assert made["path"] == "openpipeline.yml"
    assert path.read_text() == before  # Not written until a person accepts.

    store = ProposalStore(project_dir)
    proposal = store.get(made["id"])
    assert proposal is not None
    assert proposal.title == "Add glossary term: Refund"
    assert proposal.rationale == "Finance asked for it."
    assert [c.path for c in proposal.changes] == ["openpipeline.yml"]

    # The file is only written when a person accepts, through the same API as any proposal.
    client = _client(project_dir)
    assert client.get("/api/glossary").json()["terms"][-1]["name"] != "refund_id"
    accepted = client.post(f"/api/proposals/{made['id']}", json={"status": "accepted"})
    assert accepted.status_code == 200

    data = yaml.safe_load(path.read_text())
    assert data["glossary"][-1] == {
        "name": "refund_id",
        "label": "Refund",
        "definition": "Money handed back to a customer.",
    }
    old = yaml.safe_load(before)
    assert data["rules"] == old["rules"]  # Existing rules are kept.
    assert data["glossary"][:-1] == old["glossary"]
    assert "# Business rules for this project." in path.read_text()

    # And the new term is live straight away.
    terms = {t["name"]: t for t in client.get("/api/glossary").json()["terms"]}
    assert terms["refund_id"]["label"] == "Refund"
    assert client.get("/api/glossary").json()["warnings"] == []


def test_propose_glossary_term_in_a_project_without_a_file(project_dir: Path) -> None:
    (project_dir / "openpipeline.yml").unlink()
    server = create_mcp_server(project_dir)
    made = _call(server, "propose_glossary_term", {"name": "order_id", "label": "Order"})
    assert not (project_dir / "openpipeline.yml").exists()
    ProposalStore(project_dir).set_status(made["id"], "accepted")
    assert yaml.safe_load((project_dir / "openpipeline.yml").read_text()) == {
        "glossary": [{"name": "order_id", "label": "Order"}]
    }


def test_propose_glossary_term_rejects_bad_input(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    for args in ({"name": "", "label": "x"}, {"name": "x", "label": " "}):
        with pytest.raises(ToolError, match="needs a"):
            asyncio.run(server.call_tool("propose_glossary_term", args))
    assert ProposalStore(project_dir).list() == []


def test_a_rejected_glossary_proposal_changes_nothing(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    before = (project_dir / "openpipeline.yml").read_text()
    made = _call(server, "propose_glossary_term", {"name": "x_id", "label": "X"})
    ProposalStore(project_dir).set_status(made["id"], "rejected", reason="Not now")
    assert (project_dir / "openpipeline.yml").read_text() == before


def test_explain_has_a_business_view(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    data = _call(server, "explain", {"name": "customers"})
    assert data["summary"].startswith("customers combines")  # Technical, as before.
    business = data["business"]
    assert business["title"] == "Customers"
    assert "technical" not in business
    assert {t["name"] for t in business["terms_used"]} >= {"customer_id", "lifetime_value"}
    assert data["rules"][0]["id"] == "lifetime-value"


def test_list_glossary(project_dir: Path) -> None:
    server = create_mcp_server(project_dir)
    data = _call(server, "list_glossary", {})
    assert data["warnings"] == []
    assert {t["name"] for t in data["terms"]} >= {"customer_id", "orders"}


# --- CLI ---------------------------------------------------------------------------------


def test_explain_business(project_dir: Path) -> None:
    result = runner.invoke(cli_app, ["explain", "customers", str(project_dir), "--business"])
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert out.startswith("Customers\n")
    assert "Customers brings together Cleaned customer list and Orders" in out
    assert "  Lifetime value: The total of Amount paid" in out
    assert "Words used" in out
    assert "  Amount paid: Money received for the order, in dollars." in out
    assert "lifetime_value" not in out
    assert "stg_customers" not in out


def test_explain_business_json_and_unknown_model(project_dir: Path) -> None:
    result = runner.invoke(
        cli_app, ["explain", "customers", str(project_dir), "--business", "--json"]
    )
    data = json.loads(result.stdout)
    assert data["title"] == "Customers"
    assert data["technical"]["model"] == "customers"

    missing = runner.invoke(cli_app, ["explain", "nope", str(project_dir), "--business"])
    assert missing.exit_code == 1


def test_explain_without_the_flag_is_unchanged(project_dir: Path) -> None:
    result = runner.invoke(cli_app, ["explain", "customers", str(project_dir)])
    assert "lifetime_value: the total of amount" in result.stdout
