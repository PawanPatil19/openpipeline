from pathlib import Path

import pytest

from openpipeline_core import ModelGraph, UnsupportedJinja, compile_sql, load_project, plan_preview


def test_compile_maps_refs_and_sources_and_drops_config() -> None:
    sql = (
        "{{ config(materialized='table') }}\n-- hi\n{# note #}\n"
        "select * from {{ ref('a') }} join {{ source('raw', 'b') }} using (id);"
    )
    out = compile_sql(sql)
    assert "select * from a join raw.b using (id)" in out
    assert not out.endswith(";")
    out = compile_sql(sql, ref=lambda n: f"v_{n}", source=lambda s, t: f"{s}__{t}")
    assert "v_a" in out
    assert "raw__b" in out


def test_compile_refuses_other_jinja() -> None:
    with pytest.raises(UnsupportedJinja, match="var"):
        compile_sql("select {{ var('x') }} as x")
    with pytest.raises(UnsupportedJinja):
        compile_sql("{% if true %}select 1{% endif %}")


def test_plan_preview_orders_upstream_models(example_dir: Path) -> None:
    project = load_project(example_dir)
    plan = plan_preview(project, ModelGraph(project), "customers")
    names = [m.name for m in plan.models]
    assert names[-1] == "customers"
    assert set(names) == {"customers", "orders", "stg_customers", "stg_orders", "stg_payments"}
    assert names.index("stg_orders") < names.index("orders") < names.index("customers")
    assert {s.name for s in plan.sources} == {"raw.customers", "raw.orders", "raw.payments"}


def test_plan_preview_rejects_non_models(example_dir: Path) -> None:
    project = load_project(example_dir)
    with pytest.raises(KeyError):
        plan_preview(project, ModelGraph(project), "nope")
    with pytest.raises(KeyError):
        plan_preview(project, ModelGraph(project), "raw.orders")
