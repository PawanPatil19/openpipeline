"""Show what a set of file changes would do to a project, without touching it.

This powers review: an agent proposes new file contents, and a person (or the
agent, as a self-check) sees the effect on the graph before anything is written.

The "after" project is built by copying the project folder to a temporary
directory, applying the changes there, and loading both versions straight from
their files. Copying is simple and exact (the loader sees precisely what the
dbt files would look like after accepting), at the cost of time and disk that
grow with project size. Heavy folders such as the version control folder and
``target`` are skipped, so the example project takes a few milliseconds. Both
versions are read from files, never from ``target/manifest.json``, so they are
comparable.
"""

from __future__ import annotations

import difflib
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from openpipeline_core.diff import ProjectDiff, diff_projects
from openpipeline_core.graph import ModelGraph
from openpipeline_core.loader import load_project
from openpipeline_core.models import NodeKind, Project
from openpipeline_core.rules import load_rules
from openpipeline_core.story import explain_model

FileChangeKind = Literal["added", "modified", "deleted"]
NodeStatus = Literal["added", "modified", "removed", "affected", "unchanged"]

SKIP_DIRS = (
    ".git",
    "target",
    "dbt_packages",
    "logs",
    "node_modules",
    ".openpipeline",
    ".venv",
)


class FileDiff(BaseModel):
    path: str
    change: FileChangeKind
    diff: str
    """Unified diff text. Empty when the content did not change."""
    before: str
    after: str


class ParseIssue(BaseModel):
    model: str
    message: str


class ChangePreview(BaseModel):
    diff: ProjectDiff
    files: list[FileDiff] = Field(default_factory=list)
    node_statuses: dict[str, NodeStatus] = Field(default_factory=dict)
    """Status of every node, by unique id. Removed nodes are included."""
    graph: dict[str, Any] = Field(default_factory=dict)
    """Same shape as ``ModelGraph.to_dict()``, plus ``status`` on each node.
    Removed nodes are kept so a UI can draw them as ghosts."""
    new_warnings: list[str] = Field(default_factory=list)
    parse_errors: list[ParseIssue] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    """Plain-English lines describing the effect of the change."""

    def names_with_status(self, status: NodeStatus) -> list[str]:
        """Names of models (not sources or seeds) with the given status."""
        return sorted(
            n["name"]
            for n in self.graph.get("nodes", [])
            if n["status"] == status and n["kind"] == "model"
        )


def preview_changes(project_root: str | Path, changes: Iterable[tuple[str, str]]) -> ChangePreview:
    """Work out the effect of ``(path, content)`` changes. Empty content deletes the file."""
    root = Path(project_root).resolve()
    pairs = list(changes)
    before = load_project(root, prefer_manifest=False)

    with tempfile.TemporaryDirectory(prefix="openpipeline-preview-") as tmp:
        copy = Path(tmp) / "project"
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        files = [_apply(root, copy, path, content) for path, content in pairs]
        after = load_project(copy, prefer_manifest=False)
        after_rules = load_rules(copy, after)

    diff = diff_projects(before, after, base_rules=load_rules(root, before), head_rules=after_rules)
    statuses = _node_statuses(before, after)
    before_set = set(before.warnings)
    new_warnings = [w for w in after.warnings if w not in before_set]
    parse_errors = _parse_errors(after, statuses)
    graph = _merged_graph(before, after, statuses)
    return ChangePreview(
        diff=diff,
        files=files,
        node_statuses=statuses,
        graph=graph,
        new_warnings=new_warnings,
        parse_errors=parse_errors,
        summary=_summary(graph, new_warnings, parse_errors, diff),
    )


def _apply(root: Path, copy: Path, rel: str, content: str) -> FileDiff:
    target = (copy / rel).resolve()
    if not target.is_relative_to(copy.resolve()) or target == copy.resolve():
        raise ValueError(f"Path {rel!r} is outside the project")
    original = root / rel
    existed = original.is_file()
    before = original.read_text(encoding="utf-8") if existed else ""
    if content == "":
        target.unlink(missing_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    kind: FileChangeKind = "deleted" if content == "" else ("modified" if existed else "added")
    text = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"a/{rel}" if existed else "/dev/null",
            tofile="/dev/null" if content == "" else f"b/{rel}",
        )
    )
    return FileDiff(path=rel, change=kind, diff=text, before=before, after=content)


def _node_statuses(before: Project, after: Project) -> dict[str, NodeStatus]:
    statuses: dict[str, NodeStatus] = {}
    for uid, node in after.nodes.items():
        if uid not in before.nodes:
            statuses[uid] = "added"
        elif before.nodes[uid] != node:
            statuses[uid] = "modified"
        else:
            statuses[uid] = "unchanged"
    for uid in before.nodes.keys() - after.nodes.keys():
        statuses[uid] = "removed"

    after_graph, before_graph = ModelGraph(after), ModelGraph(before)
    reached: set[str] = set()
    for uid, status in statuses.items():
        if status in ("added", "modified"):
            reached.update(after_graph.downstream(uid))
        elif status == "removed":
            reached.update(c for c in before_graph.downstream(uid) if c in after.nodes)
    for uid in reached:
        if statuses.get(uid) == "unchanged":
            statuses[uid] = "affected"
    return statuses


def _parse_errors(after: Project, statuses: dict[str, NodeStatus]) -> list[ParseIssue]:
    issues: list[ParseIssue] = []
    for uid in sorted(statuses):
        node = after.nodes.get(uid)
        if (
            node is None
            or node.kind != NodeKind.MODEL
            or statuses[uid] not in ("added", "modified")
        ):
            continue
        error = explain_model(after, uid).parse_error
        if error:
            issues.append(ParseIssue(model=node.name, message=error))
    return issues


def _merged_graph(
    before: Project, after: Project, statuses: dict[str, NodeStatus]
) -> dict[str, Any]:
    graph = ModelGraph(after).to_dict()
    old = ModelGraph(before).to_dict()
    removed = {u for u, s in statuses.items() if s == "removed"}
    graph["nodes"] = sorted(
        [*graph["nodes"], *(n for n in old["nodes"] if n["id"] in removed)],
        key=lambda n: n["id"],
    )
    seen = {(e["source"], e["target"]) for e in graph["edges"]}
    for e in old["edges"]:
        if (e["source"] in removed or e["target"] in removed) and (
            (e["source"], e["target"]) not in seen
        ):
            graph["edges"].append(e)
    for n in graph["nodes"]:
        n["status"] = statuses[n["id"]]
    return graph


def _summary(
    graph: dict[str, Any],
    new_warnings: list[str],
    parse_errors: list[ParseIssue],
    diff: ProjectDiff,
) -> list[str]:
    def pick(status: str) -> list[str]:
        return sorted(
            n["name"] for n in graph["nodes"] if n["status"] == status and n["kind"] == "model"
        )

    lines: list[str] = []
    for status, label in (("added", "Adds"), ("modified", "Changes"), ("removed", "Removes")):
        items = pick(status)
        if items:
            noun = "model" if len(items) == 1 else "models"
            lines.append(f"{label} {len(items)} {noun}: {', '.join(items)}.")
    affected = pick("affected")
    if affected:
        lines.append(f"Results may change downstream in: {', '.join(affected)}.")
    touched = [r for r in diff.rule_impacts if r.level == "touched"]
    if touched:
        lines.append(
            "Touches business rules: "
            + ", ".join(f"{r.name} (owner: {r.owner})" if r.owner else r.name for r in touched)
            + "."
        )
    if not lines:
        lines.append("No models are added, changed, or removed.")
    lines.extend(f"New warning: {w}" for w in new_warnings)
    lines.extend(f"Could not read the SQL of {p.model}: {p.message}" for p in parse_errors)
    return lines
