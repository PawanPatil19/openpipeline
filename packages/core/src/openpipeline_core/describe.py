"""Describe a SQL expression in plain English.

``describe(expr)`` turns ``coalesce(a, b)`` into ``a, or b when a is missing`` and
``sum(case when x then 1 else 0 end)`` into ``the number of rows where x``. It is
deterministic, never raises, and falls back to the (shortened) SQL text for anything
it does not know. Nested macro calls written by ``jinja.to_plain_sql`` as
``__macro__name(args)`` are described as "the name macro applied to args".
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp

from openpipeline_core.jinja import MACRO_PREFIX

_MAX_DEPTH = 12
_MAX_LEN = 240
_SQL_LEN = 60


def _classes(*names: str) -> tuple[type[exp.Expr], ...]:
    """Expression classes by name, skipping any this sqlglot version does not have."""
    return tuple(getattr(exp, n) for n in names if hasattr(exp, n))


_CMP: dict[type[exp.Expr], str] = {
    exp.GT: "is more than",
    exp.GTE: "is at least",
    exp.LT: "is less than",
    exp.LTE: "is at most",
    exp.EQ: "equals",
    exp.NEQ: "is not",
    exp.NullSafeEQ: "equals",
    exp.NullSafeNEQ: "is not",
}
_ARITH: dict[type[exp.Expr], tuple[str, int]] = {
    exp.Add: ("plus", 1),
    exp.Sub: ("minus", 1),
    exp.Mul: ("times", 2),
    exp.Div: ("divided by", 2),
    exp.Mod: ("modulo", 2),
}
_COMPOUND = (
    exp.Coalesce,
    exp.Case,
    exp.Nullif,
    exp.If,
    exp.Between,
    exp.In,
    exp.Is,
    exp.Like,
    exp.And,
    exp.Or,
    exp.Not,
    exp.Window,
    exp.Filter,
)
_PREDICATES = (
    *_CMP,
    exp.And,
    exp.Or,
    exp.Not,
    exp.Is,
    exp.In,
    exp.Between,
    exp.Like,
    exp.ILike,
    exp.Exists,
)
_ADD = _classes("DateAdd", "TimestampAdd", "DatetimeAdd", "TsOrDsAdd")
_SUB = _classes("DateSub", "TimestampSub", "DatetimeSub")
_TRUNC = _classes("DateTrunc", "TimestampTrunc", "DatetimeTrunc")
_CURRENT_TIME = _classes("CurrentTimestamp", "CurrentDatetime", "CurrentTime")
_RANK = _classes("Rank", "DenseRank", "PercentRank", "CumeDist")
_TIMEISH = ("date", "time", "_at", "_on", "day", "month", "year", "created", "updated")

_AGG_PHRASES: list[tuple[tuple[type[exp.Expr], ...], str]] = [
    (_classes("Sum"), "the total of"),
    (_classes("Avg"), "the average of"),
    (_classes("Min"), "the smallest of"),
    (_classes("Max"), "the largest of"),
    (_classes("Median"), "the median of"),
    (_classes("Stddev", "StddevPop", "StddevSamp"), "the standard deviation of"),
    (_classes("Variance", "VariancePop"), "the variance of"),
    (_classes("ArrayAgg"), "the list of"),
    (_classes("AnyValue"), "any value of"),
    (_classes("ApproxDistinct"), "roughly the number of different"),
]


@dataclass(frozen=True)
class Described:
    text: str
    exact: bool
    """False when the whole expression was unknown and ``text`` is just its SQL."""


def describe(expr: exp.Expr) -> str:
    """Plain-English description of ``expr``. Never raises."""
    return describe_expr(expr).text


def describe_expr(expr: exp.Expr) -> Described:
    """Like ``describe`` but also says whether the top-level expression was understood."""
    try:
        d = _Describer()
        text = d.run(expr)
        exact = d.top_known
    except Exception:
        return Described(_sql(expr), False)
    if len(text) > _MAX_LEN:
        text = text[: _MAX_LEN - 1].rsplit(" ", 1)[0] + "…"
    return Described(text, exact)


def is_predicate(expr: exp.Expr) -> bool:
    """True for a yes/no test such as ``a > 1`` or ``b is null``."""
    while isinstance(expr, exp.Paren):
        expr = expr.this
    return isinstance(expr, _PREDICATES)


def _sql(e: exp.Expr) -> str:
    try:
        text = " ".join(e.sql().split())
    except Exception:
        text = "an expression"
    return text if len(text) <= _SQL_LEN else text[: _SQL_LEN - 1].rstrip() + "…"


def join_words(items: list[str], last: str = "and") -> str:
    if not items:
        return "nothing"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def _unparen(e: exp.Expr) -> exp.Expr:
    while isinstance(e, exp.Paren):
        e = e.this
    return e


def _arg(e: exp.Expr, key: str) -> exp.Expr | None:
    value = e.args.get(key)
    return value if isinstance(value, exp.Expr) else None


def _is_bool(e: exp.Expr | None, value: bool) -> bool:
    return isinstance(e, exp.Boolean) and bool(e.this) is value


def _unit(e: exp.Expr | None) -> str:
    """A date part such as ``day`` from a Var, string or column."""
    if e is None:
        return ""
    if isinstance(e, exp.Literal):
        return str(e.this).strip().lower()
    return (e.name or e.sql()).strip().lower()


def _plural(n: str, unit: str) -> str:
    return unit if not unit or n == "1" or unit.endswith("s") else unit + "s"


def _type_phrase(to: exp.Expr | None) -> str:
    if not isinstance(to, exp.DataType):
        return "another type"
    kind = getattr(to.this, "name", str(to.this)).upper()
    if kind in {
        "INT",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "MEDIUMINT",
        "DECIMAL",
        "NUMERIC",
        "FLOAT",
        "DOUBLE",
        "REAL",
        "UBIGINT",
        "UINT",
        "BIGDECIMAL",
        "INT128",
        "INT256",
    }:
        return "a number"
    if kind == "DATE":
        return "a date"
    if kind.startswith(("TIMESTAMP", "DATETIME")):
        return "a timestamp"
    if kind in {"VARCHAR", "TEXT", "CHAR", "NVARCHAR", "NCHAR", "STRING", "BPCHAR", "MEDIUMTEXT"}:
        return "text"
    if kind == "BOOLEAN":
        return "true-false"
    return f"a {kind.lower()}"


class _Describer:
    def __init__(self) -> None:
        self.top_known = True

    def run(self, e: exp.Expr) -> str:
        return self.d(e, 0)

    def d(self, e: exp.Expr, depth: int) -> str:
        text: str | None = None
        if depth <= _MAX_DEPTH:
            try:
                text = self._dispatch(e, depth)
            except Exception:
                text = None
        if text is None:
            if depth == 0:
                self.top_known = False
            return _sql(e)
        return text

    def atom(self, e: exp.Expr, depth: int) -> str:
        """Describe ``e`` so it can sit inside a larger phrase, in parentheses if needed."""
        inner = _unparen(e)
        text = self.d(inner, depth + 1)
        if isinstance(inner, _COMPOUND) or (isinstance(inner, exp.Cast) and ", as " in text):
            return f"({text})"
        return text

    def lst(self, items: list[exp.Expr], depth: int, last: str = "and") -> str:
        return join_words([self.d(i, depth + 1) for i in items], last)

    # --- dispatch ------------------------------------------------------------

    def _dispatch(self, e: exp.Expr, depth: int) -> str | None:
        n = depth + 1
        if isinstance(e, exp.Paren):
            return self.d(e.this, n)
        if isinstance(e, exp.Alias):
            return self.d(e.this, n)
        if isinstance(e, exp.Column):
            return e.name or None
        if isinstance(e, exp.Literal):
            return _literal(e)
        if isinstance(e, exp.Boolean):
            return "true" if e.this else "false"
        if isinstance(e, exp.Null):
            return "nothing"
        if isinstance(e, exp.Star):
            return "all columns"
        if isinstance(e, exp.Neg):
            return f"minus {self.atom(e.this, n)}"
        if isinstance(e, exp.Interval):
            return self._interval(e)
        if isinstance(e, (exp.Cast, exp.TryCast)):
            return self._cast(e, n)
        for cls, (word, prec) in _ARITH.items():
            if type(e) is cls:
                return self._arith(e, word, prec, n)
        for cmp_cls, word in _CMP.items():
            if type(e) is cmp_cls:
                return self._compare(e, word, n)
        if isinstance(e, (exp.And, exp.Or)):
            return self._logic(e, n)
        if isinstance(e, exp.Not):
            return self._not(e, n)
        if isinstance(e, exp.Is):
            return self._is(e, n)
        if isinstance(e, exp.Between):
            return (
                f"{self.atom(e.this, n)} is between "
                f"{self.atom(e.args['low'], n)} and {self.atom(e.args['high'], n)}"
            )
        if isinstance(e, exp.In):
            return self._in(e, n, negate=False)
        if isinstance(e, (exp.Like, exp.ILike)):
            return self._like(e, n, negate=bool(e.args.get("negate")))
        if isinstance(e, exp.Exists):
            return "a matching row exists"
        if isinstance(e, exp.Case):
            return self._case(e, n)
        if isinstance(e, exp.If):
            return self._if(e, n)
        if isinstance(e, exp.Coalesce):
            return self._coalesce(e, n)
        if isinstance(e, exp.Nullif):
            return (
                f"{self.d(_unparen(e.this), n)}, or missing when it equals "
                f"{self.atom(e.expression, n)}"
            )
        if isinstance(e, exp.Window):
            return self._window(e, n)
        if isinstance(e, exp.Filter):
            inner = self.d(e.this, n)
            where = _arg(e, "expression")
            cond = self.d(where.this, n) if isinstance(where, exp.Where) else None
            return f"{inner} where {cond}" if cond else inner
        if isinstance(e, exp.AggFunc):
            agg = self._agg(e, n)
            if agg is not None:
                return agg
        if isinstance(e, exp.Anonymous):
            return self._anonymous(e, n)
        return self._functions(e, n)

    # --- pieces ----------------------------------------------------------------

    def _interval(self, e: exp.Interval) -> str | None:
        value = e.this
        unit = _unit(_arg(e, "unit"))
        if isinstance(value, exp.Literal):
            raw = str(value.this).strip()
            if unit:
                return f"{raw} {_plural(raw, unit)}"
            return raw
        return None

    def _cast(self, e: exp.Cast | exp.TryCast, n: int) -> str:
        inner = _unparen(e.this)
        text = self.d(inner, n)
        phrase = _type_phrase(_arg(e, "to"))
        if isinstance(e, exp.TryCast):
            phrase += " (missing if that fails)"
        simple = isinstance(inner, (exp.Column, exp.Literal)) or " " not in text
        return f"{text} as {phrase}" if simple else f"{text}, as {phrase}"

    def _arith(self, e: exp.Expr, word: str, prec: int, n: int) -> str:
        left = self._operand(e.this, prec, n, right=False, parent=type(e))
        right = self._operand(e.expression, prec, n, right=True, parent=type(e))
        if isinstance(e, exp.Mod):
            return f"the remainder of {left} divided by {right}"
        return f"{left} {word} {right}"

    def _operand(self, e: exp.Expr, prec: int, n: int, *, right: bool, parent: type) -> str:
        inner = _unparen(e)
        text = self.d(inner, n)
        other = _ARITH.get(type(inner))
        if other is not None:
            tighter = other[1] > prec
            same = other[1] == prec and not (right and parent in (exp.Sub, exp.Div, exp.Mod))
            if not (tighter or same):
                return f"({text})"
            return text
        if isinstance(inner, _COMPOUND) or (isinstance(inner, exp.Cast) and ", as " in text):
            return f"({text})"
        return text

    def _compare(self, e: exp.Expr, word: str, n: int) -> str:
        right = _unparen(e.expression)
        if isinstance(right, exp.Boolean) and type(e) in (exp.EQ, exp.NEQ):
            neg = "" if type(e) is exp.EQ else "not "
            return f"{self.atom(e.this, n)} is {neg}{'true' if right.this else 'false'}"
        return f"{self.atom(e.this, n)} {word} {self.atom(right, n)}"

    def _logic(self, e: exp.Expr, n: int) -> str:
        cls = type(e)
        parts: list[exp.Expr] = []

        def collect(x: exp.Expr) -> None:
            x = _unparen(x) if isinstance(x, exp.Paren) and type(_unparen(x)) is cls else x
            if type(x) is cls:
                collect(x.this)
                collect(x.expression)
            else:
                parts.append(x)

        collect(e)
        word = "and" if cls is exp.And else "or"
        texts = []
        for p in parts:
            inner = _unparen(p)
            t = self.d(inner, n)
            if isinstance(inner, (exp.And, exp.Or)) and type(inner) is not cls:
                t = f"({t})"
            texts.append(t)
        return f" {word} ".join(texts)

    def _not(self, e: exp.Not, n: int) -> str:
        inner = _unparen(e.this)
        if isinstance(inner, exp.Is):
            return self._is(inner, n, negate=True)
        if isinstance(inner, exp.In):
            return self._in(inner, n, negate=True)
        if isinstance(inner, (exp.Like, exp.ILike)):
            return self._like(inner, n, negate=True)
        if isinstance(inner, exp.Between):
            text = self.d(inner, n)
            return text.replace(" is between ", " is not between ", 1)
        if isinstance(inner, exp.Exists):
            return "no matching row exists"
        return f"not {self.atom(inner, n)}"

    def _is(self, e: exp.Is, n: int, negate: bool = False) -> str:
        target = _unparen(e.expression)
        subject = self.atom(e.this, n)
        if isinstance(target, exp.Null):
            return f"{subject} is {'present' if negate else 'missing'}"
        if isinstance(target, exp.Boolean):
            value = "true" if target.this else "false"
            return f"{subject} is {'not ' if negate else ''}{value}"
        return f"{subject} is {'not ' if negate else ''}{self.atom(target, n)}"

    def _in(self, e: exp.In, n: int, negate: bool) -> str:
        subject = self.atom(e.this, n)
        neg = "not " if negate else ""
        values = list(e.expressions)
        if values:
            shown = [self.d(v, n) for v in values[:5]]
            more = f" and {len(values) - 5} more" if len(values) > 5 else ""
            return f"{subject} is {neg}one of {', '.join(shown)}{more}"
        return f"{subject} is {neg}in the results of a subquery"

    def _like(self, e: exp.Expr, n: int, negate: bool) -> str:
        verb = "does not match" if negate else "matches"
        case = " (ignoring case)" if isinstance(e, exp.ILike) else ""
        return f"{self.atom(e.this, n)} {verb} {self.atom(e.expression, n)}{case}"

    def _branches(
        self, pairs: list[tuple[exp.Expr, exp.Expr]], default: exp.Expr | None, n: int
    ) -> str:
        """Describe ``value when condition`` pairs for CASE and IF."""
        trues = [c for c, v in pairs if _is_bool(v, True)]
        falses = [c for c, v in pairs if _is_bool(v, False)]
        if trues and len(trues) == len(pairs) and (default is None or _is_bool(default, False)):
            return "true when " + " or ".join(self.d(c, n) for c in trues)
        if falses and len(falses) == len(pairs) and _is_bool(default, True):
            return "false when " + " or ".join(self.d(c, n) for c in falses)
        shown = [f"{self.d(v, n)} when {self.d(c, n)}" for c, v in pairs[:4]]
        if len(pairs) > 4:
            shown.append(f"{len(pairs) - 4} other cases")
        if default is not None:
            shown.append(f"otherwise {self.d(default, n)}")
        return ", ".join(shown)

    def _case(self, e: exp.Case, n: int) -> str:
        subject = _arg(e, "this")
        pairs: list[tuple[exp.Expr, exp.Expr]] = []
        for branch in e.args.get("ifs") or []:
            cond, value = branch.this, _arg(branch, "true")
            if value is None:
                continue
            if subject is not None:
                cond = exp.EQ(this=subject.copy(), expression=cond.copy())
            pairs.append((cond, value))
        if not pairs:
            raise ValueError("empty case")
        return self._branches(pairs, _arg(e, "default"), n)

    def _if(self, e: exp.If, n: int) -> str | None:
        true = _arg(e, "true")
        if true is None:
            return None
        return self._branches([(e.this, true)], _arg(e, "false"), n)

    def _coalesce(self, e: exp.Coalesce, n: int) -> str:
        items = [e.this, *e.expressions]
        first = self.d(_unparen(items[0]), n)
        if len(items) == 2:
            fallback = self.d(items[1], n)
            if len(first) > 50:
                return f"{first}, or {fallback} if missing"
            return f"{first}, or {fallback} when {first} is missing"
        rest = join_words([self.d(i, n) for i in items[1:]], "then")
        return f"{first}, or if missing {rest}"

    # --- aggregates and windows -------------------------------------------------

    def _agg(self, e: exp.Expr, n: int) -> str | None:
        arg = _arg(e, "this")
        if isinstance(e, exp.Count):
            if arg is None or isinstance(arg, (exp.Star, exp.Literal)):
                return "the number of rows"
            if isinstance(arg, exp.Distinct):
                return "the number of different " + self.lst(list(arg.expressions), n)
            cond = _flag_condition(arg, count=True)
            if cond is not None:
                return f"the number of rows where {self.d(cond, n)}"
            return f"the number of {self.d(arg, n)}"
        if isinstance(e, exp.Sum) and arg is not None:
            cond = _flag_condition(arg, count=False)
            if cond is not None:
                return f"the number of rows where {self.d(cond, n)}"
        for classes, phrase in _AGG_PHRASES:
            if classes and isinstance(e, classes) and arg is not None:
                if isinstance(arg, exp.Distinct):
                    return f"{phrase} different {self.lst(list(arg.expressions), n)}"
                return f"{phrase} {self.d(arg, n)}"
        if isinstance(e, _classes("LogicalAnd")) and arg is not None:
            return f"true when {self.d(arg, n)} is true in every row"
        if isinstance(e, _classes("LogicalOr")) and arg is not None:
            return f"true when {self.d(arg, n)} is true in any row"
        group_concat = _classes("GroupConcat", "StringAgg")
        if group_concat and isinstance(e, group_concat) and arg is not None:
            return f"{self.d(arg, n)} joined into one text"
        return None

    def _window(self, e: exp.Window, n: int) -> str | None:
        func = e.this
        partition = list(e.args.get("partition_by") or [])
        order = _arg(e, "order")
        where = ""
        if partition:
            where = " within its " + self.lst(partition, n)
        order_text = self._order(order, n) if order is not None else ""
        by = f", {order_text}" if order_text else ""
        if isinstance(func, exp.RowNumber):
            return f"the position of each row{where}{by}"
        if isinstance(func, _RANK):
            return f"the rank of each row{where}{by}"
        if isinstance(func, (exp.Lag, exp.Lead)):
            arg = _arg(func, "this")
            if arg is None:
                return None
            direction = "previous" if isinstance(func, exp.Lag) else "next"
            offset = _arg(func, "offset")
            if offset is not None and _literal(offset) not in ("1", None):
                before = "before" if direction == "previous" else "after"
                return f"the value of {self.d(arg, n)} {_literal(offset)} rows {before}{where}{by}"
            return f"the {direction} value of {self.d(arg, n)}{where}{by}"
        if isinstance(func, (exp.FirstValue, exp.LastValue)):
            which = "first" if isinstance(func, exp.FirstValue) else "last"
            return f"the {which} value of {self.d(func.this, n)}{where}{by}"
        if isinstance(func, exp.AggFunc):
            base = self._agg(func, n)
            if base is None:
                return None
            if order_text:
                if isinstance(func, exp.Sum) and base.startswith("the total of"):
                    base = base.replace("the total of", "the running total of", 1)
                else:
                    base += " so far"
                return f"{base}{where}{by}"
            return f"{base}{where or ' across all rows'}"
        return None

    def _order(self, order: exp.Expr, n: int) -> str:
        parts = []
        for item in order.expressions:
            target = item.this if isinstance(item, exp.Ordered) else item
            name = self.d(target, n)
            desc = bool(item.args.get("desc")) if isinstance(item, exp.Ordered) else False
            timeish = any(t in name.lower() for t in _TIMEISH)
            if timeish:
                hint = "latest first" if desc else "earliest first"
            else:
                hint = "highest first" if desc else "lowest first"
            parts.append(f"{name} ({hint})")
        if not parts:
            return ""
        return "ordered by " + ", then ".join(parts)

    # --- functions -----------------------------------------------------------------

    def _anonymous(self, e: exp.Anonymous, n: int) -> str | None:
        name = str(e.this)
        args = list(e.expressions)
        low = name.lower()
        if low.startswith(MACRO_PREFIX):
            return self._macro(low[len(MACRO_PREFIX) :], args, n)
        if low == "iff" and len(args) == 3:
            return self._branches([(args[0], args[1])], args[2], n)
        if low in ("date_part", "datepart") and len(args) == 2:
            return f"the {_unit(args[0])} of {self.atom(args[1], n)}"
        if low in ("date_diff", "datediff") and len(args) == 3:
            return self._diff(_unit(args[0]), args[1], args[2], n)
        if low in ("date_add", "dateadd") and len(args) == 3 and not _is_number(args[2]):
            return (
                f"{self.atom(args[2], n)} plus {self.d(args[1], n)} {_plural('', _unit(args[0]))}"
            )
        return None

    def _diff(self, unit: str, a: exp.Expr, b: exp.Expr, n: int) -> str:
        return f"{_plural('', unit) or 'the difference'} between {self.d(a, n)} and {self.d(b, n)}"

    def _macro(self, name: str, args: list[exp.Expr], n: int) -> str:
        if name == "var" and args:
            return f"the project variable {_plain(args[0])}"
        if name == "date_trunc" and len(args) == 2:
            return f"{self.atom(args[1], n)} cut to the {_unit(args[0])}"
        if name in ("dateadd", "date_add") and len(args) == 3:
            unit = _unit(args[0])
            return f"{self.atom(args[2], n)} plus {self.d(args[1], n)} {_plural('', unit)}"
        if name in ("datediff", "date_diff") and len(args) == 3:
            return self._diff(_unit(args[0]), args[1], args[2], n)
        if name == "generate_surrogate_key" and args:
            return f"a unique key built from {self.lst(args, n)}"
        if name == "concat" and len(args) >= 2:
            return f"{self.d(args[0], n)} joined with {self.lst(args[1:], n)}"
        if name in ("current_timestamp", "current_date") and not args:
            return "the current time" if name == "current_timestamp" else "today's date"
        if not args:
            return f"the {name} macro"
        return f"the {name} macro applied to {self.lst(args, n)}"

    def _functions(self, e: exp.Expr, n: int) -> str | None:
        if isinstance(e, _TRUNC):
            unit = _unit(_arg(e, "unit"))
            return f"{self.atom(e.this, n)} cut to the {unit}" if unit else None
        if isinstance(e, exp.Extract):
            return f"the {_unit(e.this)} of {self.atom(e.expression, n)}"
        if isinstance(e, exp.DateDiff):
            return self._diff(_unit(_arg(e, "unit")) or "day", e.expression, e.this, n)
        if isinstance(e, _ADD + _SUB):
            word = "plus" if isinstance(e, _ADD) else "minus"
            amount = _arg(e, "expression")
            if amount is None:
                return None
            count = self.d(amount, n)
            unit = _unit(_arg(e, "unit")) or "day"
            return f"{self.atom(e.this, n)} {word} {count} {_plural(count, unit)}"
        if isinstance(e, exp.CurrentDate):
            return "today's date"
        if isinstance(e, _CURRENT_TIME):
            return "the current time"
        if isinstance(e, (exp.DPipe, exp.Concat)):
            items = _flatten_concat(e)
            if len(items) >= 2:
                return f"{self.d(items[0], n)} joined with {self.lst(items[1:], n)}"
            return None
        if isinstance(e, exp.ConcatWs):
            items = list(e.expressions)
            if len(items) >= 3:
                sep = self.d(items[0], n)
                return f"{self.lst(items[1:], n)} joined with {sep} between them"
            return None
        if isinstance(e, exp.Lower):
            return f"{self.atom(e.this, n)} in lower case"
        if isinstance(e, exp.Upper):
            return f"{self.atom(e.this, n)} in upper case"
        if isinstance(e, exp.Trim):
            return f"{self.atom(e.this, n)} without surrounding spaces"
        if isinstance(e, exp.Replace):
            return (
                f"{self.atom(e.this, n)} with {self.d(e.expression, n)} "
                f"replaced by {self.d(e.args['replacement'], n)}"
            )
        if isinstance(e, exp.Substring):
            start, length = _arg(e, "start"), _arg(e, "length")
            subject = self.atom(e.this, n)
            if start is not None and length is not None and _literal(start) == "1":
                return f"the first {self.d(length, n)} characters of {subject}"
            if start is not None and length is not None:
                return (
                    f"{self.d(length, n)} characters of {subject} "
                    f"starting at position {self.d(start, n)}"
                )
            if start is not None:
                return f"{subject} from position {self.d(start, n)} on"
            return None
        hashes = _classes("MD5", "SHA", "SHA1Digest", "SHA2", "MD5Digest")
        if hashes and isinstance(e, hashes):
            return f"a hash of {self.d(e.this, n)}"
        if isinstance(e, exp.TimeToStr):
            fmt = _arg(e, "format")
            shown = self.d(fmt, n) if fmt is not None else "text"
            return f"{self.atom(e.this, n)} as text in the format {shown}"
        if isinstance(e, (exp.Left, exp.Right)):
            where = "first" if isinstance(e, exp.Left) else "last"
            return f"the {where} {self.d(e.expression, n)} characters of {self.atom(e.this, n)}"
        if isinstance(e, exp.Length):
            return f"the length of {self.atom(e.this, n)}"
        if isinstance(e, exp.Round):
            decimals = _arg(e, "decimals")
            subject = self.atom(e.this, n)
            if decimals is None:
                return f"{subject} rounded"
            return f"{subject} rounded to {self.d(decimals, n)} decimal places"
        if isinstance(e, exp.Abs):
            return f"the absolute value of {self.atom(e.this, n)}"
        if isinstance(e, exp.Ceil):
            return f"{self.atom(e.this, n)} rounded up"
        if isinstance(e, exp.Floor):
            return f"{self.atom(e.this, n)} rounded down"
        if isinstance(e, (exp.Greatest, exp.Least)):
            word = "largest" if isinstance(e, exp.Greatest) else "smallest"
            return f"the {word} of {self.lst([e.this, *e.expressions], n)}"
        return None


def _literal(e: exp.Expr) -> str | None:
    if not isinstance(e, exp.Literal):
        return None
    text = str(e.this)
    if e.is_string:
        text = text if len(text) <= 30 else text[:29] + "…"
        return "'" + text.replace("'", "''") + "'"
    return text


def _plain(e: exp.Expr) -> str:
    """A name or literal without quotes, for words like "the project variable x"."""
    if isinstance(e, exp.Literal):
        return str(e.this)
    return e.name or _sql(e)


def _is_number(e: exp.Expr) -> bool:
    return isinstance(e, exp.Literal) and not e.is_string


def _flatten_concat(e: exp.Expr) -> list[exp.Expr]:
    if isinstance(e, exp.DPipe):
        out: list[exp.Expr] = []
        for side in (e.this, e.expression):
            side = _unparen(side)
            out.extend(_flatten_concat(side) if isinstance(side, exp.DPipe) else [side])
        return out
    if isinstance(e, exp.Concat):
        return list(e.expressions)
    return [e]


def _flag_condition(arg: exp.Expr, *, count: bool) -> exp.Expr | None:
    """The condition in ``case when c then 1 else 0 end`` style flags, else ``None``.

    For ``count`` the flag may have no ELSE (``count(case when c then 1 end)``).
    """
    arg = _unparen(arg)
    cond: exp.Expr | None = None
    yes: exp.Expr | None = None
    no: exp.Expr | None = None
    if isinstance(arg, exp.Case) and arg.args.get("this") is None:
        ifs = arg.args.get("ifs") or []
        if len(ifs) != 1:
            return None
        cond, yes, no = ifs[0].this, _arg(ifs[0], "true"), _arg(arg, "default")
    elif isinstance(arg, exp.If):
        cond, yes, no = arg.this, _arg(arg, "true"), _arg(arg, "false")
    elif isinstance(arg, exp.Anonymous) and str(arg.this).lower() == "iff":
        a = list(arg.expressions)
        if len(a) == 3:
            cond, yes, no = a
    if cond is None or yes is None:
        return None
    if count:
        return cond if no is None or isinstance(no, exp.Null) else None
    one = _is_number(yes) and _literal(yes) == "1"
    zero = no is None or isinstance(no, exp.Null) or (_is_number(no) and _literal(no) == "0")
    return cond if one and zero else None
