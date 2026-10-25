"""The same story as ``story.py``, told in the business's own words.

``business_story`` takes a finished :class:`~openpipeline_core.story.ModelStory` and
rewrites it with the labels from the glossary: ``order_cost: the total of supply_cost per
order_id`` becomes "Order cost: the total of Supply cost per Order". The technical story
travels along in ``technical`` so a UI can tuck it behind "Show details".

Labels are put in by scanning the story text for identifier tokens, not by replacing
arbitrary substrings. A token is an identifier when it is ``snake_case`` or is a known
model, source or column name. Quoted string literals such as ``'completed'`` are skipped,
and so are function calls and macro names, whose spelling matters.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from openpipeline_core.describe import join_words
from openpipeline_core.glossary import (
    PREFIXES,
    Glossary,
    GlossaryTerm,
    humanize,
    prefix_of,
)
from openpipeline_core.models import Node, NodeKind, Project
from openpipeline_core.story import ModelStory

_MAX_CALCULATED_IN_SUMMARY = 4
_PASSED = "passed through"

# A quoted literal (an apostrophe inside a word, as in "today's", does not open one), or a
# name, optionally dotted like ``schema.table``.
_TOKEN = re.compile(
    r"(?<!\w)'(?:[^']|'')*(?:'|$)|(?<!\w)[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STEP = re.compile(r"^Builds a step called (.+?)(?: \(an ephemeral model\))?: (.*)$", re.S)

# Words the story engine writes itself. A bare word like this is never taken for a column
# name, so a column called ``total`` cannot turn "the total of" into "the Total of".
_VOCABULARY = frozenset(
    [
        "a",
        "about",
        "after",
        "all",
        "always",
        "an",
        "and",
        "any",
        "as",
        "at",
        "average",
        "before",
        "between",
        "by",
        "calculated",
        "case",
        "column",
        "columns",
        "combines",
        "current",
        "cut",
        "date",
        "day",
        "days",
        "different",
        "do",
        "does",
        "each",
        "earliest",
        "every",
        "everything",
        "exists",
        "false",
        "first",
        "from",
        "groups",
        "has",
        "hour",
        "hours",
        "in",
        "is",
        "it",
        "joined",
        "keeping",
        "last",
        "latest",
        "least",
        "length",
        "lower",
        "macro",
        "matches",
        "matching",
        "minus",
        "missing",
        "modulo",
        "more",
        "most",
        "nothing",
        "not",
        "number",
        "of",
        "on",
        "one",
        "only",
        "or",
        "ordered",
        "other",
        "otherwise",
        "per",
        "plus",
        "position",
        "present",
        "previous",
        "project",
        "rank",
        "rows",
        "remainder",
        "replaced",
        "result",
        "rolls",
        "rounded",
        "same",
        "smallest",
        "so",
        "step",
        "subquery",
        "taken",
        "that",
        "the",
        "then",
        "them",
        "there",
        "these",
        "this",
        "time",
        "to",
        "today",
        "total",
        "true",
        "two",
        "upper",
        "value",
        "variable",
        "when",
        "where",
        "with",
        "within",
        "without",
        "year",
        "years",
    ]
)


class Reference(BaseModel):
    name: str
    """The technical name, e.g. ``stg_orders``."""
    label: str


class BusinessColumn(BaseModel):
    name: str
    label: str
    meaning: str
    """How the column is worked out, in business words."""
    definition: str | None = None
    """What the column means: the glossary definition, else the dbt description."""


class TermUsed(BaseModel):
    name: str
    label: str
    definition: str = ""


class BusinessStory(BaseModel):
    model: str
    """The technical model name."""
    title: str
    """The model's label."""
    definition: str = ""
    """What the model is: the glossary definition, else the dbt description."""
    summary: str
    reads_from: list[Reference] = Field(default_factory=list)
    grain: list[str] = Field(default_factory=list)
    """The label of each thing that makes a row unique."""
    columns: list[BusinessColumn] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    """How it is built. Import steps ("Reads X.") are left out."""
    filters: list[str] = Field(default_factory=list)
    terms_used: list[TermUsed] = Field(default_factory=list)
    """Glossary terms that appear in this story, with their definitions."""
    technical: ModelStory
    """The same story with technical names, for "Show details"."""


class Labeler:
    """Turns technical names into labels, using the glossary and then :func:`humanize`.

    Build one per loaded project and reuse it: it indexes every node and column once.
    """

    def __init__(self, project: Project, glossary: Glossary) -> None:
        self.project = project
        self.glossary = glossary
        self._nodes: dict[str, Node] = {}
        self._sources: dict[str, Node] = {}
        self._columns: set[str] = set()
        for node in sorted(project.nodes.values(), key=lambda n: n.unique_id):
            if node.kind == NodeKind.SOURCE:
                self._sources.setdefault(node.name.lower(), node)
            else:
                self._nodes.setdefault(node.name.lower(), node)
            self._columns.update(c.name.lower() for c in node.columns)
        for term in glossary.terms:
            self._columns.update(k.lower() for k in (term.name, *term.aliases))
        self._auto = self._auto_labels()

    # --- node labels ----------------------------------------------------------------

    def _auto_labels(self) -> dict[str, str]:
        """Auto labels per node, telling apart nodes that would otherwise share one.

        ``stg_orders`` and ``orders`` both humanize to "Orders", so the staged one becomes
        "Staged orders" and the raw source table "Raw orders".
        """
        nodes = [*self._nodes.values(), *self._sources.values()]
        base = {n.unique_id: humanize(self._short(n)) for n in nodes}
        out = dict(base)
        taken = {t.label.lower() for n in nodes if (t := self._explicit_term(n)) is not None}
        for level in range(2):
            by_label: dict[str, list[Node]] = {}
            for node in nodes:
                if self._explicit_term(node) is None:
                    by_label.setdefault(out[node.unique_id].lower(), []).append(node)
            for label_key, group in by_label.items():
                if len(group) < 2 and label_key not in taken:
                    continue
                for node in group:
                    qualifier = self._qualifier(node, level)
                    if qualifier:
                        label = out[node.unique_id]
                        out[node.unique_id] = f"{qualifier} {label[:1].lower()}{label[1:]}"
        return out

    @staticmethod
    def _short(node: Node) -> str:
        """The part of a name worth reading: the table of a source, else the whole name."""
        return node.name.split(".", 1)[1] if node.kind == NodeKind.SOURCE else node.name

    def _qualifier(self, node: Node, level: int) -> str | None:
        """A word that tells ``node`` apart: its layer prefix first, then its namespace."""
        if node.kind == NodeKind.SOURCE:
            return (
                humanize(node.name.split(".", 1)[0], strip_prefixes=False) if level == 0 else None
            )
        if level == 0:
            prefix = prefix_of(node.name.rsplit("__", 1)[-1])
            if prefix is not None:
                return PREFIXES[prefix]
        parts = node.name.split("__")
        if len(parts) > 1:
            return humanize(parts[-2], strip_prefixes=False)
        return None

    def _explicit_term(self, node: Node) -> GlossaryTerm | None:
        term = self.glossary.lookup(node.name)
        if term is not None or node.kind != NodeKind.SOURCE:
            return term
        table = node.name.split(".", 1)[-1]
        if table.lower() in self._nodes:
            return None  # A model of that name owns the term.
        return self.glossary.lookup(table)

    def node_term(self, node: Node) -> GlossaryTerm | None:
        return self._explicit_term(node)

    def node_label(self, node: Node) -> str:
        term = self._explicit_term(node)
        return term.label if term is not None else self._auto.get(node.unique_id, node.name)

    # --- lookups by name -------------------------------------------------------------

    def node_named(self, name: str) -> Node | None:
        """The node a bare or dotted name refers to, if any."""
        low = name.lower()
        return self._nodes.get(low) or self._sources.get(low)

    def term_for(self, name: str) -> GlossaryTerm | None:
        """The explicit glossary term for a node or column name, if there is one."""
        node = self.node_named(name)
        if node is not None:
            return self.node_term(node)
        return self.glossary.lookup(name)

    def label(self, name: str, *, column: bool = False) -> str:
        """A label for any model, source, seed or column name."""
        if not column:
            node = self.node_named(name)
            if node is not None:
                return self.node_label(node)
        term = self.glossary.lookup(name)
        if term is not None:
            return term.label
        return humanize(name, strip_prefixes=not column)

    def is_known(self, low: str) -> bool:
        return low in self._nodes or low in self._columns


class _Run:
    """One business story's worth of label lookups, remembering which terms it used."""

    def __init__(self, labeler: Labeler, extra_known: set[str]) -> None:
        self.labeler = labeler
        self.extra = extra_known
        self.used: dict[str, GlossaryTerm] = {}

    def note(self, term: GlossaryTerm | None) -> None:
        if term is not None:
            self.used.setdefault(term.name, term)

    def node(self, name: str) -> str:
        self.note(self.labeler.term_for(name))
        return self.labeler.label(name)

    def column(self, name: str) -> str:
        self.note(self.labeler.glossary.lookup(name))
        return self.labeler.label(name, column=True)

    def ident(self, name: str) -> str:
        """A label for a column-like name that might be written as a plain identifier."""
        return self.column(name) if _IDENT.fullmatch(name) else self.text(name)

    def text(self, text: str) -> str:
        """``text`` with every identifier replaced by its label."""
        return _TOKEN.sub(lambda m: self._token(m, text), text)

    def _token(self, m: re.Match[str], text: str) -> str:
        tok = m.group(0)
        if tok.startswith("'"):
            return tok
        after = text[m.end() :]
        if after.startswith("(") or after.startswith(" macro"):
            return tok  # A function or macro name: its spelling is the point.
        low = tok.lower()
        if "." in tok:
            node = self.labeler.node_named(low)
            if node is not None:
                return self.node(node.name)
            last = low.rsplit(".", 1)[1]
            return self._bare(tok.rsplit(".", 1)[1], last) or tok
        return self._bare(tok, low) or tok

    def _bare(self, tok: str, low: str) -> str | None:
        snake = "_" in tok
        if not snake and (len(tok) < 2 or low in _VOCABULARY):
            return None
        node = self.labeler.node_named(low)
        if node is not None:
            return self.node(node.name)
        if snake or self.labeler.is_known(low) or low in self.extra:
            return self.column(tok)
        return None


def business_story(
    project: Project,
    story: ModelStory,
    glossary: Glossary | None = None,
    *,
    labeler: Labeler | None = None,
) -> BusinessStory:
    """Tell ``story`` in the project's own words. Never raises on odd SQL.

    Pass a ``labeler`` (``Labeler(project, glossary)``) when telling many stories from one
    project, such as every model, so the project is indexed only once.
    """
    if labeler is None:
        labeler = Labeler(project, glossary if glossary is not None else Glossary())
    extra = {c.name.lower() for c in story.columns} | {g.lower() for g in story.grain}
    extra |= {m.group(1).lower() for m in map(_STEP.match, story.steps) if m is not None}
    run = _Run(labeler, extra)
    node = project.get(story.model)

    title = run.node(story.model)
    definition = ""
    if node is not None:
        term = labeler.node_term(node)
        definition = (term.definition if term is not None else "") or node.description
    descriptions = {c.name: c.description for c in node.columns} if node is not None else {}

    columns = [_column(run, c.name, c.how, descriptions) for c in story.columns]
    steps = [s for s in (_step(run, raw) for raw in story.steps) if s]
    reads_from = [Reference(name=n, label=run.node(n)) for n in story.reads_from]
    grain = [run.ident(g) for g in story.grain]
    filters = [run.text(f) for f in story.filters]

    return BusinessStory(
        model=story.model,
        title=title,
        definition=definition,
        summary=_summary(run, node, story, title, reads_from, grain),
        reads_from=reads_from,
        grain=grain,
        columns=columns,
        steps=steps,
        filters=filters,
        terms_used=[
            TermUsed(name=t.name, label=t.label, definition=t.definition) for t in run.used.values()
        ],
        technical=story,
    )


def _capfirst(text: str) -> str:
    return text[:1].upper() + text[1:]


def _column(run: _Run, name: str, how: str, descriptions: dict[str, str]) -> BusinessColumn:
    if name == "*":
        return BusinessColumn(name=name, label="All columns", meaning=_capfirst(run.text(how)))
    label = run.column(name)
    term = run.labeler.glossary.lookup(name)
    definition = (term.definition if term is not None else "") or descriptions.get(name) or None
    return BusinessColumn(name=name, label=label, meaning=_meaning(run, how), definition=definition)


def _meaning(run: _Run, how: str) -> str:
    if how == f"{_PASSED} unchanged":
        return "Taken as it is"
    if how.startswith(f"{_PASSED} from "):
        return "Comes straight from " + run.text(how[len(f"{_PASSED} from ") :])
    if how.startswith("renamed from "):
        return "The same as " + run.ident(how[len("renamed from ") :])
    return _capfirst(run.text(how))


def _start(desc: str) -> str:
    return re.sub(r"^takes rows from ", "starts with ", desc)


def _step(run: _Run, raw: str) -> str | None:
    """A step in business words, or ``None`` for a plain import that adds nothing."""
    if raw.startswith("Reads ") and raw.endswith("."):
        return None
    match = _STEP.match(raw)
    if match is None:
        head, sep, rest = raw.partition(": ")
        return run.text(f"{head}{sep}{_start(rest)}" if sep else raw)
    name, desc = match.groups()
    return f"{run.ident(name)}: {run.text(_start(desc))}"


def _summary(
    run: _Run,
    node: Node | None,
    story: ModelStory,
    title: str,
    reads_from: list[Reference],
    grain: list[str],
) -> str:
    if node is None or node.kind != NodeKind.MODEL:
        return story.description or f"{title} is a {_kind(node)}."
    inputs = join_words([r.label for r in reads_from])
    if story.parse_error:
        return story.description or f"{title} reads from {inputs}."
    out = (
        f"{title} brings together {inputs}"
        if len(reads_from) > 1
        else f"{title} is built from {inputs}"
    )
    if grain:
        out += f" into one row per {join_words(grain)}"
    out += "."
    calculated = [c for c in story.columns if not c.how.startswith((_PASSED, "renamed", "every"))]
    if calculated:
        shown = [
            f"{run.column(c.name)} ({run.text(c.how)})"
            for c in calculated[:_MAX_CALCULATED_IN_SUMMARY]
        ]
        extra = len(calculated) - _MAX_CALCULATED_IN_SUMMARY
        if extra > 0:
            shown.append(f"{extra} more")
        out += " It works out " + join_words(shown) + "."
    return out


def _kind(node: Node | None) -> str:
    if node is None:
        return "model"
    return "source table" if node.kind == NodeKind.SOURCE else node.kind.value
