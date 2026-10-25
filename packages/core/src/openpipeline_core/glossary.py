"""The glossary: the business's own words for models, columns, sources and seeds.

Terms come from two places and are merged. ``openpipeline.yml`` has a ``glossary:``
list next to ``rules:``. dbt's own YAML can also carry ``meta: {label: ..., definition: ...}``
on a model or a column. When both name the same thing, the ``openpipeline.yml`` entry wins.
Anything not listed falls back to :func:`humanize`, which turns ``stg_order_items`` into
"Order items".

Like the rules registry, problems never raise. They are collected as warnings so one
typo cannot hide the whole project.
"""

from __future__ import annotations

import copy
import io
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, PrivateAttr
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from openpipeline_core.docs import FileEdit
from openpipeline_core.models import Project
from openpipeline_core.rules import RULES_FILE

GLOSSARY_FILE = RULES_FILE
"""Glossary terms live in the same file as the business rules."""

PREFIXES: dict[str, str] = {
    "stg": "Staged",
    "int": "Intermediate",
    "fct": "Fact",
    "fact": "Fact",
    "dim": "Dimension",
    "base": "Base",
    "src": "Source",
    "mart": "Mart",
}
"""Common dbt layer prefixes, with the word used to tell two same-named models apart."""

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEPARATORS = re.compile(r"[_\s]+")


def prefix_of(name: str) -> str | None:
    """The dbt layer prefix of ``name`` (``stg`` for ``stg_orders``), if it has one."""
    head, sep, rest = _after_namespace(name).partition("_")
    return head.lower() if sep and rest.strip("_") and head.lower() in PREFIXES else None


def _after_namespace(name: str) -> str:
    """Tuva-style ``a__b__c`` namespacing: keep the part after the last double underscore."""
    last = name.rsplit("__", 1)[-1]
    return last if last.strip("_") else name


def humanize(name: str, *, strip_prefixes: bool = True) -> str:
    """A readable label for a technical name.

    ``stg_order_items`` is "Order items", ``order_id`` is "Order ID", ``is_food_order`` is
    "Is food order", and a Tuva-style ``claims__medical_claim`` is "Medical claim". Pass
    ``strip_prefixes=False`` for column names, where ``base_price`` really is a base price.
    """
    base = _after_namespace(name)
    if strip_prefixes and (prefix := prefix_of(base)) is not None:
        base = base[len(prefix) :].lstrip("_")
    words = [w for w in _SEPARATORS.split(_CAMEL.sub("_", base)) if w]
    if not words:
        words = [w for w in _SEPARATORS.split(name) if w]
    if not words:
        return name
    out = ["ID" if w.lower() == "id" else w.lower() for w in words]
    if out[0] != "ID":
        out[0] = out[0][:1].upper() + out[0][1:]
    return " ".join(out)


class GlossaryTerm(BaseModel):
    name: str
    """The model, column, source or seed name this term is for."""
    label: str
    definition: str = ""
    aliases: list[str] = Field(default_factory=list)
    """Other names that mean the same thing, such as ``user_id`` for ``customer_id``."""
    origin: Literal["glossary", "meta"] = "glossary"
    """``glossary`` when written in openpipeline.yml, ``meta`` when read from dbt's YAML."""


class Glossary(BaseModel):
    terms: list[GlossaryTerm] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    _by_name: tuple[int, dict[str, GlossaryTerm]] | None = PrivateAttr(default=None)

    def lookup(self, name: str) -> GlossaryTerm | None:
        """The term for ``name`` or one of its aliases, ignoring case."""
        return self._index().get(name.lower())

    def _index(self) -> dict[str, GlossaryTerm]:
        if self._by_name is not None and self._by_name[0] == len(self.terms):
            return self._by_name[1]
        index: dict[str, GlossaryTerm] = {}
        for term in self.terms:
            for key in (term.name, *term.aliases):
                index.setdefault(key.lower(), term)
        self._by_name = (len(self.terms), index)
        return index


def load_glossary(project_root: str | Path, project: Project) -> Glossary:
    """Read ``openpipeline.yml`` and the ``meta.label`` entries in ``project``."""
    glossary = Glossary()
    path = Path(project_root) / GLOSSARY_FILE
    if path.is_file():
        _read_file(path, glossary)
    _merge_meta(project, glossary)
    return glossary


def _read_file(path: Path, glossary: Glossary) -> None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        # Worded like the rules registry's warning, so a project shows it only once.
        glossary.warnings.append(f"{GLOSSARY_FILE}: could not be read ({exc})")
        return
    if not isinstance(data, dict) or "glossary" not in data or data["glossary"] is None:
        return
    entries = data["glossary"]
    if not isinstance(entries, list):
        glossary.warnings.append(f"{GLOSSARY_FILE}: 'glossary' must be a list")
        return
    for index, entry in enumerate(entries, 1):
        term = _parse_term(entry, index, glossary)
        if term is None:
            continue
        clash = next(
            (k for k in (term.name, *term.aliases) if glossary.lookup(k) is not None), None
        )
        if clash is not None:
            other = glossary.lookup(clash)
            assert other is not None
            glossary.warnings.append(
                f"{GLOSSARY_FILE}: '{clash}' is used more than once "
                f"(already the term '{other.name}'); the first one is kept"
            )
            continue
        glossary.terms.append(term)


def _parse_term(entry: Any, index: int, glossary: Glossary) -> GlossaryTerm | None:
    if not isinstance(entry, dict):
        glossary.warnings.append(f"{GLOSSARY_FILE}: glossary entry #{index} is not a mapping")
        return None
    name = str(entry.get("name") or "").strip()
    if not name:
        glossary.warnings.append(f"{GLOSSARY_FILE}: glossary entry #{index} has no name")
        return None
    label = str(entry.get("label") or "").strip()
    if not label:
        label = humanize(name)
        glossary.warnings.append(
            f"{GLOSSARY_FILE}: glossary entry '{name}' has no label; using '{label}'"
        )
    aliases = [a.strip() for a in _string_list(entry.get("aliases")) if a.strip()]
    return GlossaryTerm(
        name=name,
        label=label,
        definition=str(entry.get("definition") or "").strip(),
        aliases=[a for a in dict.fromkeys(aliases) if a.lower() != name.lower()],
    )


def _merge_meta(project: Project, glossary: Glossary) -> None:
    """Add ``meta: {label, definition}`` from models and columns. The yml file always wins."""
    seen: dict[str, GlossaryTerm] = {}
    for node in sorted(project.nodes.values(), key=lambda n: n.unique_id):
        targets: list[tuple[str, dict[str, Any], str]] = [(node.name, node.meta, node.name)]
        targets += [(c.name, c.meta, f"{node.name}.{c.name}") for c in node.columns]
        for name, meta, where in targets:
            label = str(meta.get("label") or "").strip() if isinstance(meta, dict) else ""
            if not label:
                continue
            definition = str(meta.get("definition") or "").strip()
            if (file_term := _file_term(glossary, name)) is not None:
                _fill_definition(file_term, definition)
                continue
            earlier = seen.get(name.lower())
            if earlier is not None:
                if earlier.label != label:
                    glossary.warnings.append(
                        f"{where}: meta.label '{label}' differs from '{earlier.label}' "
                        f"set for '{name}' elsewhere; the first one is kept"
                    )
                else:
                    _fill_definition(earlier, definition)
                continue
            term = GlossaryTerm(name=name, label=label, definition=definition, origin="meta")
            seen[name.lower()] = term
            glossary.terms.append(term)


def _file_term(glossary: Glossary, name: str) -> GlossaryTerm | None:
    term = glossary.lookup(name)
    return term if term is not None and term.origin == "glossary" else None


def _fill_definition(term: GlossaryTerm, definition: str) -> None:
    if definition and not term.definition:
        term.definition = definition


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(x) for x in raw if x is not None]
    return []


# --- Proposing a term: the new content of openpipeline.yml, never written here ---------


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # Do not re-wrap long text.
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _carry_trailing_comment(old: CommentedMap, new: CommentedMap) -> None:
    """Keep the comment that follows the glossary list below it, not above the new entry.

    ruamel hangs the blank lines and comments after the last entry on that entry's last key,
    so appending without this would put the next section's comment in the middle of the list.
    """
    old_key, new_key = list(old.keys())[-1], list(new.keys())[-1]
    slot = old.ca.items.get(old_key)
    if not slot or len(slot) < 3 or slot[2] is None:
        return
    token = slot[2]
    value: str = token.value
    inline = "" if value.startswith("\n") else value.partition("\n")[0] + "\n"
    carried = value[len(inline) :]
    if not carried.strip("\n") and not carried.startswith("\n"):
        return
    if inline:
        token.value = inline
    else:
        old.ca.items[old_key][2] = None
    moved = copy.copy(token)
    moved.value = carried
    new.ca.items[new_key] = [None, None, moved, None]


def add_glossary_term(
    project_root: str | Path, name: str, label: str, definition: str = ""
) -> FileEdit:
    """The new ``openpipeline.yml`` with ``name`` added to (or updated in) ``glossary:``.

    Nothing is written. The caller files it as a proposal for a person to accept. The rest
    of the file, comments and key order included, is kept as it is. An existing entry for
    the same name keeps its aliases and gets the new label and definition.
    """
    name, label, definition = name.strip(), label.strip(), definition.strip()
    if not name:
        raise ValueError("A glossary term needs a name.")
    if not label:
        raise ValueError("A glossary term needs a label.")
    path = Path(project_root) / GLOSSARY_FILE
    y = _yaml()
    data: Any = None
    if path.is_file():
        try:
            data = y.load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"{GLOSSARY_FILE} could not be read: {exc}") from exc
        if data is not None and not isinstance(data, CommentedMap):
            raise ValueError(f"{GLOSSARY_FILE} must be a mapping to add a glossary term")
    if data is None:
        data = CommentedMap()
    entries = data.get("glossary")
    if not isinstance(entries, CommentedSeq):
        entries = CommentedSeq()
        data["glossary"] = entries
    entry = next(
        (
            e
            for e in entries
            if isinstance(e, CommentedMap) and str(e.get("name", "")).lower() == name.lower()
        ),
        None,
    )
    previous = entries[-1] if entries and isinstance(entries[-1], CommentedMap) else None
    created = entry is None
    if entry is None:
        entry = CommentedMap(name=name)
        entries.append(entry)
    entry["label"] = label
    if definition:
        entry["definition"] = definition
    if created and previous is not None:
        _carry_trailing_comment(previous, entry)
    out = io.StringIO()
    y.dump(data, out)
    return FileEdit(path=GLOSSARY_FILE, content=out.getvalue())
