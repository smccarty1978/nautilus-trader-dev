"""Live, NT-independent causal replication of the LONG (prevailing-bearish)
established/RTH/valid-fill checkpoint funnel.

FORKED from `nt_reduced_f3_top25_population_parity_smoke/implementation/
candidate_tracker.py` (source SHA recorded in results/fork_provenance.json).
Forked rather than imported because that study is being actively modified by
concurrent work; this study must be reproducible against a pinned copy.

MIRROR CHANGES vs the short-side original -- everything else is verbatim,
including all four established-filter thresholds, the 5s grid, the 1800s
timeout, and the progress-window/120s-gap logic (whose per-1s-bar evaluation
and last_extreme_ts advancement were hard-won bug fixes upstream; both are
preserved exactly):

  1. a candidate stream opens on `new_direction == -1` (prevailing BEARISH),
     not `+1`;
  2. the prevailing regime's FAVORABLE excursion is downward:
         current_mfe = (flip_close - lowest_low)  / atr        [was highs-anchor]
         current_mae = (highest_high - flip_close) / atr
  3. current_pnl uses the prevailing direction -1:
         current_pnl = -1 * (price_at_T - flip_close) / atr

These are exactly the mirror rules proved in
`long_rth_mirrored_surface_top100_training/implementation/build_surface_long.py`
(`favorable = anchor - lows`), whose self-validation guard matched the atlas
`current_mfe` at 10,253,579 checkpoints with 0 failures.

As on the short side, `current_mfe`/`current_mae` describe the PREVAILING
regime's own extension (how stretched the bearish trend is), NOT the eventual
long entry's P&L direction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

NS = 1_000_000_000

REGIME_AGE_S_MIN = 120.0
RUNNING_MFE_ATR_MIN = 1.0
NEW_PROGRESS_WINDOWS_MIN = 2
RETAINED_MFE_RATIO_MIN = 0.5
PROGRESS_GAP_NS = 120 * NS
CANDIDATE_STEP_NS = 5 * NS
CANDIDATE_TIMEOUT_NS = 1800 * NS

PREVAILING_DIRECTION = -1   # bearish
ENTRY_DIRECTION = +1        # long, counter-regime


@dataclass
class RegimeCandidateStateLong:
    """One established-BEARISH (direction=-1) regime's causal candidate state."""
    flip_ts: int
    flip_close: float
    atr_val: float

    highest_high_since_flip: float = field(default=float("-inf"))
    lowest_low_since_flip: float = field(default=float("inf"))

    _progress_count: int = 0
    _progress_previous_extreme: float = field(default=float("-inf"))
    _progress_last_extreme_ts: Optional[int] = None

    closed: bool = False
    next_checkpoint_index: int = 0
    last_close: Optional[float] = None

    def __post_init__(self):
        if not (self.atr_val > 0 and math.isfinite(self.atr_val)):
            raise ValueError(f"atr_val must be finite and positive, got {self.atr_val}")

    def on_1s_bar(self, ts_ns: int, high: float, low: float) -> None:
        if self.closed:
            raise RuntimeError("on_1s_bar called after regime closed")
        self.highest_high_since_flip = max(self.highest_high_since_flip, high)
        self.lowest_low_since_flip = min(self.lowest_low_since_flip, low)
        current_mfe = self._current_mfe()
        if current_mfe > self._progress_previous_extreme + 1e-12:
            # last_extreme_ts advances on EVERY new extreme, not only ones that
            # satisfy the 120s gap (upstream bug fix, preserved verbatim).
            if (self._progress_last_extreme_ts is None
                    or ts_ns - self._progress_last_extreme_ts >= PROGRESS_GAP_NS):
                self._progress_count += 1
            self._progress_last_extreme_ts = ts_ns
            self._progress_previous_extreme = current_mfe

    def _current_mfe(self) -> float:
        """MIRROR: bearish-favorable excursion = price BELOW the flip anchor."""
        if self.lowest_low_since_flip == float("inf"):
            return 0.0
        return max(0.0, self.flip_close - self.lowest_low_since_flip) / self.atr_val

    def _current_mae(self) -> float:
        """MIRROR: bearish-adverse excursion = price ABOVE the flip anchor."""
        if self.highest_high_since_flip == float("-inf"):
            return 0.0
        return max(0.0, self.highest_high_since_flip - self.flip_close) / self.atr_val

    def pending_checkpoint_ts(self) -> int:
        return self.flip_ts + (self.next_checkpoint_index + 1) * CANDIDATE_STEP_NS

    def is_expired(self, ts_ns: int) -> bool:
        return ts_ns - self.flip_ts >= CANDIDATE_TIMEOUT_NS

    def evaluate_checkpoint(self, T: int, price_at_T: float) -> dict:
        if self.closed:
            raise RuntimeError("evaluate_checkpoint called after regime closed")
        regime_age_s = (T - self.flip_ts) / NS
        current_mfe = self._current_mfe()
        current_mae = self._current_mae()
        # MIRROR: prevailing direction is -1.
        current_pnl = PREVAILING_DIRECTION * (price_at_T - self.flip_close) / self.atr_val
        retained = (current_pnl / current_mfe) if current_mfe > 0 else float("nan")

        established_regime_gate = bool(
            regime_age_s >= REGIME_AGE_S_MIN
            and current_mfe >= RUNNING_MFE_ATR_MIN
            and self._progress_count >= NEW_PROGRESS_WINDOWS_MIN
            and (not math.isnan(retained)) and retained >= RETAINED_MFE_RATIO_MIN
        )
        result = {
            "checkpoint_index": self.next_checkpoint_index,
            "observation_time_ns": T,
            "regime_age_s": regime_age_s,
            "running_mfe_atr": current_mfe,
            "running_mae_atr": current_mae,
            "current_pnl_atr": current_pnl,
            "new_progress_windows": self._progress_count,
            "retained_mfe_ratio": retained,
            "established_regime_gate": established_regime_gate,
            # A live tracker cannot emit a checkpoint after its own regime has
            # closed, so the fill instant is structurally guaranteed to precede
            # the (later-discovered) regime end. True by construction.
            "valid_fill": True,
            "atr_val": self.atr_val,   # frozen at flip; never re-read live
        }
        self.next_checkpoint_index += 1
        return result


class CandidateTrackerLong:
    """Drives RegimeCandidateStateLong across the live regime stream, applies
    RTH + valid-fill gates, and emits EVERY candidate (with a specific
    suppression reason when not eligible) via `on_candidate`."""

    def __init__(self, on_candidate, is_rth_fn):
        self._on_candidate = on_candidate
        self._is_rth_fn = is_rth_fn
        self._active: Optional[RegimeCandidateStateLong] = None

    def __getstate__(self):
        state = self.__dict__.copy()
        state["_on_candidate"] = None
        state["_is_rth_fn"] = None
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def on_regime_flip(self, ts_ns: int, new_direction: int, flip_close: float,
                       atr_val: float) -> None:
        """Call on every 1m-confirmed regime transition."""
        if self._active is not None:
            self._active.closed = True
            self._active = None
        # MIRROR: open only on prevailing-BEARISH regimes.
        if new_direction == PREVAILING_DIRECTION:
            if atr_val is None or not (atr_val > 0):
                return
            self._active = RegimeCandidateStateLong(
                flip_ts=ts_ns, flip_close=flip_close, atr_val=atr_val)

    def on_1s_bar(self, ts_ns: int, high: float, low: float, close: float,
                  minute_of_day: int) -> None:
        """FIRST emit any 5s-grid checkpoints due at/before this bar, using
        state reflecting only bars STRICTLY BEFORE it (both the running
        MFE/MAE extremes and the `current_price` reference = `last_close`),
        THEN update with this bar. Ordering matters: getting it backwards leaks
        the checkpoint's own bar into its own MFE/current_price."""
        active = self._active
        if active is None or active.closed:
            return

        while (not active.closed and not active.is_expired(ts_ns)
               and active.pending_checkpoint_ts() <= ts_ns and active.last_close is not None):
            T = active.pending_checkpoint_ts()
            result = active.evaluate_checkpoint(T, price_at_T=active.last_close)
            key = (active.flip_ts, PREVAILING_DIRECTION, result["checkpoint_index"], T)

            if not result["established_regime_gate"]:
                self._emit(key, result, suppressed="established_regime_gate_fail")
                continue

            decision_rth = self._is_rth_fn(minute_of_day)
            result["fill_ts_ns"] = ts_ns
            result["decision_rth"] = decision_rth
            result["fill_rth"] = decision_rth  # fill occurs at ts_ns, same session bucket
            if not decision_rth:
                self._emit(key, result, suppressed="not_rth")
                continue

            self._emit(key, result, suppressed=None)

        if not active.closed:
            active.on_1s_bar(ts_ns, high, low)
            active.last_close = close

        if active.is_expired(ts_ns) and not active.closed:
            active.closed = True
            self._active = None

    def _emit(self, key, result, suppressed):
        self._on_candidate({
            "candidate_key": key,
            "regime_start_ns": key[0],
            "regime_direction": key[1],
            "entry_direction": ENTRY_DIRECTION,
            "checkpoint_index": key[2],
            **result,
            "final_candidate_eligible": suppressed is None,
            "rejection_reason": suppressed,
        })
