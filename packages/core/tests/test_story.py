from pathlib import Path

import pytest

from openpipeline_core import Node, NodeKind, Project, explain_model, load_project


def test_customers_story(example_dir: Path) -> None:
    story = explain_model(load_project(example_dir), "customers")
    assert story.reads_from == ["stg_customers", "orders"]
    assert story.grain == ["customer_id", "first_name", "last_name"]
    how = {c.name: c.how for c in story.columns}
    assert how["lifetime_value"] == "the total of amount"
    assert how["number_of_orders"] == "the number of order_id"
    assert how["first_name"] == "passed through unchanged"
    assert "one row per customer_id" in story.summary
    assert "adds orders (keeping every row even without a match)" in story.steps[-1]


def test_ctes_become_steps(example_dir: Path) -> None:
    story = explain_model(load_project(example_dir), "orders")
    assert story.steps[0].startswith("Builds a step called payments: takes rows from stg_payments")
    assert story.steps[-1].startswith("Final result: takes rows from stg_orders")


def test_filters_and_renames(example_dir: Path) -> None:
    story = explain_model(load_project(example_dir), "stg_orders")
    assert story.filters == ["status <> 'test'"]
    assert {c.name: c.how for c in story.columns}["customer_id"] == "renamed from user_id"


def test_source_story_uses_description(example_dir: Path) -> None:
    story = explain_model(load_project(example_dir), "raw.orders")
    assert story.summary == "One row per order placed in the shop."


def test_unparseable_sql_degrades_gracefully() -> None:
    project = Project(name="x", root="/", loaded_from="files")
    project.nodes["m"] = Node(
        unique_id="m", name="m", kind=NodeKind.MODEL, raw_sql="select from where ((("
    )
    story = explain_model(project, "m")
    assert story.parse_error
    assert story.summary


def test_unknown_model() -> None:
    with pytest.raises(KeyError):
        explain_model(Project(name="x", root="/", loaded_from="files"), "nope")
