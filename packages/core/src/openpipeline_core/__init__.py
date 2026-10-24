"""OpenPipeline core: read a dbt project, build its graph, and explain it."""

from openpipeline_core.diff import ModelChange, ProjectDiff, diff_projects, render_diff_markdown
from openpipeline_core.docs import DocsUpdate, FileEdit, update_docs
from openpipeline_core.graph import ModelGraph
from openpipeline_core.loader import ProjectLoadError, load_project
from openpipeline_core.models import Column, Node, NodeKind, Project
from openpipeline_core.story import ModelStory, explain_model

__version__ = "0.1.0"

__all__ = [
    "Column",
    "DocsUpdate",
    "FileEdit",
    "ModelChange",
    "ModelGraph",
    "ModelStory",
    "Node",
    "NodeKind",
    "Project",
    "ProjectDiff",
    "ProjectLoadError",
    "__version__",
    "diff_projects",
    "explain_model",
    "load_project",
    "render_diff_markdown",
    "update_docs",
]
