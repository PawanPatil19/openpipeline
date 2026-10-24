import json
import shutil
from pathlib import Path

from openpipeline_core import (
    RuleRegistry,
    diff_projects,
    load_project,
    load_rules,
    render_diff_markdown,
)


def _rules(root: Path) -> RuleRegistry:
    return load_rules(root, load_project(root))


def _copy(example_dir: Path, dest: Path) -> Path:
    shutil.copytree(example_dir, dest)
    return dest


def test_example_rules_merge_config_and_meta(example_dir: Path) -> None:
    registry = _rules(example_dir)
    assert registry.warnings == []
    assert [r.id for r in registry.rules] == [
        "no-test-orders",
        "lifetime-value",
        "amounts-in-dollars",
    ]

    ltv = registry.get("lifetime-value")
    assert ltv is not None
    assert ltv.owner == "growth-team"
    # One link comes from openpipeline.yml, the other from meta on orders.amount.
    links = {link.model: link.columns for link in ltv.applies_to}
    assert links == {"customers": ["lifetime_value"], "orders": ["amount"]}

    # A model-level meta link, with no columns.
    assert [r.id for r in registry.rules_for("stg_payments")] == ["amounts-in-dollars"]
    assert registry.rules_for("stg_customers") == []
    assert [r.id for r in registry.rules_for_column("orders", "amount")] == ["lifetime-value"]
    assert registry.rules_for_column("orders", "order_id") == []


def test_no_rules_file_is_fine(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: demo\n")
    registry = _rules(tmp_path)
    assert registry.rules == []
    assert registry.warnings == []


def test_problems_become_warnings(example_dir: Path, tmp_path: Path) -> None:
    root = _copy(example_dir, tmp_path / "p")
    (root / "openpipeline.yml").write_text(
        """
rules:
  - id: a
    name: First
    applies_to: [{model: customers}, {model: ghost}]
  - id: a
    name: Same id again
  - name: No id
  - Not a mapping
  - id: Bad Slug
    name: Odd id
"""
    )
    stg = root / "models" / "staging" / "schema.yml"
    stg.write_text(stg.read_text().replace("[amounts-in-dollars]", "[nope]"))
    registry = _rules(root)

    assert [r.id for r in registry.rules] == ["a", "Bad Slug"]
    assert registry.get("a").name == "First"  # type: ignore[union-attr]
    text = "\n".join(registry.warnings)
    assert "unknown model 'ghost'" in text
    assert "'a' is used more than once" in text
    assert "rule #3 has no id" in text
    assert "rule #4 is not a mapping" in text
    assert "'Bad Slug' should use lowercase" in text
    assert "stg_payments: meta.rules names unknown rule 'nope'" in text
    assert [link.model for link in registry.get("a").applies_to] == ["customers"]  # type: ignore[union-attr]


def test_broken_yaml_does_not_raise(example_dir: Path, tmp_path: Path) -> None:
    root = _copy(example_dir, tmp_path / "p")
    (root / "openpipeline.yml").write_text("rules: [unclosed")
    registry = _rules(root)
    assert registry.rules == []
    assert "could not be read" in registry.warnings[0]


def test_meta_links_from_manifest(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: demo\n")
    (tmp_path / "openpipeline.yml").write_text(
        "rules:\n  - id: shipped-only\n    name: Shipped only\n    owner: ops\n"
    )
    (tmp_path / "target").mkdir()
    manifest = {
        "nodes": {
            "model.demo.orders": {
                "resource_type": "model",
                "name": "orders",
                "raw_code": "select 1 as status",
                "meta": {"rules": ["shipped-only"]},
                "columns": {"status": {"name": "status", "meta": {"rules": "shipped-only"}}},
            }
        }
    }
    (tmp_path / "target" / "manifest.json").write_text(json.dumps(manifest))
    project = load_project(tmp_path)
    assert project.loaded_from == "manifest"
    registry = load_rules(tmp_path, project)
    assert registry.warnings == []
    assert registry.get("shipped-only").applies_to[0].model == "orders"  # type: ignore[union-attr]
    assert registry.get("shipped-only").applies_to[0].columns == ["status"]  # type: ignore[union-attr]


def test_diff_flags_touched_and_downstream_rules(example_dir: Path, tmp_path: Path) -> None:
    head_dir = _copy(example_dir, tmp_path / "head")
    stg = head_dir / "models" / "staging" / "stg_orders.sql"
    stg.write_text(stg.read_text().replace("where status != 'test'", "where status = 'shipped'"))
    orders = head_dir / "models" / "marts" / "orders.sql"
    orders.write_text(
        orders.read_text().replace("    coalesce(p.amount, 0) as amount\n", "    1 as one\n")
    )

    base, head = load_project(example_dir), load_project(head_dir)
    diff = diff_projects(
        base, head, base_rules=load_rules(example_dir, base), head_rules=load_rules(head_dir, head)
    )
    by_id = {i.id: i for i in diff.rule_impacts}

    assert by_id["no-test-orders"].level == "touched"
    assert by_id["no-test-orders"].owner == "data-platform"
    assert by_id["no-test-orders"].reasons == ["`stg_orders` was modified"]
    ltv = by_id["lifetime-value"]
    assert ltv.level == "touched"
    assert ltv.models == ["orders"]
    assert "column `amount` was removed from `orders`" in ltv.reasons
    assert "orders.amount" in ltv.columns
    # Not touched, and not downstream of anything that changed.
    assert "amounts-in-dollars" not in by_id

    stg_change = next(c for c in diff.changes if c.name == "stg_orders")
    assert stg_change.rules == ["no-test-orders"]
    assert "lifetime-value" in stg_change.downstream_rules
    assert "data-platform" in stg_change.owners

    md = render_diff_markdown(diff)
    assert "#### Business rules touched" in md
    assert "**Test orders are never real orders** (owner: data-platform)" in md
    assert "- Business rules: **Test orders are never real orders**" in md
    assert "Owners to loop in: " in md
    assert "growth-team" in md


def test_downstream_only_rule_is_marked_may_be_affected(example_dir: Path, tmp_path: Path) -> None:
    head_dir = _copy(example_dir, tmp_path / "head")
    stg = head_dir / "models" / "staging" / "stg_customers.sql"
    stg.write_text(stg.read_text() + "\n-- touched\nwhere 1 = 1\n")
    base, head = load_project(example_dir), load_project(head_dir)
    diff = diff_projects(
        base, head, base_rules=load_rules(example_dir, base), head_rules=load_rules(head_dir, head)
    )
    assert [(i.id, i.level) for i in diff.rule_impacts] == [("lifetime-value", "may_be_affected")]
    md = render_diff_markdown(diff)
    assert "#### Business rules that may be affected" in md
    assert "#### Business rules touched" not in md


def test_description_only_change_does_not_touch_rules(example_dir: Path, tmp_path: Path) -> None:
    head_dir = _copy(example_dir, tmp_path / "head")
    schema = head_dir / "models" / "staging" / "schema.yml"
    schema.write_text(
        schema.read_text().replace("Payments with amounts", "All payments, with amounts")
    )
    base, head = load_project(example_dir), load_project(head_dir)
    diff = diff_projects(
        base, head, base_rules=load_rules(example_dir, base), head_rules=load_rules(head_dir, head)
    )
    assert [c.name for c in diff.changes] == ["stg_payments"]
    assert diff.rule_impacts == []


def test_deleted_model_touches_its_rules(example_dir: Path, tmp_path: Path) -> None:
    head_dir = _copy(example_dir, tmp_path / "head")
    (head_dir / "models" / "staging" / "stg_payments.sql").unlink()
    base, head = load_project(example_dir), load_project(head_dir)
    diff = diff_projects(
        base, head, base_rules=load_rules(example_dir, base), head_rules=load_rules(head_dir, head)
    )
    impact = next(i for i in diff.rule_impacts if i.id == "amounts-in-dollars")
    assert impact.level == "touched"
    assert impact.reasons == ["`stg_payments` was deleted"]
    assert "finance-team" in render_diff_markdown(diff)


def test_rule_file_changes_are_reported(example_dir: Path, tmp_path: Path) -> None:
    head_dir = _copy(example_dir, tmp_path / "head")
    rules_file = head_dir / "openpipeline.yml"
    text = rules_file.read_text().replace("Money is stored in dollars", "Money is always dollars")
    text = text.replace("owner: growth-team", "owner: finance-team")
    text += """
  - id: shipped-revenue
    name: Revenue counts once shipped
    owner: ops-team
    applies_to:
      - model: orders
"""
    rules_file.write_text(text)
    # Remove a rule entirely.
    start = text.index("  - id: no-test-orders")
    end = text.index("  - id: lifetime-value")
    rules_file.write_text(text[:start] + text[end:])

    base, head = load_project(example_dir), load_project(head_dir)
    diff = diff_projects(
        base, head, base_rules=load_rules(example_dir, base), head_rules=load_rules(head_dir, head)
    )
    assert diff.changes == []
    changes = {c.id: c for c in diff.rule_changes}
    assert changes["shipped-revenue"].change == "added"
    assert changes["no-test-orders"].change == "removed"
    assert changes["amounts-in-dollars"].details == ['Renamed from "Money is stored in dollars"']
    assert changes["lifetime-value"].details == ["Owner changed from growth-team to finance-team"]

    md = render_diff_markdown(diff)
    assert "No dbt model changes in this pull request, but business rules changed." in md
    assert "#### Changes to `openpipeline.yml`" in md
    assert "Rule added: **Revenue counts once shipped** (`shipped-revenue`) (owner: ops-team)" in md
    assert "Rule removed: **Test orders are never real orders**" in md
    assert "Owners to loop in: data-platform, finance-team, ops-team." in md


def test_diff_without_rules_is_unchanged(example_dir: Path) -> None:
    p = load_project(example_dir)
    diff = diff_projects(p, p)
    assert diff.rule_impacts == []
    assert diff.rule_changes == []
