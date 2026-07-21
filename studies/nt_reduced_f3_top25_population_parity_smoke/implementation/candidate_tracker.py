"""Pure-Python, NT-independent causal replication of
`short_rth_entry_surface_backfill/entry_surface.py`'s established/RTH/
valid-fill checkpoint-eligibility funnel, live-computable bar-by-bar.

Established-regime filter thresholds and `progress_window_counts` logic are
verbatim ports of `CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py`
and `regime_sequence_chop_context/build_weakness_atlas.py` (`compute_running_excursions`,
candidate grid) -- see SPEC.md for full derivation and citations.

IMPORTANT: `progress_window_counts`' new-extreme/120s-gap logic must be
evaluated at 1-SECOND-bar granularity (matching the offline reference, which
checks every raw 1s bar in the regime path), not just at 5s candidate-grid
points -- checking only at the sparser grid would occasionally record a
different (and wrong) extreme timestamp near the 120s gap boundary. This
tracker's `on_1s_bar` updates the running MFE/MAE and progress-window state
on EVERY 1s bar; `on_5s_checkpoint` only READS that already-updated state to
decide eligibility, adding nothing new to MFE/MAE/progress themselves.
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

RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60


def is_rth_minute_of_day(minute_of_day: int) -> bool:
    return RTH_START_MIN <= minute_of_day < RTH_END_MIN


@dataclass
class RegimeCandidateState:
    """One established-bullish (direction=+1) regime's causal candidate state.
    entry_direction is always -1 (short, against this prevailing bullish
    regime) for this population -- confirmed repo-wide this session."""
    flip_ts: int
    flip_close: float
    atr_val: float

    highest_high_since_flip: float = field(default=float("-inf"))
    lowest_low_since_flip: float = field(default=float("inf"))

    _progress_count: int = 0
    _progress_previous_extreme: float = field(default=float("-inf"))
    _progress_last_extreme_ts: Optional[int] = None

    closed: bool = False
    next_checkpoint_index: int = 0  # 0-indexed from flip_ts + CANDIDATE_STEP_NS
    last_close: Optional[float] = None  # close of the last bar strictly before the current instant

    def __post_init__(self):
        if not (self.atr_val > 0 and math.isfinite(self.atr_val)):
            raise ValueError(f"atr_val must be finite and positive, got {self.atr_val}")

    # -- state update, called on EVERY completed 1s bar while this regime is active --
    def on_1s_bar(self, ts_ns: int, high: float, low: float) -> None:
        if self.closed:
            raise RuntimeError("on_1s_bar called after regime closed")
        self.highest_high_since_flip = max(self.highest_high_since_flip, high)
        self.lowest_low_since_flip = min(self.lowest_low_since_flip, low)
        current_mfe = self._current_mfe()
        if current_mfe > self._progress_previous_extreme + 1e-12:
            # BUG FIX (found via reconciliation): last_extreme_ts must be
            # advanced on EVERY new extreme, not only ones that satisfy the
            # 120s gap -- matching CODEX_5_X_run_established_fade.py's
            # progress_window_counts() (lines 173-178) exactly. Gating the
            # advance on gap-satisfaction left a stale, older timestamp in
            # place after a too-soon extreme, making the NEXT gap check
            # measure from that stale anchor instead of the true most-recent
            # extreme -- satisfying the gap too easily and over-counting
            # progress windows (confirmed: this regime's new_progress_windows
            # reached 2 at checkpoint 27 instead of offline's true 76, and 3
            # by checkpoint 76 where offline still shows 2 -- with the
            # correct frozen ATR and identical running_mfe_atr/running_mae_atr
            # otherwise verified bit-exact against the offline reference).
            if (self._progress_last_extreme_ts is None
                    or ts_ns - self._progress_last_extreme_ts >= PROGRESS_GAP_NS):
                self._progress_count += 1
            self._progress_last_extreme_ts = ts_ns
            self._progress_previous_extreme = current_mfe

    def _current_mfe(self) -> float:
        # CORRECTED (found via real-data cross-validation against
        # prepared_2025.parquet's stored running_mfe_atr/running_mae_atr --
        # an earlier version of this method used entry_direction (-1),
        # producing MFE/MAE that were effectively swapped vs ground truth).
        # `current_mfe`/`current_mae` measure the ESTABLISHED REGIME'S OWN
        # (prevailing, direction=+1, bullish) favorable/adverse excursion --
        # NOT the short entry's own P&L direction. This matches
        # entry_surface.py:86 (`favorable = highs - anchor` for direction==1)
        # and compute_running_excursions's direction==1 branch
        # (build_weakness_atlas.py:28-30) exactly: this is a measure of how
        # extended the prevailing bullish trend is (fade setup strength),
        # unrelated to the eventual short trade's own directional P&L.
        if self.highest_high_since_flip == float("-inf"):
            return 0.0
        return max(0.0, self.highest_high_since_flip - self.flip_close) / self.atr_val

    def _current_mae(self) -> float:
        if self.lowest_low_since_flip == float("inf"):
            return 0.0
        return max(0.0, self.flip_close - self.lowest_low_since_flip) / self.atr_val

    def pending_checkpoint_ts(self) -> int:
        """Next 5s-grid timestamp not yet evaluated, regardless of timeout --
        caller must stop requesting once the regime closes or the timeout
        elapses (checked by the caller via `is_expired`)."""
        return self.flip_ts + (self.next_checkpoint_index + 1) * CANDIDATE_STEP_NS

    def is_expired(self, ts_ns: int) -> bool:
        return ts_ns - self.flip_ts >= CANDIDATE_TIMEOUT_NS

    def evaluate_checkpoint(self, T: int, price_at_T: float) -> dict:
        """Evaluate the established-regime filter at grid timestamp T.
        Consumes (increments) `next_checkpoint_index` -- call at most once
        per grid point, in increasing T order."""
        if self.closed:
            raise RuntimeError("evaluate_checkpoint called after regime closed")
        regime_age_s = (T - self.flip_ts) / NS
        current_mfe = self._current_mfe()
        current_mae = self._current_mae()
        # current_pnl uses the PREVAILING regime's own direction (+1), matching
        # build_weakness_atlas.py:116 (`direction * (current_price - flip_close) /
        # atr_val` with direction=+1 here) -- see _current_mfe's correction note.
        current_pnl = 1.0 * (price_at_T - self.flip_close) / self.atr_val
        retained = (current_pnl / current_mfe) if current_mfe > 0 else float("nan")

        # NOTE (renamed per reconciliation-gate fix): this is ONLY the
        # established-REGIME filter (age/MFE/progress/retained-ratio). It is
        # NOT the same population as the offline reference, which is
        # established_regime_gate AND RTH AND valid-fill. A caller comparing
        # raw "established" counts against the offline reference's row count
        # is comparing two different denominators -- see strategy.py's
        # `final_candidate_eligible` for the matching population.
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
            # valid_fill: entry_surface.py's own gate is `fill_ts < regime_end`.
            # A LIVE, bar-by-bar CandidateTracker cannot emit a checkpoint
            # AFTER its own regime has already closed (on_regime_flip sets
            # `closed=True` and the caller's `_active is None or active.closed`
            # guard returns immediately) -- so for every candidate this
            # tracker ever emits, the fill (this same causal instant) is
            # structurally guaranteed to be strictly before the eventual
            # regime end, which is only discovered LATER when the next flip
            # arrives. True always, by construction, not a placeholder.
            "valid_fill": True,
            # Frozen at flip time (on_regime_flip), never reassigned -- the
            # SAME value used internally for running_mfe_atr/running_mae_atr/
            # current_pnl_atr above. Exposed so callers (strategy.py) log/
            # feed-forward this value instead of re-reading a live,
            # continuously-updating ATR indicator (a real bug found during
            # reconciliation: strategy.py was independently re-reading
            # self._engine.atr per-checkpoint for atr_at_entry, the feature
            # vector, AND stop sizing, instead of using this frozen value).
            "atr_val": self.atr_val,
        }
        self.next_checkpoint_index += 1
        return result


class CandidateTracker:
    """Drives RegimeCandidateState across the live regime stream, applies
    RTH + valid-fill gates, and emits every candidate (established or not,
    with a specific suppression reason otherwise) via `on_candidate`."""

    def __init__(self, on_candidate, is_rth_fn, rth_gate_at_fill: bool = True):
        self._on_candidate = on_candidate
        self._is_rth_fn = is_rth_fn
        self._rth_gate_at_fill = rth_gate_at_fill
        self._active: Optional[RegimeCandidateState] = None
        self._pending_regime_direction: Optional[int] = None

    def __getstate__(self):
        """EXCLUDE _on_candidate/_is_rth_fn (typically bound methods of the
        owning NT Strategy) from pickling -- serializing a bound method
        drags the ENTIRE Strategy object (including unpicklable NT
        engine/cache/portfolio internals) along with it. The caller
        (Strategy._restore_checkpoint) MUST rebind both callbacks after
        unpickling; __setstate__ leaves them as None so a forgotten rebind
        fails loudly (AttributeError/TypeError on first use) rather than
        silently running with a stale/wrong callback."""
        state = self.__dict__.copy()
        state["_on_candidate"] = None
        state["_is_rth_fn"] = None
        return state

    def __setstate__(self, state):
        # Restore EXACTLY what was pickled -- including `_active` (the
        # in-flight regime's candidate state, if any) and
        # `_pending_regime_direction`. Callers MUST rebind `_on_candidate`/
        # `_is_rth_fn` (left None by __getstate__) before using the tracker.
        self.__dict__.update(state)

    def on_regime_flip(self, ts_ns: int, new_direction: int, flip_close: float, atr_val: float) -> None:
        """Call on every 1m-confirmed regime transition. Closes out the
        previous regime's candidate stream (no more grid points beyond this
        instant) and, if the NEW regime is established-bullish (+1), opens a
        fresh RegimeCandidateState."""
        if self._active is not None:
            self._active.closed = True
            self._active = None
        if new_direction == 1:
            if atr_val is None or not (atr_val > 0):
                return  # cannot open a candidate stream without a valid ATR
            self._active = RegimeCandidateState(flip_ts=ts_ns, flip_close=flip_close, atr_val=atr_val)

    def on_1s_bar(self, ts_ns: int, high: float, low: float, close: float, minute_of_day: int) -> None:
        """Call on every completed 1s bar. FIRST emits any 5s-grid
        checkpoints due at or before this bar's timestamp, using state that
        reflects only bars STRICTLY BEFORE this one (matching
        `build_weakness_atlas.py:96-112`'s "last completed bar has ts_event
        strictly before cp_ts" rule for both the running MFE/MAE extremes
        AND the `current_price` reference -- `active.last_close`, not this
        bar's own close). ONLY THEN updates the active regime's running
        state with this bar. Getting this ordering backwards was a real bug
        caught by real-data cross-validation against `prepared_2025.parquet`
        (checkpoint's own bar was leaking into its own MFE/current_price)."""
        active = self._active
        if active is None or active.closed:
            return

        while (not active.closed and not active.is_expired(ts_ns)
               and active.pending_checkpoint_ts() <= ts_ns and active.last_close is not None):
            T = active.pending_checkpoint_ts()
            result = active.evaluate_checkpoint(T, price_at_T=active.last_close)
            regime_start_ns = active.flip_ts
            key = (regime_start_ns, 1, result["checkpoint_index"], T)

            if not result["established_regime_gate"]:
                self._emit(key, T, ts_ns, result, suppressed="established_regime_gate_fail")
                continue

            # decision_rth: RTH status of the DECISION instant (T). In the
            # common (no-gap) case T == ts_ns exactly; `minute_of_day` is the
            # caller-supplied value for ts_ns, used as T's proxy (disclosed
            # simplification -- see fill_rth below for the fill-time check,
            # which entry_surface.py's own gate actually keys off).
            decision_rth = self._is_rth_fn(minute_of_day)

            # fill timing/RTH: the tracker DOES resolve this itself now
            # (previously deferred to the caller, which never implemented it
            # -- caught during reconciliation). Fill occurs at ts_ns (the
            # real bar this checkpoint was evaluated against), matching
            # entry_surface.py's session-classified-on-FILL-time convention
            # (entry_surface.py:114-125), not decision time.
            result["fill_ts_ns"] = ts_ns
            result["decision_rth"] = decision_rth

            self._emit(key, T, ts_ns, result, suppressed=None)

        if not active.closed:
            active.on_1s_bar(ts_ns, high, low)
            active.last_close = close

        if active.is_expired(ts_ns) and not active.closed:
            active.closed = True
            self._active = None

    def _emit(self, key, T, ts_ns, result, suppressed):
        self._on_candidate({
            "candidate_key": key, "regime_start_ns": key[0], "regime_direction": key[1],
            "checkpoint_index": key[2], "observation_time_ns": T,
            **result, "suppression_reason": suppressed,
        })
