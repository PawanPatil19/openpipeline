"""Change proposals from AI agents, waiting for a person to review them.

An agent never edits the dbt project directly. It files a proposal, the web UI
shows it on the graph, and a person accepts or rejects it. Proposals are plain
JSON files in ``<project>/.openpipeline/proposals`` so they are easy to inspect,
commit, or delete by hand.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from openpipeline.files import safe_path, write_file

Status = Literal["pending", "accepted", "rejected", "superseded"]


def fingerprint(path: Path) -> str | None:
    """SHA-256 of a file's content, or ``None`` if the file does not exist."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StaleProposalError(Exception):
    """Files changed on disk after the proposal was made."""

    def __init__(self, files: Sequence[str]) -> None:
        super().__init__("Files changed since this proposal was made: " + ", ".join(files))
        self.files = list(files)


class Comment(BaseModel):
    author: str
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
    base: dict[str, str | None] | None = None
    """Fingerprint of each file when the proposal was made (``None`` for a file that did
    not exist). Missing in proposals saved by older versions, which skips the check."""
    comments: list[Comment] = Field(default_factory=list)
    revises: str | None = None
    """Id of the earlier proposal this one replaces."""
    superseded_by: str | None = None


_SAFE_ID = re.compile(r"^[a-f0-9]{12}$")


class ProposalStore:
    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.dir = self.root / ".openpipeline" / "proposals"

    def create(self, proposal: Proposal) -> Proposal:
        self.check_paths([c.path for c in proposal.changes])
        if proposal.base is None:
            proposal.base = {c.path: fingerprint(self._safe_path(c.path)) for c in proposal.changes}
        old: Proposal | None = None
        if proposal.revises is not None:
            old = self.get(proposal.revises)
            if old is None:
                raise ValueError(f"No proposal with id {proposal.revises!r} to revise")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._save(proposal)
        if old is not None and old.status == "pending":
            old.status = "superseded"
            old.superseded_by = proposal.id
            self._save(old)
        return proposal

    def check_paths(self, paths: Sequence[str]) -> None:
        for path in paths:
            self._safe_path(path)

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

    def set_status(
        self,
        proposal_id: str,
        status: Literal["accepted", "rejected"],
        *,
        reason: str | None = None,
        author: str = "reviewer",
        force: bool = False,
    ) -> Proposal:
        """Accept or reject a pending proposal.

        Accepting raises ``StaleProposalError`` if a file changed since the proposal was
        made, unless ``force`` is true. A rejection reason is saved as a comment.
        """
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.status != "pending":
            raise ValueError(f"Proposal {proposal_id} is already {proposal.status}")
        if status == "accepted":
            if not force and (changed := self.changed_files(proposal)):
                raise StaleProposalError(changed)
            self._apply(proposal)
        elif reason and reason.strip():
            proposal.comments.append(Comment(author=author, text=reason.strip()))
        proposal.status = status
        self._save(proposal)
        return proposal

    def add_comment(self, proposal_id: str, author: str, text: str) -> Proposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        proposal.comments.append(Comment(author=author, text=text))
        self._save(proposal)
        return proposal

    def changed_files(self, proposal: Proposal) -> Sequence[str]:
        """Paths whose content on disk no longer matches what the proposal started from."""
        if proposal.base is None:
            return []
        return [
            c.path
            for c in proposal.changes
            if c.path in proposal.base
            and fingerprint(self._safe_path(c.path)) != proposal.base[c.path]
        ]

    def _save(self, proposal: Proposal) -> None:
        self._file(proposal.id).write_text(proposal.model_dump_json(indent=2), encoding="utf-8")

    def _apply(self, proposal: Proposal) -> None:
        for change in proposal.changes:
            safe_path(self.root, change.path)  # Check every path before writing any.
        for change in proposal.changes:
            write_file(self.root, change.path, change.content)

    def _safe_path(self, rel: str) -> Path:
        return safe_path(self.root, rel)

    def _file(self, proposal_id: str) -> Path:
        return self.dir / f"{proposal_id}.json"
