"""Find models, sources, seeds, and columns by name or description.

Scoring is simple and deterministic so results are easy to explain and test:
an exact name match beats a prefix match, which beats a substring match, which
beats a match in the description. Nodes rank above columns with the same kind
of match. Every word in the query has to match somewhere.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from openpipeline_core.lineage import ColumnLineage
from openpipeline_core.models import Node, Project

_NODE_SCORES = {"exact": 100, "prefix": 80, "substring": 60, "description": 30}
_COLUMN_SCORES = {"exact": 90, "prefix": 70, "substring": 50, "description": 25}
_KIND_ORDER = {"model": 0, "source": 1, "seed": 2, "snapshot": 3, "column": 4}
_SNIPPET_LENGTH = 120


class SearchHit(BaseModel):
    kind: Literal["model", "source", "seed", "snapshot", "column"]
    """What matched. ``"column"`` for a column hit, otherwise the node's kind."""
    node_id: str
    name: str
    """The node's name. For a column hit this is the node the column belongs to."""
    column: str | None = None
    snippet: str = ""
    score: int = 0


def search_project(
    project: Project, lineage: ColumnLineage | None, query: str, limit: int = 20
) -> list[SearchHit]:
    """Rank nodes and columns against ``query``. Best match first."""
    words = _words(query)
    if not words or limit <= 0:
        return []
    hits: list[SearchHit] = []
    for node in project.nodes.values():
        node_hit = _score(words, node.name, node.description, _NODE_SCORES)
        if node_hit is not None:
            score, snippet = node_hit
            hits.append(
                SearchHit(
                    kind=node.kind.value,
                    node_id=node.unique_id,
                    name=node.name,
                    snippet=snippet or _short(node.description),
                    score=score,
                )
            )
        hits.extend(_column_hits(node, lineage, words))
    hits.sort(key=lambda h: (-h.score, _KIND_ORDER[h.kind], h.name.lower(), h.column or ""))
    return hits[:limit]


def _column_hits(node: Node, lineage: ColumnLineage | None, words: list[str]) -> list[SearchHit]:
    described = {c.name.lower(): c.description for c in node.columns}
    names = lineage.columns(node.unique_id) if lineage else [c.name for c in node.columns]
    out: list[SearchHit] = []
    for column in names:
        description = described.get(column.lower(), "")
        found = _score(words, column, description, _COLUMN_SCORES)
        if found is None:
            continue
        score, snippet = found
        out.append(
            SearchHit(
                kind="column",
                node_id=node.unique_id,
                name=node.name,
                column=column,
                snippet=snippet or _short(description) or f"Column of {node.name}",
                score=score,
            )
        )
    return out


def _words(text: str) -> list[str]:
    return _normalise(text).split()


def _normalise(text: str) -> str:
    """Lowercase, with underscores, dots, and dashes treated as spaces."""
    return " ".join(re.split(r"[^0-9a-z]+", text.lower())).strip()


def _score(
    words: list[str], name: str, description: str, table: dict[str, int]
) -> tuple[int, str] | None:
    """The score for the weakest word, or ``None`` if any word matches nothing."""
    norm_name = _normalise(name)
    norm_desc = _normalise(description)
    whole = " ".join(words)
    lowest: int | None = None
    snippet = ""
    for word in words:
        if norm_name == whole:
            kind = "exact"
        elif norm_name.startswith(word):
            kind = "prefix"
        elif word in norm_name:
            kind = "substring"
        elif word in norm_desc:
            kind = "description"
            snippet = _around(description, word)
        else:
            return None
        score = table[kind]
        lowest = score if lowest is None else min(lowest, score)
    assert lowest is not None
    return lowest, snippet if lowest == table["description"] else ""


def _around(text: str, word: str) -> str:
    """A short piece of ``text`` around the first place ``word`` appears."""
    pos = text.lower().find(word)
    if pos < 0:
        return _short(text)
    start = max(0, pos - 40)
    piece = text[start : start + _SNIPPET_LENGTH].strip()
    return ("…" if start > 0 else "") + piece + ("…" if start + _SNIPPET_LENGTH < len(text) else "")


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _SNIPPET_LENGTH else text[: _SNIPPET_LENGTH - 1].rstrip() + "…"
