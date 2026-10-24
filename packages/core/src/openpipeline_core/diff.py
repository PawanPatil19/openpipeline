"""Compare two versions of a project and describe the change in plain words.

This powers PR summaries: what changed, what it affects downstream, and who
owns the affected models.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from openpipeline_core.graph import ModelGraph
from openpipeline_core.lineage import ColumnLineage
from openpipeline_core.models import Node, NodeKind, Project
from openpipeline_core.rules import Rule, RuleRegistry
from openpipeline_core.story import explain_model

ChangeKind = Literal["added", "removed", "modified"]
RuleImpactLevel = Literal["touched", "may_be_affected"]


class ModelChange(BaseModel):
    name: str
    unique_id: str
    change: ChangeKind
    details: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    removed_columns: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    """Ids of the business rules this model implements."""
    downstream_rules: list[str] = Field(default_factory=list)
    """Ids of rules implemented by downstream models, which may be affected."""
    column_usage: dict[str, list[str]] = Field(default_factory=dict)
    """For each removed or renamed column, the downstream columns that read it, as ``model.column``."""


class RuleImpact(BaseModel):
    """A business rule that a pull request touches, or may affect."""

    id: str
    name: str
    owner: str | None = None
    level: RuleImpactLevel
    models: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    """Column-scoped links, written ``model.column``."""
    reasons: list[str] = Field(default_factory=list)


class RuleChange(BaseModel):
    """A change to a rule definition in ``openpipeline.yml``."""

    id: str
    name: str
    owner: str | None = None
    change: ChangeKind
    details: list[str] = Field(default_factory=list)


class ProjectDiff(BaseModel):
    changes: list[ModelChange] = Field(default_factory=list)
    rule_impacts: list[RuleImpact] = Field(default_factory=list)
    rule_changes: list[RuleChange] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.changes and not self.rule_changes


def diff_projects(
    base: Project,
    head: Project,
    *,
    base_rules: RuleRegistry | None = None,
    head_rules: RuleRegistry | None = None,
    base_lineage: ColumnLineage | None = None,
) -> ProjectDiff:
    """Compare two projects. Pass the rule registries to include business rules.

    Pass ``base_lineage`` (the column lineage of ``base``) to list, for each column
    a model lost, the downstream columns that read it.
    """
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
        details, removed_columns = _modified_details(base, old, head, new)
        if details:
            changes.append(
                ModelChange(
                    name=name,
                    unique_id=new.unique_id,
                    change="modified",
                    details=details,
                    removed_columns=removed_columns,
                    column_usage=_column_usage(base, old, removed_columns, base_lineage),
                    **_impact(head, head_graph, new),
                )
            )
    result = ProjectDiff(changes=changes)
    if base_rules is not None or head_rules is not None:
        _add_rules(result, base_rules or RuleRegistry(), head_rules or RuleRegistry())
        if base_rules is not None and head_rules is not None:
            result.rule_changes = _diff_rule_files(base_rules, head_rules)
    return result


def _column_usage(
    base: Project, old: Node, removed_columns: list[str], lineage: ColumnLineage | None
) -> dict[str, list[str]]:
    """Downstream columns, in the old project, that read each removed column."""
    if lineage is None:
        return {}
    usage: dict[str, list[str]] = {}
    for column in removed_columns:
        readers = [
            f"{base.nodes[ref.node_id].name}.{ref.column}"
            for ref in lineage.downstream(old.unique_id, column)
            if ref.node_id in base.nodes and ref.node_id != old.unique_id
        ]
        if readers:
            usage[column] = readers
    return usage


def _dep_names(project: Project, node: Node) -> list[str]:
    return [project.nodes[d].name for d in node.depends_on if d in project.nodes]


def _impact(project: Project, graph: ModelGraph, node: Node) -> dict[str, list[str]]:
    affected = [project.nodes[u] for u in graph.downstream(node.unique_id)]
    models = [n for n in affected if n.kind == NodeKind.MODEL]
    owners = sorted({o for n in [node, *models] if (o := n.owner)})
    return {"downstream": [n.name for n in models], "owners": owners}


def _modified_details(
    base: Project, old: Node, head: Project, new: Node
) -> tuple[list[str], list[str]]:
    """Plain-English details of a modified model, and the columns it lost."""
    details: list[str] = []
    removed: list[str] = []
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
    return details, removed


def _add_rules(diff: ProjectDiff, base_rules: RuleRegistry, head_rules: RuleRegistry) -> None:
    """Fill in rule fields on each change and build the list of rule impacts."""
    touched: dict[str, _Acc] = {}
    maybe: dict[str, _Acc] = {}
    for c in diff.changes:
        registry = base_rules if c.change == "removed" else head_rules
        if c.change == "modified" and c.details == ["Description updated"]:
            # A wording change in the docs does not change what the model computes.
            continue
        for applied in registry.applied_to(c.name):
            acc = touched.setdefault(applied.rule.id, _Acc(applied.rule))
            acc.models.add(c.name)
            acc.columns.update(f"{c.name}.{col}" for col in applied.columns)
            acc.reasons.append(_reason(c, applied.columns))
            c.rules.append(applied.rule.id)
        for downstream in c.downstream:
            for applied in registry.applied_to(downstream):
                if applied.rule.id in c.rules or applied.rule.id in c.downstream_rules:
                    continue
                acc = maybe.setdefault(applied.rule.id, _Acc(applied.rule))
                acc.models.add(downstream)
                acc.columns.update(f"{downstream}.{col}" for col in applied.columns)
                acc.reasons.append(f"`{downstream}` reads from changed `{c.name}`")
                c.downstream_rules.append(applied.rule.id)
        owners = {o for rid in c.rules if (o := _owner(registry, rid))}
        c.owners = sorted({*c.owners, *owners})
    impacts = [acc.impact("touched") for acc in touched.values()]
    impacts += [acc.impact("may_be_affected") for rid, acc in maybe.items() if rid not in touched]
    diff.rule_impacts = sorted(impacts, key=lambda i: (i.level != "touched", i.name.lower()))


class _Acc:
    def __init__(self, rule: Rule) -> None:
        self.rule = rule
        self.models: set[str] = set()
        self.columns: set[str] = set()
        self.reasons: list[str] = []

    def impact(self, level: RuleImpactLevel) -> RuleImpact:
        return RuleImpact(
            id=self.rule.id,
            name=self.rule.name,
            owner=self.rule.owner,
            level=level,
            models=sorted(self.models),
            columns=sorted(self.columns),
            reasons=list(dict.fromkeys(self.reasons)),
        )


def _owner(registry: RuleRegistry, rule_id: str) -> str | None:
    rule = registry.get(rule_id)
    return rule.owner if rule else None


def _reason(change: ModelChange, scoped_columns: list[str]) -> str:
    name = change.name
    if change.change == "removed":
        return f"`{name}` was deleted"
    if change.change == "added":
        return f"`{name}` is new"
    lost = [c for c in change.removed_columns if c in scoped_columns]
    if lost:
        cols = ", ".join(f"`{c}`" for c in lost)
        return f"column {cols} was removed from `{name}`"
    return f"`{name}` was modified"


def _diff_rule_files(base: RuleRegistry, head: RuleRegistry) -> list[RuleChange]:
    old = {r.id: r for r in base.rules}
    new = {r.id: r for r in head.rules}
    out: list[RuleChange] = []
    for rid in sorted(new.keys() - old.keys()):
        rule = new[rid]
        out.append(_rule_change(rule, "added", [f"Applies to {_models_phrase(rule)}"]))
    for rid in sorted(old.keys() - new.keys()):
        out.append(_rule_change(old[rid], "removed", ["Rule removed"]))
    for rid in sorted(old.keys() & new.keys()):
        details = _rule_details(old[rid], new[rid])
        if details:
            out.append(_rule_change(new[rid], "modified", details))
    return sorted(out, key=lambda c: (c.name.lower(), c.id))


def _rule_change(rule: Rule, change: ChangeKind, details: list[str]) -> RuleChange:
    return RuleChange(id=rule.id, name=rule.name, owner=rule.owner, change=change, details=details)


def _models_phrase(rule: Rule) -> str:
    return ", ".join(f"`{link.model}`" for link in rule.applies_to) or "no models yet"


def _rule_details(old: Rule, new: Rule) -> list[str]:
    details: list[str] = []
    if old.name != new.name:
        details.append(f'Renamed from "{old.name}"')
    if " ".join(old.description.split()) != " ".join(new.description.split()):
        details.append("Description reworded")
    if old.owner != new.owner:
        details.append(f"Owner changed from {old.owner or 'nobody'} to {new.owner or 'nobody'}")
    old_links = {link.model: set(link.columns) for link in old.applies_to}
    new_links = {link.model: set(link.columns) for link in new.applies_to}
    for model in sorted(new_links.keys() - old_links.keys()):
        details.append(f"Now applies to `{model}`")
    for model in sorted(old_links.keys() - new_links.keys()):
        details.append(f"No longer applies to `{model}`")
    for model in sorted(old_links.keys() & new_links.keys()):
        if old_links[model] != new_links[model]:
            details.append(f"Applies to different columns of `{model}`")
    return details


def _normalise(sql: str) -> str:
    return " ".join(sql.split()).lower()


_MAX_READERS = 8
_ICONS = {"added": "🆕", "removed": "🗑️", "modified": "✏️"}


def render_diff_markdown(diff: ProjectDiff) -> str:
    """A PR comment a non-engineer can read."""
    if diff.is_empty:
        return "### OpenPipeline summary\n\nNo dbt model changes in this pull request.\n"
    lines = ["### OpenPipeline summary", ""]
    if diff.changes:
        counts = {k: sum(1 for c in diff.changes if c.change == k) for k in _ICONS}
        lines.append(
            ", ".join(f"{v} {k}" for k, v in counts.items() if v)
            + " model(s) in this pull request."
        )
    else:
        lines.append("No dbt model changes in this pull request, but business rules changed.")
    changed = {c.name for c in diff.changes}
    affected = sorted({d for c in diff.changes for d in c.downstream} - changed)
    if affected:
        lines.append(
            "Other models whose results may change: " + ", ".join(f"`{a}`" for a in affected) + "."
        )
    owners = sorted(
        {o for c in diff.changes for o in c.owners}
        | {o for r in diff.rule_changes if (o := r.owner)}
    )
    if owners:
        lines.append(f"Owners to loop in: {', '.join(owners)}.")
    lines.append("")
    lines.extend(_rules_sections(diff))
    names = {i.id: i.name for i in diff.rule_impacts}
    for c in diff.changes:
        lines.append(f"#### {_ICONS[c.change]} `{c.name}` ({c.change})")
        lines.extend(f"- {d}" for d in c.details)
        for column, readers in c.column_usage.items():
            shown = ", ".join(f"`{r}`" for r in readers[:_MAX_READERS])
            extra = len(readers) - _MAX_READERS
            more = f" and {extra} more" if extra > 0 else ""
            lines.append(f"- Removed column `{column}` is used by {shown}{more}")
        if c.downstream:
            lines.append(f"- Affects: {', '.join(f'`{d}`' for d in c.downstream)}")
        if c.rules:
            lines.append(f"- Business rules: {', '.join(_rule_names(c.rules, names))}")
        if c.downstream_rules:
            lines.append(
                "- Business rules that may be affected: "
                + ", ".join(_rule_names(c.downstream_rules, names))
            )
        lines.append("")
    return "\n".join(lines)


def _rule_names(ids: list[str], names: dict[str, str]) -> list[str]:
    return [f"**{names.get(i, i)}**" for i in ids]


def _rules_sections(diff: ProjectDiff) -> list[str]:
    lines: list[str] = []
    touched = [i for i in diff.rule_impacts if i.level == "touched"]
    maybe = [i for i in diff.rule_impacts if i.level == "may_be_affected"]
    for title, group in (
        ("Business rules touched", touched),
        ("Business rules that may be affected", maybe),
    ):
        if not group:
            continue
        lines += [f"#### {title}", ""]
        for i in group:
            lines.append(f"- **{i.name}**{_owner_note(i.owner)}")
            lines.append(f"  - Why: {'; '.join(i.reasons)}")
            lines.append(f"  - Where: {_where(i)}")
        lines.append("")
    if diff.rule_changes:
        lines += ["#### Changes to `openpipeline.yml`", ""]
        words = {"added": "Rule added", "removed": "Rule removed", "modified": "Rule changed"}
        for r in diff.rule_changes:
            lines.append(f"- {words[r.change]}: **{r.name}** (`{r.id}`){_owner_note(r.owner)}")
            if r.change != "removed":
                lines.extend(f"  - {d}" for d in r.details)
        lines.append("")
    return lines


def _owner_note(owner: str | None) -> str:
    return f" (owner: {owner})" if owner else ""


def _where(impact: RuleImpact) -> str:
    scoped: dict[str, list[str]] = {}
    for col in impact.columns:
        model, _, column = col.partition(".")
        scoped.setdefault(model, []).append(column)
    parts = []
    for model in impact.models:
        cols = scoped.get(model)
        parts.append(f"`{model}`" + (f" ({', '.join(cols)})" if cols else ""))
    return ", ".join(parts)
