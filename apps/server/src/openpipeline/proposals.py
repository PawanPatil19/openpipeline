"""Change proposals from AI agents, waiting for a person to review them.

An agent never edits the dbt project directly. It files a proposal, the web UI
shows it on the graph, and a person accepts or rejects it. Proposals are plain
JSON files in ``<project>/.openpipeline/proposals`` so they are easy to inspect,
commit, or delete by hand.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["pending", "accepted", "rejected"]


class FileChange(BaseModel):
    path: str
    """Path relative to the project root, e.g. ``models/marts/revenue.sql``."""
    content: str
    """Full new content of the file. An empty string deletes the file."""


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    rationale: str = ""
    author: str = "agent"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Status = "pending"
    changes: list[FileChange] = Field(default_factory=list)


_SAFE_ID = re.compile(r"^[a-f0-9]{12}$")


class ProposalStore:
    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.dir = self.root / ".openpipeline" / "proposals"

    def create(self, proposal: Proposal) -> Proposal:
        for change in proposal.changes:
            self._safe_path(change.path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._file(proposal.id).write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        return proposal

    def list(self, status: Status | None = None) -> list[Proposal]:
        if not self.dir.is_dir():
            return []
        items = [
            Proposal.model_validate(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(self.dir.glob("*.json"))
        ]
        items.sort(key=lambda p: p.created_at, reverse=True)
        return [p for p in items if status is None or p.status == status]

    def get(self, proposal_id: str) -> Proposal | None:
        if not _SAFE_ID.match(proposal_id):
            return None
        f = self._file(proposal_id)
        if not f.is_file():
            return None
        return Proposal.model_validate(json.loads(f.read_text(encoding="utf-8")))

    def set_status(self, proposal_id: str, status: Status) -> Proposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.status != "pending":
            raise ValueError(f"Proposal {proposal_id} is already {proposal.status}")
        if status == "accepted":
            self._apply(proposal)
        proposal.status = status
        self._file(proposal.id).write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        return proposal

    def _apply(self, proposal: Proposal) -> None:
        for change in proposal.changes:
            target = self._safe_path(change.path)
            if change.content == "":
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(change.content, encoding="utf-8")

    def _safe_path(self, rel: str) -> Path:
        """Refuse paths that escape the project or touch OpenPipeline's own folder."""
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError(f"Path {rel!r} is outside the project")
        if (
            target.is_relative_to(self.root / ".openpipeline")
            or ".git" in target.relative_to(self.root).parts
        ):
            raise ValueError(f"Path {rel!r} is not allowed")
        return target

    def _file(self, proposal_id: str) -> Path:
        return self.dir / f"{proposal_id}.json"
