"""Compare two versions of a project and describe the change in plain words.

This powers PR summaries: what changed, what it affects downstream, and who
owns the affected models.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from openpipeline_core.graph import ModelGraph
from openpipeline_core.models import Node, NodeKind, Project
from openpipeline_core.story import explain_model

ChangeKind = Literal["added", "removed", "modified"]


class ModelChange(BaseModel):
    name: str
    unique_id: str
    change: ChangeKind
    details: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)


class ProjectDiff(BaseModel):
    changes: list[ModelChange] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.changes


def diff_projects(base: Project, head: Project) -> ProjectDiff:
    base_models = {n.name: n for n in base.models()}
    head_models = {n.name: n for n in head.models()}
    base_graph, head_graph = ModelGraph(base), ModelGraph(head)
    changes: list[ModelChange] = []

    for name in sorted(head_models.keys() - base_models.keys()):
        node = head_models[name]
        changes.append(
            ModelChange(
                name=name,
                unique_id=node.unique_id,
                change="added",
                details=[
                    f"New model reading from {', '.join(_dep_names(head, node)) or 'nothing'}"
                ],
                **_impact(head, head_graph, node),
            )
        )

    for name in sorted(base_models.keys() - head_models.keys()):
        node = base_models[name]
        changes.append(
            ModelChange(
                name=name,
                unique_id=node.unique_id,
                change="removed",
                details=["Model deleted"],
                **_impact(base, base_graph, node),
            )
        )

    for name in sorted(base_models.keys() & head_models.keys()):
        old, new = base_models[name], head_models[name]
        details = _modified_details(base, old, head, new)
        if details:
            changes.append(
                ModelChange(
                    name=name,
                    unique_id=new.unique_id,
                    change="modified",
                    details=details,
                    **_impact(head, head_graph, new),
                )
            )
    return ProjectDiff(changes=changes)


def _dep_names(project: Project, node: Node) -> list[str]:
    return [project.nodes[d].name for d in node.depends_on if d in project.nodes]


def _impact(project: Project, graph: ModelGraph, node: Node) -> dict[str, list[str]]:
    affected = [project.nodes[u] for u in graph.downstream(node.unique_id)]
    models = [n for n in affected if n.kind == NodeKind.MODEL]
    owners = sorted({o for n in [node, *models] if (o := n.owner)})
    return {"downstream": [n.name for n in models], "owners": owners}


def _modified_details(base: Project, old: Node, head: Project, new: Node) -> list[str]:
    details: list[str] = []
    if _normalise(old.raw_sql) != _normalise(new.raw_sql):
        old_cols = {c.name for c in explain_model(base, old.unique_id).columns}
        new_cols = {c.name for c in explain_model(head, new.unique_id).columns}
        if added := sorted(new_cols - old_cols):
            details.append(f"New columns: {', '.join(added)}")
        if removed := sorted(old_cols - new_cols):
            details.append(f"Removed columns: {', '.join(removed)}")
        old_deps, new_deps = set(_dep_names(base, old)), set(_dep_names(head, new))
        if added_deps := sorted(new_deps - old_deps):
            details.append(f"Now also reads from {', '.join(added_deps)}")
        if dropped := sorted(old_deps - new_deps):
            details.append(f"No longer reads from {', '.join(dropped)}")
        if not details:
            details.append("Logic changed")
    if old.materialized != new.materialized:
        details.append(
            f"Stored as {new.materialized or 'default'} (was {old.materialized or 'default'})"
        )
    if old.description != new.description:
        details.append("Description updated")
    return details


def _normalise(sql: str) -> str:
    return " ".join(sql.split()).lower()


_ICONS = {"added": "🆕", "removed": "🗑️", "modified": "✏️"}


def render_diff_markdown(diff: ProjectDiff) -> str:
    """A PR comment a non-engineer can read."""
    if diff.is_empty:
        return "### OpenPipeline summary\n\nNo dbt model changes in this pull request.\n"
    lines = ["### OpenPipeline summary", ""]
    counts = {k: sum(1 for c in diff.changes if c.change == k) for k in _ICONS}
    lines.append(
        ", ".join(f"{v} {k}" for k, v in counts.items() if v) + " model(s) in this pull request."
    )
    changed = {c.name for c in diff.changes}
    affected = sorted({d for c in diff.changes for d in c.downstream} - changed)
    if affected:
        lines.append(
            "Other models whose results may change: " + ", ".join(f"`{a}`" for a in affected) + "."
        )
    owners = sorted({o for c in diff.changes for o in c.owners})
    if owners:
        lines.append(f"Owners to loop in: {', '.join(owners)}.")
    lines.append("")
    for c in diff.changes:
        lines.append(f"#### {_ICONS[c.change]} `{c.name}` ({c.change})")
        lines.extend(f"- {d}" for d in c.details)
        if c.downstream:
            lines.append(f"- Affects: {', '.join(f'`{d}`' for d in c.downstream)}")
        lines.append("")
    return "\n".join(lines)
