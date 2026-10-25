"""Business words: a story told with glossary labels, and nothing else changed."""

from pathlib import Path

import pytest

from openpipeline_core import (
    BusinessStory,
    Glossary,
    GlossaryTerm,
    Labeler,
    Project,
    business_story,
    explain_model,
    load_glossary,
    load_project,
)
from openpipeline_core.models import Column, Node, NodeKind
from openpipeline_core.story import ColumnStory, ModelStory


def _tell(root: Path, model: str) -> BusinessStory:
    project = load_project(root)
    return business_story(project, explain_model(project, model), load_glossary(root, project))


def test_example_customers(example_dir: Path) -> None:
    story = _tell(example_dir, "customers")
    assert story.title == "Customers"
    assert story.definition == "One row per person who has signed up, with their order history."
    assert story.summary == (
        "Customers brings together Cleaned customer list and Orders into one row per "
        "Customer, First name and Last name. It works out First order date (the smallest of "
        "Order date), Number of orders (the number of Order) and Lifetime value (the total "
        "of Amount paid)."
    )
    by_name = {c.name: c for c in story.columns}
    assert by_name["lifetime_value"].label == "Lifetime value"
    assert by_name["lifetime_value"].meaning == "The total of Amount paid"
    assert by_name["lifetime_value"].definition is not None
    assert by_name["customer_id"].meaning == "Comes straight from Cleaned customer list"
    assert by_name["first_name"].definition is None
    assert [(r.name, r.label) for r in story.reads_from] == [
        ("stg_customers", "Cleaned customer list"),
        ("orders", "Orders"),
    ]
    assert story.grain == ["Customer", "First name", "Last name"]
    assert story.steps == [
        "Final result: starts with Cleaned customer list, adds Orders (keeping every row "
        "even without a match), rolls up to one row per Customer, First name and Last name."
    ]


def test_technical_story_is_kept_unchanged(example_dir: Path) -> None:
    project = load_project(example_dir)
    technical = explain_model(project, "customers")
    story = business_story(project, technical, load_glossary(example_dir, project))
    assert story.technical == technical
    assert story.technical.summary.startswith("customers combines stg_customers and orders")
    assert story.model == "customers"


def test_terms_used_are_the_glossary_terms_that_appear(example_dir: Path) -> None:
    story = _tell(example_dir, "customers")
    used = {t.name: t for t in story.terms_used}
    assert {"customers", "customer_id", "stg_customers", "lifetime_value", "amount"} <= set(used)
    assert used["amount"].label == "Amount paid"
    assert used["amount"].definition == "Money received for the order, in dollars."
    assert "status" not in used  # Not in this story.
    assert len(used) == len(story.terms_used)


def test_alias_names_use_the_same_term(example_dir: Path) -> None:
    project = load_project(example_dir)
    glossary = load_glossary(example_dir, project)
    story = ModelStory(
        model="orders",
        summary="x",
        columns=[ColumnStory(name="user_id", how="renamed from user_id")],
        filters=["user_id is present"],
    )
    told = business_story(project, story, glossary)
    assert told.columns[0].label == "Customer"
    assert told.filters == ["Customer is present"]
    assert [t.name for t in told.terms_used if t.name == "customer_id"] == ["customer_id"]


def test_string_literals_are_never_touched(example_dir: Path) -> None:
    project = load_project(example_dir)
    glossary = load_glossary(example_dir, project)
    story = explain_model(project, "stg_orders")
    assert story.filters == ["status is not 'test'"]
    assert business_story(project, story, glossary).filters == ["Order status is not 'test'"]

    tricky = ModelStory(
        model="orders",
        summary="x",
        filters=[
            "status is one of 'status', 'order_id', 'it''s amount'",
            "status equals 'completed' and order_id is present",
            "status equals 'unfinished",
        ],
    )
    told = business_story(project, tricky, glossary)
    assert told.filters == [
        "Order status is one of 'status', 'order_id', 'it''s amount'",
        "Order status equals 'completed' and Order is present",
        "Order status equals 'unfinished",
    ]


def test_function_and_macro_names_and_apostrophes_survive(example_dir: Path) -> None:
    project = load_project(example_dir)
    glossary = load_glossary(example_dir, project)
    story = ModelStory(
        model="orders",
        summary="x",
        columns=[
            ColumnStory(name="m", how="calculated as date_trunc('month', order_date)"),
            ColumnStory(name="t", how="today's date minus order_date"),
            ColumnStory(name="g", how="the generate_surrogate_key macro applied to order_id"),
            ColumnStory(name="f", how="the project variable start_date"),
        ],
    )
    meanings = [c.meaning for c in business_story(project, story, glossary).columns]
    assert meanings == [
        "Calculated as date_trunc('month', Order date)",
        "Today's date minus Order date",
        "The generate_surrogate_key macro applied to Order",
        "The project variable Start date",
    ]


def test_engine_words_are_not_mistaken_for_columns() -> None:
    """A column called ``total`` must not turn the engine's "the total of" into "the Total of"."""
    project = Project(
        name="p",
        root=".",
        loaded_from="files",
        nodes={
            "model.p.m": Node(
                unique_id="model.p.m",
                name="m",
                kind=NodeKind.MODEL,
                columns=[Column(name="total"), Column(name="amount")],
            )
        },
    )
    story = ModelStory(
        model="m",
        summary="x",
        columns=[ColumnStory(name="total", how="the total of amount per total")],
    )
    told = business_story(project, story, Glossary())
    assert told.columns[0].label == "Total"
    assert told.columns[0].meaning == "The total of Amount per total"


def test_import_steps_are_dropped_and_names_become_labels(dbt_labs_jaffle_dir: Path) -> None:
    project = load_project(dbt_labs_jaffle_dir)
    technical = explain_model(project, "orders")
    assert any(s.startswith("Reads ") for s in technical.steps)

    story = business_story(project, technical, load_glossary(dbt_labs_jaffle_dir, project))
    assert story.title == "Orders"
    assert not any(s.startswith("Reads") for s in story.steps)
    assert story.steps == [
        "Order items summary: starts with Order items, rolls up to one row per Order ID.",
        "Compute booleans: starts with Orders, adds Order items summary "
        "(keeping every row even without a match).",
        "Customer order count: starts with Compute booleans.",
        "Final result: everything from Customer order count.",
    ]
    assert story.summary.startswith("Orders brings together Staged orders and Order items.")
    assert "Order cost (the total of Supply cost per Order ID)" in story.summary
    assert "and 4 more." in story.summary
    # ``stg_orders`` and ``orders`` would both read "Orders"; the staged one is told apart.
    assert [r.label for r in story.reads_from] == ["Staged orders", "Order items"]

    by_name = {c.name: c for c in story.columns}
    assert by_name["order_cost"].meaning == "The total of Supply cost per Order ID"
    assert by_name["is_food_order"].label == "Is food order"
    assert by_name["is_food_order"].meaning == "True when Count food items is more than 0"
    assert by_name["order_id"].meaning == "Comes straight from Staged orders"
    # No technical name is left in any visible sentence.
    text = " ".join([story.summary, *story.steps, *(c.meaning for c in story.columns)])
    for raw in ("order_items_summary", "supply_cost", "stg_orders", "is_food_item", "order_id"):
        assert raw not in text
    # With no glossary, dbt's own column descriptions are the definitions.
    assert by_name["order_id"].definition == "The unique key of the orders mart."


def test_same_label_models_are_told_apart() -> None:
    def model(name: str, kind: NodeKind = NodeKind.MODEL) -> Node:
        return Node(unique_id=f"x.p.{name}", name=name, kind=kind)

    nodes = [
        model("orders"),
        model("stg_orders"),
        model("int_orders"),
        model("raw.orders", NodeKind.SOURCE),
        model("a__thing"),
        model("b__thing"),
    ]
    project = Project(
        name="p", root=".", loaded_from="files", nodes={n.unique_id: n for n in nodes}
    )
    labeler = Labeler(project, Glossary())
    labels = {n.name: labeler.node_label(n) for n in nodes}
    assert labels["orders"] == "Orders"
    assert labels["stg_orders"] == "Staged orders"
    assert labels["int_orders"] == "Intermediate orders"
    assert labels["raw.orders"] == "Raw orders"
    assert labels["a__thing"] == "A thing"
    assert labels["b__thing"] == "B thing"

    # An explicit glossary label is never rewritten.
    glossary = Glossary(terms=[GlossaryTerm(name="stg_orders", label="Orders")])
    assert Labeler(project, glossary).node_label(nodes[1]) == "Orders"


def test_sources_and_seeds_get_business_summaries(dbt_labs_jaffle_dir: Path) -> None:
    project = load_project(dbt_labs_jaffle_dir)
    glossary = Glossary(terms=[GlossaryTerm(name="raw_orders", label="Web orders")])
    source = business_story(project, explain_model(project, "ecom.raw_orders"), glossary)
    assert source.title == "Web orders"
    assert source.summary
    assert source.steps == []


def test_business_story_for_unparsable_sql_does_not_crash(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: shop\nversion: '1'\n")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "broken_model.sql").write_text("select from where ((")
    project = load_project(tmp_path)
    story = explain_model(project, "broken_model")
    told = business_story(project, story, Glossary())
    assert told.title == "Broken model"
    assert told.summary
    assert told.technical.parse_error == story.parse_error


def test_model_meta_label_beats_nothing_but_loses_to_yml(tmp_path: Path) -> None:
    project = Project(
        name="p",
        root=".",
        loaded_from="files",
        nodes={
            "model.p.m": Node(
                unique_id="model.p.m",
                name="m",
                kind=NodeKind.MODEL,
                description="Dbt text.",
                meta={"label": "From meta"},
            )
        },
    )
    glossary = load_glossary(tmp_path, project)
    story = ModelStory(model="m", summary="x")
    told = business_story(project, story, glossary)
    assert told.title == "From meta"
    assert told.definition == "Dbt text."


@pytest.mark.parametrize("model", ["customers", "orders", "stg_orders", "stg_payments"])
def test_every_example_model_tells_a_clean_story(example_dir: Path, model: str) -> None:
    story = _tell(example_dir, model)
    assert story.title
    assert story.summary
    assert all(c.label and c.meaning for c in story.columns)
