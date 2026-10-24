"""Just enough Jinja handling to read dbt SQL without running dbt.

We do not render templates. We find ``ref()`` and ``source()`` calls, and we
turn the template into plain SQL that sqlglot can parse.
"""

from __future__ import annotations

import re

_STR = r"""\s*['"]([^'"]+)['"]\s*"""
REF_RE = re.compile(r"\{\{\s*ref\(" + _STR + r"(?:," + _STR + r")?\)\s*\}\}")
SOURCE_RE = re.compile(r"\{\{\s*source\(" + _STR + r"," + _STR + r"\)\s*\}\}")
CONFIG_RE = re.compile(r"\{\{\s*config\((.*?)\)\s*\}\}", re.DOTALL)
MATERIALIZED_RE = re.compile(r"""materialized\s*=\s*['"](\w+)['"]""")
_EXPR_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_STMT_RE = re.compile(r"\{%.*?%\}", re.DOTALL)
_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)


def find_refs(sql: str) -> list[str]:
    """Model names passed to ``ref()``. With two args, the second is the model."""
    out: list[str] = []
    for m in REF_RE.finditer(sql):
        name = m.group(2) or m.group(1)
        if name not in out:
            out.append(name)
    return out


def find_sources(sql: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in SOURCE_RE.finditer(sql):
        pair = (m.group(1), m.group(2))
        if pair not in out:
            out.append(pair)
    return out


def find_materialized(sql: str) -> str | None:
    cfg = CONFIG_RE.search(sql)
    if not cfg:
        return None
    m = MATERIALIZED_RE.search(cfg.group(1))
    return m.group(1) if m else None


def to_plain_sql(sql: str) -> str:
    """Replace refs and sources with table names and drop other Jinja.

    The result is for reading structure only. It is never run.
    """
    sql = _COMMENT_RE.sub("", sql)
    sql = CONFIG_RE.sub("", sql)
    sql = REF_RE.sub(lambda m: m.group(2) or m.group(1), sql)
    sql = SOURCE_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)}", sql)
    sql = _STMT_RE.sub("", sql)
    sql = _EXPR_RE.sub("NULL", sql)
    return sql.strip()
