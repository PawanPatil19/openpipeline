from pathlib import Path

from typer.testing import CliRunner

from openpipeline.cli import app
from openpipeline.demo import example_dir
from openpipeline.proposals import ProposalStore
from openpipeline_core import load_project, load_rules

runner = CliRunner()


def test_demo_no_serve_prepares_a_project(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    result = runner.invoke(app, ["demo", "--no-serve", "--dir", str(target)])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str(target.resolve())

    assert (target / "dbt_project.yml").is_file()
    assert (target / "models" / "marts" / "customers.sql").is_file()

    pending = ProposalStore(target).list("pending")
    assert len(pending) == 1
    proposal = pending[0]
    assert proposal.rationale
    paths = {c.path for c in proposal.changes}
    assert "models/marts/revenue_by_month.sql" in paths
    assert "openpipeline.yml" in paths

    # The proposal is only filed. The project itself is untouched until someone accepts.
    assert not (target / "models" / "marts" / "revenue_by_month.sql").exists()
    project = load_project(target)
    assert project.get("customers") is not None
    assert project.get("revenue_by_month") is None


def test_demo_proposal_can_be_accepted(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    assert runner.invoke(app, ["demo", "--no-serve", "--dir", str(target)]).exit_code == 0
    store = ProposalStore(target)
    store.set_status(store.list("pending")[0].id, "accepted")
    project = load_project(target)
    assert project.get("revenue_by_month") is not None
    rules = {r.id: r for r in load_rules(target, project).rules}
    assert "monthly-revenue" in rules
    assert any(link.model == "revenue_by_month" for link in rules["amounts-in-dollars"].applies_to)


def test_demo_uses_a_temp_folder_by_default() -> None:
    result = runner.invoke(app, ["demo", "--no-serve"])
    assert result.exit_code == 0, result.output
    root = Path(result.stdout.strip())
    assert (root / "dbt_project.yml").is_file()
    assert len(ProposalStore(root).list("pending")) == 1


def test_demo_refuses_a_folder_that_is_not_empty(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("mine")
    result = runner.invoke(app, ["demo", "--no-serve", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert (tmp_path / "keep.txt").read_text() == "mine"


def test_example_dir_exists() -> None:
    assert (example_dir() / "dbt_project.yml").is_file()
