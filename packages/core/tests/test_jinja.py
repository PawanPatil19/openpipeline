from openpipeline_core import jinja


def test_find_refs_handles_quotes_spacing_and_package_form() -> None:
    sql = """select * from {{ ref('a') }} join {{ref("b")}} join {{ ref('pkg', 'c') }}
    join {{ ref('a') }}"""
    assert jinja.find_refs(sql) == ["a", "b", "c"]


def test_find_sources() -> None:
    sql = "select * from {{ source('raw', 'orders') }}, {{ source( 'raw' , 'users' ) }}"
    assert jinja.find_sources(sql) == [("raw", "orders"), ("raw", "users")]


def test_find_materialized_from_config_block() -> None:
    assert jinja.find_materialized("{{ config(materialized='incremental') }} select 1") == (
        "incremental"
    )
    assert jinja.find_materialized("select 1") is None


def test_to_plain_sql_strips_jinja() -> None:
    sql = """{{ config(materialized='table') }}
    {# a comment #}
    {% if is_incremental() %}{% endif %}
    select {{ dbt_utils.star('x') }} from {{ ref('orders') }} o
    join {{ source('raw', 'users') }} u on o.id = u.id"""
    plain = jinja.to_plain_sql(sql)
    assert "{" not in plain
    assert "from orders o" in plain
    assert "raw.users u" in plain
