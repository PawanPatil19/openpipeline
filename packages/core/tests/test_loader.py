import json
from pathlib import Path

import pytest

from openpipeline_core import NodeKind, ProjectLoadError, load_project


def test_loads_example_from_files(example_dir: Path) -> None:
    project = load_project(example_dir)
    assert project.name == "jaffle_shop"
    assert project.loaded_from == "files"
    assert project.warnings == []
    assert [m.name for m in project.models()] == [
        "customers",
        "orders",
        "stg_customers",
        "stg_orders",
        "stg_payments",
    ]
    sources = [n for n in project.nodes.values() if n.kind == NodeKind.SOURCE]
    assert {s.name for s in sources} == {"raw.customers", "raw.orders", "raw.payments"}


def test_dependencies_descriptions_and_meta(example_dir: Path) -> None:
    project = load_project(example_dir)
    customers = project.get("customers")
    assert customers is not None
    assert customers.depends_on == ["model.jaffle_shop.stg_customers", "model.jaffle_shop.orders"]
    assert customers.description.startswith("One row per customer")
    assert customers.owner == "growth-team"
    assert customers.materialized == "table"

    stg = project.get("stg_customers")
    assert stg is not None
    assert stg.depends_on == ["source.jaffle_shop.raw.customers"]
    assert stg.materialized == "view"  # From the folder config in dbt_project.yml.
    assert stg.columns[0].tests == ["unique", "not_null"]


def test_missing_refs_become_warnings(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: demo\n")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "a.sql").write_text("select * from {{ ref('ghost') }}")
    project = load_project(tmp_path)
    assert project.get("a").depends_on == []  # type: ignore[union-attr]
    assert project.warnings == ["models/a.sql: ref('ghost') not found"]


def test_not_a_dbt_project(tmp_path: Path) -> None:
    with pytest.raises(ProjectLoadError):
        load_project(tmp_path)


def test_loads_from_manifest_when_present(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: demo\n")
    (tmp_path / "target").mkdir()
    manifest = {
        "nodes": {
            "model.demo.a": {
                "resource_type": "model",
                "name": "a",
                "original_file_path": "models/a.sql",
                "raw_code": "select * from {{ source('raw', 't') }}",
                "config": {"materialized": "view"},
                "depends_on": {"nodes": ["source.demo.raw.t"]},
                "columns": {"id": {"name": "id", "description": "Key"}},
            },
            "test.demo.unique_a_id": {
                "resource_type": "test",
                "column_name": "id",
                "attached_node": "model.demo.a",
                "test_metadata": {"name": "unique"},
            },
        },
        "sources": {"source.demo.raw.t": {"source_name": "raw", "name": "t", "description": "Raw"}},
    }
    (tmp_path / "target" / "manifest.json").write_text(json.dumps(manifest))
    project = load_project(tmp_path)
    assert project.loaded_from == "manifest"
    a = project.get("a")
    assert a is not None
    assert a.depends_on == ["source.demo.raw.t"]
    assert a.columns[0].tests == ["unique"]
    assert project.get("raw.t").kind == NodeKind.SOURCE  # type: ignore[union-attr]

    assert load_project(tmp_path, prefer_manifest=False).loaded_from == "files"


def test_tolerates_empty_yaml_sections(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: demo\n")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "schema.yml").write_text("version: 2\nmodels:\nsources:\n")
    (tmp_path / "models" / "a.sql").write_text("select 1 as x")
    assert [m.name for m in load_project(tmp_path).models()] == ["a"]
