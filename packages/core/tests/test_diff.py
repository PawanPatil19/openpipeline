import shutil
from pathlib import Path

from openpipeline_core import (
    ColumnLineage,
    ModelChange,
    ProjectDiff,
    diff_projects,
    load_project,
    render_diff_markdown,
)


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


def _rename_amount(project_dir: Path) -> None:
    orders = project_dir / "models" / "marts" / "orders.sql"
    orders.write_text(
        orders.read_text().replace(
            "as amount\nfrom {{ ref('stg_orders') }}", "as paid\nfrom {{ ref('stg_orders') }}"
        )
    )


def test_removed_column_lists_downstream_readers(example_dir: Path, tmp_path: Path) -> None:
    head_dir = _copy(example_dir, tmp_path / "head")
    _rename_amount(head_dir)
    base = load_project(example_dir)

    diff = diff_projects(base, load_project(head_dir), base_lineage=ColumnLineage(base))
    change = next(c for c in diff.changes if c.name == "orders")
    assert change.removed_columns == ["amount"]
    assert change.column_usage == {"amount": ["customers.lifetime_value"]}
    md = render_diff_markdown(diff)
    assert "Removed column `amount` is used by `customers.lifetime_value`" in md


def test_column_usage_is_optional_and_empty_for_unused_columns(
    example_dir: Path, tmp_path: Path
) -> None:
    head_dir = _copy(example_dir, tmp_path / "head")
    _rename_amount(head_dir)
    base, head = load_project(example_dir), load_project(head_dir)

    plain = diff_projects(base, head)
    assert all(not c.column_usage for c in plain.changes)
    assert "is used by" not in render_diff_markdown(plain)

    # A column nothing reads is removed without a usage note.
    other = _copy(example_dir, tmp_path / "other")
    customers = other / "models" / "marts" / "customers.sql"
    customers.write_text(
        customers.read_text().replace("sum(o.amount) as lifetime_value", "sum(o.amount) as ltv")
    )
    diff = diff_projects(base, load_project(other), base_lineage=ColumnLineage(base))
    change = next(c for c in diff.changes if c.name == "customers")
    assert change.removed_columns == ["lifetime_value"]
    assert change.column_usage == {}


def test_long_reader_lists_are_capped() -> None:
    change = ModelChange(
        name="m",
        unique_id="model.x.m",
        change="modified",
        column_usage={"c": [f"d{i}.c" for i in range(10)]},
    )
    md = render_diff_markdown(ProjectDiff(changes=[change]))
    assert "Removed column `c` is used by `d0.c`" in md
    assert "`d7.c` and 2 more" in md
    assert "d8.c" not in md
