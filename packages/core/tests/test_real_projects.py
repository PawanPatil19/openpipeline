"""Smoke, scale and quality-baseline tests on real public dbt projects (see fixtures/README.md)."""

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


def test_story_quality_baseline(
    tuva_stories: dict[str, ModelStory], jaffle_stories: dict[str, ModelStory]
) -> None:
    # These record TODAY's numbers as loose upper bounds. The next story-engine PR
    # must tighten them (lower the constants) as it improves the output.
    tuva_parse_errors = sum(1 for s in tuva_stories.values() if s.parse_error)
    tuva_null_columns = sum(
        1 for s in tuva_stories.values() if any("NULL" in c.how for c in s.columns)
    )
    jaffle_star_only = sum(
        1 for s in jaffle_stories.values() if s.columns and all(c.name == "*" for c in s.columns)
    )
    assert len(tuva_stories) == 309
    assert tuva_parse_errors <= 55
    assert tuva_null_columns <= 170
    assert len(jaffle_stories) == 13
    assert jaffle_star_only <= 13
