"""The glossary: loading, validation, dbt meta labels, the humanizer, and proposing a term."""

import shutil
from pathlib import Path

import pytest
import yaml

from openpipeline_core import Project, add_glossary_term, humanize, load_glossary, load_project
from openpipeline_core.models import Column, Node, NodeKind


def _copy(example_dir: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(example_dir, dest)
    return dest


def _write_glossary(root: Path, text: str) -> None:
    (root / "openpipeline.yml").write_text(text, encoding="utf-8")


def _load(root: Path):  # type: ignore[no-untyped-def]
    return load_glossary(root, load_project(root))


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("order_items_subtotal", "Order items subtotal"),
        ("customer_id", "Customer ID"),
        ("id", "ID"),
        ("is_food_order", "Is food order"),
        ("has_refund", "Has refund"),
        ("stg_orders", "Orders"),
        ("int_orders_joined", "Orders joined"),
        ("fct_orders", "Orders"),
        ("fact_sales", "Sales"),
        ("dim_customers", "Customers"),
        ("base_payments", "Payments"),
        ("src_users", "Users"),
        ("mart_revenue", "Revenue"),
        ("stg_ecom__orders", "Orders"),
        ("claims_preprocessing__normalized_input__medical_claim", "Medical claim"),
        ("core__patient", "Patient"),
        ("customerId", "Customer ID"),
        ("ORDER_ID", "Order ID"),
        ("_dbt_source_relation", "Dbt source relation"),
        ("stg_", "Stg"),
        ("stg", "Stg"),
        ("orders", "Orders"),
    ],
)
def test_humanize(name: str, label: str) -> None:
    assert humanize(name) == label


def test_humanize_can_keep_prefixes_for_columns() -> None:
    assert humanize("base_price", strip_prefixes=False) == "Base price"
    assert humanize("base_price") == "Price"
    # A double underscore is namespacing for models, but a column keeps reading well too.
    assert humanize("a__b", strip_prefixes=False) == "B"


def test_example_glossary_loads_cleanly(example_dir: Path) -> None:
    glossary = load_glossary(example_dir, load_project(example_dir))
    assert glossary.warnings == []
    customer = glossary.lookup("customer_id")
    assert customer is not None
    assert customer.label == "Customer"
    assert customer.definition == "The person who placed the order."
    assert glossary.lookup("USER_ID") is customer  # Aliases and case do not matter.
    assert glossary.lookup("nope") is None
    assert {"customers", "orders", "stg_orders", "lifetime_value"} <= {
        t.name for t in glossary.terms
    }


def test_no_glossary_file_is_fine(tmp_path: Path, example_dir: Path) -> None:
    root = _copy(example_dir, tmp_path)
    (root / "openpipeline.yml").unlink()
    glossary = _load(root)
    assert glossary.terms == []
    assert glossary.warnings == []


def test_problems_are_warnings_not_crashes(tmp_path: Path, example_dir: Path) -> None:
    root = _copy(example_dir, tmp_path)
    _write_glossary(
        root,
        """
glossary:
  - name: customer_id
    label: Customer
    aliases: [user_id, buyer_id]
  - name: customer_id
    label: Client
  - name: buyer_id
    label: Buyer
  - name: order_id
  - label: Nameless
  - just a string
  - name: ok
    label: Fine
""",
    )
    glossary = _load(root)
    warnings = "\n".join(glossary.warnings)
    assert "'customer_id' is used more than once" in warnings
    assert "'buyer_id' is used more than once" in warnings
    assert "entry 'order_id' has no label; using 'Order ID'" in warnings
    assert "entry #5 has no name" in warnings
    assert "entry #6 is not a mapping" in warnings
    by_name = {t.name: t for t in glossary.terms}
    assert by_name["customer_id"].label == "Customer"  # The first one is kept.
    assert by_name["order_id"].label == "Order ID"
    assert "buyer_id" not in by_name
    assert "ok" in by_name


@pytest.mark.parametrize(
    "text",
    ["glossary: nope\n", "glossary:\n  customer_id: Customer\n", "glossary: [: bad", "- a\n- b\n"],
)
def test_malformed_file_never_raises(tmp_path: Path, example_dir: Path, text: str) -> None:
    root = _copy(example_dir, tmp_path)
    _write_glossary(root, text)
    glossary = _load(root)
    assert glossary.terms == []


def test_glossary_key_is_optional_and_rules_still_load(tmp_path: Path, example_dir: Path) -> None:
    from openpipeline_core import load_rules

    root = _copy(example_dir, tmp_path)
    _write_glossary(root, "rules:\n  - id: a\n    name: A\n")
    project = load_project(root)
    assert load_glossary(root, project).terms == []
    assert [r.id for r in load_rules(root, project).rules] == ["a"]


def _project_with_meta() -> Project:
    def node(name: str, columns: list[Column], meta: dict[str, object] | None = None) -> Node:
        return Node(
            unique_id=f"model.p.{name}",
            name=name,
            kind=NodeKind.MODEL,
            columns=columns,
            meta=meta or {},
        )

    return Project(
        name="p",
        root=".",
        loaded_from="files",
        nodes={
            "model.p.a": node(
                "a",
                [
                    Column(name="amount", meta={"label": "Money", "definition": "Dollars paid."}),
                    Column(name="plain"),
                ],
                {"label": "Alpha", "definition": "The first one."},
            ),
            "model.p.b": node("b", [Column(name="amount", meta={"label": "Cash"})]),
        },
    )


def test_labels_from_dbt_meta(tmp_path: Path) -> None:
    glossary = load_glossary(tmp_path, _project_with_meta())
    alpha = glossary.lookup("a")
    assert alpha is not None
    assert (alpha.label, alpha.definition, alpha.origin) == ("Alpha", "The first one.", "meta")
    amount = glossary.lookup("amount")
    assert amount is not None
    assert (amount.label, amount.definition) == ("Money", "Dollars paid.")
    assert glossary.lookup("plain") is None
    # b.amount says "Cash" where a.amount says "Money": the first (by id) is kept, loudly.
    assert any("'Cash' differs from 'Money'" in w for w in glossary.warnings)


def test_yml_entry_wins_over_meta(tmp_path: Path) -> None:
    _write_glossary(
        tmp_path,
        "glossary:\n  - name: amount\n    label: Amount paid\n"
        "  - name: a\n    label: Apples\n    definition: Mine.\n",
    )
    glossary = load_glossary(tmp_path, _project_with_meta())
    amount = glossary.lookup("amount")
    assert amount is not None
    assert amount.label == "Amount paid"
    assert amount.origin == "glossary"
    assert amount.definition == "Dollars paid."  # Missing text is filled in from meta.
    a = glossary.lookup("a")
    assert a is not None
    assert (a.label, a.definition) == ("Apples", "Mine.")  # What the yml says is kept.
    assert [t.name for t in glossary.terms].count("amount") == 1


def test_meta_labels_are_read_from_dbt_yaml_files(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: shop\nversion: '1'\n")
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text("select 1 as order_id")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: orders
    meta: {label: Sales orders, definition: Every order.}
    columns:
      - name: order_id
        meta: {label: Order number}
"""
    )
    glossary = _load(tmp_path)
    assert glossary.lookup("orders").label == "Sales orders"  # type: ignore[union-attr]
    assert glossary.lookup("order_id").label == "Order number"  # type: ignore[union-attr]


# --- Proposing a term ----------------------------------------------------------------


def test_add_term_keeps_the_rest_of_the_file(example_dir: Path) -> None:
    before = (example_dir / "openpipeline.yml").read_text()
    edit = add_glossary_term(example_dir, "refund_id", "Refund", "Money handed back.")
    assert (example_dir / "openpipeline.yml").read_text() == before  # Nothing is written.
    assert edit.path == "openpipeline.yml"

    data = yaml.safe_load(edit.content)
    old = yaml.safe_load(before)
    assert data["rules"] == old["rules"]
    assert data["glossary"][:-1] == old["glossary"]
    assert data["glossary"][-1] == {
        "name": "refund_id",
        "label": "Refund",
        "definition": "Money handed back.",
    }
    # Comments and the folded descriptions survive, and the next section's comment stays
    # below the glossary instead of ending up in the middle of it.
    assert "# Business rules for this project." in edit.content
    assert edit.content.index("refund_id") < edit.content.index("# Business rules for this")
    assert "      Orders with the status" in edit.content
    removed = [line for line in edit.content.splitlines() if line not in before.splitlines()]
    assert removed == [
        "  - name: refund_id",
        "    label: Refund",
        "    definition: Money handed back.",
    ]


def test_add_term_creates_the_section_and_the_file(tmp_path: Path) -> None:
    edit = add_glossary_term(tmp_path, "order_id", "Order")
    assert yaml.safe_load(edit.content) == {"glossary": [{"name": "order_id", "label": "Order"}]}
    assert not (tmp_path / "openpipeline.yml").exists()

    (tmp_path / "openpipeline.yml").write_text(
        "# Rules\nrules:\n  - id: a  # keep me\n    name: A\n", encoding="utf-8"
    )
    edit = add_glossary_term(tmp_path, "order_id", "Order", "One purchase.")
    assert "# Rules" in edit.content
    assert "# keep me" in edit.content
    data = yaml.safe_load(edit.content)
    assert data["rules"] == [{"id": "a", "name": "A"}]
    assert data["glossary"] == [
        {"name": "order_id", "label": "Order", "definition": "One purchase."}
    ]


def test_add_term_updates_an_existing_entry_in_place(example_dir: Path) -> None:
    edit = add_glossary_term(example_dir, "CUSTOMER_ID", "Shopper", "Who buys.")
    data = yaml.safe_load(edit.content)
    entries = [e for e in data["glossary"] if e["name"] == "customer_id"]
    assert entries == [
        {
            "name": "customer_id",
            "label": "Shopper",
            "definition": "Who buys.",
            "aliases": ["user_id"],
        }
    ]
    assert len(data["glossary"]) == len(
        yaml.safe_load((example_dir / "openpipeline.yml").read_text())["glossary"]
    )


def test_add_term_keeps_an_inline_comment_on_the_last_entry(tmp_path: Path) -> None:
    (tmp_path / "openpipeline.yml").write_text(
        "glossary:\n  - name: a\n    label: A  # the first\n\n# Rules next\nrules: []\n"
    )
    edit = add_glossary_term(tmp_path, "b", "B")
    assert "label: A  # the first" in edit.content
    assert edit.content.index("name: b") < edit.content.index("# Rules next")
    assert yaml.safe_load(edit.content)["glossary"][-1] == {"name": "b", "label": "B"}


@pytest.mark.parametrize(
    ("name", "label"),
    [("", "Label"), ("   ", "Label"), ("name", ""), ("name", "  ")],
)
def test_add_term_needs_a_name_and_label(tmp_path: Path, name: str, label: str) -> None:
    with pytest.raises(ValueError, match="needs a"):
        add_glossary_term(tmp_path, name, label)


def test_add_term_refuses_an_unreadable_file(tmp_path: Path) -> None:
    (tmp_path / "openpipeline.yml").write_text("glossary: [: bad")
    with pytest.raises(ValueError, match="could not be read"):
        add_glossary_term(tmp_path, "a", "A")
    (tmp_path / "openpipeline.yml").write_text("- just\n- a list\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        add_glossary_term(tmp_path, "a", "A")
