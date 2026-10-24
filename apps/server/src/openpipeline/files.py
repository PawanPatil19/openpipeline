"""Safe file writes inside a dbt project.

Everything that writes project files (accepting a proposal, saving docs from
the UI) goes through here, so a path can never leave the project or touch
``.git`` or OpenPipeline's own folder.
"""

from __future__ import annotations

from pathlib import Path


def safe_path(root: str | Path, rel: str) -> Path:
    """Resolve ``rel`` inside ``root``, or raise ``ValueError`` if it is not allowed."""
    base = Path(root).resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base) or target == base:
        raise ValueError(f"Path {rel!r} is outside the project")
    if target.is_relative_to(base / ".openpipeline") or ".git" in target.relative_to(base).parts:
        raise ValueError(f"Path {rel!r} is not allowed")
    return target


def write_file(root: str | Path, rel: str, content: str) -> Path:
    """Write ``content`` to ``rel``. Empty content deletes the file."""
    target = safe_path(root, rel)
    if content == "":
        target.unlink(missing_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return target
