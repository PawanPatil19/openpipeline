from pathlib import Path

from openpipeline_core import Node, NodeKind, Project, load_project, readable_sql
from openpipeline_core.sql_source import RelationIndex, dialect_for_adapter


def _project(adapter: str | None = "duckdb") -> Project:
    project = Project(name="shop", root="/", loaded_from="manifest", adapter=adapter)
    for node in (
        Node(
            unique_id="model.shop.stg_orders",
            name="stg_orders",
            kind=NodeKind.MODEL,
            relation_name='"dev"."main"."stg_orders"',
        ),
        Node(
            unique_id="seed.shop.countries",
            name="countries",
            kind=NodeKind.SEED,
            relation_name='"dev"."main"."countries"',
        ),
        Node(
            unique_id="source.shop.ecom.raw_orders",
            name="ecom.raw_orders",
            kind=NodeKind.SOURCE,
            relation_name='"dev"."raw"."raw_orders"',
        ),
        Node(
            unique_id="model.shop.dup_a",
            name="dup_a",
            kind=NodeKind.MODEL,
            relation_name="`proj`.`a`.`dup`",
        ),
        Node(
            unique_id="model.shop.dup_b",
            name="dup_b",
            kind=NodeKind.MODEL,
            relation_name="`proj`.`b`.`dup`",
        ),
    ):
        project.nodes[node.unique_id] = node
    return project


def _read(project: Project, compiled: str, raw: str = "select 1") -> str:
    node = Node(
        unique_id="model.shop.m",
        name="m",
        kind=NodeKind.MODEL,
        raw_sql=raw,
        compiled_sql=compiled,
    )
    result = readable_sql(project, node)
    assert result.tree is not None
    return result.tree.sql()


def test_physical_names_become_the_short_names_to_plain_sql_would_use() -> None:
    sql = _read(
        _project(),
        'select * from "dev"."main"."stg_orders" o '
        'join "dev"."raw"."raw_orders" r on o.id = r.id '
        'join "dev"."main"."countries" using (code)',
    )
    assert sql == (
        "SELECT * FROM stg_orders AS o JOIN ecom.raw_orders AS r ON o.id = r.id "
        "JOIN countries USING (code)"
    )


def test_matching_ignores_quotes_and_case_and_falls_back_to_last_two_parts() -> None:
    project = _project("snowflake")
    # Different catalog, same schema.table: matched on the last two parts.
    assert "FROM stg_orders" in _read(project, 'select * from "OTHERDB"."MAIN"."STG_ORDERS"')
    # Unqualified name that is unique among relation names.
    assert "FROM stg_orders" in _read(project, "select * from stg_orders")
    index = RelationIndex(project)
    node = index.resolve(["DEV", "MAIN", "Stg_Orders"])
    assert node is not None
    assert node.name == "stg_orders"


def test_ambiguous_last_part_is_left_alone_but_two_parts_resolve() -> None:
    project = _project("bigquery")
    assert "FROM dup" in _read(project, "select * from dup")
    assert "FROM dup_b" in _read(project, "select * from `x`.`b`.`dup`")


def test_ctes_are_never_rewritten() -> None:
    sql = _read(
        _project(),
        'with stg_orders as (select * from "dev"."main"."stg_orders") select * from stg_orders',
    )
    assert sql == "WITH stg_orders AS (SELECT * FROM stg_orders) SELECT * FROM stg_orders"
    # The inner reference is the model, the outer one is still the CTE.
    result = readable_sql(
        _project(),
        Node(
            unique_id="model.shop.m",
            name="m",
            kind=NodeKind.MODEL,
            compiled_sql='with raw_orders as (select * from "dev"."raw"."raw_orders") '
            "select * from raw_orders",
        ),
    )
    assert result.tree is not None
    assert "FROM ecom.raw_orders" in result.tree.sql()
    assert result.tree.sql().endswith("SELECT * FROM raw_orders")


def test_compiled_sql_is_preferred_and_flagged() -> None:
    node = Node(
        unique_id="model.shop.m",
        name="m",
        kind=NodeKind.MODEL,
        raw_sql="select {{ f('a') }} from {{ ref('stg_orders') }}",
        compiled_sql="select a + 1 as x from stg_orders",
    )
    result = readable_sql(_project(), node)
    assert result.from_compiled is True
    assert result.error is None
    assert result.tree is not None
    assert "a + 1" in result.tree.sql()


def test_unparseable_compiled_sql_falls_back_to_raw() -> None:
    node = Node(
        unique_id="model.shop.m",
        name="m",
        kind=NodeKind.MODEL,
        raw_sql="select a from {{ ref('stg_orders') }}",
        compiled_sql="select from where (((",
    )
    result = readable_sql(_project(), node)
    assert result.from_compiled is False
    assert result.tree is not None
    assert result.tree.sql() == "SELECT a FROM stg_orders"


def test_both_unparseable_reports_an_error_and_never_raises() -> None:
    node = Node(
        unique_id="model.shop.m",
        name="m",
        kind=NodeKind.MODEL,
        raw_sql="select from where (((",
        compiled_sql="select 'unterminated",
    )
    result = readable_sql(_project(), node)
    assert result.tree is None
    assert result.error
    empty = readable_sql(_project(), node.model_copy(update={"raw_sql": "", "compiled_sql": ""}))
    assert empty.tree is None
    assert empty.error


def test_dialect_comes_from_the_adapter_unless_given() -> None:
    assert dialect_for_adapter("sqlserver") == "tsql"
    assert dialect_for_adapter("fabric") == "tsql"
    assert dialect_for_adapter("athena") == "trino"
    assert dialect_for_adapter("databricks") == "databricks"
    assert dialect_for_adapter("mystery") is None
    assert dialect_for_adapter(None) is None
    # `::` only parses in some dialects; an explicit dialect wins over the adapter.
    project = _project("bigquery")
    node = Node(
        unique_id="model.shop.m", name="m", kind=NodeKind.MODEL, compiled_sql="select a::int from t"
    )
    assert readable_sql(project, node, "duckdb").tree is not None


def test_manifest_loader_fills_compiled_sql_relation_names_and_adapter(
    dbt_labs_jaffle_dir: Path,
) -> None:
    project = load_project(dbt_labs_jaffle_dir)
    assert project.adapter == "duckdb"
    orders = project.get("orders")
    assert orders is not None
    assert orders.relation_name == '"dev"."main"."orders"'
    assert "stg_orders" in orders.compiled_sql
    assert "{{" not in orders.compiled_sql
    source = project.nodes["source.jaffle_shop.ecom.raw_orders"]
    assert source.relation_name == '"dev"."raw"."raw_orders"'
    files = load_project(dbt_labs_jaffle_dir, prefer_manifest=False)
    assert files.adapter is None
    assert all(n.compiled_sql == "" and n.relation_name is None for n in files.nodes.values())
