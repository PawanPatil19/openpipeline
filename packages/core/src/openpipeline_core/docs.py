"""Write model and column descriptions back into a dbt project's YAML files.

The functions here never touch the disk. They return the new content of the one
YAML file that needs to change, so the caller decides whether to write it
straight away (a person saving in the UI) or file it as a proposal (an agent).

YAML is edited with ruamel.yaml in round-trip mode, so comments, key order, and
quoting in the rest of the file are kept.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from openpipeline_core.models import NodeKind, Project


class FileEdit(BaseModel):
    path: str
    """Path relative to the project root."""
    content: str
    """Full new content of the file."""


class DocsUpdate(BaseModel):
    """New documentation for one model. ``None`` means leave it as it is."""

    description: str | None = None
    columns: dict[str, str] = Field(default_factory=dict)
    """Column name to new description. Columns not listed keep theirs."""


_SKIP_DIRS = {"target", "dbt_packages", "logs", ".openpipeline", ".git", "node_modules", ".venv"}


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # Do not re-wrap long descriptions.
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def update_docs(project: Project, name_or_id: str, update: DocsUpdate) -> FileEdit:
    """Return the YAML file edit that applies ``update`` to a model.

    Finds the properties file that already documents the model. When there is
    none, adds an entry to ``schema.yml`` next to the model's SQL file,
    creating that file if needed.
    """
    node = project.get(name_or_id)
    if node is None or node.kind != NodeKind.MODEL:
        raise KeyError(f"No model named {name_or_id!r}")
    if node.path is None:
        raise ValueError(f"Model {node.name!r} has no file path")

    root = Path(project.root)
    found = find_properties_file(root, node.name)
    y = _yaml()
    data: Any
    if found is not None:
        rel, data = found
    else:
        rel = str(Path(node.path).parent / "schema.yml")
        target = root / rel
        data = _load(y, target) if target.is_file() else None
        if not isinstance(data, CommentedMap):
            data = CommentedMap(version=2)
    entry = _model_entry(data, node.name)

    if update.description is not None:
        entry["description"] = update.description
    if update.columns:
        columns = entry.get("columns")
        if not isinstance(columns, CommentedSeq):
            columns = CommentedSeq()
            entry["columns"] = columns
        by_name = {c.get("name"): c for c in columns if isinstance(c, CommentedMap)}
        for col, desc in update.columns.items():
            if col in by_name:
                by_name[col]["description"] = desc
            else:
                columns.append(CommentedMap(name=col, description=desc))

    out = io.StringIO()
    y.dump(data, out)
    return FileEdit(path=rel, content=out.getvalue())


def find_properties_file(root: Path, model: str) -> tuple[str, CommentedMap] | None:
    """The YAML file (relative path and parsed content) that documents ``model``."""
    y = _yaml()
    for yml in sorted([*root.rglob("*.yml"), *root.rglob("*.yaml")]):
        rel = yml.relative_to(root)
        if _SKIP_DIRS.intersection(rel.parts[:-1]):
            continue
        if yml.name == "dbt_project.yml":
            continue
        data = _load(y, yml)
        if not isinstance(data, CommentedMap):
            continue
        for entry in data.get("models") or []:
            if isinstance(entry, CommentedMap) and entry.get("name") == model:
                return str(rel), data
    return None


def _load(y: YAML, path: Path) -> Any:
    try:
        return y.load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _model_entry(data: CommentedMap, model: str) -> CommentedMap:
    models = data.get("models")
    if not isinstance(models, CommentedSeq):
        models = CommentedSeq()
        data["models"] = models
    for entry in models:
        if isinstance(entry, CommentedMap) and entry.get("name") == model:
            return entry
    entry = CommentedMap(name=model)
    models.append(entry)
    return entry
