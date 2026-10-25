"""Following columns through CTEs, subqueries and ``select *``, plus the new wording."""

from openpipeline_core import (
    Column,
    ColumnLineage,
    Node,
    NodeKind,
    Project,
    explain_model,
)


def _project(**models: str) -> Project:
    """A files-mode project with an undocumented source ``raw.t`` and one model per kwarg."""
    project = Project(name="x", root="/", loaded_from="files")
    project.nodes["source.x.raw.t"] = Node(
        unique_id="source.x.raw.t", name="raw.t", kind=NodeKind.SOURCE
    )
    for name, sql in models.items():
        project.nodes[f"model.x.{name}"] = Node(
            unique_id=f"model.x.{name}", name=name, kind=NodeKind.MODEL, raw_sql=sql
        )
    for node in list(project.nodes.values()):
        if node.kind == NodeKind.MODEL:
            node.depends_on = [
                uid
                for uid, other in project.nodes.items()
                if f"ref('{other.name}')" in node.raw_sql
            ]
    return project


def _how(project: Project, name: str) -> dict[str, str]:
    return {c.name: c.how for c in explain_model(project, name).columns}


def test_star_expands_through_ctes_to_the_real_columns() -> None:
    project = _project(
        base="select id as order_id, amount, status from raw.t",
        m="""with src as (select * from {{ ref('base') }}),
             big as (select *, amount * 2 as doubled from src where amount > 10)
             select * from big""",
    )
    story = explain_model(project, "m")
    assert [c.name for c in story.columns] == ["order_id", "amount", "status", "doubled"]
    cols = {c.name: c for c in story.columns}
    assert cols["order_id"].how == "passed through from base"
    assert cols["order_id"].from_step is None
    assert cols["doubled"].how == "amount times 2"
    assert cols["doubled"].from_step == "big"
    assert story.filters == ["amount is more than 10"]
    assert story.steps == [
        "Reads base.",
        "Builds a step called big: takes rows from src, keeps only rows where "
        "amount is more than 10.",
        "Final result: everything from big.",
    ]


def test_star_over_unknown_columns_is_kept_and_names_the_source() -> None:
    project = _project(m="with a as (select * from raw.t) select *, 1 as one from a")
    story = explain_model(project, "m")
    assert [(c.name, c.how) for c in story.columns] == [
        ("*", "every column from raw.t"),
        ("one", "always 1"),
    ]
    assert story.steps[0] == "Reads raw.t."


def test_columns_computed_in_a_cte_keep_their_story_and_step() -> None:
    project = _project(
        m="""with totals as (select order_id, sum(amount) as total from raw.t group by 1),
             flagged as (select order_id, total, total > 100 as is_big from totals)
             select order_id as id, total, is_big from flagged""",
    )
    story = explain_model(project, "m")
    cols = {c.name: c for c in story.columns}
    assert cols["total"].how == "the total of amount per order_id"
    assert cols["total"].from_step == "totals"
    assert cols["is_big"].how == "true when total is more than 100"
    assert cols["is_big"].from_step == "flagged"
    assert cols["id"].how == "renamed from order_id"
    assert story.grain == ["id"]
    assert "one row per id" in story.summary


def test_positional_group_by_resolves_to_the_column_name() -> None:
    project = _project(
        m="select order_id, status, count(*) as n from raw.t group by 1, 2 order by 1",
    )
    story = explain_model(project, "m")
    assert story.grain == ["order_id", "status"]
    assert "one row per order_id and status" in story.summary
    assert _how(project, "m")["n"] == "the number of rows per order_id and status"
    assert story.steps[-1] == (
        "Final result: takes rows from raw.t, rolls up to one row per order_id and status."
    )
    # An expression behind a position is named by its alias, not shown as a number.
    expr = _project(m="select date_trunc('day', ts) as day, count(*) as n from raw.t group by 1")
    assert explain_model(expr, "m").grain == ["day"]


def test_group_by_all_and_expression_keys() -> None:
    project = _project(m="select a, lower(b) as b2, sum(c) as c from raw.t group by all")
    assert explain_model(project, "m").grain == ["a", "b2"]
    project = _project(m="select sum(c) as c from raw.t group by lower(b)")
    assert explain_model(project, "m").grain == ["b in lower case"]


def test_grain_is_inherited_only_through_plain_selects() -> None:
    grouped = "with g as (select a, sum(b) as s from raw.t group by a)"
    assert explain_model(_project(m=f"{grouped} select * from g"), "m").grain == ["a"]
    kept = explain_model(_project(m=f"{grouped} select a, s from g where s > 1"), "m")
    assert kept.grain == ["a"]
    # Dropping the key, or joining, loses the grain.
    assert explain_model(_project(m=f"{grouped} select s from g"), "m").grain == []
    joined = f"{grouped} select * from g join raw.t on g.a = t.a"
    assert explain_model(_project(m=joined), "m").grain == []


def test_upstream_columns_come_from_lineage_when_given() -> None:
    project = _project(base="select * from raw.t", m="select * from {{ ref('base') }}")
    plain = explain_model(project, "m")
    assert [(c.name, c.how) for c in plain.columns] == [("*", "every column from base")]

    class FakeLineage:
        def columns(self, node_id: str) -> list[str]:
            return ["a", "b"] if node_id == "model.x.base" else []

    story = explain_model(project, "m", lineage=FakeLineage())  # type: ignore[arg-type]
    assert [(c.name, c.how) for c in story.columns] == [
        ("a", "passed through from base"),
        ("b", "passed through from base"),
    ]


def test_real_lineage_object_is_accepted() -> None:
    project = _project(base="select a, b from raw.t", m="select * from {{ ref('base') }}")
    story = explain_model(project, "m", lineage=ColumnLineage(project))
    assert [c.name for c in story.columns] == ["a", "b"]


def test_upstream_story_columns_are_used_without_lineage_and_docs_as_last_resort() -> None:
    project = _project(base="select a, b from raw.t", m="select * from {{ ref('base') }}")
    assert [c.name for c in explain_model(project, "m").columns] == ["a", "b"]
    # base's SQL cannot give columns (star over an unknown table), so its docs are used.
    project = _project(base="select * from raw.t", m="select * from {{ ref('base') }}")
    project.nodes["model.x.base"].columns = [Column(name="docs_col")]
    assert [c.name for c in explain_model(project, "m").columns] == ["docs_col"]


def test_subqueries_and_joins_are_followed() -> None:
    project = _project(
        base="select a, b from raw.t",
        m="""select s.a, s.n, b.b as other
             from (select a, count(*) as n from raw.t group by a) s
             join {{ ref('base') }} b on b.a = s.a""",
    )
    assert _how(project, "m") == {
        "a": "passed through from raw.t",
        "n": "the number of rows per a",
        "other": "renamed from b",
    }
    assert "takes rows from a subquery" in explain_model(project, "m").steps[-1]


def test_union_takes_columns_from_the_first_query() -> None:
    project = _project(m="select a, 1 as src from raw.t union all select a, 2 from raw.t")
    story = explain_model(project, "m")
    assert [c.name for c in story.columns] == ["a", "src"]
    assert story.steps[-1] == "Final result: stacks the results of 2 queries."


def test_macros_in_files_mode_are_described_not_null() -> None:
    project = _project(
        m="select {{ cents_to_dollars('amount') }} as amount, {{ foo() }} as f from raw.t"
    )
    how = _how(project, "m")
    assert how["amount"] == "the cents_to_dollars macro applied to amount"
    assert how["f"] == "the foo macro"
    assert "NULL" not in " ".join(how.values())


def test_a_macro_standing_in_for_a_table_does_not_break_the_story() -> None:
    project = _project(
        m="with days as ({{ dbt.date_spine('day', 'a', 'b') }}) select * from days",
    )
    story = explain_model(project, "m")
    assert story.parse_error is None
    assert story.steps[0] == "Reads date_spine."


def test_if_else_in_files_mode_keeps_one_branch_and_parses() -> None:
    project = _project(m="select a, {% if var('x') %} b {% else %} c {% endif %} as v from raw.t")
    story = explain_model(project, "m")
    assert story.parse_error is None
    assert _how(project, "m")["v"] == "renamed from b"


def test_compiled_sql_wins_over_raw_sql() -> None:
    project = Project(name="x", root="/", loaded_from="manifest", adapter="duckdb")
    project.nodes["model.x.stg"] = Node(
        unique_id="model.x.stg", name="stg", kind=NodeKind.MODEL, relation_name='"d"."s"."stg"'
    )
    project.nodes["model.x.m"] = Node(
        unique_id="model.x.m",
        name="m",
        kind=NodeKind.MODEL,
        depends_on=["model.x.stg"],
        raw_sql="select {{ cents('a') }} as a from {{ ref('stg') }}",
        compiled_sql='select (a / 100)::numeric(16, 2) as a from "d"."s"."stg"',
    )
    story = explain_model(project, "m")
    assert story.columns[0].how == "a divided by 100, as a number"
    assert story.steps == ["Final result: takes rows from stg."]
    assert story.parse_error is None


def test_unknown_expressions_say_calculated_as() -> None:
    project = _project(m="select mystery_fn(a) as z from raw.t")
    assert _how(project, "m")["z"] == "calculated as MYSTERY_FN(a)"
