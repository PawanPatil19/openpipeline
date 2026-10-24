from pathlib import Path

import pytest

from openpipeline_core import ColumnLineage, ColumnRef, load_project

SHOP = "model.jaffle_shop."
RAW = "source.jaffle_shop.raw."


@pytest.fixture
def shop(example_dir: Path) -> ColumnLineage:
    return ColumnLineage(load_project(example_dir))


def _make(tmp_path: Path, models: dict[str, str], schema: str = "") -> ColumnLineage:
    (tmp_path / "dbt_project.yml").write_text("name: t\nversion: '1'\n")
    folder = tmp_path / "models"
    folder.mkdir()
    for name, sql in models.items():
        (folder / f"{name}.sql").write_text(sql)
    if schema:
        (folder / "schema.yml").write_text(schema)
    return ColumnLineage(load_project(tmp_path))


def test_output_columns_for_every_model(shop: ColumnLineage) -> None:
    assert shop.columns(SHOP + "customers") == [
        "customer_id",
        "first_name",
        "last_name",
        "first_order_date",
        "number_of_orders",
        "lifetime_value",
    ]
    assert shop.columns(SHOP + "orders") == [
        "order_id",
        "customer_id",
        "order_date",
        "status",
        "amount",
    ]
    assert shop.columns(SHOP + "stg_payments") == [
        "payment_id",
        "order_id",
        "payment_method",
        "amount",
    ]
    assert shop.columns(SHOP + "stg_orders") == ["order_id", "customer_id", "order_date", "status"]
    assert shop.columns(SHOP + "stg_customers") == ["customer_id", "first_name", "last_name"]


def test_every_model_column_has_upstream(shop: ColumnLineage) -> None:
    names = ("customers", "orders", "stg_customers", "stg_orders", "stg_payments")
    for uid in (SHOP + n for n in names):
        for column in shop.columns(uid):
            assert shop.direct_upstream(uid, column), (uid, column)


def test_lifetime_value_traces_to_the_raw_payment_amount(shop: ColumnLineage) -> None:
    assert shop.upstream(SHOP + "customers", "lifetime_value") == [
        ColumnRef(SHOP + "orders", "amount"),
        ColumnRef(SHOP + "stg_payments", "amount"),
        ColumnRef(RAW + "payments", "amount"),
    ]
    assert shop.upstream(SHOP + "customers", "lifetime_value", recursive=False) == [
        ColumnRef(SHOP + "orders", "amount")
    ]


def test_renames_and_downstream(shop: ColumnLineage) -> None:
    assert shop.direct_upstream(SHOP + "stg_customers", "customer_id") == [
        ColumnRef(RAW + "customers", "id")
    ]
    assert shop.downstream(RAW + "payments", "amount") == [
        ColumnRef(SHOP + "stg_payments", "amount"),
        ColumnRef(SHOP + "orders", "amount"),
        ColumnRef(SHOP + "customers", "lifetime_value"),
    ]
    assert shop.downstream(RAW + "payments", "amount", recursive=False) == [
        ColumnRef(SHOP + "stg_payments", "amount")
    ]


def test_source_columns_are_learned_from_use(shop: ColumnLineage) -> None:
    assert shop.columns(RAW + "orders") == ["id", "user_id", "order_date", "status"]


def test_lookup_ignores_case_and_unknown_columns_are_empty(shop: ColumnLineage) -> None:
    assert shop.upstream(SHOP + "customers", "LIFETIME_VALUE")
    assert shop.upstream(SHOP + "customers", "nope") == []
    assert shop.downstream("model.nope", "x") == []
    assert shop.columns("model.nope") == []


def test_join_aggregate_and_expression_columns(tmp_path: Path) -> None:
    lin = _make(
        tmp_path,
        {
            "a": "select 1 as id, 2 as x, 3 as y",
            "b": "select 1 as id, 5 as z",
            "c": (
                "select a.id, sum(a.x + b.z) as total, count(*) as n, 'k' as const "
                "from {{ ref('a') }} a join {{ ref('b') }} b on a.id = b.id group by a.id"
            ),
        },
    )
    c = "model.t.c"
    assert lin.columns(c) == ["id", "total", "n", "const"]
    assert lin.direct_upstream(c, "id") == [ColumnRef("model.t.a", "id")]
    assert set(lin.direct_upstream(c, "total")) == {
        ColumnRef("model.t.a", "x"),
        ColumnRef("model.t.b", "z"),
    }
    assert lin.direct_upstream(c, "n") == []
    assert lin.direct_upstream(c, "const") == []


def test_ctes_with_the_same_name_as_the_model_they_read(tmp_path: Path) -> None:
    lin = _make(
        tmp_path,
        {
            "orders": "select 1 as order_id, 2 as amount",
            "report": (
                "with orders as (select * from {{ ref('orders') }}), "
                "totals as (select order_id, amount * 2 as doubled from orders) "
                "select order_id as id, doubled from totals"
            ),
        },
    )
    assert lin.direct_upstream("model.t.report", "id") == [ColumnRef("model.t.orders", "order_id")]
    assert lin.upstream("model.t.report", "doubled") == [ColumnRef("model.t.orders", "amount")]


def test_select_star_uses_columns_from_upstream_lineage(tmp_path: Path) -> None:
    lin = _make(
        tmp_path,
        {
            "base": "select 1 as id, 2 as name",
            "wide": "select * from {{ ref('base') }}",
            "mixed": (
                "select b.*, 1 as extra from {{ ref('base') }} b join {{ ref('wide') }} w on 1 = 1"
            ),
        },
    )
    assert lin.columns("model.t.wide") == ["id", "name"]
    assert lin.direct_upstream("model.t.wide", "name") == [ColumnRef("model.t.base", "name")]
    assert lin.upstream("model.t.mixed", "id") == [ColumnRef("model.t.base", "id")]
    assert "extra" in lin.columns("model.t.mixed")


def test_select_star_from_source_uses_documented_columns(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: t\nversion: '1'\n")
    folder = tmp_path / "models"
    folder.mkdir()
    (folder / "src.yml").write_text(
        "version: 2\nsources:\n  - name: raw\n    tables:\n"
        "      - name: users\n        columns:\n          - name: id\n          - name: email\n"
    )
    (folder / "u.sql").write_text("select * from {{ source('raw', 'users') }}")
    lin = ColumnLineage(load_project(tmp_path))
    assert lin.columns("model.t.u") == ["id", "email"]
    assert lin.upstream("model.t.u", "email") == [ColumnRef("source.t.raw.users", "email")]


def test_unparseable_sql_degrades_to_documented_columns(tmp_path: Path) -> None:
    lin = _make(
        tmp_path,
        {"broken": "selec from from where ((", "fine": "select id from {{ ref('broken') }}"},
        schema="version: 2\nmodels:\n  - name: broken\n    columns:\n      - name: id\n",
    )
    assert lin.columns("model.t.broken") == ["id"]
    assert lin.upstream("model.t.broken", "id") == []
    assert lin.upstream("model.t.fine", "id") == [ColumnRef("model.t.broken", "id")]


def test_non_select_sql_and_empty_models_do_not_raise(tmp_path: Path) -> None:
    lin = _make(tmp_path, {"weird": "create table x (a int)", "empty": "", "j": "{{ foo() }}"})
    for name in ("weird", "empty", "j"):
        assert lin.columns(f"model.t.{name}") == []


def test_ambiguous_unqualified_column_does_not_raise(tmp_path: Path) -> None:
    lin = _make(
        tmp_path,
        {
            "a": "select 1 as id",
            "b": "select 1 as id",
            "c": "select id from {{ ref('a') }} join {{ ref('b') }} on 1 = 1",
        },
    )
    assert lin.columns("model.t.c") == ["id"]
    assert len(lin.direct_upstream("model.t.c", "id")) <= 2


def test_union_traces_both_sides(tmp_path: Path) -> None:
    lin = _make(
        tmp_path,
        {
            "a": "select 1 as id",
            "b": "select 2 as other",
            "u": "select id as k from {{ ref('a') }} union all select other from {{ ref('b') }}",
        },
    )
    assert set(lin.upstream("model.t.u", "k")) == {
        ColumnRef("model.t.a", "id"),
        ColumnRef("model.t.b", "other"),
    }


def test_lineage_nodes_includes_own_node_and_every_hop(shop: ColumnLineage) -> None:
    assert shop.lineage_nodes(SHOP + "orders", "amount") == {
        SHOP + "orders",
        SHOP + "stg_payments",
        RAW + "payments",
        SHOP + "customers",
    }
