"""Preview a model's rows by running its SQL on sample data in memory.

The engine uses an in-memory DuckDB. It never connects to a warehouse and it
never writes to disk. Sample data comes from three places, in this order:

1. The project's seeds (CSV files), as tables named after the seed.
2. A sample data folder holding ``<source>.<table>.csv`` or ``.parquet`` files
   that stand in for dbt sources.
3. Optionally a ``.duckdb`` file, attached read-only, with a schema per source.

DuckDB is an optional install: ``pip install 'openpipeline[preview]'``.
"""

from __future__ import annotations

import datetime
import decimal
import math
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlglot
import yaml
from pydantic import BaseModel
from sqlglot.errors import SqlglotError

from openpipeline.state import ProjectState
from openpipeline_core import Node, NodeKind, Project, UnsupportedJinja, compile_sql, plan_preview

if TYPE_CHECKING:
    import duckdb

DEFAULT_LIMIT = 20
MAX_LIMIT = 200
DEFAULT_TIMEOUT = 5.0
SAMPLE_FOLDER = "sample_data"
INSTALL_HINT = "Install DuckDB to preview rows: pip install 'openpipeline[preview]'"
_MAX_SAFE_INT = 2**53
_CATALOG_RE = re.compile(r"Table with name \"?([\w.\-]+)\"? does not exist", re.IGNORECASE)
_SCHEMA_RE = re.compile(r"Schema with name \"?([\w\-]+)\"? does not exist", re.IGNORECASE)


def duckdb_installed() -> bool:
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return False
    return True


class SampleError(BaseModel):
    message: str
    model: str | None = None
    missing_table: str | None = None
    """Name of the table to add, such as ``raw.orders``, when data is missing."""


class SampleResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_limit: int
    error: SampleError | None = None


class SampleTable(BaseModel):
    name: str
    """How the project refers to it: ``orders`` for a seed, ``raw.orders`` for a source."""
    kind: str
    """``seed``, ``source``, or ``duckdb``."""
    path: str


class SampleStatus(BaseModel):
    duckdb: bool
    install_hint: str | None
    sample_data: str | None
    tables: list[SampleTable]


@dataclass(frozen=True)
class _Table:
    schema: str | None
    name: str
    kind: str
    path: Path

    @property
    def key(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name


class _ModelError(Exception):
    def __init__(self, message: str, model: str, missing: str | None = None) -> None:
        super().__init__(message)
        self.model = model
        self.missing = missing


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


def json_safe(value: Any) -> Any:
    """Turn a DuckDB value into something JSON can carry."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value if abs(value) < _MAX_SAFE_INT else str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray):
        return bytes(value).hex()
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _read_function(path: Path) -> str:
    fn = "read_parquet" if path.suffix.lower() == ".parquet" else "read_csv_auto"
    return f"{fn}({_lit(str(path))})"


def _first_line(exc: Exception) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _missing_from_error(text: str) -> str | None:
    m = _CATALOG_RE.search(text) or _SCHEMA_RE.search(text)
    return m.group(1) if m else None


def _missing_message(model: str, table: str) -> str:
    if "." in table:
        return f"{model} reads {table}, but there is no sample data for it."
    return f"{model} reads {table}, but its sample file was not found."


def _preview_config(root: Path) -> dict[str, str]:
    """Read the optional ``preview:`` section of ``openpipeline.yml``.

    Understands ``sample_data`` (a folder or ``.duckdb`` file, relative to the
    project) and ``dialect``. Anything else is ignored, and so is a file that
    cannot be read.
    """
    try:
        data = yaml.safe_load((root / "openpipeline.yml").read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return {}
    section = data.get("preview") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return {}
    return {
        key: value.strip()
        for key in ("sample_data", "dialect")
        if isinstance(value := section.get(key), str) and value.strip()
    }


class SampleEngine:
    """Runs model previews for one project."""

    def __init__(
        self,
        state: ProjectState,
        *,
        sample_data: str | Path | None = None,
        dialect: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.state = state
        configured = _preview_config(state.root)
        chosen = sample_data or os.environ.get("OPENPIPELINE_SAMPLE_DATA")
        self.sample_data: Path | None = None
        if chosen:
            self.sample_data = Path(chosen).expanduser().resolve()
        elif "sample_data" in configured:
            # Paths in the file are relative to the project, not the working folder.
            self.sample_data = (state.root / Path(configured["sample_data"]).expanduser()).resolve()
        self.dialect = (
            dialect or os.environ.get("OPENPIPELINE_DIALECT") or configured.get("dialect")
        )
        self.timeout = timeout

    @property
    def location(self) -> Path:
        return self.sample_data or self.state.root / SAMPLE_FOLDER

    # --- Discovering sample data ------------------------------------------

    def _duckdb_files(self) -> list[Path]:
        p = self.location
        if p.is_file() and p.suffix.lower() in {".duckdb", ".db"}:
            return [p]
        if p.is_dir():
            return sorted(p.glob("*.duckdb"))
        return []

    def _seed_tables(self, project: Project) -> list[_Table]:
        out: list[_Table] = []
        for node in project.nodes.values():
            if node.kind != NodeKind.SEED or not node.path:
                continue
            path = Path(project.root) / node.path
            if path.is_file():
                out.append(_Table(None, node.name, "seed", path))
        return sorted(out, key=lambda t: t.key)

    def _source_tables(self) -> list[_Table]:
        folder = self.location
        out: list[_Table] = []
        if not folder.is_dir():
            return out
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in {".csv", ".parquet"}:
                continue
            source, _, table = path.stem.partition(".")
            if source and table:
                out.append(_Table(source, table, "source", path))
        return out

    def _display(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.state.root))
        except ValueError:
            return str(path)

    def status(self) -> SampleStatus:
        project = self.state.project()
        installed = duckdb_installed()
        tables = [
            SampleTable(name=t.key, kind=t.kind, path=self._display(t.path))
            for t in [*self._seed_tables(project), *self._source_tables()]
        ]
        if installed:
            for db_file in self._duckdb_files():
                tables += [
                    SampleTable(name=key, kind="duckdb", path=self._display(db_file))
                    for key in self._list_duckdb_tables(db_file)
                ]
        return SampleStatus(
            duckdb=installed,
            install_hint=None if installed else INSTALL_HINT,
            sample_data=self._display(self.location) if self.location.exists() else None,
            tables=tables,
        )

    @staticmethod
    def _list_duckdb_tables(db_file: Path) -> list[str]:
        import duckdb

        try:
            con = duckdb.connect(":memory:")
            try:
                con.execute(f"ATTACH {_lit(str(db_file))} AS sample_db (READ_ONLY)")
                rows = con.execute(
                    "select table_schema, table_name from information_schema.tables "
                    "where table_catalog = 'sample_db' order by 1, 2"
                ).fetchall()
            finally:
                con.close()
        except duckdb.Error:
            return []
        return [f"{s}.{t}" if s != "main" else str(t) for s, t in rows]

    # --- Running a preview ------------------------------------------------

    def sample(self, name: str, limit: int | None = None) -> SampleResult:
        """Run model ``name`` on sample data. Raises ``KeyError`` for an unknown model."""
        row_limit = clamp_limit(limit)
        project = self.state.project()
        plan = plan_preview(project, self.state.graph(), name)

        def fail(
            message: str, model: str | None = None, missing: str | None = None
        ) -> SampleResult:
            err = SampleError(message=message, model=model, missing_table=missing)
            return SampleResult(columns=[], rows=[], row_limit=row_limit, error=err)

        if not duckdb_installed():
            return fail(INSTALL_HINT)

        import duckdb

        con = duckdb.connect(":memory:")
        timer = threading.Timer(self.timeout, con.interrupt)
        timer.daemon = True
        current = plan.target.name
        try:
            timer.start()
            tables = self._register(con, project, plan.seeds, plan.sources)
            # Sample data is loaded. Model SQL must not read or write any file.
            con.execute("SET enable_external_access = false")
            for model in plan.models:
                current = model.name
                missing = self._first_missing(model, project, tables)
                if missing is not None:
                    return fail(_missing_message(model.name, missing), model.name, missing)
                self._create_view(con, model)
            cursor = con.execute(f"SELECT * FROM {_quote(plan.target.name)} LIMIT {row_limit}")
            columns = [d[0] for d in cursor.description]
            rows = [[json_safe(v) for v in row] for row in cursor.fetchall()]
            return SampleResult(columns=columns, rows=rows, row_limit=row_limit)
        except _ModelError as exc:
            return fail(str(exc), exc.model, exc.missing)
        except duckdb.InterruptException:
            return fail(
                f"{current} took longer than {self.timeout:g} seconds on the sample data, "
                "so the preview was stopped.",
                current,
            )
        except duckdb.Error as exc:
            missing = _missing_from_error(str(exc))
            if missing:
                return fail(_missing_message(current, missing), current, missing)
            return fail(f"{current}: {_first_line(exc)}", current)
        finally:
            timer.cancel()
            con.close()

    def _register(
        self,
        con: duckdb.DuckDBPyConnection,
        project: Project,
        seeds: list[Node],
        sources: list[Node],
    ) -> set[str]:
        """Load the sample tables the plan needs. Returns the keys that exist."""
        have: set[str] = set()
        seed_files = {t.name: t for t in self._seed_tables(project)}
        for seed in seeds:
            table = seed_files.get(seed.name)
            if table is not None:
                con.execute(
                    f"CREATE TABLE {_quote(seed.name)} AS SELECT * FROM {_read_function(table.path)}"
                )
                have.add(seed.name)
        folder_files = {t.key: t for t in self._source_tables()}
        attached = self._attach(con)
        for src in sources:
            schema, _, table_name = src.name.partition(".")
            key = f"{schema}.{table_name}"
            target = f"{_quote(schema)}.{_quote(table_name)}"
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote(schema)}")
            file = folder_files.get(key)
            if file is not None:
                con.execute(f"CREATE TABLE {target} AS SELECT * FROM {_read_function(file.path)}")
                have.add(key)
                continue
            for alias in attached:
                owner = con.execute(
                    "select table_schema from information_schema.tables "
                    "where table_catalog = ? and table_schema in (?, 'main') "
                    "and table_name = ? order by table_schema = ? desc limit 1",
                    [alias, schema, table_name, schema],
                ).fetchone()
                if owner:
                    con.execute(
                        f"CREATE VIEW {target} AS "
                        f"SELECT * FROM {_quote(alias)}.{_quote(owner[0])}.{_quote(table_name)}"
                    )
                    have.add(key)
                    break
        return have

    def _attach(self, con: duckdb.DuckDBPyConnection) -> list[str]:
        aliases: list[str] = []
        for i, db_file in enumerate(self._duckdb_files()):
            alias = f"sample_db_{i}"
            con.execute(f"ATTACH {_lit(str(db_file))} AS {alias} (READ_ONLY)")
            aliases.append(alias)
        return aliases

    @staticmethod
    def _first_missing(model: Node, project: Project, tables: set[str]) -> str | None:
        """The first source or seed this model reads that has no sample data."""
        for uid in model.depends_on:
            dep = project.nodes.get(uid)
            if (
                dep is not None
                and dep.kind in (NodeKind.SOURCE, NodeKind.SEED)
                and dep.name not in tables
            ):
                return dep.name
        return None

    def _create_view(self, con: duckdb.DuckDBPyConnection, model: Node) -> None:
        import duckdb

        try:
            compiled = compile_sql(model.raw_sql)
        except UnsupportedJinja as exc:
            raise _ModelError(f"{model.name}: {exc}", model.name) from exc
        try:
            statements = sqlglot.transpile(compiled, read=self.dialect, write="duckdb")
        except (SqlglotError, ValueError) as exc:
            raise _ModelError(f"{model.name}: {_first_line(exc)}", model.name) from exc
        if len(statements) != 1:
            raise _ModelError(f"{model.name}: expected one SELECT statement.", model.name)
        run: Callable[[str], Any] = con.execute
        try:
            run(f"CREATE OR REPLACE VIEW {_quote(model.name)} AS {statements[0]}")
        except duckdb.InterruptException:
            raise
        except duckdb.Error as exc:
            missing = _missing_from_error(str(exc))
            if missing:
                raise _ModelError(
                    _missing_message(model.name, missing), model.name, missing
                ) from exc
            raise _ModelError(f"{model.name}: {_first_line(exc)}", model.name) from exc
