"""The six primitive interfaces the host talks to.  Nothing scientific lives here.

A *tracker binding* is the runtime face of a registered tracker or feature host.  The
host constructs it from the compiled plan (``implementation`` dotted path, ``params``,
resolved ``inputs``), feeds it completed bars of the streams it declared, routes the
events other bindings emit to it, tells it about trigger transitions, and reads its
fields when a predicate or an output column asks for them.  What the binding *computes*
is the registered primitive's business.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple

NS = 1_000_000_000

REQUIRED = object()   # sentinel for a parameter with no default


@dataclass(frozen=True)
class BarView:
    """One completed bar as the host sees it (integers are UTC nanoseconds)."""
    stream: str
    ts_event: int      # interval open
    ts_init: int       # interval close == availability
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class EmittedEvent:
    """An event a binding produced while consuming one bar (or one trigger transition)."""
    name: str
    payload: Mapping[str, Any]


@dataclass
class EpochView:
    """What a predicate closure or a binding may read at one decision (sub-)epoch.

    ``event`` is the tracker event that opened a sub-epoch (a completed-bucket regime
    turn, for instance) or ``None`` for the base epoch of a bar.
    """
    T: int
    price: float
    bar: Optional[BarView]
    trackers: Mapping[str, Any]
    state: str = "OBSERVE"
    event: Optional[Mapping[str, Any]] = None
    event_source: Optional[str] = None
    ages: Mapping[str, Optional[float]] = None          # state -> seconds in state (None if not active)
    fired_flags: Mapping[str, bool] = None              # state -> fired this epoch
    in_position: bool = False
    grid_index: Optional[int] = None
    edge_memory: Any = None                             # trigger-graph event edge memory (host-owned)

    def tracker(self, name: str) -> Any:
        return self.trackers[name]

    def age_seconds(self, state: Optional[str] = None) -> Optional[float]:
        if self.ages is None:
            return None
        return self.ages.get(state or self.state)

    def fired(self, state: str) -> bool:
        return bool(self.fired_flags and self.fired_flags.get(state))


class TrackerBinding(Protocol):
    """Runtime protocol.  Declarative metadata lives on the class (see ``BindingMeta``)."""

    def on_bar(self, input_key: str, bar: BarView) -> None: ...
    def on_event(self, input_key: str, event: EmittedEvent) -> None: ...
    def drain_events(self) -> List[EmittedEvent]: ...
    def epoch_value(self, name: str, epoch: EpochView) -> Any: ...
    def on_trigger_transition(self, state: str, kind: str, ts: int, epoch: EpochView) -> None: ...


class BindingMeta(Protocol):
    """Class-level declarations the compiler reads without instantiating anything."""
    CAPABILITY: str
    PARAMS: Mapping[str, Any]           # name -> default (REQUIRED for mandatory)
    INPUTS: Mapping[str, str]           # input key -> "stream" | "tracker" | "stream?" | "tracker?"
    FIELDS: Tuple[str, ...]             # attributes readable by predicates / output columns
    EPOCH_FIELDS: Tuple[str, ...]       # values that need the epoch (T, price, event)
    EVENTS: Tuple[str, ...]             # event names this binding emits
    SUBSCRIBES: Tuple[str, ...]         # event names this binding consumes (from its tracker inputs)
    WARMUP_BARS: int
    CADENCE: str


class SessionTable(Protocol):
    """Session gating as integer intervals; built by the runner from the dataset calendar."""

    def in_session(self, ts_ns: int) -> bool: ...
    def session_close(self, ts_ns: int) -> Optional[int]: ...


Predicate = Callable[[EpochView], Any]

__all__ = ["NS", "REQUIRED", "BarView", "EmittedEvent", "EpochView", "TrackerBinding", "BindingMeta",
           "SessionTable", "Predicate"]
