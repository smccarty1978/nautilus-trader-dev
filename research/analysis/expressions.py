"""The bounded row-wise expression grammar of ``analysis.derive.columns``.

This is NOT an eval engine. An expression is a string in a small fixed grammar, tokenised and
parsed here by a hand-written recursive-descent parser into a JSON AST; nothing is ever handed to
``eval``/``exec``/``compile``/``pandas.eval``. The AST is canonical (``canonical``) so a declared
column's definition is hashable, and the compiler proves every referenced column exists before
anything runs (``static_check``).

Grammar (lowest to highest precedence)::

    expr    := or
    or      := and ('or' and)*
    and     := not ('and' not)*
    not     := 'not' not | cmp
    cmp     := add (('<' | '<=' | '>' | '>=' | '==' | '!=') add)?      -- never chained
    add     := mul (('+' | '-') mul)*
    mul     := unary (('*' | '/') unary)*
    unary   := '-' unary | atom
    atom    := NUMBER | 'STRING' | true | false | null | IDENT | `quoted column`
             | FUNC '(' args ')' | '(' expr ')'

Functions (a closed whitelist, fixed arity): ``abs(x)``, ``sign(x)``, ``sqrt(x)``,
``min(a, b)``, ``max(a, b)``, ``is_null(x)``, ``not_null(x)``, ``where(cond, a, b)``,
``coalesce(a, b, ...)``, ``concat(a, b, ...)``, ``cut(x, [edges...], [labels...])``.

Null semantics (row-wise; no imputation, no cross-row access):

* arithmetic, ``abs``/``sign``/``sqrt``/``min``/``max``, comparisons and ``concat`` are NULL if any
  operand is NULL; a non-finite arithmetic result is NULL; ``sqrt`` of a negative is NULL;
* ``a / b`` with ``b == 0`` is NULL under ``div_zero: null`` (default) and an error under
  ``div_zero: error``;
* ``and`` / ``or`` / ``not`` are three-valued (Kleene): ``false and null`` is false, ``true or null``
  is true;
* ``where(cond, a, b)`` is NULL where ``cond`` is NULL;
* ``is_null`` / ``not_null`` are never NULL; ``coalesce`` is the first non-NULL argument;
* ``cut`` is left-closed: ``x < e0 -> labels[0]``, ``e_i <= x < e_{i+1} -> labels[i+1]``,
  ``x >= e_last -> labels[-1]``; NULL stays NULL.

Integer columns (e.g. nanosecond timestamps) stay exact integers through ``+ - *`` and comparisons
with other integers; any float operand or a division moves the result to float64.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class ExpressionError(ValueError):
    pass


FUNCTIONS: Dict[str, Tuple[int, Optional[int]]] = {   # name -> (min args, max args or None)
    "abs": (1, 1), "sign": (1, 1), "sqrt": (1, 1), "min": (2, 2), "max": (2, 2),
    "is_null": (1, 1), "not_null": (1, 1), "where": (3, 3), "coalesce": (2, None),
    "concat": (2, None), "cut": (3, 3),
}
KEYWORDS = {"and", "or", "not", "true", "false", "null"}
COMPARATORS = ("<=", ">=", "==", "!=", "<", ">")

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<str>'(?:[^'\\]|\\.)*')
  | (?P<qcol>`[^`]+`)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|==|!=|[-+*/<>(),\[\]])
""", re.VERBOSE)


def _tokenize(text: str) -> List[Tuple[str, str]]:
    if not isinstance(text, str) or not text.strip():
        raise ExpressionError("EXPRESSION_EMPTY")
    out: List[Tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise ExpressionError(f"EXPRESSION_SYNTAX: unexpected character {text[pos]!r} at {pos} in {text!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        out.append((kind, m.group()))
    return out


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.toks = _tokenize(text)
        self.i = 0

    def peek(self) -> Tuple[str, str]:
        return self.toks[self.i] if self.i < len(self.toks) else ("eof", "")

    def take(self) -> Tuple[str, str]:
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, value: str) -> None:
        kind, v = self.take()
        if v != value or kind not in ("op", "ident"):
            raise ExpressionError(f"EXPRESSION_SYNTAX: expected {value!r}, got {v or 'end of input'!r} in {self.text!r}")

    def is_kw(self, word: str) -> bool:
        kind, v = self.peek()
        return kind == "ident" and v == word

    def parse(self) -> Dict[str, Any]:
        node = self.or_()
        if self.peek()[0] != "eof":
            raise ExpressionError(f"EXPRESSION_SYNTAX: trailing {self.peek()[1]!r} in {self.text!r}")
        return node

    def or_(self):
        node = self.and_()
        while self.is_kw("or"):
            self.take()
            node = {"op": "or", "args": [node, self.and_()]}
        return node

    def and_(self):
        node = self.not_()
        while self.is_kw("and"):
            self.take()
            node = {"op": "and", "args": [node, self.not_()]}
        return node

    def not_(self):
        if self.is_kw("not"):
            self.take()
            return {"op": "not", "args": [self.not_()]}
        return self.cmp()

    def cmp(self):
        node = self.add()
        kind, v = self.peek()
        if kind == "op" and v in COMPARATORS:
            self.take()
            node = {"op": v, "args": [node, self.add()]}
            kind, v = self.peek()
            if kind == "op" and v in COMPARATORS:
                raise ExpressionError(f"EXPRESSION_SYNTAX: chained comparison in {self.text!r}; combine with 'and'")
        return node

    def add(self):
        node = self.mul()
        while self.peek() in (("op", "+"), ("op", "-")):
            node = {"op": self.take()[1], "args": [node, self.mul()]}
        return node

    def mul(self):
        node = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            node = {"op": self.take()[1], "args": [node, self.unary()]}
        return node

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            inner = self.unary()
            if "num" in inner:
                return {"num": -inner["num"]}
            return {"op": "neg", "args": [inner]}
        return self.atom()

    def atom(self):
        kind, v = self.take()
        if kind == "num":
            f = float(v)
            return {"num": int(f) if re.fullmatch(r"\d+", v) else f}
        if kind == "str":
            return {"str": re.sub(r"\\(.)", r"\1", v[1:-1])}
        if kind == "qcol":
            return {"col": v[1:-1]}
        if kind == "op" and v == "(":
            node = self.or_()
            self.expect(")")
            return node
        if kind == "op" and v == "[":
            raise ExpressionError(f"EXPRESSION_SYNTAX: a list literal is only allowed as a cut() argument in {self.text!r}")
        if kind == "ident":
            if v == "true":
                return {"bool": True}
            if v == "false":
                return {"bool": False}
            if v == "null":
                return {"null": True}
            if v in KEYWORDS:
                raise ExpressionError(f"EXPRESSION_SYNTAX: unexpected keyword {v!r} in {self.text!r}")
            if self.peek() == ("op", "("):
                return self.call(v)
            return {"col": v}
        raise ExpressionError(f"EXPRESSION_SYNTAX: unexpected {v or 'end of input'!r} in {self.text!r}")

    def call(self, name: str):
        if name not in FUNCTIONS:
            raise ExpressionError(f"EXPRESSION_FUNCTION_UNKNOWN: {name!r}; allowed {sorted(FUNCTIONS)}")
        self.expect("(")
        args: List[Any] = []
        if self.peek() != ("op", ")"):
            while True:
                if name == "cut" and len(args) in (1, 2):
                    args.append(self.list_literal())
                else:
                    args.append(self.or_())
                if self.peek() == ("op", ","):
                    self.take()
                    continue
                break
        self.expect(")")
        lo, hi = FUNCTIONS[name]
        if len(args) < lo or (hi is not None and len(args) > hi):
            raise ExpressionError(f"EXPRESSION_ARITY: {name}() takes {lo}{'' if hi == lo else '+' if hi is None else f'..{hi}'} arguments, got {len(args)}")
        if name == "cut":
            edges, labels = args[1]["list"], args[2]["list"]
            if not edges or any("num" not in e for e in edges):
                raise ExpressionError("EXPRESSION_CUT_INVALID: edges must be a non-empty list of numbers")
            vals = [e["num"] for e in edges]
            if any(b <= a for a, b in zip(vals, vals[1:])):
                raise ExpressionError(f"EXPRESSION_CUT_INVALID: edges must be strictly increasing, got {vals}")
            if len(labels) != len(edges) + 1 or any("str" not in lab for lab in labels):
                raise ExpressionError(f"EXPRESSION_CUT_INVALID: labels must be {len(edges) + 1} strings (one more than the edges)")
            if len({lab["str"] for lab in labels}) != len(labels):
                raise ExpressionError("EXPRESSION_CUT_INVALID: labels must be distinct")
        return {"fn": name, "args": args}

    def list_literal(self):
        self.expect("[")
        items: List[Any] = []
        if self.peek() != ("op", "]"):
            while True:
                items.append(self.unary())
                if self.peek() == ("op", ","):
                    self.take()
                    continue
                break
        self.expect("]")
        return {"list": items}


def parse(text: str) -> Dict[str, Any]:
    """Parse one expression into its canonical JSON AST, or raise ``ExpressionError``."""
    return _Parser(text).parse()


def canonical(ast: Mapping[str, Any]) -> str:
    return json.dumps(ast, sort_keys=True, separators=(",", ":"))


def definition_sha256(ast: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(ast).encode("utf-8")).hexdigest()


def referenced_columns(ast: Any) -> Set[str]:
    out: Set[str] = set()

    def walk(n: Any) -> None:
        if isinstance(n, Mapping):
            if "col" in n:
                out.add(str(n["col"]))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(ast)
    return out


_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_columns(columns: Sequence[Mapping[str, Any]]) -> List[Tuple[str, str]]:
    """Expand the declared column list into ordered ``(name, expression)`` pairs.

    An entry is ``{name, expr}`` or a template ``{name, expr, each: {var: [values...]}}``: the
    cartesian product over ``each`` (variables in SORTED name order, values in declared order, so
    the expansion is independent of mapping order) substitutes ``{var}`` in both name and expr.
    An unresolved ``{placeholder}`` is an error, never passed through.
    """
    import itertools
    if not isinstance(columns, (list, tuple)) or not columns:
        raise ExpressionError("DERIVE_COLUMNS_EMPTY: declare at least one column")
    out: List[Tuple[str, str]] = []
    for i, entry in enumerate(columns):
        if not isinstance(entry, Mapping) or not entry.get("name") or not entry.get("expr"):
            raise ExpressionError(f"DERIVE_COLUMN_INVALID: columns[{i}] needs name and expr")
        extra = set(entry) - {"name", "expr", "each"}
        if extra:
            raise ExpressionError(f"DERIVE_COLUMN_INVALID: columns[{i}] unknown keys {sorted(extra)}")
        each = entry.get("each") or {}
        if not isinstance(each, Mapping):
            raise ExpressionError(f"DERIVE_COLUMN_INVALID: columns[{i}].each must be a mapping of var -> [values]")
        names = sorted(each)
        for n in names:
            if not isinstance(each[n], (list, tuple)) or not each[n]:
                raise ExpressionError(f"DERIVE_COLUMN_INVALID: columns[{i}].each.{n} must be a non-empty list")
        for combo in (itertools.product(*[each[n] for n in names]) if names else [()]):
            name, expr = str(entry["name"]), str(entry["expr"])
            for var, value in zip(names, combo):
                name = name.replace("{" + var + "}", str(value))
                expr = expr.replace("{" + var + "}", str(value))
            left = _PLACEHOLDER.findall(name) + _PLACEHOLDER.findall(expr)
            if left:
                raise ExpressionError(f"DERIVE_TEMPLATE_UNRESOLVED: columns[{i}] placeholders {sorted(set(left))} have no 'each' values")
            out.append((name, expr))
    return out


def static_check(params: Mapping[str, Any], known: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Compile-time proof for a derive step: every expression parses and references only columns
    that exist (the input frame's, or ones declared EARLIER in the same step); no derived name
    collides. Returns ``(errors, output_columns)``."""
    errors: List[str] = []
    cols = set(known)
    order = list(known)
    try:
        pairs = expand_columns(params.get("columns") or [])
    except ExpressionError as exc:
        return [str(exc)], order
    for name, expr in pairs:
        try:
            ast = parse(expr)
        except ExpressionError as exc:
            errors.append(f"{name}: {exc}")
            continue
        missing = sorted(referenced_columns(ast) - cols)
        if missing:
            errors.append(f"DERIVE_COLUMN_UNKNOWN: {name} references {missing}, which are neither plan columns nor earlier derived columns")
        if name in cols:
            errors.append(f"DERIVE_COLUMN_EXISTS: {name!r} already exists; a derived column never overwrites one")
        cols.add(name)
        order.append(name)
    if params.get("keep") is not None:
        try:
            missing = sorted(referenced_columns(parse(str(params["keep"]))) - cols)
            if missing:
                errors.append(f"DERIVE_COLUMN_UNKNOWN: keep references {missing}")
        except ExpressionError as exc:
            errors.append(f"keep: {exc}")
    if str(params.get("div_zero", "null")) not in ("null", "error"):
        errors.append(f"DERIVE_DIV_ZERO_INVALID: {params.get('div_zero')!r} (null | error)")
    return errors, order


# --------------------------------------------------------------------------- #
# vectorised evaluation
# --------------------------------------------------------------------------- #
class _V:
    """A typed column value: kind in {num, int, bool, str, null}."""
    __slots__ = ("kind", "s")

    def __init__(self, kind: str, s: Any) -> None:
        self.kind, self.s = kind, s


class Evaluator:
    def __init__(self, frame: Any, *, div_zero: str = "null") -> None:
        import numpy as np
        import pandas as pd
        self.np, self.pd = np, pd
        self.frame = frame
        self.index = frame.index
        self.div_zero = div_zero

    # -- leaves -------------------------------------------------------------------
    def column(self, name: str) -> _V:
        pd, np = self.pd, self.np
        if name not in self.frame.columns:
            raise ExpressionError(f"DERIVE_COLUMN_UNKNOWN: {name!r} is not a column of the input frame")
        s = self.frame[name]
        dt = s.dtype
        if pd.api.types.is_bool_dtype(dt):
            return _V("bool", s.astype("boolean"))
        if pd.api.types.is_integer_dtype(dt):
            return _V("int", s.astype("Int64"))
        if pd.api.types.is_float_dtype(dt):
            return _V("num", pd.Series(s.to_numpy(dtype="float64", na_value=np.nan), index=self.index))
        if dt == object or pd.api.types.is_string_dtype(dt):
            nn = s.dropna()
            if nn.empty:
                return _V("null", None)
            if all(isinstance(v, str) for v in nn):
                return _V("str", s.astype(object).where(s.notna(), None))
            if all(isinstance(v, (bool, np.bool_)) for v in nn):
                return _V("bool", s.astype("boolean"))
            if all(isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) for v in nn):
                return _V("num", pd.to_numeric(s, errors="coerce").astype("float64"))
            raise ExpressionError(f"DERIVE_TYPE: column {name!r} mixes value types")
        raise ExpressionError(f"DERIVE_TYPE: column {name!r} has unsupported dtype {dt}")

    def const(self, node: Mapping[str, Any]) -> _V:
        pd = self.pd
        n = len(self.index)
        if "num" in node:
            v = node["num"]
            if isinstance(v, int):
                return _V("int", pd.Series([v] * n, index=self.index, dtype="Int64"))
            return _V("num", pd.Series([float(v)] * n, index=self.index, dtype="float64"))
        if "str" in node:
            return _V("str", pd.Series([node["str"]] * n, index=self.index, dtype=object))
        if "bool" in node:
            return _V("bool", pd.Series([bool(node["bool"])] * n, index=self.index, dtype="boolean"))
        return _V("null", None)

    # -- coercions ------------------------------------------------------------------
    def as_float(self, v: _V):
        np, pd = self.np, self.pd
        if v.kind == "null":
            return pd.Series(np.nan, index=self.index, dtype="float64")
        if v.kind == "int":
            return pd.Series(v.s.to_numpy(dtype="float64", na_value=np.nan), index=self.index)
        if v.kind == "num":
            return v.s
        raise ExpressionError(f"DERIVE_TYPE: expected a number, got {v.kind}")

    def as_bool(self, v: _V):
        if v.kind == "null":
            return self.pd.Series(self.pd.NA, index=self.index, dtype="boolean")
        if v.kind != "bool":
            raise ExpressionError(f"DERIVE_TYPE: expected a boolean, got {v.kind}")
        return v.s

    def as_str(self, v: _V):
        if v.kind == "null":
            return self.pd.Series([None] * len(self.index), index=self.index, dtype=object)
        if v.kind != "str":
            raise ExpressionError(f"DERIVE_TYPE: expected a string, got {v.kind}")
        return v.s

    def null_mask(self, v: _V):
        if v.kind == "null":
            return self.pd.Series(True, index=self.index)
        return v.s.isna()

    def finite(self, s):
        np = self.np
        return s.where(np.isfinite(s), np.nan)

    # -- evaluation -------------------------------------------------------------------
    def eval(self, node: Mapping[str, Any]) -> _V:
        if "col" in node:
            return self.column(node["col"])
        if any(k in node for k in ("num", "str", "bool", "null")):
            return self.const(node)
        if "op" in node:
            return self.op(node["op"], [self.eval(a) for a in node["args"]])
        if "fn" in node:
            return self.fn(node["fn"], node["args"])
        raise ExpressionError(f"EXPRESSION_AST_INVALID: {node!r}")

    def op(self, op: str, args: List[_V]) -> _V:
        pd, np = self.pd, self.np
        if op in ("and", "or"):
            a, b = self.as_bool(args[0]), self.as_bool(args[1])
            return _V("bool", (a & b) if op == "and" else (a | b))
        if op == "not":
            return _V("bool", ~self.as_bool(args[0]))
        if op == "neg":
            v = args[0]
            if v.kind == "int":
                return _V("int", -v.s)
            return _V("num", -self.as_float(v))
        a, b = args
        if op in ("+", "-", "*"):
            if a.kind == "int" and b.kind == "int":
                return _V("int", a.s + b.s if op == "+" else a.s - b.s if op == "-" else a.s * b.s)
            x, y = self.as_float(a), self.as_float(b)
            return _V("num", self.finite(x + y if op == "+" else x - y if op == "-" else x * y))
        if op == "/":
            x, y = self.as_float(a), self.as_float(b)
            zero = y.eq(0.0) & x.notna()
            if zero.any() and self.div_zero == "error":
                raise ExpressionError(f"DERIVE_DIVIDE_BY_ZERO: {int(zero.sum())} row(s) divide by zero under div_zero: error")
            with np.errstate(divide="ignore", invalid="ignore"):
                q = x / y.where(~y.eq(0.0), np.nan)
            return _V("num", self.finite(q))
        if op in COMPARATORS:
            null = self.null_mask(a) | self.null_mask(b)
            kinds = {a.kind, b.kind} - {"null"}
            if not kinds:
                return _V("bool", pd.Series(pd.NA, index=self.index, dtype="boolean"))
            if kinds <= {"int"}:
                x, y = a.s, b.s
            elif kinds <= {"int", "num"}:
                x, y = self.as_float(a), self.as_float(b)
            elif kinds == {"str"} or kinds == {"bool"}:
                if op not in ("==", "!="):
                    raise ExpressionError(f"DERIVE_TYPE: {op} is not defined for {kinds.pop()} values")
                x = self.as_str(a) if "str" in kinds else self.as_bool(a)
                y = self.as_str(b) if "str" in kinds else self.as_bool(b)
            else:
                raise ExpressionError(f"DERIVE_TYPE: cannot compare {a.kind} with {b.kind}")
            fn = {"<": "lt", "<=": "le", ">": "gt", ">=": "ge", "==": "eq", "!=": "ne"}[op]
            res = getattr(x.astype(object) if kinds in ({"str"}, {"bool"}) else x, fn)(
                y.astype(object) if kinds in ({"str"}, {"bool"}) else y)
            res = pd.Series(res.to_numpy(dtype=object, na_value=False), index=self.index).astype(bool).astype("boolean")
            res[null.to_numpy()] = pd.NA
            return _V("bool", res)
        raise ExpressionError(f"EXPRESSION_OPERATOR_UNKNOWN: {op!r}")

    def fn(self, name: str, raw: List[Mapping[str, Any]]) -> _V:
        pd, np = self.pd, self.np
        if name == "cut":
            x = self.as_float(self.eval(raw[0]))
            edges = [float(e["num"]) for e in raw[1]["list"]]
            labels = [lab["str"] for lab in raw[2]["list"]]
            idx = np.searchsorted(np.asarray(edges), x.to_numpy(), side="right")
            out = pd.Series(np.asarray(labels, dtype=object)[np.clip(idx, 0, len(labels) - 1)], index=self.index, dtype=object)
            return _V("str", out.where(x.notna(), None))
        args = [self.eval(a) for a in raw]
        if name in ("is_null", "not_null"):
            m = self.null_mask(args[0])
            return _V("bool", (m if name == "is_null" else ~m).astype("boolean"))
        if name == "abs":
            v = args[0]
            return _V("int", v.s.abs()) if v.kind == "int" else _V("num", self.as_float(v).abs())
        if name == "sign":
            v = args[0]
            x = self.as_float(v)
            return _V("num", pd.Series(np.sign(x.to_numpy()), index=self.index))
        if name == "sqrt":
            x = self.as_float(args[0])
            with np.errstate(invalid="ignore"):
                return _V("num", self.finite(pd.Series(np.sqrt(x.where(x >= 0, np.nan).to_numpy()), index=self.index)))
        if name in ("min", "max"):
            a, b = args
            if a.kind == "int" and b.kind == "int":
                out = a.s.where((a.s <= b.s) if name == "min" else (a.s >= b.s), b.s)
                out[(a.s.isna() | b.s.isna()).to_numpy()] = pd.NA
                return _V("int", out)
            x, y = self.as_float(a), self.as_float(b)
            out = np.minimum(x, y) if name == "min" else np.maximum(x, y)   # NaN-propagating
            return _V("num", pd.Series(out, index=self.index))
        if name == "where":
            c = self.as_bool(args[0])
            return self._select(c, args[1], args[2])
        if name == "coalesce":
            out = args[0]
            for nxt in args[1:]:
                keep = ~self.null_mask(out)
                out = self._select(keep.astype("boolean"), out, nxt)
            return out
        if name == "concat":
            parts = [self.as_str(a) for a in args]
            null = parts[0].isna()
            acc = parts[0].fillna("")
            for p in parts[1:]:
                null = null | p.isna()
                acc = acc + p.fillna("")
            return _V("str", acc.where(~null, None).astype(object))
        raise ExpressionError(f"EXPRESSION_FUNCTION_UNKNOWN: {name!r}")

    def _select(self, cond, a: _V, b: _V) -> _V:
        pd, np = self.pd, self.np
        kinds = {a.kind, b.kind} - {"null"}
        if not kinds:
            return _V("null", None)
        if kinds <= {"int"}:
            kind, x, y = "int", (a.s if a.kind == "int" else pd.Series(pd.NA, index=self.index, dtype="Int64")), \
                (b.s if b.kind == "int" else pd.Series(pd.NA, index=self.index, dtype="Int64"))
        elif kinds <= {"int", "num"}:
            kind, x, y = "num", self.as_float(a), self.as_float(b)
        elif kinds == {"str"}:
            kind, x, y = "str", self.as_str(a), self.as_str(b)
        elif kinds == {"bool"}:
            kind, x, y = "bool", self.as_bool(a), self.as_bool(b)
        else:
            raise ExpressionError(f"DERIVE_TYPE: where()/coalesce() branches must share a type, got {a.kind} and {b.kind}")
        take_a = cond.fillna(False).to_numpy(dtype=bool)
        is_null = cond.isna().to_numpy()
        if kind == "num":
            out = pd.Series(np.where(take_a, x.to_numpy(), y.to_numpy()), index=self.index, dtype="float64")
            out[is_null] = np.nan
        else:
            out = y.copy()
            out[take_a] = x[take_a]
            out[is_null] = pd.NA if kind in ("int", "bool") else None
        return _V(kind, out)

    def materialize(self, v: _V):
        pd, np = self.pd, self.np
        if v.kind == "null":
            return pd.Series([None] * len(self.index), index=self.index, dtype=object)
        return v.s


__all__ = ["ExpressionError", "FUNCTIONS", "parse", "canonical", "definition_sha256", "referenced_columns",
           "expand_columns", "static_check", "Evaluator"]
