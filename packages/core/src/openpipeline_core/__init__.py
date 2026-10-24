"""OpenPipeline core: read a dbt project, build its graph, and explain it."""

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
from openpipeline_core.loader import ProjectLoadError, load_project
from openpipeline_core.models import Column, Node, NodeKind, Project
from openpipeline_core.preview import ChangePreview, FileDiff, ParseIssue, preview_changes
from openpipeline_core.rules import ModelRule, Rule, RuleLink, RuleRegistry, load_rules
from openpipeline_core.story import ModelStory, explain_model

__version__ = "0.1.0"

__all__ = [
    "ChangePreview",
    "Column",
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
    "Project",
    "ProjectDiff",
    "ProjectLoadError",
    "Rule",
    "RuleChange",
    "RuleImpact",
    "RuleLink",
    "RuleRegistry",
    "__version__",
    "diff_projects",
    "explain_model",
    "load_project",
    "load_rules",
    "preview_changes",
    "render_diff_markdown",
    "update_docs",
]
