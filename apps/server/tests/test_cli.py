import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from openpipeline import __version__
from openpipeline.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_explain(project_dir: Path) -> None:
    result = runner.invoke(app, ["explain", "customers", str(project_dir)])
    assert result.exit_code == 0
    assert "one row per customer_id" in result.stdout

    as_json = runner.invoke(app, ["explain", "customers", str(project_dir), "--json"])
    assert json.loads(as_json.stdout)["model"] == "customers"

    missing = runner.invoke(app, ["explain", "nope", str(project_dir)])
    assert missing.exit_code == 1


def test_graph(project_dir: Path) -> None:
    result = runner.invoke(app, ["graph", str(project_dir)])
    assert result.exit_code == 0
    assert len(json.loads(result.stdout)["nodes"]) == 8


def test_bad_project_dir(tmp_path: Path) -> None:
    result = runner.invoke(app, ["graph", str(tmp_path)])
    assert result.exit_code == 2


def test_review_writes_markdown(project_dir: Path, tmp_path: Path) -> None:
    head = tmp_path / "head"
    shutil.copytree(project_dir, head)
    (head / "models" / "marts" / "revenue.sql").write_text(
        "select sum(amount) as revenue from {{ ref('orders') }}"
    )
    out = tmp_path / "summary.md"
    result = runner.invoke(app, ["review", str(project_dir), str(head), "-o", str(out)])
    assert result.exit_code == 0
    assert "`revenue` (added)" in out.read_text()
