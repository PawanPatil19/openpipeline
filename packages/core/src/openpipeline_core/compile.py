"""Turn a model's SQL into runnable SQL, and work out what it needs to run.

These helpers are pure: they need no database. The preview engine in the
server package uses them to run a model on sample data.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from openpipeline_core import jinja
from openpipeline_core.graph import ModelGraph
from openpipeline_core.models import Node, NodeKind, Project


class UnsupportedJinja(ValueError):
    """The SQL uses Jinja that we cannot resolve without running dbt."""


def _default_source(source: str, table: str) -> str:
    return f"{source}.{table}"


def compile_sql(
    raw_sql: str,
    *,
    ref: Callable[[str], str] = lambda name: name,
    source: Callable[[str, str], str] = _default_source,
) -> str:
    """Replace ``ref()`` and ``source()`` with table names and drop ``config()``.

    Unlike ``to_plain_sql``, this refuses to guess. Any other Jinja (macros,
    ``if`` blocks, ``var()``) raises ``UnsupportedJinja`` so we never run SQL
    that is not what dbt would build.
    """
    sql = jinja._COMMENT_RE.sub("", raw_sql)
    sql = jinja.CONFIG_RE.sub("", sql)
    sql = jinja.REF_RE.sub(lambda m: ref(m.group(2) or m.group(1)), sql)
    sql = jinja.SOURCE_RE.sub(lambda m: source(m.group(1), m.group(2)), sql)
    leftover = re.search(r"\{\{.*?\}\}|\{%.*?%\}", sql, re.DOTALL)
    if leftover:
        snippet = " ".join(leftover.group(0).split())
        raise UnsupportedJinja(f"This SQL uses Jinja we cannot run: {snippet[:60]}")
    return sql.strip().rstrip(";").strip()


@dataclass
class PreviewPlan:
    """What it takes to run one model: the models to build, and the tables to load."""

    target: Node
    models: list[Node] = field(default_factory=list)
    """Upstream models then the target, each after everything it reads from."""
    sources: list[Node] = field(default_factory=list)
    seeds: list[Node] = field(default_factory=list)
    unsupported: list[Node] = field(default_factory=list)
    """Upstream nodes we cannot build, such as snapshots."""


def plan_preview(project: Project, graph: ModelGraph, name: str) -> PreviewPlan:
    """Plan a preview of model ``name``. Raises ``KeyError`` for an unknown model."""
    node = project.get(name)
    if node is None or node.kind != NodeKind.MODEL:
        raise KeyError(f"No model named {name!r}")
    wanted = {node.unique_id, *graph.upstream(node.unique_id)}
    plan = PreviewPlan(target=node)
    for uid in graph.topological_order():
        if uid not in wanted:
            continue
        n = project.nodes[uid]
        if n.kind == NodeKind.MODEL:
            plan.models.append(n)
        elif n.kind == NodeKind.SOURCE:
            plan.sources.append(n)
        elif n.kind == NodeKind.SEED:
            plan.seeds.append(n)
        else:
            plan.unsupported.append(n)
    return plan
