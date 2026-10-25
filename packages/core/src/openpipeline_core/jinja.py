"""Just enough Jinja handling to read dbt SQL without running dbt.

We do not render templates. We find ``ref()`` and ``source()`` calls, and we
turn the template into plain SQL that sqlglot can parse. When a manifest is
available the story engine uses dbt's own compiled SQL instead (see
``sql_source``); this module is the best effort for projects read from files.
"""

from __future__ import annotations

import re
from functools import lru_cache

import sqlglot
from sqlglot import exp
from sqlglot.tokens import Tokenizer

_STR = r"""\s*['"]([^'"]+)['"]\s*"""
REF_RE = re.compile(r"\{\{\s*ref\(" + _STR + r"(?:," + _STR + r")?\)\s*\}\}")
SOURCE_RE = re.compile(r"\{\{\s*source\(" + _STR + r"," + _STR + r"\)\s*\}\}")
CONFIG_RE = re.compile(r"\{\{\s*config\((.*?)\)\s*\}\}", re.DOTALL)
MATERIALIZED_RE = re.compile(r"""materialized\s*=\s*['"](\w+)['"]""")
_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)

_TOKEN_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)
_TAG_RE = re.compile(r"\{%-?\s*(\w+)\s*(.*?)\s*-?%\}", re.DOTALL)
_END_TAGS = {
    "endif": "if",
    "endfor": "for",
    "endmacro": "macro",
    "endset": "set",
    "endcall": "call",
    "endfilter": "filter",
    "endraw": "raw",
}
_SKIP_BLOCKS = {"macro", "call", "filter", "raw"}
"""Blocks whose body is not SQL we can read: dropped along with their tags."""

_IDENT_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_CALL_RE = re.compile(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\((.*)\)", re.DOTALL)
_QUOTED_RE = re.compile(r"""'[^']*'|"[^"]*\"""")
_NOT_MACROS = {
    "ref",
    "source",
    "config",
    "this",
    "is_incremental",
    "return",
    "adapter",
    "target",
    "env_var",
    "run_query",
    "log",
    "exceptions",
    "execute",
    "modules",
    "flags",
    "load_result",
    "statement",
    "caller",
    "loop",
}
"""Jinja helpers that do not produce a SQL expression, so they stay NULL."""

MACRO_PREFIX = "__macro__"
"""Prefix of the SQL function that stands in for a macro call in plain SQL."""


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


class _Frame:
    __slots__ = ("inside", "kind")

    def __init__(self, kind: str, inside: bool) -> None:
        self.kind = kind
        self.inside = inside
        """Whether text inside this block is kept."""


def _strip_statements(sql: str) -> str:
    """Resolve ``{% %}`` blocks and turn each ``{{ }}`` into SQL.

    ``if``/``elif``/``else`` keep only the first branch (nesting is tracked with a
    stack). ``for`` keeps its body once. ``macro`` and block ``set`` bodies, and
    every other tag, are dropped.
    """
    out: list[str] = []
    stack: list[_Frame] = []
    pos = 0

    def emitting() -> bool:
        return stack[-1].inside if stack else True

    for m in _TOKEN_RE.finditer(sql):
        if emitting():
            out.append(sql[pos : m.start()])
        pos = m.end()
        token = m.group(0)
        if token.startswith("{{"):
            if emitting():
                out.append(_expr_to_sql(token[2:-2]))
            continue
        tag = _TAG_RE.fullmatch(token)
        if tag is None:
            continue
        name, rest = tag.group(1), tag.group(2)
        here = emitting()
        if name in ("if", "for"):
            stack.append(_Frame(name, here))
        elif name in ("elif", "else"):
            if stack and stack[-1].kind in ("if", "for"):
                stack[-1].inside = False
        elif name in _SKIP_BLOCKS or (name == "set" and "=" not in rest):
            stack.append(_Frame(name, False))
        elif name in _END_TAGS:
            wanted = _END_TAGS[name]
            for i in range(len(stack) - 1, -1, -1):
                if stack[i].kind == wanted:
                    del stack[i:]
                    break
    if emitting():
        out.append(sql[pos:])
    return "".join(out)


def _expr_to_sql(body: str) -> str:
    """SQL for the inside of one ``{{ ... }}``: a macro call, or NULL."""
    call = macro_call_sql(body)
    return call if call is not None else "NULL"


def macro_call_sql(body: str) -> str | None:
    """``cents_to_dollars('amount')`` becomes ``__macro__cents_to_dollars(amount)``.

    Quoted plain identifiers (``'amount'``, ``'orders.amount'``) become column
    references, other strings stay strings, numbers stay numbers, and a list
    argument is spread into several arguments. ``dbt.date_trunc(...)`` drops its
    package prefix. ``var('x')`` keeps its name as a string, ``__macro__var('x')``: a call, not a
    bare string literal, so it is never mistaken for data. Returns ``None`` for
    anything else, which the caller turns into NULL.
    """
    body = body.strip().strip("-").strip()
    m = _CALL_RE.fullmatch(body)
    if m is None:
        return None
    dotted, inner = m.group(1), m.group(2)
    if dotted.split(".")[0] in _NOT_MACROS or "|" in _QUOTED_RE.sub("", inner):
        return None
    args = _split_args(inner)
    if args is None:
        return None
    sql_args: list[str] = []
    keep_strings = dotted.split(".")[-1] == "var"
    for arg in args:
        converted = _arg_sql(arg, keep_strings=keep_strings)
        if converted is None:
            return None
        sql_args.extend(converted)
    return f"{MACRO_PREFIX}{dotted.split('.')[-1]}({', '.join(sql_args)})"


def _split_args(inner: str) -> list[str] | None:
    """Split on top-level commas, respecting quotes and brackets."""
    args: list[str] = []
    depth = 0
    quote = ""
    current: list[str] = []
    for ch in inner:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            current.append(ch)
        elif ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return None
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current))
            current = []
        else:
            current.append(ch)
    if quote or depth != 0:
        return None
    if "".join(current).strip() or args:
        args.append("".join(current))
    return [a.strip() for a in args]


def _arg_sql(arg: str, *, keep_strings: bool = False) -> list[str] | None:
    if arg.startswith("[") and arg.endswith("]"):
        items = _split_args(arg[1:-1])
        if items is None:
            return None
        out: list[str] = []
        for item in items:
            if item.startswith("["):
                return None
            converted = _arg_sql(item)
            if converted is None:
                return None
            out.extend(converted)
        return out
    if len(arg) >= 2 and arg[0] in "'\"" and arg[-1] == arg[0] and arg[0] not in arg[1:-1]:
        text = arg[1:-1]
        if _IDENT_RE.fullmatch(text) and not keep_strings:
            return [_column_sql(text)]
        return ["'" + text.replace("'", "''") + "'"]
    if _NUMBER_RE.fullmatch(arg):
        return [arg]
    if arg.lower() in ("true", "false"):
        return [arg.lower()]
    if arg.lower() in ("none", "null"):
        return ["NULL"]
    return None


@lru_cache(maxsize=512)
def _bare_ok(name: str) -> bool:
    """Whether ``name`` parses as a plain unquoted column name."""
    try:
        tree = sqlglot.parse_one(f"select {name}")
    except sqlglot.errors.SqlglotError:
        return False
    cols = list(tree.find_all(exp.Column))
    return len(cols) == 1 and cols[0].name == name and name.upper() not in Tokenizer.KEYWORDS


def _column_sql(dotted: str) -> str:
    """A column reference. Names that are SQL keywords are quoted so the query still parses."""
    return ".".join(p if _bare_ok(p) else f'"{p}"' for p in dotted.split("."))


def to_plain_sql(sql: str) -> str:
    """Replace refs and sources with table names and make the rest readable SQL.

    ``{{ macro('a', 1) }}`` becomes a ``__macro__macro(a, 1)`` function call (see
    ``macro_call_sql``); any other expression becomes NULL. ``if``/``elif``/``else``
    keeps only the first branch and ``for`` keeps its body once. The result is for
    reading structure only. It is never run.
    """
    sql = _COMMENT_RE.sub("", sql)
    sql = CONFIG_RE.sub("", sql)
    sql = REF_RE.sub(lambda m: m.group(2) or m.group(1), sql)
    sql = SOURCE_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)}", sql)
    return _strip_statements(sql).strip()
