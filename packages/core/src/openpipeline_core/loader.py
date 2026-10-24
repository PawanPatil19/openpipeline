"""Load a dbt project from its manifest or straight from its files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from openpipeline_core import jinja
from openpipeline_core.models import Column, Node, NodeKind, Project

_KINDS = {k.value: k for k in NodeKind}


class ProjectLoadError(Exception):
    """The path is not a dbt project, or its files could not be read."""


def load_project(path: str | Path, *, prefer_manifest: bool = True) -> Project:
    """Read the dbt project at ``path``.

    Uses ``target/manifest.json`` when it exists and ``prefer_manifest`` is true,
    and otherwise reads the SQL and YAML files directly.
    """
    root = Path(path).resolve()
    project_file = root / "dbt_project.yml"
    if not project_file.is_file():
        raise ProjectLoadError(f"No dbt_project.yml found in {root}")
    config = _read_yaml(project_file)
    manifest = root / "target" / "manifest.json"
    if prefer_manifest and manifest.is_file():
        return _load_from_manifest(root, config, manifest)
    return _load_from_files(root, config)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProjectLoadError(f"Could not parse {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


# --- From manifest.json ------------------------------------------------------


def _load_from_manifest(root: Path, config: dict[str, Any], manifest_path: Path) -> Project:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectLoadError(f"Could not parse {manifest_path}: {exc}") from exc

    project = Project(
        name=str(config.get("name", root.name)), root=str(root), loaded_from="manifest"
    )
    tests_by_node: dict[str, dict[str, list[str]]] = {}

    for uid, raw in manifest.get("nodes", {}).items():
        rtype = raw.get("resource_type")
        if rtype == "test":
            _collect_manifest_test(raw, tests_by_node)
            continue
        kind = _KINDS.get(rtype)
        if kind is None:
            continue
        project.nodes[uid] = Node(
            unique_id=uid,
            name=raw.get("name", uid.split(".")[-1]),
            kind=kind,
            description=raw.get("description") or "",
            path=raw.get("original_file_path"),
            raw_sql=raw.get("raw_code") or raw.get("raw_sql") or "",
            materialized=(raw.get("config") or {}).get("materialized"),
            depends_on=list((raw.get("depends_on") or {}).get("nodes", [])),
            columns=[
                Column(
                    name=c.get("name", n),
                    description=c.get("description") or "",
                    meta=dict(c.get("meta") or (c.get("config") or {}).get("meta") or {}),
                )
                for n, c in (raw.get("columns") or {}).items()
            ],
            tags=list(raw.get("tags") or []),
            meta=dict(raw.get("meta") or (raw.get("config") or {}).get("meta") or {}),
        )

    for uid, raw in manifest.get("sources", {}).items():
        project.nodes[uid] = Node(
            unique_id=uid,
            name=f"{raw.get('source_name')}.{raw.get('name')}",
            kind=NodeKind.SOURCE,
            description=raw.get("description") or "",
            path=raw.get("original_file_path"),
            columns=[
                Column(
                    name=c.get("name", n),
                    description=c.get("description") or "",
                    meta=dict(c.get("meta") or (c.get("config") or {}).get("meta") or {}),
                )
                for n, c in (raw.get("columns") or {}).items()
            ],
            meta=dict(raw.get("meta") or {}),
        )

    for uid, by_column in tests_by_node.items():
        node = project.nodes.get(uid)
        if node is None:
            continue
        for col in node.columns:
            col.tests = by_column.get(col.name, [])

    project.nodes = {
        uid: n.model_copy(update={"depends_on": [d for d in n.depends_on if d in project.nodes]})
        for uid, n in project.nodes.items()
    }
    return project


def _collect_manifest_test(raw: dict[str, Any], out: dict[str, dict[str, list[str]]]) -> None:
    column = raw.get("column_name")
    attached = raw.get("attached_node") or next(
        iter((raw.get("depends_on") or {}).get("nodes", [])), None
    )
    test_name = (raw.get("test_metadata") or {}).get("name")
    if column and attached and test_name:
        out.setdefault(attached, {}).setdefault(column, []).append(test_name)


# --- Straight from files -----------------------------------------------------


def _load_from_files(root: Path, config: dict[str, Any]) -> Project:
    name = str(config.get("name", root.name))
    project = Project(name=name, root=str(root), loaded_from="files")

    model_dirs = [root / p for p in config.get("model-paths", ["models"])]
    seed_dirs = [root / p for p in config.get("seed-paths", ["seeds"])]
    snapshot_dirs = [root / p for p in config.get("snapshot-paths", ["snapshots"])]

    yml_models: dict[str, dict[str, Any]] = {}
    for d in model_dirs + seed_dirs + snapshot_dirs:
        for yml in sorted([*d.rglob("*.yml"), *d.rglob("*.yaml")]) if d.is_dir() else []:
            data = _read_yaml(yml)
            rel = str(yml.relative_to(root))
            for entry in (data.get("models") or []) + (data.get("seeds") or []):
                if isinstance(entry, dict) and "name" in entry:
                    yml_models[entry["name"]] = entry
            for src in data.get("sources") or []:
                _add_source(project, name, src, rel)

    pending_refs: dict[str, list[str]] = {}
    pending_sources: dict[str, list[tuple[str, str]]] = {}

    for kind, dirs, pattern in (
        (NodeKind.MODEL, model_dirs, "*.sql"),
        (NodeKind.SNAPSHOT, snapshot_dirs, "*.sql"),
        (NodeKind.SEED, seed_dirs, "*.csv"),
    ):
        for d in dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.rglob(pattern)):
                node_name = f.stem
                uid = f"{kind.value}.{name}.{node_name}"
                sql = f.read_text(encoding="utf-8") if kind != NodeKind.SEED else ""
                doc = yml_models.get(node_name, {})
                project.nodes[uid] = Node(
                    unique_id=uid,
                    name=node_name,
                    kind=kind,
                    description=doc.get("description", "") or "",
                    path=str(f.relative_to(root)),
                    raw_sql=sql,
                    materialized=jinja.find_materialized(sql)
                    or (doc.get("config") or {}).get("materialized")
                    or _folder_materialization(config, name, f.relative_to(d).parts[:-1])
                    if kind == NodeKind.MODEL
                    else None,
                    columns=[_column(c) for c in doc.get("columns") or [] if isinstance(c, dict)],
                    tags=list((doc.get("config") or {}).get("tags", doc.get("tags", [])) or []),
                    meta=dict(doc.get("meta") or (doc.get("config") or {}).get("meta") or {}),
                )
                pending_refs[uid] = jinja.find_refs(sql)
                pending_sources[uid] = jinja.find_sources(sql)

    by_name = {n.name: uid for uid, n in project.nodes.items() if n.kind != NodeKind.SOURCE}
    for uid, refs in pending_refs.items():
        deps: list[str] = []
        for ref in refs:
            if ref in by_name:
                deps.append(by_name[ref])
            else:
                project.warnings.append(f"{project.nodes[uid].path}: ref('{ref}') not found")
        for src, table in pending_sources[uid]:
            src_uid = f"source.{name}.{src}.{table}"
            if src_uid in project.nodes:
                deps.append(src_uid)
            else:
                project.warnings.append(
                    f"{project.nodes[uid].path}: source('{src}', '{table}') not declared"
                )
        project.nodes[uid].depends_on = deps
    return project


def _add_source(project: Project, pkg: str, src: dict[str, Any], rel_path: str) -> None:
    src_name = src.get("name")
    if not src_name:
        return
    for table in src.get("tables") or []:
        if not isinstance(table, dict) or "name" not in table:
            continue
        uid = f"source.{pkg}.{src_name}.{table['name']}"
        project.nodes[uid] = Node(
            unique_id=uid,
            name=f"{src_name}.{table['name']}",
            kind=NodeKind.SOURCE,
            description=table.get("description") or src.get("description") or "",
            path=rel_path,
            columns=[_column(c) for c in table.get("columns") or [] if isinstance(c, dict)],
            meta=dict(table.get("meta") or {}),
        )


def _column(raw: dict[str, Any]) -> Column:
    tests: list[str] = []
    for t in raw.get("tests", raw.get("data_tests", [])) or []:
        if isinstance(t, str):
            tests.append(t)
        elif isinstance(t, dict) and t:
            tests.append(next(iter(t)))
    return Column(
        name=raw["name"],
        description=raw.get("description") or "",
        tests=tests,
        meta=dict(raw.get("meta") or (raw.get("config") or {}).get("meta") or {}),
    )


def _folder_materialization(
    config: dict[str, Any], project_name: str, folders: tuple[str, ...]
) -> str | None:
    """Apply ``+materialized`` settings from dbt_project.yml, deepest folder wins."""
    scope = (config.get("models") or {}).get(project_name) or {}
    found = scope.get("+materialized") or scope.get("materialized")
    for folder in folders:
        scope = scope.get(folder) if isinstance(scope, dict) else None
        if not isinstance(scope, dict):
            break
        found = scope.get("+materialized") or scope.get("materialized") or found
    return str(found) if found else None
