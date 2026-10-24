import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from openpipeline.api import create_app
from openpipeline.proposals import FileChange, Proposal, ProposalStore


def _client(project_dir: Path) -> TestClient:
    return TestClient(create_app(project_dir, serve_ui=False))


def test_health_and_project(project_dir: Path) -> None:
    client = _client(project_dir)
    assert client.get("/api/health").json()["status"] == "ok"
    info = client.get("/api/project").json()
    assert info["name"] == "jaffle_shop"
    assert info["model_count"] == 5
    assert info["source_count"] == 3


def test_graph_story_impact(project_dir: Path) -> None:
    client = _client(project_dir)
    graph = client.get("/api/graph").json()
    assert len(graph["nodes"]) == 8

    story = client.get("/api/models/customers/story").json()
    assert story["grain"] == ["customer_id", "first_name", "last_name"]

    impact = client.get("/api/models/stg_orders/impact").json()
    assert impact["downstream"] == ["orders", "customers"]

    assert client.get("/api/models/nope").status_code == 404


def test_reloads_when_files_change(project_dir: Path) -> None:
    client = _client(project_dir)
    assert client.get("/api/project").json()["model_count"] == 5
    time.sleep(0.01)
    (project_dir / "models" / "marts" / "revenue.sql").write_text(
        "select sum(amount) as revenue from {{ ref('orders') }}"
    )
    assert client.get("/api/project").json()["model_count"] == 6


def test_accept_and_reject_proposals(project_dir: Path) -> None:
    store = ProposalStore(project_dir)
    accepted = store.create(
        Proposal(
            title="Add revenue",
            changes=[FileChange(path="models/marts/revenue.sql", content="select 1 as revenue")],
        )
    )
    rejected = store.create(Proposal(title="Nope"))
    client = _client(project_dir)

    assert len(client.get("/api/proposals?status=pending").json()) == 2

    r = client.post(f"/api/proposals/{accepted.id}", json={"status": "accepted"})
    assert r.status_code == 200
    assert (project_dir / "models" / "marts" / "revenue.sql").read_text() == "select 1 as revenue"

    assert (
        client.post(f"/api/proposals/{rejected.id}", json={"status": "rejected"}).status_code == 200
    )
    again = client.post(f"/api/proposals/{accepted.id}", json={"status": "rejected"})
    assert again.status_code == 409
    missing = client.post("/api/proposals/000000000000", json={"status": "accepted"})
    assert missing.status_code == 404


def test_serves_ui_when_built(project_dir: Path, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>openpipeline</html>")
    monkeypatch.setattr("openpipeline.api.STATIC_DIR", static)
    client = TestClient(create_app(project_dir))
    assert "openpipeline" in client.get("/").text
    assert "openpipeline" in client.get("/models/customers").text  # SPA fallback
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/does-not-exist").status_code == 404


def test_save_docs_writes_yaml_and_returns_model(project_dir: Path) -> None:
    client = _client(project_dir)
    resp = client.put(
        "/api/models/customers/docs",
        json={"description": "Everyone who ordered.", "columns": {"first_name": "Given name."}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "Everyone who ordered."
    assert {c["name"]: c["description"] for c in body["columns"]}["first_name"] == "Given name."
    # The change is on disk and the graph sees it.
    assert "Everyone who ordered." in (project_dir / "models/marts/schema.yml").read_text()
    again = client.get("/api/models/customers").json()
    assert again["description"] == "Everyone who ordered."
    nodes = {n["name"]: n for n in client.get("/api/graph").json()["nodes"]}
    assert nodes["customers"]["description"] == "Everyone who ordered."


def test_save_docs_rejects_unknown_and_non_models(project_dir: Path) -> None:
    client = _client(project_dir)
    assert client.put("/api/models/nope/docs", json={"description": "x"}).status_code == 404
    assert client.put("/api/models/raw_orders/docs", json={"description": "x"}).status_code == 404


def _ai_client(project_dir: Path, fake: Any) -> TestClient:
    return TestClient(create_app(project_dir, serve_ui=False, ai_client=fake))


def test_ai_status(project_dir: Path, fake_ai: Any) -> None:
    off = _client(project_dir).get("/api/ai").json()
    assert off["available"] is False
    assert off["reason"]
    on = _ai_client(project_dir, fake_ai).get("/api/ai").json()
    assert on == {"available": True, "model": "fake-claude", "reason": None}


def test_ai_explanation_and_cache(project_dir: Path, fake_ai: Any) -> None:
    client = _ai_client(project_dir, fake_ai)
    url = "/api/models/customers/ai-explanation"
    first = client.post(url).json()
    assert first["summary"] == "One row per customer."
    assert first["cached"] is False
    assert first["ai_model"] == "fake-claude"
    assert client.post(url).json()["cached"] is True
    assert len(fake_ai.calls) == 1
    assert client.post(url + "?refresh=true").json()["cached"] is False
    assert len(fake_ai.calls) == 2


def test_ai_explanation_errors(project_dir: Path, fake_ai: Any) -> None:
    unavailable = _client(project_dir).post("/api/models/customers/ai-explanation")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]

    fake_ai.error = "Rate limited."
    failed = _ai_client(project_dir, fake_ai).post("/api/models/customers/ai-explanation")
    assert failed.status_code == 502
    assert failed.json()["detail"] == "Rate limited."

    client = _ai_client(project_dir, fake_ai)
    assert client.post("/api/models/nope/ai-explanation").status_code == 404
    assert client.post("/api/models/raw_orders/ai-explanation").status_code == 404
