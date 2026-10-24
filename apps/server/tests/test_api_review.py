import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openpipeline.api import create_app
from openpipeline.proposals import FileChange, Proposal, ProposalStore


def _client(project_dir: Path) -> TestClient:
    return TestClient(create_app(project_dir, serve_ui=False))


def _propose(
    project_dir: Path,
    path: str = "models/marts/revenue.sql",
    content: str = "select 1 as r",
) -> str:
    store = ProposalStore(project_dir)
    return store.create(Proposal(title="t", changes=[FileChange(path=path, content=content)])).id


def test_preview_endpoint(project_dir: Path) -> None:
    client = _client(project_dir)
    pid = _propose(project_dir, content="select * from {{ ref('orders') }}")
    r = client.get(f"/api/proposals/{pid}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["files"][0]["change"] == "added"
    assert body["diff"]["changes"][0]["name"] == "revenue"
    assert any(n["status"] == "added" for n in body["graph"]["nodes"])
    assert client.get("/api/proposals/000000000000/preview").status_code == 404
    assert not (project_dir / "models" / "marts" / "revenue.sql").exists()


def test_base_fingerprints_recorded(project_dir: Path) -> None:
    store = ProposalStore(project_dir)
    p = store.create(
        Proposal(
            title="t",
            changes=[
                FileChange(path="models/staging/stg_orders.sql", content="select 1"),
                FileChange(path="models/new.sql", content="select 1"),
            ],
        )
    )
    assert p.base is not None
    assert len(p.base["models/staging/stg_orders.sql"] or "") == 64
    assert p.base["models/new.sql"] is None


def test_accept_conflict_then_force(project_dir: Path) -> None:
    target = project_dir / "models" / "staging" / "stg_orders.sql"
    pid = _propose(project_dir, "models/staging/stg_orders.sql", "select 1 as id")
    client = _client(project_dir)
    target.write_text(target.read_text() + "\n-- edited by someone\n")

    r = client.post(f"/api/proposals/{pid}", json={"status": "accepted"})
    assert r.status_code == 409
    assert r.json()["detail"]["changed_files"] == ["models/staging/stg_orders.sql"]
    assert "edited by someone" in target.read_text()

    r = client.post(f"/api/proposals/{pid}", json={"status": "accepted", "force": True})
    assert r.status_code == 200
    assert target.read_text() == "select 1 as id"


def test_conflict_when_new_file_appears_meanwhile(project_dir: Path) -> None:
    pid = _propose(project_dir)
    (project_dir / "models" / "marts" / "revenue.sql").write_text("select 2")
    client = _client(project_dir)
    assert client.post(f"/api/proposals/{pid}", json={"status": "accepted"}).status_code == 409


def test_comments_and_reject_reason(project_dir: Path) -> None:
    pid = _propose(project_dir)
    client = _client(project_dir)
    r = client.post(f"/api/proposals/{pid}/comments", json={"text": "Why a new model?"})
    assert r.status_code == 200
    assert r.json()["comments"][0]["author"] == "reviewer"
    assert client.post(f"/api/proposals/{pid}/comments", json={"text": ""}).status_code == 422
    missing = client.post("/api/proposals/000000000000/comments", json={"text": "x"})
    assert missing.status_code == 404

    r = client.post(f"/api/proposals/{pid}", json={"status": "rejected", "reason": "Not needed"})
    body = r.json()
    assert body["status"] == "rejected"
    assert [c["text"] for c in body["comments"]] == ["Why a new model?", "Not needed"]


def test_revises_supersedes_pending(project_dir: Path) -> None:
    store = ProposalStore(project_dir)
    old = _propose(project_dir)
    new = store.create(
        Proposal(
            title="v2",
            revises=old,
            changes=[FileChange(path="models/marts/r.sql", content="select 1")],
        )
    )
    client = _client(project_dir)
    listed = {p["id"]: p for p in client.get("/api/proposals").json()}
    assert listed[old]["status"] == "superseded"
    assert listed[old]["superseded_by"] == new.id
    assert listed[new.id]["revises"] == old
    assert client.post(f"/api/proposals/{old}", json={"status": "accepted"}).status_code == 409


def test_unknown_revises_is_refused(project_dir: Path) -> None:
    with pytest.raises(ValueError, match="to revise"):
        ProposalStore(project_dir).create(Proposal(title="x", revises="000000000000"))


def test_old_format_proposal_json_still_loads(project_dir: Path) -> None:
    folder = project_dir / ".openpipeline" / "proposals"
    folder.mkdir(parents=True)
    (folder / "abcdef123456.json").write_text(
        json.dumps(
            {
                "id": "abcdef123456",
                "title": "Old",
                "rationale": "",
                "author": "agent",
                "created_at": "2026-01-01T00:00:00Z",
                "status": "pending",
                "changes": [{"path": "models/marts/old.sql", "content": "select 1"}],
            }
        )
    )
    client = _client(project_dir)
    listed = client.get("/api/proposals").json()
    assert listed[0]["comments"] == []
    assert listed[0]["base"] is None
    # No fingerprint was recorded, so accepting skips the conflict check.
    r = client.post("/api/proposals/abcdef123456", json={"status": "accepted"})
    assert r.status_code == 200
    assert (project_dir / "models" / "marts" / "old.sql").exists()
