import time
from pathlib import Path

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
