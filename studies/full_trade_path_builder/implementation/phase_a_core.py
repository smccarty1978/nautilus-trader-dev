"""Pure causal primitives for Phase A.

These objects contain no pandas logic.  The NT strategy owns event routing and
passes only completed bars/facts into these primitives.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

NS = 1_000_000_000
HORIZON_NS = 300 * NS


@dataclass(frozen=True)
class SourceProvenance:
    max_source_ts_event_1s: int
    max_source_ts_init_1s: int
    max_source_ts_event_1m: Optional[int]
    max_source_ts_init_1m: Optional[int]

    def assert_admissible(self, decision_ns: int) -> None:
        if self.max_source_ts_event_1s >= decision_ns:
            raise ValueError("1s ts_event must be strictly before decision")
        if self.max_source_ts_init_1s > decision_ns:
            raise ValueError("1s ts_init must be at or before decision")
        if self.max_source_ts_init_1m is not None and self.max_source_ts_init_1m >= decision_ns:
            raise ValueError("1m ts_init must be strictly before decision")


@dataclass(frozen=True)
class LabelResult:
    label_flip_le_300: Optional[int]
    censored: bool
    confirm_flip_ns: Optional[int]
    seconds_to_flip: Optional[float]


def label_checkpoint(
    decision_ns: int,
    bearish_confirm_flip_ns: Optional[int],
    observation_end_ns: int,
) -> LabelResult:
    """Apply the frozen `(T,T+300s]` target and right-censor contract."""
    flip = bearish_confirm_flip_ns
    if flip is not None and decision_ns < flip <= decision_ns + HORIZON_NS:
        return LabelResult(1, False, flip, (flip - decision_ns) / NS)
    if observation_end_ns >= decision_ns + HORIZON_NS:
        return LabelResult(0, False, flip, None if flip is None else (flip - decision_ns) / NS)
    return LabelResult(None, True, flip, None if flip is None else (flip - decision_ns) / NS)


def next_flip_after(decision_ns: int, flip_times: Iterable[int]) -> Optional[int]:
    """Return the first strictly future confirmed flip."""
    return next((int(t) for t in flip_times if int(t) > decision_ns), None)


def checkpoint_index(regime_start_ns: int, decision_ns: int) -> Optional[int]:
    """Return the frozen 0-based grid index, or None off-grid/outside timeout."""
    delta = decision_ns - regime_start_ns
    if delta < 5 * NS or delta >= 1800 * NS or delta % (5 * NS):
        return None
    return delta // (5 * NS) - 1


def should_dispatch(regime_start_ns: int, bar_ts_init: int) -> bool:
    """A checkpoint exists only on an exact 1s availability callback."""
    return checkpoint_index(regime_start_ns, bar_ts_init) is not None
