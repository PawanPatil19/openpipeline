"""OpenPipeline core: read a dbt project, build its graph, and explain it."""

from openpipeline_core.compile import PreviewPlan, UnsupportedJinja, compile_sql, plan_preview
from openpipeline_core.diff import (
    ModelChange,
    ProjectDiff,
    RuleChange,
    RuleImpact,
    diff_projects,
    render_diff_markdown,
)
from openpipeline_core.docs import DocsUpdate, FileEdit, update_docs
from openpipeline_core.graph import ModelGraph
from openpipeline_core.lineage import ColumnLineage, ColumnRef
from openpipeline_core.loader import ProjectLoadError, load_project
from openpipeline_core.models import Column, Node, NodeKind, Project
from openpipeline_core.preview import ChangePreview, FileDiff, ParseIssue, preview_changes
from openpipeline_core.rules import ModelRule, Rule, RuleLink, RuleRegistry, load_rules
from openpipeline_core.search import SearchHit, search_project
from openpipeline_core.sql_source import ReadableSQL, readable_sql
from openpipeline_core.story import ColumnStory, ModelStory, explain_model

__version__ = "1.0.0"

__all__ = [
    "ChangePreview",
    "Column",
    "ColumnLineage",
    "ColumnRef",
    "ColumnStory",
    "DocsUpdate",
    "FileDiff",
    "FileEdit",
    "ModelChange",
    "ModelGraph",
    "ModelRule",
    "ModelStory",
    "Node",
    "NodeKind",
    "ParseIssue",
    "PreviewPlan",
    "Project",
    "ProjectDiff",
    "ProjectLoadError",
    "ReadableSQL",
    "Rule",
    "RuleChange",
    "RuleImpact",
    "RuleLink",
    "RuleRegistry",
    "SearchHit",
    "UnsupportedJinja",
    "__version__",
    "compile_sql",
    "diff_projects",
    "explain_model",
    "load_project",
    "load_rules",
    "plan_preview",
    "preview_changes",
    "readable_sql",
    "render_diff_markdown",
    "search_project",
    "update_docs",
]
