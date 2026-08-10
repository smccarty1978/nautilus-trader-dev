"""Exact-availability checkpoint dispatcher for Phase A."""
from __future__ import annotations

from typing import Callable, Optional

from studies.nt_reduced_f3_top25_population_parity_smoke.implementation.candidate_tracker import (
    CANDIDATE_TIMEOUT_NS,
    RegimeCandidateState,
)


class CausalBullishCandidateTracker:
    """Tracks established bullish regimes without retrospective gap catch-up."""

    def __init__(
        self,
        on_checkpoint: Callable[[dict], None],
        on_missing: Callable[[dict], None],
        is_rth_decision: Callable[[int], bool],
    ):
        self._on_checkpoint = on_checkpoint
        self._on_missing = on_missing
        self._is_rth_decision = is_rth_decision
        self._active: Optional[RegimeCandidateState] = None

    def on_regime_flip(
        self, confirm_flip_ns: int, new_direction: int, flip_close: float, regime_atr: float
    ) -> None:
        if self._active is not None:
            self._active.closed = True
        self._active = None
        if new_direction == 1 and regime_atr is not None and regime_atr > 0:
            self._active = RegimeCandidateState(
                flip_ts=confirm_flip_ns, flip_close=flip_close, atr_val=regime_atr
            )

    def on_completed_1s(
        self, ts_event: int, ts_init: int, high: float, low: float, close: float
    ) -> None:
        active = self._active
        if active is None or active.closed:
            return
        if ts_event >= ts_init:
            raise ValueError("completed 1s bar must have ts_event < ts_init")

        # The bar ending at availability T is admissible at T.
        active.on_1s_bar(ts_event, high, low)
        active.last_close = close

        while active.pending_checkpoint_ts() < ts_init:
            missing_t = active.pending_checkpoint_ts()
            if missing_t - active.flip_ts >= CANDIDATE_TIMEOUT_NS:
                active.closed = True
                self._active = None
                return
            self._on_missing({
                "regime_start_ns": active.flip_ts,
                "regime_direction": 1,
                "checkpoint_index": active.next_checkpoint_index,
                "checkpoint_decision_ns": missing_t,
                "suppression_reason": "missing_dispatch_bar",
            })
            active.next_checkpoint_index += 1

        if active.pending_checkpoint_ts() == ts_init:
            if ts_init - active.flip_ts >= CANDIDATE_TIMEOUT_NS:
                active.closed = True
                self._active = None
                return
            result = active.evaluate_checkpoint(ts_init, price_at_T=close)
            result.update({
                "regime_start_ns": active.flip_ts,
                "regime_direction": 1,
                "checkpoint_decision_ns": ts_init,
                "checkpoint_availability_ns": ts_init,
                "dispatch_bar_ts_event": ts_event,
                "dispatch_bar_ts_init": ts_init,
                "decision_rth": bool(self._is_rth_decision(ts_init)),
            })
            self._on_checkpoint(result)

        if ts_init - active.flip_ts >= CANDIDATE_TIMEOUT_NS:
            active.closed = True
            self._active = None
