import pytest
import sqlglot

from openpipeline_core.describe import describe, describe_expr, is_predicate


def d(sql: str, dialect: str = "duckdb") -> str:
    return describe(sqlglot.parse_one(sql, read=dialect))


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        # case
        (
            "case when amount > 100 then 'large' when amount > 10 then 'small' else 'other' end",
            "'large' when amount is more than 100, 'small' when amount is more than 10, "
            "otherwise 'other'",
        ),
        ("case when n > 0 then true else false end", "true when n is more than 0"),
        ("case when n > 0 then true end", "true when n is more than 0"),
        ("case when a then false else true end", "false when a"),
        ("case status when 'x' then 1 else 0 end", "1 when status equals 'x', otherwise 0"),
        ("iff(a > 1, 'x', 'y')", "'x' when a is more than 1, otherwise 'y'"),
        # null handling
        ("coalesce(a, b)", "a, or b when a is missing"),
        ("coalesce(a, b, 0)", "a, or if missing b then 0"),
        ("nullif(a, 0)", "a, or missing when it equals 0"),
        ("a is null", "a is missing"),
        ("a is not null", "a is present"),
        # casts
        ("cast(x as integer)", "x as a number"),
        ("x::date", "x as a date"),
        ("x::varchar", "x as text"),
        ("cast(x as boolean)", "x as true-false"),
        ("cast(x as timestamp)", "x as a timestamp"),
        ("(subtotal / 100)::numeric(16, 2)", "subtotal divided by 100, as a number"),
        # arithmetic
        ("subtotal / 100", "subtotal divided by 100"),
        ("a - b", "a minus b"),
        ("a + b", "a plus b"),
        ("a * b", "a times b"),
        ("(a + b) * c", "(a plus b) times c"),
        ("a - (b - c)", "a minus (b minus c)"),
        ("a / (b * c)", "a divided by (b times c)"),
        ("-a", "minus a"),
        # comparisons and logic
        ("a > 1", "a is more than 1"),
        ("a >= 1", "a is at least 1"),
        ("a < 1", "a is less than 1"),
        ("a <= 1", "a is at most 1"),
        ("a = 'x'", "a equals 'x'"),
        ("a <> 'x'", "a is not 'x'"),
        ("flag = true", "flag is true"),
        ("a > 1 and b < 2", "a is more than 1 and b is less than 2"),
        ("a > 1 or (b = 2 and c = 3)", "a is more than 1 or (b equals 2 and c equals 3)"),
        ("(a or b) and c", "(a or b) and c"),
        ("not a", "not a"),
        ("a in (1, 2, 3)", "a is one of 1, 2, 3"),
        ("a not in ('x', 'y')", "a is not one of 'x', 'y'"),
        ("a between 1 and 5", "a is between 1 and 5"),
        ("a not between 1 and 5", "a is not between 1 and 5"),
        ("name like 'x%'", "name matches 'x%'"),
        ("name not like 'x%'", "name does not match 'x%'"),
        # aggregates
        ("sum(amount)", "the total of amount"),
        ("count(order_id)", "the number of order_id"),
        ("count(distinct customer_id)", "the number of different customer_id"),
        ("count(*)", "the number of rows"),
        ("avg(x)", "the average of x"),
        ("min(x)", "the smallest of x"),
        ("max(x)", "the largest of x"),
        ("sum(case when is_food then 1 else 0 end)", "the number of rows where is_food"),
        (
            "sum(case when status = 'done' then 1 else 0 end)",
            "the number of rows where status equals 'done'",
        ),
        ("count(case when a > 1 then 1 end)", "the number of rows where a is more than 1"),
        ("sum(x) / sum(y)", "the total of x divided by the total of y"),
        # windows
        (
            "row_number() over (partition by customer_id order by ordered_at asc)",
            "the position of each row within its customer_id, ordered by ordered_at "
            "(earliest first)",
        ),
        (
            "rank() over (order by score desc)",
            "the rank of each row, ordered by score (highest first)",
        ),
        (
            "dense_rank() over (partition by a, b order by n)",
            "the rank of each row within its a and b, ordered by n (lowest first)",
        ),
        (
            "sum(x) over (partition by a order by created_at)",
            "the running total of x within its a, ordered by created_at (earliest first)",
        ),
        ("sum(x) over (partition by a)", "the total of x within its a"),
        ("sum(x) over ()", "the total of x across all rows"),
        (
            "lag(x) over (partition by a order by created_at desc)",
            "the previous value of x within its a, ordered by created_at (latest first)",
        ),
        ("lead(x) over (order by n)", "the next value of x, ordered by n (lowest first)"),
        # dates
        ("date_trunc('day', ordered_at)", "ordered_at cut to the day"),
        ("extract(year from d)", "the year of d"),
        ("date_part('month', d)", "the month of d"),
        ("datediff('day', a, b)", "days between a and b"),
        ("date_diff('day', a, b)", "days between a and b"),
        ("d + interval '3 day'", "d plus 3 days"),
        ("current_date", "today's date"),
        # strings
        ("a || b", "a joined with b"),
        ("a || ' ' || b", "a joined with ' ' and b"),
        ("concat(a, b, c)", "a joined with b and c"),
        ("lower(x)", "x in lower case"),
        ("upper(x)", "x in upper case"),
        ("trim(x)", "x without surrounding spaces"),
        ("replace(x, 'a', 'b')", "x with 'a' replaced by 'b'"),
        ("substring(x, 1, 3)", "the first 3 characters of x"),
        # numbers
        ("round(x, 2)", "x rounded to 2 decimal places"),
        ("abs(x)", "the absolute value of x"),
        ("greatest(a, b)", "the largest of a and b"),
        ("least(a, b)", "the smallest of a and b"),
        # literals
        ("'x'", "'x'"),
        ("42", "42"),
        ("true", "true"),
        ("null", "nothing"),
        # macros left by jinja.to_plain_sql
        ("__macro__cents_to_dollars(subtotal)", "the cents_to_dollars macro applied to subtotal"),
        ("__macro__date_trunc(day, ordered_at)", "ordered_at cut to the day"),
        ("__macro__thing()", "the thing macro"),
        ("__macro__var('start_date')", "the project variable start_date"),
        ("__macro__generate_surrogate_key(a, b)", "a unique key built from a and b"),
        ("__macro__lookup(a, 'x', 3)", "the lookup macro applied to a, 'x' and 3"),
    ],
)
def test_describe(sql: str, expected: str) -> None:
    assert d(sql) == expected


def test_unknown_functions_fall_back_to_sql_text() -> None:
    result = describe_expr(sqlglot.parse_one("mystery_fn(a, b)"))
    assert result.exact is False
    assert result.text == "MYSTERY_FN(a, b)"
    assert d("coalesce(mystery_fn(a), 0)").startswith("MYSTERY_FN(a), or 0 when")


def test_known_expression_is_exact_and_long_sql_is_shortened() -> None:
    assert describe_expr(sqlglot.parse_one("a + 1")).exact is True
    long = "mystery_fn(" + ", ".join(f"column_{i}" for i in range(40)) + ")"
    text = describe(sqlglot.parse_one(long))
    assert len(text) <= 61
    assert text.endswith("…")


def test_deep_nesting_does_not_raise() -> None:
    sql = "x" + "".join(f" + (y{i} * 2)" for i in range(300))
    assert describe(sqlglot.parse_one(sql))  # truncated, but a string
    nested = "coalesce(" * 40 + "a" + ", 0)" * 40
    assert describe(sqlglot.parse_one(nested))


def test_never_raises_on_odd_nodes() -> None:
    for sql in ("select 1", "a[1]", "a.b.c", "x -> 'y'", "case end"):
        try:
            tree = sqlglot.parse_one(sql, read="duckdb")
        except sqlglot.errors.SqlglotError:
            continue
        assert isinstance(describe(tree), str)


def test_is_predicate() -> None:
    assert is_predicate(sqlglot.parse_one("a > 1"))
    assert is_predicate(sqlglot.parse_one("(a is null)"))
    assert not is_predicate(sqlglot.parse_one("a + 1"))
    assert not is_predicate(sqlglot.parse_one("sum(a)"))
