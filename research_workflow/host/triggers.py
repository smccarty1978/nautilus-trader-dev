"""Trigger-state engine: OBSERVE -> WATCH -> ARMED -> ENTERED -> ADD -> EXIT.

The states and the evaluation order are the platform's; the predicates are the plan's.
Per sub-epoch, in this order:

1. ``reset_when`` (graph level, edge events): every active state expires, counters
   reset, and the sub-epoch is consumed -- nothing else is evaluated.
2. the active state's ``expire_when``: the state expires to OBSERVE; consumed.
3. state entries in precedence order; a state whose ``chain`` flag is set may be
   entered in the same sub-epoch as its predecessor; at most
   ``max_transitions_per_epoch`` entries otherwise.
4. ``entry.when`` (bounded by ``max_per_watch`` and ``cooldown``).

Event tests are edge-triggered: the sub-epoch that observes a tracker event consumes
it.  Every transition is returned so the host can notify trackers and the ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from research_workflow.host.interfaces import NS, EpochView
from research_workflow.host.predicate_eval import EdgeMemory, compile_predicate, event_references, top_level_disjuncts

OBSERVE = "OBSERVE"


@dataclass
class Transition:
    kind: str            # "enter" | "expire" | "entry"
    state: str
    ts: int
    reason: str
    epoch_event_ts: Optional[int] = None


@dataclass
class _State:
    name: str
    enter: Any
    expire: Optional[Any]
    from_states: Tuple[str, ...]
    chain: bool
    expire_parts: List[Tuple[str, Any]] = field(default_factory=list)


class TriggerEngine:
    def __init__(self, spec: Mapping[str, Any], epoch_fields: Mapping[str, Set[str]]) -> None:
        self.spec = dict(spec)
        self.states: Dict[str, _State] = {}
        refs: Set[Tuple[str, str]] = set()
        for name, st in (spec.get("states") or {}).items():
            enter_ast = st["enter_when"]["ast"]
            expire_ast = st["expire_when"]["ast"] if st.get("expire_when") else None
            refs |= event_references(enter_ast)
            parts: List[Tuple[str, Any]] = []
            if expire_ast is not None:
                refs |= event_references(expire_ast)
                from research_workflow.grammar.predicates import render
                parts = [(render(d), compile_predicate(d, epoch_fields=epoch_fields)) for d in top_level_disjuncts(expire_ast)]
            self.states[name] = _State(
                name=name, enter=compile_predicate(enter_ast, epoch_fields=epoch_fields),
                expire=compile_predicate(expire_ast, epoch_fields=epoch_fields) if expire_ast is not None else None,
                from_states=tuple(st.get("from") or [OBSERVE]), chain=bool(st.get("chain", False)), expire_parts=parts)
        self.order: List[str] = [s for s in (spec.get("precedence") or []) if s in self.states] or list(self.states)
        for name in self.states:
            if name not in self.order:
                self.order.append(name)
        reset = spec.get("reset_when")
        self.reset_parts: List[Tuple[str, Any]] = []
        if reset:
            from research_workflow.grammar.predicates import render
            refs |= event_references(reset["ast"])
            self.reset_parts = [(render(d), compile_predicate(d, epoch_fields=epoch_fields)) for d in top_level_disjuncts(reset["ast"])]
        entry = spec.get("entry")
        self.entry = compile_predicate(entry["when"]["ast"], epoch_fields=epoch_fields) if entry else None
        if entry:
            refs |= event_references(entry["when"]["ast"])
        self.max_per_watch: Optional[int] = (entry or {}).get("max_per_watch")
        self.cooldown_ns: Optional[int] = (entry or {}).get("cooldown_ns")
        self.max_transitions = int(spec.get("max_transitions_per_epoch", 1))
        self.event_refs = refs
        self.edge_memory = EdgeMemory()
        # runtime state
        self.state = OBSERVE
        self.entered_ts: Dict[str, int] = {}
        self.entries_in_watch = 0
        self.last_entry_ts: Optional[int] = None
        self.fired_flags: Dict[str, bool] = {}

    # -- helpers ------------------------------------------------------------------
    def ages(self, T: int) -> Dict[str, Optional[float]]:
        return {name: ((T - ts) / NS if ts is not None else None) for name, ts in self.entered_ts.items()}

    def _expire_all(self, ts: int, reason: str, out: List[Transition]) -> None:
        for name in list(self.entered_ts):
            out.append(Transition("expire", name, ts, reason))
        self.entered_ts.clear()
        self.state = OBSERVE
        self.entries_in_watch = 0

    # -- evaluation -----------------------------------------------------------------
    def evaluate(self, epoch: EpochView) -> Tuple[List[Transition], bool]:
        """Evaluate one sub-epoch; returns (transitions, entry_fired)."""
        epoch.edge_memory = self.edge_memory
        epoch.state = self.state
        epoch.ages = self.ages(epoch.T)
        epoch.fired_flags = self.fired_flags
        out: List[Transition] = []
        entry_fired = False
        try:
            for text, pred in self.reset_parts:
                if pred(epoch):
                    self._expire_all(epoch.T, f"reset:{text}", out)
                    return out, False
            if self.state != OBSERVE:
                st = self.states[self.state]
                if st.expire is not None and st.expire(epoch):
                    reason = next((t for t, p in st.expire_parts if p(epoch)), "expire")
                    self._expire_all(epoch.T, f"expire:{reason}", out)
                    return out, False
            entered = 0
            for name in self.order:
                st = self.states[name]
                if self.state not in st.from_states:
                    continue
                # a non-chained state needs a fresh sub-epoch; a chained state may follow its predecessor
                if entered >= max(self.max_transitions, 1) and not st.chain:
                    continue
                epoch.state = self.state
                if st.enter(epoch):
                    if self.state == OBSERVE:
                        self.entries_in_watch = 0
                    self.state = name
                    self.entered_ts[name] = epoch.T
                    epoch.state = name
                    epoch.ages = self.ages(epoch.T)
                    out.append(Transition("enter", name, epoch.T, "enter", (epoch.event or {}).get("close_ts")))
                    entered += 1
            if self.entry is not None and self.state != OBSERVE:
                epoch.state = self.state
                if self.max_per_watch is not None and self.entries_in_watch >= self.max_per_watch:
                    pass
                elif self.cooldown_ns is not None and self.last_entry_ts is not None and epoch.T - self.last_entry_ts < self.cooldown_ns:
                    pass
                elif self.entry(epoch):
                    entry_fired = True
                    self.entries_in_watch += 1
                    self.last_entry_ts = epoch.T
                    out.append(Transition("entry", self.state, epoch.T, "entry", (epoch.event or {}).get("close_ts")))
            return out, entry_fired
        finally:
            self.edge_memory.consume(epoch.trackers, self.event_refs)


__all__ = ["TriggerEngine", "Transition", "OBSERVE"]
