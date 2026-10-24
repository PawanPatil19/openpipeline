import json
import shutil
from pathlib import Path
from typing import Any

import pytest
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


def test_explain_with_ai(project_dir: Path, fake_ai: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("openpipeline.cli.default_client", lambda: fake_ai)
    result = runner.invoke(app, ["explain", "customers", str(project_dir), "--ai"])
    assert result.exit_code == 0
    assert "In plain words (written by fake-claude)" in result.stdout
    assert "One row per customer." in result.stdout
    assert "Check: Customers with no orders" in result.stdout

    as_json = runner.invoke(app, ["explain", "customers", str(project_dir), "--ai", "--json"])
    assert json.loads(as_json.stdout)["ai"]["summary"] == "One row per customer."


def test_explain_with_ai_unavailable_falls_back(project_dir: Path) -> None:
    result = runner.invoke(app, ["explain", "customers", str(project_dir), "--ai"])
    assert result.exit_code == 0
    assert "one row per customer_id" in result.stdout
    assert "AI explanation not available" in result.stderr


def _head_with_revenue(project_dir: Path, tmp_path: Path) -> Path:
    head = tmp_path / "head"
    shutil.copytree(project_dir, head)
    (head / "models" / "marts" / "revenue.sql").write_text("select 1 as revenue")
    return head


def test_review_with_ai_adds_overview_after_heading(
    project_dir: Path, tmp_path: Path, fake_ai: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("openpipeline.cli.default_client", lambda: fake_ai)
    head = _head_with_revenue(project_dir, tmp_path)
    result = runner.invoke(app, ["review", str(project_dir), str(head), "--ai"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "### OpenPipeline summary"
    assert lines[2] == "**In plain words.** A new revenue table is added for finance."
    assert "`revenue` (added)" in result.stdout


def test_review_with_ai_failure_warns_and_keeps_summary(
    project_dir: Path, tmp_path: Path, fake_ai: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_ai.error = "Could not reach the Anthropic API."
    monkeypatch.setattr("openpipeline.cli.default_client", lambda: fake_ai)
    head = _head_with_revenue(project_dir, tmp_path)
    result = runner.invoke(app, ["review", str(project_dir), str(head), "--ai"])
    assert result.exit_code == 0
    assert "Warning: skipping the AI overview" in result.stderr
    assert "In plain words" not in result.stdout
    assert "`revenue` (added)" in result.stdout

    unavailable = runner.invoke(app, ["review", str(project_dir), str(head), "--ai"])
    assert unavailable.exit_code == 0
    assert "Warning" in unavailable.stderr


def test_sample_prints_a_table(project_dir: Path) -> None:
    pytest.importorskip("duckdb")
    result = runner.invoke(app, ["sample", "orders", str(project_dir), "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "order_id" in result.stdout
    assert "(3 rows, limit 3)" in result.stdout


def test_sample_reports_missing_data(project_dir: Path, tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["sample", "orders", str(project_dir), "--sample-data", str(empty)])
    assert result.exit_code == 1
    assert "raw.orders" in result.output
    assert runner.invoke(app, ["sample", "nope", str(project_dir)]).exit_code == 1


def test_review_lists_columns_used_downstream(project_dir: Path, tmp_path: Path) -> None:
    head = tmp_path / "head"
    shutil.copytree(project_dir, head)
    orders = head / "models" / "marts" / "orders.sql"
    orders.write_text(
        orders.read_text().replace(
            "as amount\nfrom {{ ref('stg_orders') }}", "as paid\nfrom {{ ref('stg_orders') }}"
        )
    )
    result = runner.invoke(app, ["review", str(project_dir), str(head)])
    assert result.exit_code == 0
    assert "Removed column `amount` is used by `customers.lifetime_value`" in result.stdout
