import shutil
import time
from pathlib import Path

import pytest

from openpipeline_core import load_project, preview_changes
from openpipeline_core.preview import ChangePreview


def _name(p: ChangePreview, uid: str) -> str:
    return next(n["name"] for n in p.graph["nodes"] if n["id"] == uid)


def _status(p: ChangePreview, name: str) -> str:
    return next(n["status"] for n in p.graph["nodes"] if n["name"] == name)


def _edges(p: ChangePreview) -> set[tuple[str, str]]:
    return {(_name(p, e["source"]), _name(p, e["target"])) for e in p.graph["edges"]}


def test_add_model(example_dir: Path) -> None:
    p = preview_changes(
        example_dir,
        [("models/marts/revenue.sql", "select sum(amount) as revenue from {{ ref('orders') }}")],
    )
    assert _status(p, "revenue") == "added"
    assert _status(p, "orders") == "unchanged"
    assert p.files[0].change == "added"
    assert p.files[0].diff.startswith("--- /dev/null")
    assert ("orders", "revenue") in _edges(p)
    assert [c.change for c in p.diff.changes] == ["added"]
    assert p.new_warnings == []
    assert p.summary[0] == "Adds 1 model: revenue."
    # The real project is untouched.
    assert not (example_dir / "models" / "marts" / "revenue.sql").exists()


def test_modify_marks_downstream_affected(example_dir: Path) -> None:
    text = (example_dir / "models" / "staging" / "stg_orders.sql").read_text()
    new = text.replace("select", "select 1 as extra_flag,", 1)
    assert new != text
    p = preview_changes(example_dir, [("models/staging/stg_orders.sql", new)])
    assert _status(p, "stg_orders") == "modified"
    assert _status(p, "orders") == "affected"
    assert _status(p, "customers") == "affected"
    assert _status(p, "stg_payments") == "unchanged"
    assert p.files[0].change == "modified"
    assert "+select 1 as extra_flag" in p.files[0].diff
    assert p.files[0].before == text
    assert p.files[0].after == new
    assert p.names_with_status("affected") == ["customers", "orders"]


def test_delete_model_keeps_ghost(example_dir: Path) -> None:
    p = preview_changes(example_dir, [("models/staging/stg_payments.sql", "")])
    assert _status(p, "stg_payments") == "removed"
    assert p.files[0].change == "deleted"
    assert any(c.change == "removed" for c in p.diff.changes)
    assert _status(p, "orders") in ("affected", "modified")
    assert any("stg_payments" in w for w in p.new_warnings)
    assert ("stg_payments", "orders") in _edges(p)


def test_ref_to_missing_model_warns(example_dir: Path) -> None:
    p = preview_changes(
        example_dir, [("models/marts/bad.sql", "select * from {{ ref('does_not_exist') }}")]
    )
    assert any("does_not_exist" in w for w in p.new_warnings)
    assert any(line.startswith("New warning") for line in p.summary)


def test_existing_warnings_are_not_new(tmp_path: Path, example_dir: Path) -> None:
    root = tmp_path / "p"
    shutil.copytree(example_dir, root)
    (root / "models" / "marts" / "bad.sql").write_text("select * from {{ ref('nope') }}")
    assert load_project(root, prefer_manifest=False).warnings
    p = preview_changes(root, [("models/marts/other.sql", "select 1 as x")])
    assert p.new_warnings == []


def test_parse_error_reported(example_dir: Path) -> None:
    p = preview_changes(example_dir, [("models/marts/broken.sql", "select from from where (")])
    assert [e.model for e in p.parse_errors] == ["broken"]


def test_unsafe_path_refused(example_dir: Path) -> None:
    with pytest.raises(ValueError, match="outside the project"):
        preview_changes(example_dir, [("../evil.sql", "x")])


def test_fast_enough(example_dir: Path) -> None:
    start = time.perf_counter()
    preview_changes(example_dir, [("models/marts/revenue.sql", "select 1 as x")])
    assert time.perf_counter() - start < 2


def test_preview_reports_business_rules_touched(example_dir: Path) -> None:
    project = example_dir
    sql = (project / "models" / "marts" / "customers.sql").read_text()
    preview = preview_changes(
        project,
        [("models/marts/customers.sql", sql.replace("sum(o.amount)", "sum(o.amount) * 2"))],
    )
    touched = {r.id for r in preview.diff.rule_impacts if r.level == "touched"}
    assert "lifetime-value" in touched
    assert any(line.startswith("Touches business rules:") for line in preview.summary)


def test_preview_names_downstream_readers_of_a_removed_column(example_dir: Path) -> None:
    orders = (example_dir / "models" / "marts" / "orders.sql").read_text()
    renamed = orders.replace(
        "as amount\nfrom {{ ref('stg_orders') }}", "as paid\nfrom {{ ref('stg_orders') }}"
    )
    assert renamed != orders
    preview = preview_changes(example_dir, [("models/marts/orders.sql", renamed)])
    change = next(c for c in preview.diff.changes if c.name == "orders")
    assert change.column_usage == {"amount": ["customers.lifetime_value"]}
    assert any(
        "orders.amount is still read by customers.lifetime_value" in line
        for line in preview.summary
    )
