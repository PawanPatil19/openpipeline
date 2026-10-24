import shutil
from pathlib import Path

from openpipeline_core import diff_projects, load_project, render_diff_markdown


def _copy(example_dir: Path, dest: Path) -> Path:
    shutil.copytree(example_dir, dest)
    return dest


def test_no_changes(example_dir: Path) -> None:
    p = load_project(example_dir)
    diff = diff_projects(p, p)
    assert diff.is_empty
    assert "No dbt model changes" in render_diff_markdown(diff)


def test_modified_added_removed(example_dir: Path, tmp_path: Path) -> None:
    head_dir = _copy(example_dir, tmp_path / "head")
    orders = head_dir / "models" / "marts" / "orders.sql"
    orders.write_text(
        orders.read_text().replace(
            "coalesce(p.amount, 0) as amount", "coalesce(p.amount, 0) as amount,\n    1 as is_paid"
        )
    )
    (head_dir / "models" / "marts" / "revenue.sql").write_text(
        "select sum(amount) as revenue from {{ ref('orders') }}"
    )
    (head_dir / "models" / "staging" / "stg_customers.sql").unlink()

    diff = diff_projects(load_project(example_dir), load_project(head_dir))
    by_name = {c.name: c for c in diff.changes}

    assert by_name["revenue"].change == "added"
    assert by_name["stg_customers"].change == "removed"
    assert by_name["stg_customers"].downstream == ["customers"]
    assert by_name["stg_customers"].owners == ["growth-team"]

    orders_change = by_name["orders"]
    assert orders_change.change == "modified"
    assert "New columns: is_paid" in orders_change.details
    assert set(orders_change.downstream) == {"customers", "revenue"}

    md = render_diff_markdown(diff)
    assert "1 added, 1 removed, 1 modified" in md
    assert "`orders` (modified)" in md
    assert "growth-team" in md
    assert "Other models whose results may change: `customers`." in md
