import datetime
import decimal
import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openpipeline.api import create_app
from openpipeline.sample import MAX_LIMIT, SampleEngine, clamp_limit, json_safe
from openpipeline.state import ProjectState

duckdb = pytest.importorskip("duckdb")

MODELS = ["stg_customers", "stg_orders", "stg_payments", "orders", "customers"]


def _engine(
    project_dir: Path,
    *,
    sample_data: Path | None = None,
    dialect: str | None = None,
    timeout: float = 5.0,
) -> SampleEngine:
    return SampleEngine(
        ProjectState(project_dir), sample_data=sample_data, dialect=dialect, timeout=timeout
    )


def _write_model(project_dir: Path, name: str, sql: str) -> None:
    (project_dir / "models" / "marts" / f"{name}.sql").write_text(sql)


@pytest.mark.parametrize("model", MODELS)
def test_every_jaffle_model_previews(project_dir: Path, model: str) -> None:
    result = _engine(project_dir).sample(model)
    assert result.error is None, result.error
    assert result.rows
    assert len(result.rows) <= 20
    json.dumps(result.model_dump())  # JSON-safe


def test_values_are_correct(project_dir: Path) -> None:
    result = _engine(project_dir).sample("orders", 200)
    assert result.columns == ["order_id", "customer_id", "order_date", "status", "amount"]
    assert result.rows[0][0] == 1
    assert isinstance(result.rows[0][2], str)  # dates become strings
    assert all(r[3] != "test" for r in result.rows)  # staging filter applied


def test_limit_is_clamped(project_dir: Path) -> None:
    assert clamp_limit(None) == 20
    assert clamp_limit(0) == 1
    assert clamp_limit(10_000) == MAX_LIMIT
    assert len(_engine(project_dir).sample("stg_orders", 3).rows) == 3
    assert _engine(project_dir).sample("stg_orders", 5000).row_limit == MAX_LIMIT


def test_missing_source_names_model_and_table(project_dir: Path) -> None:
    (project_dir / "sample_data" / "raw.orders.csv").unlink()
    result = _engine(project_dir).sample("customers")
    assert result.error is not None
    assert result.error.missing_table == "raw.orders"
    assert result.error.model == "stg_orders"
    assert "raw.orders" in result.error.message
    assert result.rows == []


def test_no_sample_folder_reports_first_missing(project_dir: Path) -> None:
    shutil.rmtree(project_dir / "sample_data")
    result = _engine(project_dir).sample("stg_customers")
    assert result.error is not None
    assert result.error.missing_table == "raw.customers"


def test_unsupported_jinja_error(project_dir: Path) -> None:
    _write_model(project_dir, "v", "select {{ var('x') }} as x from {{ ref('orders') }}")
    result = _engine(project_dir).sample("v")
    assert result.error is not None
    assert result.error.model == "v"
    assert "Jinja" in result.error.message


def test_sql_error_names_model(project_dir: Path) -> None:
    _write_model(project_dir, "bad", "select nope from {{ ref('orders') }}")
    result = _engine(project_dir).sample("bad")
    assert result.error is not None
    assert result.error.model == "bad"
    assert result.error.missing_table is None


def test_undeclared_table_is_reported_as_missing(project_dir: Path) -> None:
    _write_model(project_dir, "m", "select * from ghost.things")
    result = _engine(project_dir).sample("m")
    assert result.error is not None
    assert result.error.missing_table is not None
    assert "ghost" in result.error.missing_table


def test_timeout_stops_slow_models(project_dir: Path) -> None:
    _write_model(
        project_dir,
        "slow",
        "select sum(a.range * b.range) as n "
        "from range(1000000000) a cross join range(1000000000) b",
    )
    started = time.monotonic()
    result = _engine(project_dir, timeout=0.5).sample("slow")
    assert time.monotonic() - started < 10
    assert result.error is not None
    assert "took longer" in result.error.message
    assert result.error.model == "slow"


def test_seeds_become_tables(project_dir: Path) -> None:
    (project_dir / "seeds").mkdir()
    (project_dir / "seeds" / "countries.csv").write_text("code,name\nNZ,New Zealand\nFR,France\n")
    _write_model(
        project_dir, "c", "select upper(name) as name from {{ ref('countries') }} order by code"
    )
    result = _engine(project_dir).sample("c")
    assert result.error is None, result.error
    assert result.rows == [["FRANCE"], ["NEW ZEALAND"]]
    status = _engine(project_dir).status()
    assert any(t.name == "countries" and t.kind == "seed" for t in status.tables)


def test_custom_sample_folder_and_parquet(project_dir: Path, tmp_path: Path) -> None:
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    con = duckdb.connect()
    for name in ("customers", "orders", "payments"):
        src = project_dir / "sample_data" / f"raw.{name}.csv"
        out = folder / f"raw.{name}.parquet"
        con.execute(f"copy (select * from read_csv_auto('{src}')) to '{out}' (format parquet)")
    shutil.rmtree(project_dir / "sample_data")
    result = _engine(project_dir, sample_data=folder).sample("customers")
    assert result.error is None, result.error
    assert result.rows


def test_duckdb_file_is_attached_read_only(project_dir: Path, tmp_path: Path) -> None:
    db = tmp_path / "sample.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create schema raw")
    for name in ("customers", "orders", "payments"):
        src = project_dir / "sample_data" / f"raw.{name}.csv"
        con.execute(f"create table raw.{name} as select * from read_csv_auto('{src}')")
    con.close()
    shutil.rmtree(project_dir / "sample_data")
    engine = _engine(project_dir, sample_data=db)
    names = {t.name for t in engine.status().tables}
    assert names == {"raw.customers", "raw.orders", "raw.payments"}
    result = engine.sample("customers")
    assert result.error is None, result.error
    assert result.rows


def test_dialect_is_transpiled(project_dir: Path) -> None:
    _write_model(
        project_dir,
        "sf",
        "select iff(status = 'completed', 1, 0) as done from {{ ref('stg_orders') }}",
    )
    assert _engine(project_dir, dialect="snowflake").sample("sf").error is None


def test_nothing_is_written(project_dir: Path) -> None:
    before = sorted(p.relative_to(project_dir) for p in project_dir.rglob("*"))
    _engine(project_dir).sample("customers")
    assert sorted(p.relative_to(project_dir) for p in project_dir.rglob("*")) == before


def test_sample_data_does_not_change_nodes(project_dir: Path) -> None:
    project = ProjectState(project_dir).project()
    assert len(project.nodes) == 8
    assert not [n for n in project.nodes.values() if n.kind == "seed"]


def test_model_sql_cannot_read_files(project_dir: Path) -> None:
    secret = project_dir / "secret.csv"
    secret.write_text("a\n1\n")
    _write_model(project_dir, "peek", f"select * from read_csv_auto('{secret}')")
    result = _engine(project_dir).sample("peek")
    assert result.error is not None
    assert result.rows == []


def test_json_safe() -> None:
    assert json_safe(decimal.Decimal("1.50")) == "1.50"
    assert json_safe(datetime.date(2026, 1, 2)) == "2026-01-02"
    assert json_safe(float("nan")) == "nan"
    assert json_safe(2**60) == str(2**60)
    assert json_safe(b"\x01") == "01"


def test_api(project_dir: Path) -> None:
    client = TestClient(create_app(project_dir, serve_ui=False))
    status = client.get("/api/sample/status").json()
    assert status["duckdb"] is True
    assert {t["name"] for t in status["tables"]} == {"raw.customers", "raw.orders", "raw.payments"}

    body = client.get("/api/models/customers/sample?limit=5").json()
    assert body["error"] is None
    assert len(body["rows"]) == 5
    assert body["row_limit"] == 5
    assert "customer_id" in body["columns"]

    assert client.get("/api/models/nope/sample").status_code == 404
    assert client.get("/api/models/customers/sample?limit=0").status_code == 422
    assert client.get("/api/models/customers/sample?limit=999").status_code == 422

    (project_dir / "sample_data" / "raw.payments.csv").unlink()
    err = client.get("/api/models/orders/sample").json()
    assert err["error"]["missing_table"] == "raw.payments"
    assert err["error"]["model"] == "stg_payments"


def test_api_without_duckdb(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("openpipeline.sample.duckdb_installed", lambda: False)
    client = TestClient(create_app(project_dir, serve_ui=False))
    status = client.get("/api/sample/status").json()
    assert status["duckdb"] is False
    assert "openpipeline[preview]" in status["install_hint"]
    body = client.get("/api/models/orders/sample").json()
    assert "openpipeline[preview]" in body["error"]["message"]


def test_env_var_sets_sample_folder(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("OPENPIPELINE_SAMPLE_DATA", str(empty))
    result = _engine(project_dir).sample("stg_orders")
    assert result.error is not None
    assert result.error.missing_table == "raw.orders"


def test_preview_section_of_openpipeline_yml_sets_defaults(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENPIPELINE_SAMPLE_DATA", raising=False)
    monkeypatch.delenv("OPENPIPELINE_DIALECT", raising=False)
    shutil.copytree(project_dir / "sample_data", project_dir / "fixtures")
    (project_dir / "openpipeline.yml").write_text(
        "preview:\n  sample_data: fixtures\n  dialect: snowflake\n"
    )
    engine = _engine(project_dir)
    assert engine.sample_data == (project_dir / "fixtures").resolve()
    assert engine.dialect == "snowflake"
    assert engine.sample("customers").error is None

    # Flags beat env vars, and env vars beat the file.
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("OPENPIPELINE_SAMPLE_DATA", str(other))
    monkeypatch.setenv("OPENPIPELINE_DIALECT", "bigquery")
    assert _engine(project_dir).sample_data == other.resolve()
    assert _engine(project_dir).dialect == "bigquery"
    flagged = _engine(project_dir, sample_data=project_dir / "sample_data", dialect="postgres")
    assert flagged.sample_data == (project_dir / "sample_data").resolve()
    assert flagged.dialect == "postgres"


def test_bad_preview_section_is_ignored(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENPIPELINE_SAMPLE_DATA", raising=False)
    monkeypatch.delenv("OPENPIPELINE_DIALECT", raising=False)
    for text in ("preview: nope\n", "preview:\n  dialect: 5\n", "- a\n- b\n", ": : :\n"):
        (project_dir / "openpipeline.yml").write_text(text)
        engine = _engine(project_dir)
        assert engine.sample_data is None
        assert engine.dialect is None
