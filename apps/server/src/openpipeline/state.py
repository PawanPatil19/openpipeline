"""Keeps the loaded project in memory and reloads it when files change."""

from __future__ import annotations

import threading
from pathlib import Path

from openpipeline_core import (
    ColumnLineage,
    Glossary,
    Labeler,
    ModelGraph,
    Project,
    RuleRegistry,
    load_glossary,
    load_project,
    load_rules,
)

_WATCHED = {".sql", ".yml", ".yaml", ".csv", ".json"}
_SKIP_DIRS = {".git", "node_modules", "dbt_packages", ".openpipeline", "logs"}


class ProjectState:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._lock = threading.Lock()
        # Building lineage can take tens of seconds on a large project. It has its
        # own lock so other requests are not held up while it runs.
        self._lineage_lock = threading.Lock()
        self._fingerprint: tuple[int, int] | None = None
        self._project: Project | None = None
        self._graph: ModelGraph | None = None
        self._rules: RuleRegistry | None = None
        self._glossary: Glossary | None = None
        self._labeler: Labeler | None = None
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

    def glossary(self) -> Glossary:
        """Glossary terms from ``openpipeline.yml`` and ``meta.label`` entries."""
        self._refresh()
        assert self._glossary is not None
        return self._glossary

    def labeler(self) -> Labeler:
        """Turns names into business labels. Built once per reload, since it indexes everything."""
        self._refresh()
        with self._lock:
            if self._labeler is None:
                assert self._project is not None
                assert self._glossary is not None
                self._labeler = Labeler(self._project, self._glossary)
            return self._labeler

    def lineage(self) -> ColumnLineage:
        """Column lineage for the whole project. Built on first use, rebuilt on reload."""
        self._refresh()
        with self._lineage_lock:
            with self._lock:
                if self._lineage is not None:
                    return self._lineage
                assert self._project is not None
                assert self._graph is not None
                project, graph = self._project, self._graph
            built = ColumnLineage(project, graph)
            with self._lock:
                if self._project is project:
                    self._lineage = built
            return built

    def cached_lineage(self) -> ColumnLineage | None:
        """Column lineage if it is already built for the current project, else ``None``.

        For callers that can do without it, such as stories, so they never wait
        for a full build.
        """
        self._refresh()
        with self._lock:
            return self._lineage

    def _refresh(self) -> None:
        fp = self._compute_fingerprint()
        with self._lock:
            if fp == self._fingerprint and self._project is not None:
                return
            self._project = load_project(self.root)
            self._graph = ModelGraph(self._project)
            self._rules = load_rules(self.root, self._project)
            self._glossary = load_glossary(self.root, self._project)
            self._labeler = None
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
