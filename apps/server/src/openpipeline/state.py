"""Keeps the loaded project in memory and reloads it when files change."""

from __future__ import annotations

import threading
from pathlib import Path

from openpipeline_core import (
    ColumnLineage,
    ModelGraph,
    Project,
    RuleRegistry,
    load_project,
    load_rules,
)

_WATCHED = {".sql", ".yml", ".yaml", ".csv", ".json"}
_SKIP_DIRS = {".git", "node_modules", "dbt_packages", ".openpipeline", "logs"}


class ProjectState:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._lock = threading.Lock()
        self._fingerprint: tuple[int, int] | None = None
        self._project: Project | None = None
        self._graph: ModelGraph | None = None
        self._rules: RuleRegistry | None = None
        self._lineage: ColumnLineage | None = None

    def project(self) -> Project:
        self._refresh()
        assert self._project is not None
        return self._project

    def graph(self) -> ModelGraph:
        self._refresh()
        assert self._graph is not None
        return self._graph

    def rules(self) -> RuleRegistry:
        """Business rules from ``openpipeline.yml`` and ``meta.rules`` links."""
        self._refresh()
        assert self._rules is not None
        return self._rules

    def lineage(self) -> ColumnLineage:
        """Column lineage for the whole project. Built on first use, rebuilt on reload."""
        self._refresh()
        with self._lock:
            if self._lineage is None:
                assert self._project is not None
                assert self._graph is not None
                self._lineage = ColumnLineage(self._project, self._graph)
            return self._lineage

    def _refresh(self) -> None:
        fp = self._compute_fingerprint()
        with self._lock:
            if fp == self._fingerprint and self._project is not None:
                return
            self._project = load_project(self.root)
            self._graph = ModelGraph(self._project)
            self._rules = load_rules(self.root, self._project)
            self._lineage = None
            self._fingerprint = fp

    def _compute_fingerprint(self) -> tuple[int, int]:
        """File count and newest modification time. Cheap enough per request."""
        count, newest = 0, 0
        for path in self.root.rglob("*"):
            if path.suffix not in _WATCHED or _SKIP_DIRS.intersection(path.parts):
                continue
            if path.parent.name == "target" and path.name != "manifest.json":
                continue
            count += 1
            newest = max(newest, path.stat().st_mtime_ns)
        return count, newest
