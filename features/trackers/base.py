"""Base class for every platform-v2 tracker binding.

Lives apart from ``features/trackers/host_bindings.py`` (the registration module) on purpose: a new
binding module imports ``BaseBinding`` from here, and the registration module resolves seeded
bindings lazily from ``research_workflow/capabilities_index.yaml``, so nothing imports the other
at module load and no hand edit of the registration module is needed to add a tracker
(chore/capability-modularity, 2026-09-08).
"""
from __future__ import annotations

from typing import Any, List, Mapping

from research_workflow.host.interfaces import REQUIRED, BarView, EmittedEvent, EpochView

class BaseBinding:
    CAPABILITY = ""
    PARAMS: Mapping[str, Any] = {}
    INPUTS: Mapping[str, str] = {}
    FIELDS: tuple = ()
    EPOCH_FIELDS: tuple = ()
    EVENTS: tuple = ()
    SUBSCRIBES: tuple = ()
    WARMUP_BARS = 0
    CADENCE = "per_source_bar"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        self.params = dict(params)
        self.inputs = dict(inputs)
        self._events: List[EmittedEvent] = []
        for name, default in self.PARAMS.items():
            if name not in self.params:
                if default is REQUIRED:
                    raise ValueError(f"{self.CAPABILITY}: parameter {name!r} is required")
                self.params[name] = default

    def emit(self, name: str, payload: Mapping[str, Any]) -> None:
        self._events.append(EmittedEvent(name, payload))

    def drain_events(self) -> List[EmittedEvent]:
        out, self._events = self._events, []
        return out

    def on_bar(self, input_key: str, bar: BarView) -> None:  # pragma: no cover - overridden
        return None

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        return None

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        raise KeyError(name)

    def on_trigger_transition(self, state: str, kind: str, ts: int, epoch: EpochView) -> None:
        return None


# --------------------------------------------------------------------------- #
# tracker.regime.dual_ema
# --------------------------------------------------------------------------- #


__all__ = ["BaseBinding", "REQUIRED", "BarView", "EmittedEvent", "EpochView"]
