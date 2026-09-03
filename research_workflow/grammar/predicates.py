"""The intentionally tiny predicate language of the study grammar.

Vocabulary (nothing else parses):

    comparisons      a >= b, a > b, a <= b, a < b, a == b, a != b, a in [x, y]
    boolean logic    and, or, not, parentheses
    references       regime_1m.age_s, pullback.depth_atr, state, in_position, T
    unary minus      -regime_1m.dir            (sign flip of a reference/literal only)
    durations        600s, 5m                  (seconds)
    literals         numbers, true/false/null, 'quoted', BARE_UPPER (a state name)
    event tests      regime_1m.flipped, regime_5s.turned(to=regime_1m.dir),
                     score.crossed(level=0.6), triggers.ARMED.fired, age(WATCH)

Anything mathematically richer -- windows, ratios, ranks, arithmetic between fields --
belongs in a registered feature or tracker, never here.  The parser produces a JSON
serializable AST that the compiler validates against the declared context and that the
host compiles once into closures (``research_workflow.host.predicate_eval``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<duration>\d+(?:\.\d+)?(?:s|m|h)\b)
  | (?P<number>\d+\.\d+|\d+)
  | (?P<string>'[^']*'|"[^"]*")
  | (?P<op>>=|<=|==|!=|>|<)
  | (?P<punct>[()\[\],.=:\-])
  | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
""", re.X)

_DURATION_UNIT = {"s": 1, "m": 60, "h": 3600}
_KEYWORDS = {"and", "or", "not", "in", "true", "false", "null", "none"}


class PredicateSyntaxError(ValueError):
    """The text is outside the predicate language."""


@dataclass(frozen=True)
class _Tok:
    kind: str
    value: str
    pos: int


def tokenize(text: str) -> List[_Tok]:
    out: List[_Tok] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            raise PredicateSyntaxError(f"PREDICATE_SYNTAX: unexpected character {text[pos]!r} at {pos} in {text!r}")
        kind = m.lastgroup
        if kind != "ws":
            out.append(_Tok(kind, m.group(kind), pos))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.toks = tokenize(text)
        self.i = 0

    def peek(self) -> Optional[_Tok]:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self, kind: Optional[str] = None, value: Optional[str] = None) -> _Tok:
        t = self.peek()
        if t is None or (kind and t.kind != kind) or (value is not None and t.value != value):
            want = value or kind or "token"
            raise PredicateSyntaxError(f"PREDICATE_SYNTAX: expected {want!r} at {t.pos if t else len(self.text)} in {self.text!r}")
        self.i += 1
        return t

    def at(self, kind: str, value: Optional[str] = None) -> bool:
        t = self.peek()
        return t is not None and t.kind == kind and (value is None or t.value == value)

    # expr := or
    def parse(self) -> Dict[str, Any]:
        node = self.parse_or()
        if self.peek() is not None:
            t = self.peek()
            raise PredicateSyntaxError(f"PREDICATE_SYNTAX: trailing {t.value!r} at {t.pos} in {self.text!r}")
        return node

    def parse_or(self) -> Dict[str, Any]:
        parts = [self.parse_and()]
        while self.at("name", "or"):
            self.take(); parts.append(self.parse_and())
        return parts[0] if len(parts) == 1 else {"op": "or", "args": parts}

    def parse_and(self) -> Dict[str, Any]:
        parts = [self.parse_not()]
        while self.at("name", "and"):
            self.take(); parts.append(self.parse_not())
        return parts[0] if len(parts) == 1 else {"op": "and", "args": parts}

    def parse_not(self) -> Dict[str, Any]:
        if self.at("name", "not"):
            self.take()
            return {"op": "not", "arg": self.parse_not()}
        return self.parse_cmp()

    def parse_cmp(self) -> Dict[str, Any]:
        left = self.parse_operand()
        if self.at("op"):
            op = self.take().value
            right = self.parse_operand()
            return {"op": "cmp", "cmp": op, "left": left, "right": right}
        if self.at("name", "in"):
            self.take()
            right = self.parse_operand()
            if right.get("op") != "list":
                raise PredicateSyntaxError(f"PREDICATE_SYNTAX: 'in' requires a [list] in {self.text!r}")
            return {"op": "in", "left": left, "right": right}
        return left

    def parse_operand(self) -> Dict[str, Any]:
        t = self.peek()
        if t is None:
            raise PredicateSyntaxError(f"PREDICATE_SYNTAX: unexpected end of {self.text!r}")
        if t.kind == "punct" and t.value == "(":
            self.take(); node = self.parse_or(); self.take("punct", ")"); return node
        if t.kind == "punct" and t.value == "[":
            self.take(); items = []
            if not self.at("punct", "]"):
                items.append(self.parse_operand())
                while self.at("punct", ","):
                    self.take(); items.append(self.parse_operand())
            self.take("punct", "]")
            return {"op": "list", "items": items}
        if t.kind == "punct" and t.value == "-":
            self.take()
            return {"op": "neg", "arg": self.parse_operand()}
        if t.kind == "duration":
            self.take()
            num, unit = t.value[:-1], t.value[-1]
            return {"op": "const", "value": float(num) * _DURATION_UNIT[unit], "unit": "seconds"}
        if t.kind == "number":
            self.take()
            v = float(t.value) if "." in t.value else int(t.value)
            return {"op": "const", "value": v}
        if t.kind == "string":
            self.take()
            return {"op": "const", "value": t.value[1:-1]}
        if t.kind == "name":
            low = t.value.lower()
            if low in ("true", "false"):
                self.take(); return {"op": "const", "value": low == "true"}
            if low in ("null", "none"):
                self.take(); return {"op": "const", "value": None}
            if low in ("and", "or", "not", "in"):
                raise PredicateSyntaxError(f"PREDICATE_SYNTAX: keyword {t.value!r} cannot be an operand in {self.text!r}")
            return self.parse_ref_or_call()
        raise PredicateSyntaxError(f"PREDICATE_SYNTAX: unexpected {t.value!r} at {t.pos} in {self.text!r}")

    def parse_ref_or_call(self) -> Dict[str, Any]:
        path = [self.take("name").value]
        while self.at("punct", "."):
            self.take(); path.append(self.take("name").value)
        if self.at("punct", "("):
            self.take()
            args: Dict[str, Any] = {}
            positional: List[Dict[str, Any]] = []
            if not self.at("punct", ")"):
                while True:
                    t = self.peek()
                    nxt = self.toks[self.i + 1] if self.i + 1 < len(self.toks) else None
                    if t is not None and t.kind == "name" and nxt is not None and nxt.kind == "punct" and nxt.value in ("=", ":"):
                        key = self.take("name").value; self.take("punct")
                        args[key] = self.parse_operand()
                    else:
                        positional.append(self.parse_operand())
                    if self.at("punct", ","):
                        self.take(); continue
                    break
            self.take("punct", ")")
            node: Dict[str, Any] = {"op": "call", "path": path, "args": args}
            if positional:
                node["positional"] = positional
            return node
        if len(path) == 1 and path[0].isupper() and not path[0].isdigit():
            # A bare ALL-CAPS name is a state literal (WATCH, ARMED, ENTERED ...).
            return {"op": "const", "value": path[0], "state_literal": True}
        return {"op": "ref", "path": path}


_ALLOWED_OPS = {"and", "or", "not", "cmp", "in", "list", "neg", "const", "ref", "call"}


def parse_predicate(text: str) -> Dict[str, Any]:
    """Parse ``text`` into the predicate AST; raises :class:`PredicateSyntaxError`."""
    if not isinstance(text, str) or not text.strip():
        raise PredicateSyntaxError("PREDICATE_SYNTAX: empty predicate")
    return _Parser(text).parse()


def referenced_roots(ast: Dict[str, Any]) -> Set[str]:
    """Every root name referenced (tracker ids plus the reserved ``state``/``age``/``T``...)."""
    out: Set[str] = set()

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        op = n.get("op")
        if op in ("ref", "call"):
            out.add(n["path"][0])
            for a in (n.get("args") or {}).values():
                walk(a)
            for a in n.get("positional") or ():
                walk(a)
        elif op in ("and", "or"):
            for a in n["args"]:
                walk(a)
        elif op in ("not", "neg"):
            walk(n["arg"])
        elif op in ("cmp", "in"):
            walk(n["left"]); walk(n["right"])
        elif op == "list":
            for a in n["items"]:
                walk(a)
    walk(ast)
    return out


def referenced_paths(ast: Dict[str, Any]) -> List[Tuple[str, ...]]:
    """Every (root, attr, ...) path referenced, in evaluation order (for validation)."""
    out: List[Tuple[str, ...]] = []

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        op = n.get("op")
        if op in ("ref", "call"):
            out.append(tuple(n["path"]))
            for a in (n.get("args") or {}).values():
                walk(a)
            for a in n.get("positional") or ():
                walk(a)
        elif op in ("and", "or"):
            for a in n["args"]:
                walk(a)
        elif op in ("not", "neg"):
            walk(n["arg"])
        elif op in ("cmp", "in"):
            walk(n["left"]); walk(n["right"])
        elif op == "list":
            for a in n["items"]:
                walk(a)
    walk(ast)
    return out


def render(ast: Dict[str, Any]) -> str:
    """Canonical text of an AST (stable, used for plan identity and audit packets)."""
    op = ast["op"]
    if op == "const":
        v = ast["value"]
        if ast.get("unit") == "seconds":
            return f"{int(v) if float(v).is_integer() else v}s"
        if isinstance(v, str):
            return v if ast.get("state_literal") else repr(v)
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        return repr(v)
    if op == "ref":
        return ".".join(ast["path"])
    if op == "call":
        args = [f"{k}={render(v)}" for k, v in ast["args"].items()]
        args = [render(p) for p in ast.get("positional", ())] + args
        return ".".join(ast["path"]) + "(" + ", ".join(args) + ")"
    if op == "neg":
        return "-" + render(ast["arg"])
    if op == "not":
        return "not " + _paren(ast["arg"], {"and", "or", "cmp", "in"})
    if op in ("and", "or"):
        return f" {op} ".join(_paren(a, {"or"} if op == "and" else set()) for a in ast["args"])
    if op == "cmp":
        return f"{render(ast['left'])} {ast['cmp']} {render(ast['right'])}"
    if op == "in":
        return f"{render(ast['left'])} in {render(ast['right'])}"
    if op == "list":
        return "[" + ", ".join(render(i) for i in ast["items"]) + "]"
    raise PredicateSyntaxError(f"PREDICATE_AST: unknown op {op!r}")


def _paren(node: Dict[str, Any], wrap_ops: Set[str]) -> str:
    s = render(node)
    return f"({s})" if node["op"] in wrap_ops else s


__all__ = ["PredicateSyntaxError", "parse_predicate", "referenced_roots", "referenced_paths", "render", "tokenize"]
