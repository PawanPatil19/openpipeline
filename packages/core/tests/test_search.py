from pathlib import Path

from openpipeline_core import ColumnLineage, SearchHit, load_project, search_project


def _search(example_dir: Path, query: str, limit: int = 20) -> list[SearchHit]:
    project = load_project(example_dir)
    return search_project(project, ColumnLineage(project), query, limit)


def test_exact_beats_prefix_beats_substring_beats_description(example_dir: Path) -> None:
    exact = _search(example_dir, "orders")
    assert (exact[0].kind, exact[0].name, exact[0].score) == ("model", "orders", 100)
    assert all(h.score < 100 for h in exact[1:])
    assert {"stg_orders", "raw.orders"} <= {h.name for h in exact}

    prefix = _search(example_dir, "stg")
    assert {h.name for h in prefix if h.kind == "model"} == {
        "stg_customers",
        "stg_orders",
        "stg_payments",
    }
    assert {h.score for h in prefix} == {80}

    substring = _search(example_dir, "payment")
    by_name = {(h.kind, h.name, h.column): h.score for h in substring}
    assert by_name[("model", "stg_payments", None)] == 60
    # A description-only match ranks below name matches.
    desc = _search(example_dir, "cents")
    assert [h.name for h in desc] == ["stg_payments"]
    assert desc[0].score == 30
    assert "cents" in desc[0].snippet


def test_column_hits_carry_the_column_and_a_snippet(example_dir: Path) -> None:
    hits = _search(example_dir, "lifetime_value")
    top = hits[0]
    assert (top.kind, top.name, top.column) == ("column", "customers", "lifetime_value")
    assert "paid us" in top.snippet
    undocumented = _search(example_dir, "payment_method")
    assert any(h.column == "payment_method" and h.snippet for h in undocumented)


def test_every_word_must_match_and_punctuation_is_ignored(example_dir: Path) -> None:
    hits = _search(example_dir, "customer id")
    assert next(h.column for h in hits if h.name == "stg_customers") == "customer_id"
    assert _search(example_dir, "orders zzz") == []
    assert _search(example_dir, "raw.customers")[0].name == "raw.customers"


def test_limit_empty_query_and_ties_are_deterministic(example_dir: Path) -> None:
    assert _search(example_dir, "") == []
    assert _search(example_dir, "   ") == []
    assert len(_search(example_dir, "order", limit=3)) == 3
    assert _search(example_dir, "order") == _search(example_dir, "order")
    assert _search(example_dir, "order", limit=0) == []


def test_works_without_a_lineage_index(example_dir: Path) -> None:
    project = load_project(example_dir)
    hits = search_project(project, None, "lifetime")
    assert hits[0].column == "lifetime_value"
