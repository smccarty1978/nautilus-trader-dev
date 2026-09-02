"""Compile predicate ASTs (``research_workflow.grammar.predicates``) into closures -- once.

Null semantics: a comparison against ``None`` is ``False`` (an unwarmed tracker never
qualifies); ``== null`` / ``!= null`` test nullness explicitly.  Event tests are
edge-triggered through the trigger graph's edge memory (``epoch.edge_memory``): a
tracker event is *fresh* until the sub-epoch that observed it ends.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Set, Tuple

from research_workflow.host.interfaces import EpochView

Closure = Callable[[EpochView], Any]

_RESERVED_ROOTS = {"state", "age", "T", "price", "in_position", "triggers", "epoch"}


class PredicateCompileError(ValueError):
    pass


def _cmp(op: str) -> Callable[[Any, Any], bool]:
    if op == ">=": return lambda a, b: a is not None and b is not None and a >= b
    if op == "<=": return lambda a, b: a is not None and b is not None and a <= b
    if op == ">": return lambda a, b: a is not None and b is not None and a > b
    if op == "<": return lambda a, b: a is not None and b is not None and a < b
    if op == "==": return lambda a, b: a == b
    if op == "!=": return lambda a, b: a != b
    raise PredicateCompileError(f"PREDICATE_CMP: unknown comparator {op!r}")


def _getter(path: Sequence[str], epoch_fields: Mapping[str, Set[str]]) -> Closure:
    root = path[0]
    if root == "state":
        return lambda e: e.state
    if root == "T":
        return lambda e: e.T
    if root == "price":
        return lambda e: e.price
    if root == "in_position":
        return lambda e: e.in_position
    if root == "age":
        return lambda e: e.age_seconds(None)
    if root == "epoch":
        attr = path[1]
        if attr == "event":
            key = path[2] if len(path) > 2 else None
            return (lambda e: (e.event or {}).get(key)) if key else (lambda e: e.event)
        if attr == "index":
            return lambda e: e.grid_index
        return lambda e: getattr(e, attr)
    if root == "triggers":
        state = path[1]
        return lambda e: e.fired(state)
    # tracker reference
    if len(path) == 1:
        return lambda e: e.trackers[root]
    attr = path[1]
    rest = tuple(path[2:])
    if attr in epoch_fields.get(root, set()):
        base = lambda e: e.trackers[root].epoch_value(attr, e)
    else:
        base = lambda e: getattr(e.trackers[root], attr)
    if not rest:
        return base

    def deep(e: EpochView) -> Any:
        v = base(e)
        for r in rest:
            v = None if v is None else getattr(v, r)
        return v
    return deep


_EVENT_TESTS = {"flipped", "changed", "turned", "crossed", "fired", "new_leg", "terminated"}


def _event_test(path: Sequence[str], args: Mapping[str, Closure]) -> Closure:
    tracker_id, event = path[0], path[1]
    if event in ("turned", "crossed"):
        def turned(e: EpochView) -> bool:
            ev = e.event
            if ev is None or e.event_source != tracker_id:
                return False
            if "to" in args:
                want = args["to"](e)
                if want is None or int(ev.get("direction", 0)) != int(want):
                    return False
            if "from" in args:
                want = args["from"](e)
                if want is None or int(ev.get("prev_direction", 0)) != int(want):
                    return False
            return True
        return turned

    def fresh(e: EpochView) -> bool:
        mem = e.edge_memory
        tracker = e.trackers[tracker_id]
        seq = getattr(tracker, f"{event}_seq", None)
        if seq is None:
            return bool(getattr(tracker, event, False))
        if mem is None:
            return bool(getattr(tracker, event, seq > 0))
        return mem.fresh(tracker_id, event, int(seq))
    return fresh


def compile_predicate(ast: Mapping[str, Any], *, epoch_fields: Mapping[str, Set[str]] | None = None,
                      allow_events: bool = True) -> Closure:
    ef = dict(epoch_fields or {})

    def build(n: Mapping[str, Any]) -> Closure:
        op = n["op"]
        if op == "const":
            v = n["value"]
            return lambda e, v=v: v
        if op == "ref":
            path = list(n["path"])
            if len(path) >= 2 and path[0] not in _RESERVED_ROOTS and path[1] in _EVENT_TESTS:
                if not allow_events:
                    raise PredicateCompileError(f"PREDICATE_EVENT_NOT_ALLOWED: {'.'.join(path)}")
                return _event_test(path, {})
            return _getter(path, ef)
        if op == "call":
            path = list(n["path"])
            args = {k: build(v) for k, v in (n.get("args") or {}).items()}
            positional = [build(p) for p in n.get("positional") or ()]
            if path == ["age"]:
                st = positional[0] if positional else None
                return (lambda e, st=st: e.age_seconds(st(e))) if st else (lambda e: e.age_seconds(None))
            if len(path) >= 2 and path[1] in _EVENT_TESTS:
                if not allow_events:
                    raise PredicateCompileError(f"PREDICATE_EVENT_NOT_ALLOWED: {'.'.join(path)}")
                return _event_test(path, args)
            if path[0] == "triggers" and path[-1] == "fired" and len(path) == 1 + 2:  # host-constant: triggers.<state>.fired
                state = path[1]
                return lambda e, state=state: e.fired(state)
            raise PredicateCompileError(f"PREDICATE_CALL: {'.'.join(path)} is not a callable primitive")
        if op == "neg":
            inner = build(n["arg"])
            return lambda e, f=inner: (None if f(e) is None else -f(e))
        if op == "not":
            inner = build(n["arg"])
            return lambda e, f=inner: not f(e)
        if op == "and":
            parts = [build(a) for a in n["args"]]
            def _and(e: EpochView, parts=parts) -> bool:
                for p in parts:
                    if not p(e):
                        return False
                return True
            return _and
        if op == "or":
            parts = [build(a) for a in n["args"]]
            def _or(e: EpochView, parts=parts) -> bool:
                for p in parts:
                    if p(e):
                        return True
                return False
            return _or
        if op == "cmp":
            left, right, fn = build(n["left"]), build(n["right"]), _cmp(n["cmp"])
            return lambda e, l=left, r=right, fn=fn: fn(l(e), r(e))
        if op == "in":
            left = build(n["left"]); items = [build(i) for i in n["right"]["items"]]
            return lambda e, l=left, items=items: l(e) in [i(e) for i in items]
        if op == "list":
            items = [build(i) for i in n["items"]]
            return lambda e, items=items: [i(e) for i in items]
        raise PredicateCompileError(f"PREDICATE_AST: unknown op {op!r}")

    return build(ast)


def top_level_disjuncts(ast: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    return list(ast["args"]) if ast.get("op") == "or" else [ast]


def event_references(ast: Mapping[str, Any]) -> Set[Tuple[str, str]]:
    """(tracker_id, event) pairs whose edge memory a graph must maintain."""
    out: Set[Tuple[str, str]] = set()

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        op = n.get("op")
        if op in ("ref", "call"):
            path = n["path"]
            if len(path) >= 2 and path[0] not in _RESERVED_ROOTS and path[1] in _EVENT_TESTS and path[1] not in ("turned", "crossed"):
                out.add((path[0], path[1]))
            for a in (n.get("args") or {}).values():
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


class EdgeMemory:
    """Per-graph memory of consumed tracker event sequence numbers."""

    def __init__(self) -> None:
        self._seen: Dict[Tuple[str, str], int] = {}

    def fresh(self, tracker_id: str, event: str, seq: int) -> bool:
        return seq > self._seen.get((tracker_id, event), 0)

    def consume(self, trackers: Mapping[str, Any], refs: Set[Tuple[str, str]]) -> None:
        for tracker_id, event in refs:
            seq = getattr(trackers[tracker_id], f"{event}_seq", None)
            if seq is not None:
                self._seen[(tracker_id, event)] = int(seq)


__all__ = ["compile_predicate", "top_level_disjuncts", "event_references", "EdgeMemory", "PredicateCompileError"]
