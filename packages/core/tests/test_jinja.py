import sqlglot

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


def test_macros_become_function_calls_with_columns_as_identifiers() -> None:
    sql = (
        "select {{ cents_to_dollars('subtotal') }} as s, "
        "{{ dbt.date_trunc('day','ordered_at') }} as d, "
        "{{ dbt_utils.generate_surrogate_key(['a', 'b.c']) }} as k, "
        "{{ my_macro('x y', 3, true) }} as m, "
        "{{ var('start_date') }} as v "
        "from {{ ref('orders') }}"
    )
    plain = jinja.to_plain_sql(sql)
    assert "__macro__cents_to_dollars(subtotal) as s" in plain
    assert "__macro__date_trunc(day, ordered_at) as d" in plain
    assert "__macro__generate_surrogate_key(a, b.c) as k" in plain
    assert "__macro__my_macro('x y', 3, true) as m" in plain
    assert "__macro__var('start_date') as v" in plain
    assert plain.endswith("from orders")
    sqlglot.parse_one(plain)  # every one of them parses


def test_unparseable_expressions_fall_back_to_null() -> None:
    for body in (
        "my_macro(some_var)",  # a Jinja variable, not a column name
        "my_macro(a=1)",
        "my_macro(other('x'))",
        "my_macro('a') | trim",
        "this",
        "some_var",
        "adapter.dispatch('x')()",
        "ref(model_name)",
    ):
        assert jinja.to_plain_sql(f"select {{{{ {body} }}}} as c") == "select NULL as c", body


def test_keywords_used_as_column_names_stay_parseable() -> None:
    plain = jinja.to_plain_sql("select {{ pick('order', 'date', 'end', 'select') }} from t")
    assert '"date"' in plain
    assert '"end"' in plain
    tree = sqlglot.parse_one(plain)
    pick = tree.find(sqlglot.exp.Anonymous)
    assert pick is not None
    assert [a.name for a in pick.expressions] == ["order", "date", "end", "select"]


def test_if_keeps_only_the_first_branch() -> None:
    sql = "select {% if flag %}a{% elif other %}b{% else %}c{% endif %} from t"
    assert jinja.to_plain_sql(sql) == "select a from t"
    assert jinja.to_plain_sql("select {% if x %}a{% endif %} from t") == "select a from t"
    assert jinja.to_plain_sql("select {% if x %}{% else %}c{% endif %} from t") == "select  from t"


def test_nested_if_is_tracked_with_a_stack() -> None:
    sql = (
        "select 1 {% if a %} , 2 {% if b %} , 3 {% else %} , 4 {% endif %} , 5 "
        "{% else %} , 6 {% if c %} , 7 {% endif %} , 8 {% endif %} , 9"
    )
    assert "".join(jinja.to_plain_sql(sql).split()) == "select1,2,3,5,9"
    # An if inside the dropped branch must not leak, and a following sibling still works.
    sql = "{% if a %}x{% else %}{% if b %}y{% else %}z{% endif %}{% endif %}{% if c %}p{% endif %}"
    assert jinja.to_plain_sql(sql) == "xp"


def test_for_keeps_body_once_and_other_tags_are_dropped() -> None:
    sql = (
        "{% set cols = ['a', 'b'] %}select {% for c in cols %}{{ c }},{% endfor %} 1 "
        "{%- set x -%}drop me{%- endset -%} from t"
    )
    plain = jinja.to_plain_sql(sql)
    assert plain == "select NULL, 1  from t"
    macro = "{% macro f(x) %}select 1{% endmacro %}select 2"
    assert jinja.to_plain_sql(macro) == "select 2"


def test_comments_and_config_are_still_removed() -> None:
    sql = "{{ config(materialized='table') }}{# note {{ x }} #}select 1"
    assert jinja.to_plain_sql(sql) == "select 1"
