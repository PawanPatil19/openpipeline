from pathlib import Path

import pytest

from openpipeline.proposals import FileChange, Proposal, ProposalStore


@pytest.mark.parametrize(
    "path", ["../evil.sql", "/etc/passwd", ".openpipeline/proposals/x.json", ".git/config", "."]
)
def test_rejects_unsafe_paths(project_dir: Path, path: str) -> None:
    store = ProposalStore(project_dir)
    with pytest.raises(ValueError, match=r"outside the project|not allowed"):
        store.create(Proposal(title="bad", changes=[FileChange(path=path, content="x")]))


def test_empty_content_deletes_file(project_dir: Path) -> None:
    store = ProposalStore(project_dir)
    target = project_dir / "models" / "staging" / "stg_payments.sql"
    p = store.create(
        Proposal(
            title="rm", changes=[FileChange(path="models/staging/stg_payments.sql", content="")]
        )
    )
    store.set_status(p.id, "accepted")
    assert not target.exists()


def test_get_rejects_odd_ids(project_dir: Path) -> None:
    assert ProposalStore(project_dir).get("../../etc") is None
