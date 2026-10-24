"""Business rules: named, owned, and linked to the models that implement them.

Rules are written in ``openpipeline.yml`` at the dbt project root and can also
be linked from dbt's own YAML with ``meta: {rules: [rule_id]}`` on a model or a
column. Both sources are merged. Problems never raise; they are collected as
warnings so one typo cannot hide the whole project.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from openpipeline_core.models import Project

RULES_FILE = "openpipeline.yml"

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class RuleLink(BaseModel):
    """A rule applies to a model, and optionally only to some of its columns."""

    model: str
    columns: list[str] = Field(default_factory=list)
    """Empty means the rule applies to the model as a whole."""


class Rule(BaseModel):
    id: str
    name: str
    description: str = ""
    owner: str | None = None
    tags: list[str] = Field(default_factory=list)
    applies_to: list[RuleLink] = Field(default_factory=list)


class ModelRule(BaseModel):
    """A rule as it applies to one model, with the columns it is scoped to."""

    rule: Rule
    columns: list[str] = Field(default_factory=list)


class RuleRegistry(BaseModel):
    rules: list[Rule] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def get(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    def applied_to(self, model: str) -> list[ModelRule]:
        """Rules linked to ``model``, with the columns each one is scoped to."""
        out: list[ModelRule] = []
        for rule in self.rules:
            for link in rule.applies_to:
                if link.model == model:
                    out.append(ModelRule(rule=rule, columns=list(link.columns)))
                    break
        return out

    def rules_for(self, model: str) -> list[Rule]:
        """Every rule linked to ``model``, whether or not it is column-scoped."""
        return [m.rule for m in self.applied_to(model)]

    def rules_for_column(self, model: str, column: str) -> list[Rule]:
        """Rules explicitly scoped to ``column`` of ``model``."""
        return [m.rule for m in self.applied_to(model) if column in m.columns]


def load_rules(project_root: str | Path, project: Project) -> RuleRegistry:
    """Read ``openpipeline.yml`` and the ``meta.rules`` links in ``project``."""
    registry = RuleRegistry()
    path = Path(project_root) / RULES_FILE
    if path.is_file():
        _read_rules_file(path, project, registry)
    _merge_meta_links(project, registry)
    return registry


def _read_rules_file(path: Path, project: Project, registry: RuleRegistry) -> None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        registry.warnings.append(f"{RULES_FILE}: could not be read ({exc})")
        return
    if data is None:
        return
    if not isinstance(data, dict):
        registry.warnings.append(f"{RULES_FILE}: expected a mapping with a 'rules' key")
        return
    entries = data.get("rules") or []
    if not isinstance(entries, list):
        registry.warnings.append(f"{RULES_FILE}: 'rules' must be a list")
        return
    seen: set[str] = set()
    for index, entry in enumerate(entries, 1):
        rule = _parse_rule(entry, index, project, registry)
        if rule is None:
            continue
        if rule.id in seen:
            registry.warnings.append(
                f"{RULES_FILE}: rule id '{rule.id}' is used more than once; the first one is kept"
            )
            continue
        seen.add(rule.id)
        registry.rules.append(rule)


def _parse_rule(entry: Any, index: int, project: Project, registry: RuleRegistry) -> Rule | None:
    if not isinstance(entry, dict):
        registry.warnings.append(f"{RULES_FILE}: rule #{index} is not a mapping")
        return None
    rule_id = str(entry.get("id") or "").strip()
    if not rule_id:
        registry.warnings.append(f"{RULES_FILE}: rule #{index} has no id")
        return None
    if not _SLUG.match(rule_id):
        registry.warnings.append(
            f"{RULES_FILE}: rule id '{rule_id}' should use lowercase letters, numbers, "
            "dashes, and underscores"
        )
    owner = entry.get("owner")
    links: list[RuleLink] = []
    raw_links = entry.get("applies_to") or []
    if not isinstance(raw_links, list):
        registry.warnings.append(f"{RULES_FILE}: rule '{rule_id}': 'applies_to' must be a list")
        raw_links = []
    for raw in raw_links:
        link = _parse_link(raw, rule_id, project, registry)
        if link is not None:
            _add_link(links, link)
    return Rule(
        id=rule_id,
        name=str(entry.get("name") or rule_id),
        description=str(entry.get("description") or "").strip(),
        owner=str(owner) if owner else None,
        tags=_string_list(entry.get("tags")),
        applies_to=links,
    )


def _parse_link(
    raw: Any, rule_id: str, project: Project, registry: RuleRegistry
) -> RuleLink | None:
    if isinstance(raw, str):
        raw = {"model": raw}
    if not isinstance(raw, dict) or not raw.get("model"):
        registry.warnings.append(
            f"{RULES_FILE}: rule '{rule_id}' has an applies_to entry without a model"
        )
        return None
    model = str(raw["model"])
    if project.get(model) is None:
        registry.warnings.append(
            f"{RULES_FILE}: rule '{rule_id}' applies to unknown model '{model}'"
        )
        return None
    return RuleLink(model=model, columns=_string_list(raw.get("columns")))


def _merge_meta_links(project: Project, registry: RuleRegistry) -> None:
    by_id = {r.id: r for r in registry.rules}
    for node in sorted(project.nodes.values(), key=lambda n: n.unique_id):
        sources: list[tuple[str | None, Any]] = [(None, node.meta.get("rules"))]
        sources += [(c.name, c.meta.get("rules")) for c in node.columns]
        for column, raw in sources:
            for rule_id in _string_list(raw):
                rule = by_id.get(rule_id)
                if rule is None:
                    where = f"{node.name}.{column}" if column else node.name
                    registry.warnings.append(f"{where}: meta.rules names unknown rule '{rule_id}'")
                    continue
                _add_link(
                    rule.applies_to,
                    RuleLink(model=node.name, columns=[column] if column else []),
                )


def _add_link(links: list[RuleLink], new: RuleLink) -> None:
    """Add a link, merging with an existing link to the same model."""
    for link in links:
        if link.model == new.model:
            link.columns.extend(c for c in new.columns if c not in link.columns)
            return
    links.append(new)


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(x) for x in raw if x is not None]
    return []
