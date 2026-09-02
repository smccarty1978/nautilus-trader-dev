"""Entry-reference library: one registered enum, one implementation per executable reference.

An entry reference names the price a forward path is measured from.  Each carries the
contract type(s) it may serve and its fill model; the compiler refuses a label contract
that names a fill reference and a trade contract that names a research mark.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class EntryReference:
    name: str
    description: str
    contracts: Tuple[str, ...]                # "label" | "trade"
    executable: bool                          # a runtime binding exists in this phase
    fill_model: Mapping[str, object] = field(default_factory=dict)
    sparse_rule: str = "first printed bar strictly after the decision timestamp"
    version: int = 1

    def to_dict(self) -> Dict[str, object]:
        return {"id": f"entry.{self.name}", "name": self.name, "description": self.description, "contracts": list(self.contracts),
                "executable": self.executable, "fill_model": dict(self.fill_model), "sparse_rule": self.sparse_rule, "version": self.version}


ENTRY_REFERENCES: Dict[str, EntryReference] = {
    "next_bar_open": EntryReference(
        "next_bar_open", "OPEN of the first execution bar strictly after the decision timestamp T; entry instant = that bar's open time.",
        ("label", "trade"), True, {"reference_price": "next_bar_open", "latency_bars": 0, "slippage_ticks": 0.0, "spread_ticks": 0.0}),
    "next_printed_bar_open": EntryReference(
        "next_printed_bar_open", "Alias of next_bar_open on a sparse tape: a no-print second resolves to the next printed bar and the delay is recorded.",
        ("label", "trade"), True, {"reference_price": "next_bar_open", "latency_bars": 0, "slippage_ticks": 0.0, "spread_ticks": 0.0},
        sparse_rule="no-print seconds are skipped; entry lands on the next printed bar; delay = entry_ts - T"),
    "decision_close": EntryReference(
        "decision_close", "CLOSE of the bar at the decision timestamp -- a research mark, never a fill (a label contract may not use it as an entry).",
        ("research_mark",), False, {"reference_price": "decision_close"}),
    "confirmation_close": EntryReference(
        "confirmation_close", "CLOSE of the confirming bar (requires a confirmation primitive; no runtime binding in this phase).",
        ("label", "trade"), False, {"reference_price": "confirmation_close"}),
    "limit_at": EntryReference(
        "limit_at", "Resting limit at a declared price; fill only when the tape trades through it (trade contract only; not bound in this phase).",
        ("trade",), False, {"order_type": "limit"}),
    "stop_at": EntryReference(
        "stop_at", "Stop order at a declared price; fill at or beyond it (trade contract only; not bound in this phase).",
        ("trade",), False, {"order_type": "stop"}),
}


def resolve_entry_reference(name: str, contract: str) -> Tuple[Optional[EntryReference], Optional[str]]:
    """(reference, problem) -- problem is a typed gap message when the reference cannot serve ``contract``."""
    ref = ENTRY_REFERENCES.get(name)
    if ref is None:
        return None, f"entry reference {name!r} is not registered"
    if contract not in ref.contracts:
        if name == "decision_close" and contract == "label":
            return ref, "a label contract has no fill reference: decision_close is a research mark, not an entry; use next_bar_open"
        return ref, f"entry reference {name!r} serves {list(ref.contracts)}, not a {contract} contract"
    if not ref.executable:
        return ref, f"no runtime binding executes entry reference {name!r} in this phase"
    return ref, None


__all__ = ["EntryReference", "ENTRY_REFERENCES", "resolve_entry_reference"]
