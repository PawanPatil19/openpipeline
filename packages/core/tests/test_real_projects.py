"""Smoke, scale and quality-baseline tests on real public dbt projects (see fixtures/README.md)."""

import re
import time
from pathlib import Path

import pytest

from openpipeline_core import ColumnLineage, load_project, search_project
from openpipeline_core.graph import ModelGraph
from openpipeline_core.models import Project
from openpipeline_core.story import ModelStory, explain_model


@pytest.fixture(scope="session")
def tuva_project(tuva_dir: Path) -> Project:
    return load_project(tuva_dir)


@pytest.fixture(scope="session")
def tuva_stories(tuva_project: Project) -> dict[str, ModelStory]:
    return {m.name: explain_model(tuva_project, m.unique_id) for m in tuva_project.models()}


@pytest.fixture(scope="session")
def jaffle_project(dbt_labs_jaffle_dir: Path) -> Project:
    return load_project(dbt_labs_jaffle_dir)


@pytest.fixture(scope="session")
def jaffle_files_project(dbt_labs_jaffle_dir: Path) -> Project:
    return load_project(dbt_labs_jaffle_dir, prefer_manifest=False)


@pytest.fixture(scope="session")
def jaffle_files_stories(jaffle_files_project: Project) -> dict[str, ModelStory]:
    return {
        m.name: explain_model(jaffle_files_project, m.unique_id)
        for m in jaffle_files_project.models()
    }


@pytest.fixture(scope="session")
def jaffle_stories(jaffle_project: Project) -> dict[str, ModelStory]:
    return {m.name: explain_model(jaffle_project, m.unique_id) for m in jaffle_project.models()}


def test_jaffle_loads_from_manifest_and_files(dbt_labs_jaffle_dir: Path) -> None:
    from_manifest = load_project(dbt_labs_jaffle_dir)
    from_files = load_project(dbt_labs_jaffle_dir, prefer_manifest=False)
    assert from_manifest.loaded_from == "manifest"
    assert from_files.loaded_from == "files"
    assert len(from_manifest.models()) == len(from_files.models()) == 13
    assert from_files.warnings == []

    assert {m.name for m in from_manifest.models()} == {m.name for m in from_files.models()}
    by_name_files = {m.name: m for m in from_files.models()}
    for model in from_manifest.models():
        other = by_name_files[model.name]
        names_manifest = {from_manifest.nodes[d].name for d in model.depends_on}
        names_files = {from_files.nodes[d].name for d in other.depends_on}
        assert names_manifest == names_files, model.name


def test_tuva_loads_and_graph_is_acyclic(tuva_project: Project) -> None:
    assert len(tuva_project.models()) >= 300
    graph = ModelGraph(tuva_project)
    order = graph.topological_order()
    assert len(order) == len(set(order)) == len(tuva_project.nodes)
    position = {uid: i for i, uid in enumerate(order)}
    for uid in tuva_project.nodes:
        for parent in graph.parents(uid):
            assert position[parent] < position[uid]


@pytest.mark.parametrize("which", ["jaffle", "tuva"])
def test_every_model_explains_with_lineage_and_search(
    which: str, jaffle_project: Project, tuva_project: Project
) -> None:
    project = jaffle_project if which == "jaffle" else tuva_project
    for model in project.models():
        story = explain_model(project, model.unique_id)
        assert story.model == model.name

    lineage = ColumnLineage(project)
    for model in project.models():
        for column in lineage.columns(model.unique_id):
            lineage.upstream(model.unique_id, column)
            lineage.downstream(model.unique_id, column)

    for query in ("order", "customer", "claim patient", "no_such_thing_xyz"):
        hits = search_project(project, lineage, query, limit=10)
        assert len(hits) <= 10


def test_scale_load_and_explain_tuva(tuva_dir: Path) -> None:
    start = time.perf_counter()
    project = load_project(tuva_dir)
    for model in project.models():
        explain_model(project, model.unique_id)
    elapsed = time.perf_counter() - start
    assert elapsed < 30, f"loading and explaining tuva took {elapsed:.1f}s"


def _quality(stories: dict[str, ModelStory]) -> dict[str, int]:
    return {
        "parse_errors": sum(1 for s in stories.values() if s.parse_error),
        "null_columns": sum(1 for s in stories.values() if any("NULL" in c.how for c in s.columns)),
        "star_only": sum(
            1 for s in stories.values() if s.columns and all(c.name == "*" for c in s.columns)
        ),
        "any_star": sum(1 for s in stories.values() if any(c.name == "*" for c in s.columns)),
        "unreadable_expressions": sum(
            1 for s in stories.values() for c in s.columns if c.how.startswith("calculated as")
        ),
    }


def test_story_quality_baseline(
    tuva_stories: dict[str, ModelStory],
    jaffle_stories: dict[str, ModelStory],
    jaffle_files_stories: dict[str, ModelStory],
) -> None:
    # Measured numbers. Before the story-v2 engine these were: tuva 55 parse errors, 170
    # models with NULL columns, 16 star-only; jaffle (manifest and files) 13 of 13 star-only.
    # Lower a bound when the engine improves; never raise one.
    assert len(tuva_stories) == 309
    tuva = _quality(tuva_stories)
    assert tuva["parse_errors"] <= 0
    # The 4 left are columns that really compare against the text 'NULL', not macros gone wrong.
    assert tuva["null_columns"] <= 4
    assert tuva["star_only"] <= 0
    assert tuva["any_star"] <= 0
    assert tuva["unreadable_expressions"] <= 0

    assert len(jaffle_stories) == len(jaffle_files_stories) == 13
    for label, stories in (("manifest", jaffle_stories), ("files", jaffle_files_stories)):
        jaffle = _quality(stories)
        assert jaffle["parse_errors"] <= 0, label
        assert jaffle["null_columns"] <= 0, label
        assert jaffle["star_only"] <= 0, label
        assert jaffle["any_star"] <= 0, label
        assert jaffle["unreadable_expressions"] <= 0, label


def test_no_story_describes_a_macro_as_null_in_files_mode(
    jaffle_files_stories: dict[str, ModelStory],
) -> None:
    for story in jaffle_files_stories.values():
        for column in story.columns:
            assert "NULL" not in column.how, (story.model, column.name)


@pytest.mark.parametrize("mode", ["manifest", "files"])
def test_golden_stg_orders(
    mode: str, jaffle_stories: dict[str, ModelStory], jaffle_files_stories: dict[str, ModelStory]
) -> None:
    story = (jaffle_stories if mode == "manifest" else jaffle_files_stories)["stg_orders"]
    assert story.parse_error is None
    assert story.reads_from == ["ecom.raw_orders"]
    how = {c.name: c.how for c in story.columns}
    assert list(how) == [
        "order_id",
        "location_id",
        "customer_id",
        "subtotal_cents",
        "tax_paid_cents",
        "order_total_cents",
        "subtotal",
        "tax_paid",
        "order_total",
        "ordered_at",
    ]
    assert how["order_id"] == "renamed from id"
    assert how["ordered_at"] == "ordered_at cut to the day"
    if mode == "manifest":
        assert how["subtotal"] == "subtotal divided by 100, as a number"
    else:
        assert how["subtotal"] == "the cents_to_dollars macro applied to subtotal"
    assert all("NULL" not in h for h in how.values())
    assert story.steps == [
        "Reads ecom.raw_orders.",
        "Builds a step called renamed: takes rows from source.",
        "Final result: everything from renamed.",
    ]
    assert {c.name: c.from_step for c in story.columns}["subtotal"] == "renamed"


@pytest.mark.parametrize("mode", ["manifest", "files"])
def test_golden_orders(
    mode: str, jaffle_stories: dict[str, ModelStory], jaffle_files_stories: dict[str, ModelStory]
) -> None:
    story = (jaffle_stories if mode == "manifest" else jaffle_files_stories)["orders"]
    assert story.parse_error is None
    names = [c.name for c in story.columns]
    assert "*" not in names
    assert names[:3] == ["order_id", "location_id", "customer_id"]
    assert names[-8:] == [
        "order_cost",
        "order_items_subtotal",
        "count_food_items",
        "count_drink_items",
        "count_order_items",
        "is_food_order",
        "is_drink_order",
        "customer_order_number",
    ]
    cols = {c.name: c for c in story.columns}
    assert cols["order_id"].how == "passed through from stg_orders"
    assert cols["order_cost"].how == "the total of supply_cost per order_id"
    assert cols["order_cost"].from_step == "order_items_summary"
    assert cols["count_food_items"].how == "the number of rows where is_food_item per order_id"
    assert cols["is_food_order"].how == "true when count_food_items is more than 0"
    assert cols["is_food_order"].from_step == "compute_booleans"
    assert cols["customer_order_number"].how == (
        "the position of each row within its customer_id, ordered by ordered_at (earliest first)"
    )
    assert cols["customer_order_number"].from_step == "customer_order_count"
    assert story.steps[0] == "Reads stg_orders."
    assert "rolls up to one row per order_id" in story.steps[2]
    assert story.steps[-1] == "Final result: everything from customer_order_count."
    assert "one row per 1" not in " ".join(story.steps)


def test_golden_orders_with_lineage_matches_without(
    jaffle_project: Project, jaffle_stories: dict[str, ModelStory]
) -> None:
    lineage = ColumnLineage(jaffle_project)
    with_lineage = explain_model(jaffle_project, "orders", lineage=lineage)
    assert [c.name for c in with_lineage.columns] == [
        c.name for c in jaffle_stories["orders"].columns
    ]
    assert with_lineage.columns == jaffle_stories["orders"].columns


def test_group_by_position_is_never_shown_as_a_number(
    jaffle_stories: dict[str, ModelStory], jaffle_files_stories: dict[str, ModelStory]
) -> None:
    for stories in (jaffle_stories, jaffle_files_stories):
        for story in stories.values():
            assert all(not g.isdigit() for g in story.grain), story.model
            assert not any(re.search(r"one row per \d", t) for t in [story.summary, *story.steps])


def test_tuva_compiled_sql_resolves_to_node_names(tuva_project: Project) -> None:
    """Physical relation names map back, so reads_from and the story agree on tables."""
    story = explain_model(tuva_project, "normalized_input__int_admit_source_voting")
    assert story.parse_error is None
    text = " ".join(story.steps)
    assert '"' not in text
    assert "dev." not in text
    assert "__dbt__cte__" not in text
    assert "Builds a step called normalized_input__stg_medical_claim (an ephemeral model)" in text
    assert story.grain == ["claim_id", "data_source", "normalized_code", "normalized_description"]
    cols = {c.name: c for c in story.columns}
    assert cols["occurrence_count"].how == "the number of rows"
    assert cols["occurrence_count"].from_step == "distinct_counts"
    assert cols["occurrence_row_count"].how.startswith("the position of each row within its")
    assert cols["claim_id"].how == "passed through from input_layer__medical_claim"
