"""Collector v2 — leak-safe, checkpoint-native, within-regime collector.

Spec: collector_v2_spec.md
Contract: models/ml_5m_flip/feature_contract_v2.json

Architecture (this skeleton):
  - Strategy subclass that subscribes to 1s + 1m bars.
  - Aggregates 30s (from 1s) and 5m (from 1m) bars internally.
  - Maintains regime state at 1m / 30s / 5m, ATR(14), SMA(20,50),
    EMA(3,9), session high/low, rolling 1s/1m/30s buffers.
  - On confirmed flip (regime flip + bar+1 HH/LL): creates EventState,
    snaps root features (§6.1–§6.3, §6.6 at signal).
  - For each active event: snaps checkpoint features every 30s boundary
    until termination (opposing 1m regime flip OR max_checkpoint_s).
  - Forward-path tracker (separate code path) computes labels
    (§7.1–§7.4) for each checkpoint's hypothetical execution.
  - On event termination: emits one row per checkpoint to
    feature_snapshots + outcome_labels parquet tables.

Skeleton policy:
  - FRAMEWORK is complete: event lifecycle, aggregation, termination,
    output writing, QA logging.
  - FEATURE FORMULAS are stubbed with TODO markers — each will be
    filled out in a subsequent work order driven by
    feature_contract_v2.json. This file is the scaffold.
  - LABEL computation is stubbed for the 4 families in phase 1 scope
    (MFE/MAE grid, bracket races, regime exit, clean-path) with TODOs.
"""

import os
import sys
import json
from collections import deque
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd
import pytz

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import AverageTrueRange
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

CT = pytz.timezone("America/Chicago")
NQ_MULT = 20.0
COMMISSION = 5.0

# Checkpoint grid: every 30s from T=0 through max_checkpoint_s (default 1800)
# Populated per-event based on config.max_checkpoint_s

# Bracket set for label computation (§7.2)
BRACKETS = [
    (1.0, 1.0, "pt100_before_sl100"),
    (1.5, 1.0, "pt150_before_sl100"),
    (2.0, 1.0, "pt200_before_sl100"),
    (3.0, 1.5, "pt300_before_sl150"),
]

# Forward MFE/MAE windows (§7.1)
FWD_WINDOWS_S = [30, 60, 120, 180, 300, 600]

# Clean-path label horizons (§7.4)
CLEAN_PATH_HORIZONS = [120, 180, 300, 600]


# ==================================================================
# Lightweight indicators (1m-level uses NT's AverageTrueRange;
# 30s/5m-level uses these local implementations for the aggregated
# timeframes since NT doesn't expose a "custom" aggregation cleanly)
# ==================================================================

class LocalEMA:
    """Exponential moving average on raw scalar input."""

    __slots__ = ("period", "alpha", "value", "count", "initialized")

    def __init__(self, period: int):
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value = 0.0
        self.count = 0
        self.initialized = False

    def update(self, v: float) -> None:
        self.count += 1
        if self.count == 1:
            self.value = v
        else:
            self.value = self.alpha * v + (1 - self.alpha) * self.value
        if self.count >= self.period:
            self.initialized = True


class LocalSMA:
    """Simple moving average on raw scalar input, backed by a deque."""

    __slots__ = ("period", "_buf")

    def __init__(self, period: int):
        self.period = period
        self._buf: deque = deque(maxlen=period)

    @property
    def initialized(self) -> bool:
        return len(self._buf) >= self.period

    @property
    def value(self) -> float:
        return sum(self._buf) / len(self._buf) if self._buf else 0.0

    def update(self, v: float) -> None:
        self._buf.append(v)

    def history_value(self, bars_ago: int) -> Optional[float]:
        """Return SMA value as it was `bars_ago` bars ago.

        NOTE: this uses the CURRENT buffer contents; for proper lookback
        we maintain a parallel history deque in the parent collector.
        """
        if bars_ago >= len(self._buf):
            return None
        # current avg is sum(last N) / N; we can't reconstruct prior
        # averages from the current deque alone — parent must track
        # snapshots. This is a placeholder.
        raise NotImplementedError(
            "Use parent collector's _prev_sma_* deques instead.")


class RegimeState:
    """EMA3/9 sticky regime on H/L/C for one timeframe.

    Regime is +1 when close > both emaH_3 AND emaH_9.
    Regime is -1 when close < both emaL_3 AND emaL_9.
    Else: sticky (unchanged from prior).
    """

    __slots__ = (
        "emaH_3", "emaH_9", "emaL_3", "emaL_9", "ema3", "ema9",
        "regime", "bars_in_regime", "completed_bars", "flip_history",
    )

    def __init__(self):
        self.emaH_3 = LocalEMA(3)
        self.emaH_9 = LocalEMA(9)
        self.emaL_3 = LocalEMA(3)
        self.emaL_9 = LocalEMA(9)
        self.ema3 = LocalEMA(3)
        self.ema9 = LocalEMA(9)
        self.regime = 0
        self.bars_in_regime = 0
        self.completed_bars = 0
        # (completed_bars_index, new_regime) pairs, recent window
        self.flip_history: deque = deque(maxlen=100)

    def update(self, h: float, l: float, c: float) -> int:
        self.emaH_3.update(h)
        self.emaH_9.update(h)
        self.emaL_3.update(l)
        self.emaL_9.update(l)
        self.ema3.update(c)
        self.ema9.update(c)
        self.completed_bars += 1

        if not (self.emaH_3.initialized and self.emaH_9.initialized
                and self.emaL_3.initialized and self.emaL_9.initialized):
            return self.regime

        new_r = self.regime
        if c > self.emaH_3.value and c > self.emaH_9.value:
            new_r = 1
        elif c < self.emaL_3.value and c < self.emaL_9.value:
            new_r = -1

        if new_r != self.regime:
            self.regime = new_r
            self.bars_in_regime = 1
            self.flip_history.append((self.completed_bars, new_r))
        else:
            self.bars_in_regime += 1
        return self.regime


# ==================================================================
# Bar records
# ==================================================================

class Bar1m:
    __slots__ = (
        "ts_event", "o", "h", "l", "c", "v",
        "up_vol", "down_vol",
    )

    def __init__(self, ts_event, o, h, l, c, v, up_vol, down_vol):
        self.ts_event = ts_event
        self.o, self.h, self.l, self.c, self.v = o, h, l, c, v
        self.up_vol = up_vol
        self.down_vol = down_vol


class Bar30s:
    __slots__ = ("ts_event", "o", "h", "l", "c", "v")

    def __init__(self, ts_event, o, h, l, c, v):
        self.ts_event = ts_event
        self.o, self.h, self.l, self.c, self.v = o, h, l, c, v


# ==================================================================
# Event + checkpoint state
# ==================================================================

class CheckpointFeatures:
    """Container for checkpoint-dynamic feature values + a few
    checkpoint-tracking flags. One of these per (event, T)."""

    def __init__(self, T: int):
        self.T = T
        self.observation_time: Optional[int] = None  # ns
        self.fill_time: Optional[int] = None  # ns
        self.fill_price: Optional[float] = None  # execution_price
        self.alive_at_T: bool = False
        self.dead_before_T: bool = False
        self.fillable_at_T: bool = False

        # Checkpoint-dynamic feature values (populated by
        # _snap_checkpoint). Dict for flexibility during development;
        # will be converted to fixed schema at emit time.
        self.features: dict = {}


class EventState:
    """All per-event state. Created on confirmed flip+HH/LL, destroyed
    when terminated + emitted."""

    def __init__(self, event_id: int, signal_time_ns: int,
                  signal_direction: int, flip_bar: Bar1m,
                  bar1: Bar1m, atr_at_signal: float,
                  max_checkpoint_s: int):
        self.event_id = event_id
        self.signal_time = signal_time_ns
        self.signal_direction = signal_direction
        self.flip_bar = flip_bar
        self.bar1 = bar1
        self.atr_at_signal = atr_at_signal
        self.max_checkpoint_s = max_checkpoint_s

        # Regime-5m state captured at signal time (pre-bar+1 update per
        # §3.5 snap-call-order semantics — populated by caller)
        self.regime_5m_at_signal: int = 0

        # Root features snapped at signal_time (immutable once set)
        self.root_features: dict = {}

        # Per-checkpoint features
        self.checkpoints: dict[int, CheckpointFeatures] = {}

        # Per-checkpoint forward-path trackers (for labels)
        self.forward_trackers: dict[int, "ForwardPathTracker"] = {}

        # Termination state
        self.regime_exit_time: Optional[int] = None
        self.regime_exit_price: Optional[float] = None
        self.regime_exit_reason: Optional[str] = None  # per §7.3 enum
        self.terminated: bool = False

        # Post-signal tracking buffers (used for §6.5)
        self.bars_since_signal_1m: list[Bar1m] = []
        self.continuation_count: int = 0
        self.consec_continuation: int = 0
        self.bars_since_continuation: int = 0

        # Per-event progress/pullback tracking (1s granularity)
        self.max_progress_atr: float = 0.0
        self.max_pullback_atr: float = 0.0
        self.max_progress_price: Optional[float] = None
        self.t_peak_ns: Optional[int] = None
        self.min_fav_price_since_peak: Optional[float] = None


class ForwardPathTracker:
    """Per-checkpoint forward-path tracker (labels).

    Tracks at 1s bar granularity from fill_time forward. Records:
      - peak MFE / MAE over each window in FWD_WINDOWS_S
      - bracket race outcomes (first of PT/SL to hit)
      - terminates with regime_exit info when event ends

    Snap-time invariant: this tracker is UPDATED on each 1s bar; the
    feature-snapshot table NEVER reads from it. Labels are emitted
    only after event termination (§7).
    """

    def __init__(self, fill_time_ns: int, fill_price: float,
                 direction: int, atr_at_signal: float,
                 max_lookahead_s: int = 1800):
        self.fill_time = fill_time_ns
        self.fill_price = fill_price
        self.direction = direction
        self.atr = max(atr_at_signal, 1e-9)
        # Hard cap on tracker lookahead (relative to fill_time) —
        # guards data-gap scenarios (e.g., exchange halt mid-event).
        # Updates past this cutoff are ignored so bracket resolution
        # can't extend implausibly far past fill_time.
        self.max_lookahead_s = max_lookahead_s

        # Peak MFE/MAE in each window (populated as windows close)
        self.peak_mfe_by_window: dict[int, float] = {
            w: 0.0 for w in FWD_WINDOWS_S}
        self.peak_mae_by_window: dict[int, float] = {
            w: 0.0 for w in FWD_WINDOWS_S}
        self.window_closed_censored: dict[int, bool] = {
            w: False for w in FWD_WINDOWS_S}

        # Running peaks used during tracking
        self._running_peak_mfe = 0.0
        self._running_peak_mae = 0.0

        # Bracket outcomes: 1=PT first, 0=SL first, None=neither
        self.bracket_outcomes: dict[str, Optional[int]] = {
            name: None for _, _, name in BRACKETS}
        self.bracket_resolution_time_s: dict[str, Optional[float]] = {
            name: None for _, _, name in BRACKETS}
        self.bracket_resolution_price: dict[str, Optional[float]] = {
            name: None for _, _, name in BRACKETS}

    def update(self, h: float, l: float, ts_event_ns: int) -> None:
        """Called on every 1s bar with ts_event >= fill_time."""
        elapsed_s = (ts_event_ns - self.fill_time) / 1_000_000_000.0
        if elapsed_s > self.max_lookahead_s:
            return  # past lookahead cap — don't resolve brackets here
        d = self.direction
        ep = self.fill_price
        atr = self.atr
        if d == 1:
            bar_mfe_atr = max(0.0, (h - ep) / atr)
            bar_mae_atr = max(0.0, (ep - l) / atr)
        else:
            bar_mfe_atr = max(0.0, (ep - l) / atr)
            bar_mae_atr = max(0.0, (h - ep) / atr)

        # Snapshot running peaks BEFORE updating for bracket-crossing
        # detection on this bar (§7.2).
        prev_running_mfe = self._running_peak_mfe
        prev_running_mae = self._running_peak_mae

        if bar_mfe_atr > self._running_peak_mfe:
            self._running_peak_mfe = bar_mfe_atr
        if bar_mae_atr > self._running_peak_mae:
            self._running_peak_mae = bar_mae_atr

        # Update per-window peaks for windows still in their observation
        # phase (elapsed_s ≤ w). Beyond that, the window is closed and
        # its peak stays at the last recorded value.
        for w in FWD_WINDOWS_S:
            if elapsed_s <= w:
                self.peak_mfe_by_window[w] = self._running_peak_mfe
                self.peak_mae_by_window[w] = self._running_peak_mae

        # Bracket race resolution (§7.2). For each unresolved bracket,
        # check whether PT and/or SL were crossed FOR THE FIRST TIME on
        # this bar (i.e., prev_running < threshold ≤ current_running).
        # If both crossed on the same bar, apply "more-decisive crossing"
        # tie rule using intra-bar peak values.
        for pt_R, sl_R, name in BRACKETS:
            if self.bracket_outcomes[name] is not None:
                continue  # already resolved
            pt_now = (self._running_peak_mfe >= pt_R
                       and prev_running_mfe < pt_R)
            sl_now = (self._running_peak_mae >= sl_R
                       and prev_running_mae < sl_R)
            if not (pt_now or sl_now):
                continue

            if pt_now and sl_now:
                # Same-bar tie — "more-decisive crossing" (§7.2)
                pt_factor = bar_mfe_atr / pt_R
                sl_factor = bar_mae_atr / sl_R
                outcome = 1 if pt_factor > sl_factor else 0
            elif pt_now:
                outcome = 1
            else:
                outcome = 0

            self.bracket_outcomes[name] = outcome
            self.bracket_resolution_time_s[name] = elapsed_s
            # Resolution price = PT or SL level clipped to bar range.
            if outcome == 1:
                level = ep + d * pt_R * atr
            else:
                level = ep - d * sl_R * atr
            self.bracket_resolution_price[name] = (
                max(l, min(h, level)))

    def on_termination_censor(self, elapsed_s: float) -> None:
        """Called when the event terminates before all windows have
        closed. Marks windows beyond elapsed_s as censored."""
        for w in FWD_WINDOWS_S:
            if elapsed_s < w:
                self.window_closed_censored[w] = True


# ==================================================================
# Config
# ==================================================================

class CollectorV2Config(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    warmup_1m_bars: int = 150
    max_checkpoint_s: int = 1800
    max_fill_slippage_s: int = 60  # reject fills whose 1s bar arrives
                                    # >N s after intended fill_time
                                    # (guards against exchange-halt gaps)
    rth_only_filter: bool = False  # emit ETH events too; downstream filters
    features_output: str = "v2_feature_snapshots.parquet"
    labels_output: str = "v2_outcome_labels.parquet"
    events_summary_output: str = "v2_event_summary.parquet"
    qa_log_output: str = "v2_collection_qa.log"


# ==================================================================
# Main collector
# ==================================================================

class CollectorV2(Strategy):
    """v2 collector skeleton — feature/label emission framework.

    Feature math is stubbed for subsequent work orders; lifecycle and
    aggregation are fully functional.
    """

    def __init__(self, config: CollectorV2Config):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        # 1m indicators
        self.atr_14 = AverageTrueRange(14)
        self.sma20_1m = LocalSMA(20)
        self.sma50_1m = LocalSMA(50)

        # History deques for slope computations (parallel to SMA/EMA
        # updates so history_value() works properly)
        self._prev_sma20 = deque(maxlen=6)   # for 5-bar slope
        self._prev_sma50 = deque(maxlen=11)  # for 10-bar slope
        self._prev_ema3_1m = deque(maxlen=6)

        # 1m regime
        self.regime_1m = RegimeState()

        # 30s aggregation buffers + regime
        self._1s_for_30s: list[tuple] = []
        self.regime_30s = RegimeState()
        self.sma20_30s = LocalSMA(20)
        self._recent_30s: deque = deque(maxlen=30)

        # 5m aggregation buffers + regime
        self._1m_for_5m: list[Bar1m] = []
        self.regime_5m = RegimeState()
        self.sma20_5m = LocalSMA(20)
        self._recent_5m: deque = deque(maxlen=20)

        # EMA3 history for slope computation (30s, 5m)
        self._prev_ema3_30s: deque = deque(maxlen=6)
        self._prev_ema3_5m: deque = deque(maxlen=6)

        # 1s bar buffer (for micro features at checkpoint time)
        self._recent_1s: deque = deque(maxlen=180)

        # 1m bar buffer (for pre-signal context + continuation)
        self._recent_1m: deque = deque(maxlen=70)
        self._1m_count = 0

        # Per-1m volume direction accumulator
        self._current_1m_minute: Optional[int] = None
        self._current_1m_up_vol = 0.0
        self._current_1m_down_vol = 0.0

        # Session tracking
        self._session_start_key: Optional[str] = None
        self._session_high: float = -1e18
        self._session_low: float = 1e18
        self._session_bar_count: int = 0  # bars since session start

        # Warmup tracking
        self._warmup_complete = False
        self._events_skipped_warmup = 0

        # 1m flip pending state (awaiting bar+1 HH/LL)
        self._flip_pending: Optional[dict] = None

        # Prior-regime MFE tracking (for prior_regime_mfe_atr, §15.6)
        # We track MFE of the CURRENT confirmed regime as it evolves.
        # When a new flip fires, the current regime becomes "prior" and
        # its MFE is stashed.
        self._curr_regime_direction: int = 0
        self._curr_regime_bar1_close: Optional[float] = None
        self._curr_regime_peak_fav: Optional[float] = None
        self._curr_regime_start_bar: int = 0
        self._prior_regime_mfe_pts: Optional[float] = None

        # Completed regime durations (bars) — last 10, for
        # avg_regime_duration_last_5
        self._completed_regime_durations: deque = deque(maxlen=10)

        # Active events
        self._active_events: list[EventState] = []
        self._event_counter: int = 0

        # Output accumulators
        self._feature_records: list[dict] = []
        self._label_records: list[dict] = []
        self._event_summary_records: list[dict] = []

        # Diagnostics
        self._diag = {
            "flips": 0,
            "confirmed": 0,
            "skipped_no_hhll": 0,
            "events_skipped_warmup": 0,
            "events_terminated_regime_flip": 0,
            "events_terminated_max_horizon": 0,
            "events_terminated_data_end": 0,
            "checkpoints_snapped": 0,
            "fills_executed": 0,
            "fills_skipped_unfillable": 0,
            "fills_skipped_slippage_cap": 0,
            "fills_skipped_past_horizon": 0,
        }

    # --------------------------------------------------------------
    # NT lifecycle
    # --------------------------------------------------------------
    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self._bt_1m = BarType.from_str(self._cfg.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)

    def on_bar(self, bar: Bar):
        # §3.5: 1s processes before 1m at shared ts_init; NT respects
        # add-order for same ts_init, and we subscribed 1s first.
        if bar.bar_type == self._bt_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._on_1m(bar)

    def on_stop(self):
        # Any still-active events are terminated as data_end
        for ev in self._active_events:
            self._terminate_event(
                ev, reason="data_end",
                exit_time=ev.signal_time + ev.max_checkpoint_s * 1_000_000_000,
                exit_price=self._current_1s_close())
        self._active_events = []

        # Write outputs
        self._write_outputs()

    # --------------------------------------------------------------
    # 1s bar handling
    # --------------------------------------------------------------
    def _on_1s(self, bar: Bar):
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume) if hasattr(bar, "volume") else 0.0

        # Session high/low update (before any other processing)
        self._update_session(ts, h, l)

        # 1s bar buffer (for micro features)
        self._recent_1s.append((ts, o, h, l, c, v))

        # 1m volume direction accumulator
        minute_floor = (ts // 60_000_000_000) * 60_000_000_000
        if self._current_1m_minute != minute_floor:
            self._current_1m_minute = minute_floor
            self._current_1m_up_vol = 0.0
            self._current_1m_down_vol = 0.0
        if c > o:
            self._current_1m_up_vol += v
        elif c < o:
            self._current_1m_down_vol += v

        # Resolve fillability + instantiate ForwardPathTrackers for any
        # checkpoint whose fill_time == current bar ts_event (§5.5, §7.1).
        # Must run BEFORE the tracker-update loop so this bar's h/l/ts
        # are seen by the freshly-created tracker.
        self._try_fill_pending_checkpoints(ts, o)

        # Update forward trackers for all active events whose fill_time
        # has passed. (Labels are tracked on every 1s bar per §5.5.)
        for ev in self._active_events:
            for tracker in ev.forward_trackers.values():
                if tracker is not None and ts >= tracker.fill_time:
                    tracker.update(h, l, ts)

        # 30s aggregation: when a 1s bar CLOSES a 30s window, emit.
        # Per §5.5: check if ts_event is a 30s boundary — if so, the
        # _previous_ 30s window (covering [ts - 30s, ts)) closes here.
        # Implementation uses a buffer-and-emit pattern.
        if (ts % 30_000_000_000) == 0 and len(self._1s_for_30s) > 0:
            self._emit_30s_bar(ts)

        self._1s_for_30s.append((ts, o, h, l, c, v))

        # Update post-signal progress for active events
        for ev in self._active_events:
            if ts >= ev.signal_time:
                self._update_post_signal_state(ev, h, l, c, ts)

    def _emit_30s_bar(self, close_ts: int):
        """Aggregate buffered 1s bars into a 30s bar that just closed.
        Update 30s regime + sma20_30s. Fire checkpoint snaps for any
        active event whose observation_time == close_ts.
        """
        bars = self._1s_for_30s
        if not bars:
            return
        agg_o = bars[0][1]
        agg_h = max(b[2] for b in bars)
        agg_l = min(b[3] for b in bars)
        agg_c = bars[-1][4]
        agg_v = sum(b[5] for b in bars)
        # 30s bar's open time = close_ts - 30s
        agg_ts = close_ts - 30_000_000_000
        rec = Bar30s(agg_ts, agg_o, agg_h, agg_l, agg_c, agg_v)
        self._recent_30s.append(rec)

        # Update 30s regime and sma20_30s per §5.5
        self.regime_30s.update(agg_h, agg_l, agg_c)
        self.sma20_30s.update(agg_c)
        if self.regime_30s.ema3.initialized:
            self._prev_ema3_30s.append(self.regime_30s.ema3.value)

        # Clear buffer
        self._1s_for_30s = []

        # Fire checkpoint snaps for events whose observation_time
        # matches this close
        for ev in self._active_events:
            T = int((close_ts - ev.signal_time) / 1_000_000_000)
            if T < 0 or T > ev.max_checkpoint_s:
                continue
            if T % 30 != 0:
                continue  # not a valid checkpoint
            if T in ev.checkpoints:
                continue  # already snapped
            self._snap_checkpoint(ev, T, close_ts)

    # --------------------------------------------------------------
    # 1m bar handling
    # --------------------------------------------------------------
    def _on_1m(self, bar: Bar):
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume) if hasattr(bar, "volume") else 0.0

        # ts_init_delta sanity check (per §3.5)
        expected = 60_000_000_000
        actual = bar.ts_init - bar.ts_event
        if actual != expected:
            raise RuntimeError(
                f"1m bar ts_init_delta={actual} (expected {expected}). "
                "Catalog not properly wrangled — halt collection.")

        rec = Bar1m(ts, o, h, l, c, v,
                     self._current_1m_up_vol, self._current_1m_down_vol)
        self._recent_1m.append(rec)
        self._1m_count += 1
        self._session_bar_count += 1

        # Update 1m indicators
        self.atr_14.update_raw(h, l, c)
        self.sma20_1m.update(c)
        self.sma50_1m.update(c)
        if self.sma20_1m.initialized:
            self._prev_sma20.append(self.sma20_1m.value)
        if self.sma50_1m.initialized:
            self._prev_sma50.append(self.sma50_1m.value)

        # Capture PRE-UPDATE regime_5m for §3.5 snap semantics:
        # T_000 snap reads regime_5m state AFTER the 30s update but
        # BEFORE this bar+1's _update_5m call. For root features
        # captured in _check_confirmation (same _on_1m), we take the
        # regime_5m state AFTER the 5m update — which reflects full
        # current indicator state.
        # Implementation: we do _update_5m AFTER flip/confirmation
        # handling, so root-feature snap sees 5m state BEFORE this
        # bar+1's potential 5m boundary update.
        prev_regime_1m = self.regime_1m.regime
        regime_5m_before_bar = self.regime_5m.regime

        new_r_1m = self.regime_1m.update(h, l, c)
        if self.regime_1m.ema3.initialized:
            self._prev_ema3_1m.append(self.regime_1m.ema3.value)

        # 5m aggregation (fires if this 1m bar closes a 5m window)
        self._update_5m(rec)

        # Warmup check
        if not self._warmup_complete:
            self._warmup_complete = self._check_warmup_done()

        # Flip detection + confirmation flow
        flip_occurred = (prev_regime_1m != 0 and new_r_1m != 0
                          and prev_regime_1m != new_r_1m)

        if flip_occurred:
            self._diag["flips"] += 1
            self._handle_new_flip(rec, new_r_1m,
                                    regime_5m_before_bar)
        elif self._flip_pending is not None:
            # Bar+1 of pending flip — check HH/LL confirmation
            self._check_confirmation(rec, regime_5m_before_bar)

        # Update active events: post-signal 1m tracking + termination
        self._update_active_events_on_1m(
            rec, prev_regime_1m, new_r_1m, flip_occurred)

    def _update_5m(self, rec: Bar1m):
        """Aggregate 5 1m bars into a 5m bar when minute_of_hour % 5 == 4."""
        self._1m_for_5m.append(rec)
        minute_of_hour = (rec.ts_event // 60_000_000_000) % 60
        if minute_of_hour % 5 == 4 and len(self._1m_for_5m) >= 5:
            sub = self._1m_for_5m[-5:]
            agg_h = max(b.h for b in sub)
            agg_l = min(b.l for b in sub)
            agg_c = sub[-1].c
            agg_v = sum(b.v for b in sub)
            self.regime_5m.update(agg_h, agg_l, agg_c)
            self.sma20_5m.update(agg_c)
            if self.regime_5m.ema3.initialized:
                self._prev_ema3_5m.append(self.regime_5m.ema3.value)
            agg_ts = sub[0].ts_event
            self._recent_5m.append({
                "ts": agg_ts, "h": agg_h, "l": agg_l, "c": agg_c,
                "v": agg_v, "regime": self.regime_5m.regime,
            })
            self._1m_for_5m = []

    # --------------------------------------------------------------
    # Session
    # --------------------------------------------------------------
    def _update_session(self, ts: int, h: float, l: float):
        dt_ct = pd.Timestamp(ts, unit="ns", tz="UTC").astimezone(CT)
        if dt_ct.hour >= 17:
            key = str(dt_ct.date())
        else:
            key = str((dt_ct - pd.Timedelta(days=1)).date())
        if key != self._session_start_key:
            self._session_start_key = key
            self._session_high = h
            self._session_low = l
            self._session_bar_count = 0
        else:
            if h > self._session_high:
                self._session_high = h
            if l < self._session_low:
                self._session_low = l

    # --------------------------------------------------------------
    # Warmup
    # --------------------------------------------------------------
    def _check_warmup_done(self) -> bool:
        """Per §3.6 minimum history requirement."""
        if not self.atr_14.initialized:
            return False
        if not self.sma50_1m.initialized:
            return False
        if self.regime_5m.completed_bars < 9:
            return False
        if self.regime_30s.completed_bars < 9:
            return False
        if self._1m_count < self._cfg.warmup_1m_bars:
            return False
        return True

    # --------------------------------------------------------------
    # Flip / confirmation
    # --------------------------------------------------------------
    def _handle_new_flip(self, bar: Bar1m, new_regime: int,
                         regime_5m_before_bar: int):
        """A new 1m regime flip was detected on this bar. Set up
        _flip_pending to await bar+1 HH/LL confirmation."""
        # If an unconfirmed flip was pending, it's abandoned (the new
        # flip is the fresh regime)
        if self._flip_pending is not None:
            self._flip_pending = None

        # Capture prior regime MFE before starting the new regime.
        # The "prior regime" is the one that just ended (whose direction
        # was the opposite of new_regime).
        if (self._curr_regime_bar1_close is not None
                and self._curr_regime_peak_fav is not None
                and self._curr_regime_direction != 0):
            diff = (self._curr_regime_peak_fav
                     - self._curr_regime_bar1_close)
            mfe_pts = diff * self._curr_regime_direction
            self._prior_regime_mfe_pts = max(0.0, mfe_pts)
            # Record duration (bars from bar+1 confirmation through flip
            # bar inclusive)
            duration = self._1m_count - self._curr_regime_start_bar
            self._completed_regime_durations.append(max(1, duration))
        else:
            self._prior_regime_mfe_pts = None

        # Reset current-regime tracking for the new regime (bar+1 not
        # yet known — will be set in _check_confirmation if confirmed)
        self._curr_regime_direction = new_regime
        self._curr_regime_bar1_close = None
        self._curr_regime_peak_fav = None
        self._curr_regime_start_bar = self._1m_count

        # Terminate any active events whose direction is opposite to
        # the new regime (regime flip against them)
        for ev in list(self._active_events):
            if new_regime == -ev.signal_direction:
                self._terminate_event(
                    ev, reason="regime_flip",
                    exit_time=bar.ts_event + 60_000_000_000,
                    exit_price=bar.c)

        atr = self.atr_14.value if self.atr_14.initialized else 0.0
        self._flip_pending = {
            "flip_bar": bar,
            "direction": new_regime,
            "atr_at_flip": atr,
            "flip_time": bar.ts_event,
            "prior_regime_duration_bars": self.regime_1m.bars_in_regime - 1,
            "regime_5m_before_flip_bar": regime_5m_before_bar,
            "prior_regime_mfe_pts": self._prior_regime_mfe_pts,
        }

    def _check_confirmation(self, bar1: Bar1m,
                              regime_5m_before_bar: int):
        """bar1 is the bar immediately after the flip. Check HH/LL."""
        fp = self._flip_pending
        if fp is None:
            return

        flip_bar = fp["flip_bar"]
        d = fp["direction"]
        if d == 1:
            made = bar1.h > flip_bar.h
        else:
            made = bar1.l < flip_bar.l

        if not made:
            self._diag["skipped_no_hhll"] += 1
            self._flip_pending = None
            return

        # Confirmed. Apply warmup gate before emitting.
        if not self._warmup_complete:
            self._diag["events_skipped_warmup"] += 1
            self._flip_pending = None
            return

        # Create event
        self._diag["confirmed"] += 1
        self._event_counter += 1
        signal_time = bar1.ts_event + 60_000_000_000
        atr_at_signal = (self.atr_14.value
                          if self.atr_14.initialized else 1e-9)

        ev = EventState(
            event_id=self._event_counter,
            signal_time_ns=signal_time,
            signal_direction=d,
            flip_bar=flip_bar,
            bar1=bar1,
            atr_at_signal=atr_at_signal,
            max_checkpoint_s=self._cfg.max_checkpoint_s,
        )
        # regime_5m_at_signal = state BEFORE bar+1's 5m update
        # (_update_5m will run AFTER _check_confirmation, but the pre-
        # update value is what was captured at the top of _on_1m as
        # regime_5m_before_bar).
        ev.regime_5m_at_signal = regime_5m_before_bar

        # Record bar1 close as the current regime's anchor for
        # prior_regime_mfe_atr of the NEXT event (§15.6 F3).
        self._curr_regime_bar1_close = bar1.c
        self._curr_regime_peak_fav = bar1.c

        # Snap root features (§6.1–§6.3, §6.6 signal-time)
        ev.root_features = self._snap_root_features(ev, fp)

        self._active_events.append(ev)
        self._flip_pending = None

    # --------------------------------------------------------------
    # Active-event per-1m update (termination, continuation counters)
    # --------------------------------------------------------------
    def _update_active_events_on_1m(self, rec: Bar1m,
                                      prev_regime_1m: int,
                                      new_r_1m: int,
                                      flip_occurred: bool):
        # Update current-regime peak favorable (for future
        # prior_regime_mfe_atr)
        if (self._curr_regime_bar1_close is not None
                and self._curr_regime_direction != 0
                and rec.ts_event >= (self._curr_regime_start_bar * 0)
                # ^ the start-bar gate is a no-op; bar+1 tracking
                # starts once bar1_close is set (gated above).
                ):
            if self._curr_regime_direction == 1:
                if self._curr_regime_peak_fav is None \
                        or rec.h > self._curr_regime_peak_fav:
                    self._curr_regime_peak_fav = rec.h
            else:
                if self._curr_regime_peak_fav is None \
                        or rec.l < self._curr_regime_peak_fav:
                    self._curr_regime_peak_fav = rec.l

        still_active = []
        for ev in self._active_events:
            # Append to post-signal buffer if after signal_time
            if rec.ts_event >= ev.signal_time:
                ev.bars_since_signal_1m.append(rec)
                # Continuation tracking (§6.5 B)
                if len(ev.bars_since_signal_1m) >= 2:
                    prev_b = ev.bars_since_signal_1m[-2]
                    if ev.signal_direction == 1:
                        cont = rec.h > prev_b.h
                    else:
                        cont = rec.l < prev_b.l
                    if cont:
                        ev.continuation_count += 1
                        ev.consec_continuation += 1
                        ev.bars_since_continuation = 0
                    else:
                        ev.consec_continuation = 0
                        ev.bars_since_continuation += 1

            # max-horizon check. Per §5: max_horizon fires on the 1m
            # bar whose CLOSE is at or past signal_time + max_checkpoint_s.
            # Condition uses >= so the bar closing AT max_checkpoint_s
            # is the terminator (not the next bar, which would give an
            # off-by-one of +60s between synthetic and actual termination).
            age_ns = rec.ts_event + 60_000_000_000 - ev.signal_time
            if age_ns / 1_000_000_000 >= ev.max_checkpoint_s:
                # Use actual bar's ts_init as exit_time. With signal_time
                # aligned to a 1m boundary and max_checkpoint_s divisible
                # by 60, this equals signal_time + max_checkpoint_s
                # exactly — matching the spec's "close of the bar at
                # signal_time + max_checkpoint_s".
                self._terminate_event(
                    ev, reason="max_horizon_reached",
                    exit_time=rec.ts_event + 60_000_000_000,
                    exit_price=rec.c)
                continue

            # (regime-flip termination is handled in _handle_new_flip
            # when a NEW flip is detected; this bar may be that bar,
            # in which case the event was already removed. Otherwise
            # keep the event alive.)
            if not ev.terminated:
                still_active.append(ev)
        self._active_events = still_active

    def _update_post_signal_state(self, ev: EventState,
                                    h: float, l: float, c: float,
                                    ts: int):
        """Update post-signal progress tracking on each 1s bar
        (per §15.7 and §6.5 A definitions)."""
        sig_px = ev.bar1.c
        atr = max(ev.atr_at_signal, 1e-9)
        d = ev.signal_direction

        # Init on first call
        if ev.t_peak_ns is None:
            ev.t_peak_ns = ev.signal_time
            ev.max_progress_price = sig_px
            ev.min_fav_price_since_peak = sig_px

        # Favorable excursion this bar (signed: positive = in trade dir)
        fav_peak = h if d == 1 else l
        unfav_peak = l if d == 1 else h

        fav_atr = max(0.0, (fav_peak - sig_px) * d / atr)
        unfav_atr = max(0.0, (sig_px - unfav_peak) * d / atr)

        # New running peak: update T_peak and reset since-peak tracker
        if fav_atr > ev.max_progress_atr:
            ev.max_progress_atr = fav_atr
            ev.t_peak_ns = ts
            ev.max_progress_price = fav_peak
            # Reset since-peak tracker to the current bar's unfavorable
            # extreme (the bar achieving peak may still have a pullback)
            ev.min_fav_price_since_peak = unfav_peak
        else:
            # Update since-peak tracker (lowest low for long, highest
            # high for short, since T_peak)
            if d == 1:
                if unfav_peak < ev.min_fav_price_since_peak:
                    ev.min_fav_price_since_peak = unfav_peak
            else:
                if unfav_peak > ev.min_fav_price_since_peak:
                    ev.min_fav_price_since_peak = unfav_peak

        # Max pullback (ATR units, monotonic)
        if unfav_atr > ev.max_pullback_atr:
            ev.max_pullback_atr = unfav_atr

    # --------------------------------------------------------------
    # Feature snaps — ROOT (signal_time)
    # Implementation follows feature_contract_v2.json definitions.
    # --------------------------------------------------------------
    def _snap_root_features(self, ev: EventState, fp: dict) -> dict:
        """Snap all signal-time features (§6.1, §6.2, §6.3, §6.6 sig).

        Returns a dict keyed by feature contract name.
        """
        feats = {}

        # Static fields
        feats["signal_direction"] = int(ev.signal_direction)
        feats["atr_at_signal"] = float(ev.atr_at_signal)
        feats["atr_14"] = float(ev.atr_at_signal)  # compat_alias
        feats["bar1_confirmed_hh_ll"] = 1  # constant_by_construction

        # Family helpers — each adds to feats in place
        self._snap_flip_anatomy(ev, feats)
        self._snap_bar1_anatomy(ev, feats)
        self._snap_two_bar(ev, feats)
        for N in (3, 5, 10):
            self._snap_pre_signal_lookback(ev, N, feats)
        self._snap_compression(ev, feats)
        self._snap_local_structure(ev, feats)
        self._snap_trend_quality(ev, feats)
        self._snap_regime_context(ev, fp, feats)
        self._snap_ma_state(ev, feats)
        self._snap_vol_state(ev, feats)
        self._snap_session_at_signal(ev, feats)

        return feats

    # ------ helpers ------

    def _pre_signal_bars(self, N: int) -> list:
        """Return the N 1m bars ending just before flip_bar, in
        forward order [B[1], ..., B[N]]. Requires >=N+2 bars in
        _recent_1m (we need flip_bar, bar1, plus N pre-signal bars)."""
        if len(self._recent_1m) < N + 2:
            return []
        # _recent_1m[-1] = bar1, [-2] = flip_bar, pre-signal = [-N-2:-2]
        return list(self._recent_1m)[-(N + 2):-2]

    def _prior_1m_bar(self, ev: EventState) -> "Bar1m":
        """The 1m bar immediately before flip_bar. Falls back to
        flip_bar itself if insufficient history."""
        if len(self._recent_1m) >= 3:
            return self._recent_1m[-3]
        return ev.flip_bar

    def _snap_flip_anatomy(self, ev: EventState, f: dict) -> None:
        """§6.1 flip bar anatomy — 13 features."""
        fb = ev.flip_bar
        atr = max(ev.atr_at_signal, 1e-9)
        rng = fb.h - fb.l
        body = abs(fb.c - fb.o)
        d = ev.signal_direction

        f["flip_range_atr"] = rng / atr
        f["flip_body_atr"] = body / atr
        f["flip_body_pct"] = body / rng if rng > 0 else 0.0
        f["flip_close_location"] = (
            (fb.c - fb.l) / rng if rng > 0 else 0.5)
        f["flip_upper_wick_pct"] = (
            (fb.h - max(fb.o, fb.c)) / rng if rng > 0 else 0.0)
        f["flip_lower_wick_pct"] = (
            (min(fb.o, fb.c) - fb.l) / rng if rng > 0 else 0.0)
        f["flip_volume"] = float(fb.v)
        f["flip_vol_vs_20avg"] = self._vol_vs_Navg(fb.v, 20, offset=1)
        prior = self._prior_1m_bar(ev)
        f["flip_close_vs_prior_close_atr"] = (
            (fb.c - prior.c) * d / atr)
        f["flip_high_vs_prior_high_atr"] = (
            (fb.h - prior.h) * d / atr)
        f["flip_low_vs_prior_low_atr"] = (
            (fb.l - prior.l) * d / atr)
        up_v = fb.up_vol
        dn_v = fb.down_vol
        f["flip_bar_bullish_volume_pct"] = (
            up_v / (up_v + dn_v) if (up_v + dn_v) > 0 else 0.5)
        f["flip_bar_vol_rank_20"] = self._vol_rank_N(fb.v, 20, offset=1)

    def _snap_bar1_anatomy(self, ev: EventState, f: dict) -> None:
        """§6.1 bar+1 anatomy — 14 features (bar1_confirmed_hh_ll set
        separately as constant)."""
        b1 = ev.bar1
        fb = ev.flip_bar
        atr = max(ev.atr_at_signal, 1e-9)
        rng = b1.h - b1.l
        body = abs(b1.c - b1.o)
        d = ev.signal_direction

        f["bar1_range_atr"] = rng / atr
        f["bar1_body_atr"] = body / atr
        f["bar1_body_pct"] = body / rng if rng > 0 else 0.0
        f["bar1_close_location"] = (
            (b1.c - b1.l) / rng if rng > 0 else 0.5)
        f["bar1_upper_wick_pct"] = (
            (b1.h - max(b1.o, b1.c)) / rng if rng > 0 else 0.0)
        f["bar1_lower_wick_pct"] = (
            (min(b1.o, b1.c) - b1.l) / rng if rng > 0 else 0.0)
        f["bar1_volume"] = float(b1.v)
        f["bar1_vol_vs_flip_vol"] = (
            b1.v / fb.v if fb.v > 0 else 1.0)
        f["bar1_vol_rank_20"] = self._vol_rank_N(b1.v, 20, offset=0)
        hh_amt = ((b1.h - fb.h) if d == 1 else (fb.l - b1.l))
        f["bar1_hh_amount_atr"] = hh_amt / atr
        f["bar1_close_vs_flip_close_atr"] = (
            (b1.c - fb.c) * d / atr)
        f["bar1_close_above_flip_close"] = (
            1 if (b1.c - fb.c) * d > 0 else 0)
        # bar1 close in favor of direction past midpoint
        loc = (b1.c - b1.l) / rng if rng > 0 else 0.5
        f["bar1_close_above_50pct_range"] = (
            1 if (d == 1 and loc > 0.5) or (d == -1 and loc < 0.5)
            else 0)
        up_v = b1.up_vol
        dn_v = b1.down_vol
        f["bar1_bullish_volume_pct"] = (
            up_v / (up_v + dn_v) if (up_v + dn_v) > 0 else 0.5)

    def _snap_two_bar(self, ev: EventState, f: dict) -> None:
        """§6.1 two-bar sequence — 6 features."""
        fb, b1 = ev.flip_bar, ev.bar1
        atr = max(ev.atr_at_signal, 1e-9)
        d = ev.signal_direction
        h_max = max(fb.h, b1.h)
        l_min = min(fb.l, b1.l)
        two_rng = h_max - l_min
        two_body = (b1.c - fb.o) * d

        f["two_bar_range_atr"] = two_rng / atr
        f["two_bar_body_atr"] = two_body / atr
        f["two_bar_close_vs_open_pct"] = (
            (b1.c - fb.o) / fb.o if fb.o > 0 else 0.0)
        f["two_bar_volume_total"] = float(fb.v + b1.v)
        f["two_bar_vol_vs_40avg"] = self._vol_vs_Navg(
            fb.v + b1.v, 40, offset=1, window_sum=True)
        # flip_low_to_bar1_high_atr is a compat_alias of two_bar_range_atr
        f["flip_low_to_bar1_high_atr"] = two_rng / atr

    def _snap_pre_signal_lookback(self, ev: EventState, N: int,
                                    f: dict) -> None:
        """§6.2A — 13 features per N ∈ {3, 5, 10}."""
        bars = self._pre_signal_bars(N)
        atr = max(ev.atr_at_signal, 1e-9)
        d = ev.signal_direction

        if len(bars) < N:
            # Insufficient history — populate with defaults / NaN
            for suffix, default in [
                ("range_atr", float("nan")),
                ("net_return_atr", float("nan")),
                ("body_efficiency", 0.0),
                ("up_bar_fraction", float("nan")),
                ("down_bar_fraction", float("nan")),
                ("hh_count", float("nan")),
                ("ll_count", float("nan")),
                ("close_near_high_fraction", float("nan")),
                ("close_near_low_fraction", float("nan")),
                ("volume_total", 0.0),
                ("vol_vs_avg", 1.0),
                ("mean_body_pct", float("nan")),
                ("mean_wickiness", float("nan")),
            ]:
                f[f"pre_{N}_{suffix}"] = default
            return

        B1, BN = bars[0], bars[-1]
        ranges = [b.h - b.l for b in bars]
        body_sum = sum(abs(b.c - b.o) for b in bars)
        range_sum = sum(ranges)
        vol_total = sum(b.v for b in bars)

        f[f"pre_{N}_range_atr"] = (sum(ranges) / N) / atr
        f[f"pre_{N}_net_return_atr"] = (BN.c - B1.o) * d / atr
        f[f"pre_{N}_body_efficiency"] = (
            abs(BN.c - B1.o) / range_sum if range_sum > 0 else 0.0)

        up_count = sum(1 for b in bars if b.c > b.o)
        down_count = sum(1 for b in bars if b.c < b.o)
        f[f"pre_{N}_up_bar_fraction"] = up_count / N
        f[f"pre_{N}_down_bar_fraction"] = down_count / N

        if N >= 2:
            hh = sum(1 for j in range(1, N)
                     if bars[j].h > bars[j - 1].h)
            ll = sum(1 for j in range(1, N)
                     if bars[j].l < bars[j - 1].l)
            f[f"pre_{N}_hh_count"] = hh / (N - 1)
            f[f"pre_{N}_ll_count"] = ll / (N - 1)
        else:
            f[f"pre_{N}_hh_count"] = 0.0
            f[f"pre_{N}_ll_count"] = 0.0

        near_high = 0
        near_low = 0
        valid_range_bars = 0
        for b in bars:
            r = b.h - b.l
            if r <= 0:
                continue
            valid_range_bars += 1
            cl = (b.c - b.l) / r
            if cl >= 0.75:
                near_high += 1
            if cl <= 0.25:
                near_low += 1
        f[f"pre_{N}_close_near_high_fraction"] = (
            near_high / valid_range_bars
            if valid_range_bars > 0 else 0.0)
        f[f"pre_{N}_close_near_low_fraction"] = (
            near_low / valid_range_bars
            if valid_range_bars > 0 else 0.0)

        f[f"pre_{N}_volume_total"] = float(vol_total)
        baseline = self._vol_mean_prior_N(20, offset=N + 2)
        f[f"pre_{N}_vol_vs_avg"] = (
            vol_total / (N * baseline) if baseline > 0 else 1.0)

        body_pcts = [
            abs(b.c - b.o) / max(b.h - b.l, 1e-9) for b in bars]
        f[f"pre_{N}_mean_body_pct"] = sum(body_pcts) / N

        wickinesses = []
        for b in bars:
            r = b.h - b.l
            upper = b.h - max(b.o, b.c)
            lower = min(b.o, b.c) - b.l
            wickinesses.append((upper + lower) / max(r, 1e-9))
        f[f"pre_{N}_mean_wickiness"] = sum(wickinesses) / N

    def _snap_compression(self, ev: EventState, f: dict) -> None:
        """§6.2B — 4 compression ratios + 1 flag."""
        last_3 = self._pre_signal_bars(3)
        prior_7 = (self._pre_signal_bars(10)[:-3]
                    if len(self._pre_signal_bars(10)) >= 10 else [])

        if len(last_3) < 3 or len(prior_7) < 7:
            for name in (
                "pre_signal_range_compression_3v10",
                "pre_signal_body_compression_3v10",
                "pre_signal_atr_ratio_3v10",
                "pre_signal_vol_compression_3v10",
            ):
                f[name] = float("nan")
            f["pre_signal_breakout_from_compression_flag"] = 0
            return

        def mean_range(bars):
            return sum(b.h - b.l for b in bars) / len(bars)

        def mean_body(bars):
            return sum(abs(b.c - b.o) for b in bars) / len(bars)

        def true_range_mean(bars):
            # Wilder TR: max(H-L, |H-prev_close|, |L-prev_close|)
            trs = []
            for j, b in enumerate(bars):
                if j == 0:
                    trs.append(b.h - b.l)
                else:
                    pc = bars[j - 1].c
                    trs.append(max(b.h - b.l,
                                     abs(b.h - pc),
                                     abs(b.l - pc)))
            return sum(trs) / len(trs)

        def mean_vol(bars):
            return sum(b.v for b in bars) / len(bars)

        mr_3 = mean_range(last_3)
        mr_7 = mean_range(prior_7)
        f["pre_signal_range_compression_3v10"] = (
            mr_3 / max(mr_7, 1e-9))
        f["pre_signal_body_compression_3v10"] = (
            mean_body(last_3) / max(mean_body(prior_7), 1e-9))
        f["pre_signal_atr_ratio_3v10"] = (
            true_range_mean(last_3) /
            max(true_range_mean(prior_7), 1e-9))
        f["pre_signal_vol_compression_3v10"] = (
            mean_vol(last_3) / max(mean_vol(prior_7), 1e-9))

        atr = max(ev.atr_at_signal, 1e-9)
        flip_range_norm = (
            ev.flip_bar.h - ev.flip_bar.l) / atr
        mean_range_last_3_norm = mr_3 / atr
        f["pre_signal_breakout_from_compression_flag"] = (
            1 if (f["pre_signal_range_compression_3v10"] < 0.6
                  and flip_range_norm > 1.5 * mean_range_last_3_norm)
            else 0)

    def _snap_local_structure(self, ev: EventState, f: dict) -> None:
        """§6.2C — 8 features."""
        fb = ev.flip_bar
        atr = max(ev.atr_at_signal, 1e-9)
        d = ev.signal_direction

        for N in (5, 10):
            bars = self._pre_signal_bars(N)
            if len(bars) < N:
                f[f"dist_to_recent_high_{N}_atr"] = float("nan")
                f[f"dist_to_recent_low_{N}_atr"] = float("nan")
                continue
            max_h = max(b.h for b in bars)
            min_l = min(b.l for b in bars)
            f[f"dist_to_recent_high_{N}_atr"] = (max_h - fb.c) / atr
            f[f"dist_to_recent_low_{N}_atr"] = (fb.c - min_l) / atr

        bars10 = self._pre_signal_bars(10)
        if len(bars10) >= 10:
            max_h = max(b.h for b in bars10)
            min_l = min(b.l for b in bars10)
            mid = (max_h + min_l) / 2.0
            f["dist_to_recent_midpoint_10_atr"] = (fb.c - mid) / atr
            rng_10 = max_h - min_l
            f["position_in_recent_range_10"] = (
                (fb.c - min_l) / rng_10 if rng_10 > 1e-9 else 0.5)
            failed = 0
            for j in range(1, 10):
                cur, prev = bars10[j], bars10[j - 1]
                if (cur.h > prev.h and cur.c < prev.h):
                    failed += 1
                elif (cur.l < prev.l and cur.c > prev.l):
                    failed += 1
            f["failed_push_count_pre_signal"] = failed
            if d == 1:
                f["swing_extension_at_signal_atr"] = (
                    (fb.c - min_l) / atr)
            else:
                f["swing_extension_at_signal_atr"] = (
                    (max_h - fb.c) / atr)
        else:
            f["dist_to_recent_midpoint_10_atr"] = float("nan")
            f["position_in_recent_range_10"] = 0.5
            f["failed_push_count_pre_signal"] = 0
            f["swing_extension_at_signal_atr"] = float("nan")

    def _snap_trend_quality(self, ev: EventState, f: dict) -> None:
        """§6.2D — 6 features (3 stems × N ∈ {5, 10})."""
        for N in (5, 10):
            bars = self._pre_signal_bars(N)
            if len(bars) < N:
                f[f"pre_signal_trend_efficiency_{N}"] = float("nan")
                f[f"pre_signal_chopiness_{N}"] = float("nan")
                f[f"pre_signal_directional_consistency_{N}"] = float("nan")
                continue
            B1, BN = bars[0], bars[-1]
            net = abs(BN.c - B1.o)
            path = sum(b.h - b.l for b in bars)
            eff = net / path if path > 0 else 0.0
            f[f"pre_signal_trend_efficiency_{N}"] = eff
            f[f"pre_signal_chopiness_{N}"] = 1.0 - eff
            # directional consistency: fraction of bars with close-to-
            # close sign matching net direction
            net_dir = 1 if BN.c > B1.o else (-1 if BN.c < B1.o else 0)
            if net_dir == 0 or N < 2:
                f[f"pre_signal_directional_consistency_{N}"] = 0.0
                continue
            agree = 0
            for j in range(1, N):
                diff = bars[j].c - bars[j - 1].c
                sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
                if sign == net_dir:
                    agree += 1
            f[f"pre_signal_directional_consistency_{N}"] = (
                agree / (N - 1))

    def _snap_regime_context(self, ev: EventState, fp: dict,
                               f: dict) -> None:
        """§6.3 1m regime context — 6 features."""
        f["prior_regime_duration_bars"] = int(
            fp.get("prior_regime_duration_bars", 0))

        prior_mfe_pts = fp.get("prior_regime_mfe_pts")
        if prior_mfe_pts is None:
            f["prior_regime_mfe_atr"] = float("nan")
        else:
            atr = max(ev.atr_at_signal, 1e-9)
            f["prior_regime_mfe_atr"] = max(0.0, prior_mfe_pts) / atr

        # Count flips in last 30 / 60 1m bars (history uses
        # completed_bars index)
        flips = list(self.regime_1m.flip_history)
        now_bar = self.regime_1m.completed_bars
        f["regime_flips_last_30min"] = sum(
            1 for bar_idx, _ in flips if now_bar - bar_idx <= 30)
        f["regime_flips_last_60min"] = sum(
            1 for bar_idx, _ in flips if now_bar - bar_idx <= 60)

        # avg_regime_duration_last_5
        durations = list(self._completed_regime_durations)
        last_5 = durations[-5:]
        f["avg_regime_duration_last_5"] = (
            float(sum(last_5) / len(last_5))
            if last_5 else float("nan"))

        # consecutive_trend_bars_pre_flip: count consecutive same-
        # direction close-to-close moves in the 5 pre-flip bars,
        # counting from the end backward
        bars5 = self._pre_signal_bars(5)
        count = 0
        if len(bars5) >= 2:
            # iterate from most recent backward
            prev_sign = None
            for j in range(len(bars5) - 1, 0, -1):
                diff = bars5[j].c - bars5[j - 1].c
                sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
                if sign == 0:
                    break
                if prev_sign is None:
                    prev_sign = sign
                    count = 1
                elif sign == prev_sign:
                    count += 1
                else:
                    break
        f["consecutive_trend_bars_pre_flip"] = count

    def _snap_ma_state(self, ev: EventState, f: dict) -> None:
        """§6.3 signal-time MA/trend — 9 features (atr_14 already set)."""
        fb = ev.flip_bar
        atr = max(ev.atr_at_signal, 1e-9)

        sma20 = self.sma20_1m.value if self.sma20_1m.initialized else fb.c
        sma50 = self.sma50_1m.value if self.sma50_1m.initialized else fb.c
        f["price_vs_sma20_atr"] = (fb.c - sma20) / atr
        f["price_vs_sma50_atr"] = (fb.c - sma50) / atr

        # Slopes: current - value 5/10 bars ago (from prev deques)
        if len(self._prev_sma20) >= 6:
            f["sma20_slope_atr"] = (
                self._prev_sma20[-1] - self._prev_sma20[0]) / atr
        else:
            f["sma20_slope_atr"] = float("nan")
        if len(self._prev_sma50) >= 11:
            f["sma50_slope_atr"] = (
                self._prev_sma50[-1] - self._prev_sma50[0]) / atr
        else:
            f["sma50_slope_atr"] = float("nan")
        f["sma20_vs_sma50_atr"] = (sma20 - sma50) / atr

        if len(self._prev_ema3_1m) >= 6:
            f["ema3_slope_atr"] = (
                self._prev_ema3_1m[-1] - self._prev_ema3_1m[0]) / atr
        else:
            f["ema3_slope_atr"] = float("nan")

        # ema_spread_atr: regime_1m emaH3 - emaL3 over atr
        if (self.regime_1m.emaH_3.initialized
                and self.regime_1m.emaL_3.initialized):
            f["ema_spread_atr"] = (
                self.regime_1m.emaH_3.value
                - self.regime_1m.emaL_3.value) / atr
        else:
            f["ema_spread_atr"] = float("nan")

        if (self.regime_1m.ema3.initialized
                and self.regime_1m.ema9.initialized):
            f["ema3_ema9_spread_atr"] = (
                self.regime_1m.ema3.value
                - self.regime_1m.ema9.value) / atr
        else:
            f["ema3_ema9_spread_atr"] = float("nan")

    def _snap_vol_state(self, ev: EventState, f: dict) -> None:
        """§6.3 signal-time volume — 6 features."""
        # vol_1m_20avg: mean of last 20 1m bar volumes (rolling,
        # includes flip_bar + bar1)
        bars20 = (list(self._recent_1m)[-20:]
                   if len(self._recent_1m) >= 1 else [])
        if len(bars20) > 0:
            f["vol_1m_20avg"] = sum(b.v for b in bars20) / len(bars20)
        else:
            f["vol_1m_20avg"] = 0.0

        def vol_ratio_up_down(N: int) -> float:
            bars = (list(self._recent_1m)[-N:]
                     if len(self._recent_1m) >= N else [])
            up = sum(b.up_vol for b in bars)
            dn = sum(b.down_vol for b in bars)
            return up / dn if dn > 0 else 1.0

        f["vol_ratio_up_down_10bar"] = vol_ratio_up_down(10)
        f["vol_ratio_up_down_20bar"] = vol_ratio_up_down(20)

        # vol_acceleration_5bar: (last 5 mean - prior 5 mean) / prior 5 mean
        bars10 = (list(self._recent_1m)[-10:]
                    if len(self._recent_1m) >= 10 else [])
        if len(bars10) == 10:
            last5 = sum(b.v for b in bars10[-5:]) / 5
            prior5 = sum(b.v for b in bars10[:5]) / 5
            f["vol_acceleration_5bar"] = (
                (last5 - prior5) / prior5 if prior5 > 0 else 0.0)
        else:
            f["vol_acceleration_5bar"] = 0.0

        # high_vol_bar_count_10: count of last 10 bars with vol > 1.5
        # × vol_1m_20avg
        threshold = 1.5 * f["vol_1m_20avg"]
        f["high_vol_bar_count_10"] = (
            sum(1 for b in bars10 if b.v > threshold)
            if bars10 and threshold > 0 else 0)

        # cumulative_volume_bias_10: sum(up - down) / sum(total) last 10
        if bars10:
            total = sum(b.v for b in bars10)
            bias = sum(b.up_vol - b.down_vol for b in bars10)
            f["cumulative_volume_bias_10"] = (
                bias / total if total > 0 else 0.0)
        else:
            f["cumulative_volume_bias_10"] = 0.0

    def _snap_session_at_signal(self, ev: EventState, f: dict) -> None:
        """§6.6 session / timing at signal — 9 features."""
        atr = max(ev.atr_at_signal, 1e-9)
        dt_ct = pd.Timestamp(
            ev.signal_time, unit="ns", tz="UTC").astimezone(CT)
        ct_min = dt_ct.hour * 60 + dt_ct.minute
        f["is_rth"] = 1 if 510 <= ct_min < 900 else 0
        f["hour_of_day"] = int(dt_ct.hour)
        f["minute_of_hour"] = int(dt_ct.minute)
        f["minutes_since_rth_open"] = int(ct_min - 510)

        cur_px = ev.bar1.c
        if self._session_high > -1e17:
            f["distance_from_session_high_atr"] = (
                self._session_high - cur_px) / atr
        else:
            f["distance_from_session_high_atr"] = 0.0
        if self._session_low < 1e17:
            f["distance_from_session_low_atr"] = (
                cur_px - self._session_low) / atr
        else:
            f["distance_from_session_low_atr"] = 0.0
        if self._session_high > -1e17 and self._session_low < 1e17:
            mid = (self._session_high + self._session_low) / 2.0
            f["distance_from_session_mid_atr"] = (cur_px - mid) / atr
        else:
            f["distance_from_session_mid_atr"] = 0.0

        f["session_bars_since_open"] = int(self._session_bar_count)
        f["session_warmup_flag"] = (
            1 if self._session_bar_count < 10 else 0)

    # ---- 1m volume utilities ----

    def _vol_vs_Navg(self, vol: float, N: int, offset: int = 1,
                      window_sum: bool = False) -> float:
        """vol / mean volume of N bars ending `offset` bars before the
        most recent (so offset=1 excludes the most recent bar).

        If window_sum=True, numerator is treated as total over W bars
        and the comparison is `vol / (N * mean_vol_prior_N)` — used by
        two_bar_vol_vs_40avg.
        """
        bars = list(self._recent_1m)
        # Exclude the last `offset` bars
        eligible = bars[:-offset] if offset > 0 else bars
        if len(eligible) < N:
            return 1.0
        window = eligible[-N:]
        avg = sum(b.v for b in window) / N
        if avg <= 0:
            return 1.0
        if window_sum:
            return vol / (len(window) * avg)  # == vol / (N*avg)
        return vol / avg

    def _vol_mean_prior_N(self, N: int, offset: int) -> float:
        """Mean volume of N 1m bars ending `offset` bars before the
        most recent. Returns 0.0 if insufficient history."""
        bars = list(self._recent_1m)
        eligible = bars[:-offset] if offset > 0 else bars
        if len(eligible) < N:
            return 0.0
        window = eligible[-N:]
        return sum(b.v for b in window) / N

    def _vol_rank_N(self, vol: float, N: int, offset: int) -> float:
        """Rank of `vol` among the prior N 1m bar volumes (excluding
        the most recent `offset` bars). Returns fraction in [0, 1]
        where 0 = lowest, 1 = highest. Returns 0.5 if insufficient."""
        bars = list(self._recent_1m)
        eligible = bars[:-offset] if offset > 0 else bars
        if len(eligible) < N:
            return 0.5
        window = [b.v for b in eligible[-N:]]
        below = sum(1 for v in window if v < vol)
        return below / N

    def _try_fill_pending_checkpoints(self, ts: int, o: float) -> None:
        """Resolve fillability for any checkpoint whose intended fill_time
        has been reached.

        Per §7.1:
          - intended fill_time = decision_time + 30s (a 30s boundary)
          - Resolves on the FIRST 1s bar with ts_event ≥ fill_time — this
            accommodates Databento OHLCV-1s gaps (sparse-bar seconds
            during illiquid periods) and mirrors live-trading semantics
            where the next tick is used for fill. The tracker's actual
            fill_time is the 1s bar's ts_event (may be > intended).
          - fill_price = open of the resolving 1s bar
          - fillable_at_T = True iff the event is still alive strictly
            after the actual fill bar (i.e., regime_exit_time is None
            or > ts).

        Checkpoints are iterated in ascending T order so that earlier
        fills resolve before later ones (relevant when a single 1s bar
        clears multiple pending fills after a gap).
        """
        for ev in self._active_events:
            for T in sorted(ev.checkpoints.keys()):
                cp = ev.checkpoints[T]
                if T in ev.forward_trackers:
                    continue  # already resolved
                if cp.fill_time is None or cp.fill_time > ts:
                    continue  # fill_time not yet reached

                # Intended fill_time has passed. Attempt fill at current
                # bar open. Fillability gated by:
                #   1. Fill must land within the event's max-horizon
                #      window (fill_time ≤ signal_time + max_checkpoint_s)
                #   2. Event liveness at ts (regime still active)
                #   3. Fill slippage ≤ max_fill_slippage_s (guards
                #      session-halt gaps where the next 1s bar is an
                #      hour later)
                horizon_ns = (ev.signal_time
                    + ev.max_checkpoint_s * 1_000_000_000)
                # Strict inequality: a fill AT max_horizon is the event's
                # end moment — by "strictly alive after fill_time", not
                # fillable.
                if cp.fill_time >= horizon_ns:
                    cp.fillable_at_T = False
                    ev.forward_trackers[T] = None
                    self._diag["fills_skipped_past_horizon"] += 1
                    continue
                slip_ns = ts - cp.fill_time
                slip_cap_ns = (
                    self._cfg.max_fill_slippage_s * 1_000_000_000)
                if slip_ns > slip_cap_ns:
                    cp.fillable_at_T = False
                    ev.forward_trackers[T] = None
                    self._diag["fills_skipped_slippage_cap"] += 1
                    continue
                if (ev.regime_exit_time is not None
                        and ev.regime_exit_time <= ts):
                    cp.fillable_at_T = False
                    ev.forward_trackers[T] = None
                    self._diag["fills_skipped_unfillable"] += 1
                    continue

                cp.fillable_at_T = True
                cp.fill_price = o
                # Record the ACTUAL fill bar ts on the tracker (may be
                # > cp.fill_time if there was a 1s-bar gap). cp.fill_time
                # stays as intended decision_time + 30s for audit.
                tracker = ForwardPathTracker(
                    fill_time_ns=ts,
                    fill_price=o,
                    direction=ev.signal_direction,
                    atr_at_signal=ev.atr_at_signal,
                    max_lookahead_s=ev.max_checkpoint_s,
                )
                ev.forward_trackers[T] = tracker
                self._diag["fills_executed"] += 1

    def _snap_checkpoint(self, ev: EventState, T: int,
                          current_ts: int):
        """Snap checkpoint-dynamic features at T (§6.4, §6.5, §6.6 ckp).

        Runs when a 30s bar closes AT current_ts and the event has an
        observation_time matching T. Reads indicator/state values that
        reflect all bars with ts_init <= current_ts (30s update fired,
        1m/5m at shared ts_init NOT yet fired — per §5.5).
        """
        cp = ev.checkpoints.setdefault(T, CheckpointFeatures(T))
        cp.observation_time = current_ts

        # alive_at_T: regime still active strictly after observation_time
        if (ev.regime_exit_time is None
                or ev.regime_exit_time > current_ts):
            cp.alive_at_T = True
            cp.dead_before_T = False
        else:
            cp.alive_at_T = False
            cp.dead_before_T = True
            return  # dead — no feature snap

        # fill_time (§7.1): execution at open of 30s bar starting at
        # current_ts + 30s (so fill_time = current_ts + 30s). The
        # fillable_at_T flag is resolved in _try_fill_pending_checkpoints
        # when the 1s bar at fill_time arrives — fillable iff the
        # event is still alive strictly after fill_time.
        cp.fill_time = current_ts + 30_000_000_000

        # Populate features
        f = cp.features
        f["atr_at_checkpoint"] = (
            self.atr_14.value if self.atr_14.initialized else 0.0)

        self._ckp_time_elapsed(ev, T, current_ts, f)
        self._ckp_price_position(ev, current_ts, f)
        self._ckp_30s_state(ev, f)
        self._ckp_1m_state(ev, f)
        self._ckp_5m_state(ev, f)
        self._ckp_micro(ev, current_ts, f)
        self._ckp_progress(ev, f)
        self._ckp_continuation(ev, current_ts, f)
        self._ckp_extension(ev, f)
        self._ckp_session_at_checkpoint(ev, current_ts, f)

        self._diag["checkpoints_snapped"] += 1

        # TODO[label/tracker]: instantiate ForwardPathTracker when the
        # 1s bar at fill_time arrives. For now the tracker stays at
        # None — labels unpopulated. Addressed in WO3.

    # ---- checkpoint family helpers ----

    def _ckp_time_elapsed(self, ev: EventState, T: int,
                           current_ts: int, f: dict) -> None:
        """§6.4 A — 7 features."""
        f["checkpoint_s"] = T
        f["checkpoint_minutes"] = T / 60.0
        f["checkpoint_bars_since_signal_1m"] = T // 60
        f["checkpoint_bars_since_signal_30s"] = T // 30

        # Time relative to surrounding 1m / 5m boundaries
        # decision_time is a 30s boundary. 1m boundaries occur every 60s.
        # time_since_last_1m_bar_close = current_ts mod 60, in seconds
        mod_60s = (current_ts // 1_000_000_000) % 60
        f["time_since_last_1m_bar_close_s"] = int(mod_60s)
        f["time_until_next_1m_bar_close_s"] = int((60 - mod_60s) % 60)

        # 5m close happens every 5 minutes at CT minute_of_hour % 5 == 4
        # (i.e., minutes 4, 9, 14, ..., 59 of each hour).
        # But actually closes happen at the next minute boundary. In
        # terms of UTC seconds since epoch modulo 300s:
        mod_300 = (current_ts // 1_000_000_000) % 300
        # The next 5m boundary in this cycle (wrt modulo 300) is at 300
        f["time_until_next_5m_bar_close_s"] = int((300 - mod_300) % 300)

    def _ckp_price_position(self, ev: EventState, current_ts: int,
                              f: dict) -> None:
        """§6.4 B — 9 features. Uses current 1s close at decision_time."""
        cur_px = self._current_1s_close()
        atr = max(ev.atr_at_signal, 1e-9)
        d = ev.signal_direction
        sig_px = ev.bar1.c

        f["price_vs_signal_close_atr"] = (cur_px - sig_px) * d / atr
        f["price_vs_flip_bar_high_atr"] = (
            (cur_px - ev.flip_bar.h) * d / atr)
        f["price_vs_flip_bar_low_atr"] = (
            (cur_px - ev.flip_bar.l) * d / atr)
        f["price_vs_bar1_high_atr"] = (
            (cur_px - ev.bar1.h) * d / atr)
        f["price_vs_bar1_low_atr"] = (
            (cur_px - ev.bar1.l) * d / atr)

        # MA-based distances (unsigned, not dir-adjusted)
        if self.sma20_30s.initialized:
            f["price_vs_sma20_30s_atr"] = (
                (cur_px - self.sma20_30s.value) / atr)
        else:
            f["price_vs_sma20_30s_atr"] = 0.0

        if self.sma20_5m.initialized:
            f["price_vs_sma20_5m_atr"] = (
                (cur_px - self.sma20_5m.value) / atr)
        else:
            f["price_vs_sma20_5m_atr"] = 0.0

        if self.regime_30s.ema3.initialized:
            f["price_vs_ema3_30s_atr"] = (
                (cur_px - self.regime_30s.ema3.value) / atr)
        else:
            f["price_vs_ema3_30s_atr"] = 0.0

        if self.regime_5m.ema3.initialized:
            f["price_vs_ema3_5m_atr"] = (
                (cur_px - self.regime_5m.ema3.value) / atr)
        else:
            f["price_vs_ema3_5m_atr"] = 0.0

    def _ckp_30s_state(self, ev: EventState, f: dict) -> None:
        """§6.4 C — 9 features. 30s aggregation fired already per §5.5."""
        d = ev.signal_direction
        atr = max(ev.atr_at_signal, 1e-9)

        f["regime_30s_aligned"] = (
            1 if self.regime_30s.regime == d else 0)
        f["regime_30s_direction"] = int(self.regime_30s.regime)
        f["regime_30s_duration_bars"] = int(
            self.regime_30s.bars_in_regime)

        # ema3 slope 30s (current vs 5 30s bars ago)
        if len(self._prev_ema3_30s) >= 6:
            f["ema3_slope_30s_atr"] = (
                self._prev_ema3_30s[-1] - self._prev_ema3_30s[0]) / atr
        else:
            f["ema3_slope_30s_atr"] = 0.0

        if (self.regime_30s.emaH_3.initialized
                and self.regime_30s.emaL_3.initialized):
            f["ema_spread_30s_atr"] = (
                self.regime_30s.emaH_3.value
                - self.regime_30s.emaL_3.value) / atr
        else:
            f["ema_spread_30s_atr"] = 0.0

        # In-progress 30s bar (buffered 1s bars in next window)
        buf = self._1s_for_30s
        if buf:
            max_h = max(b[2] for b in buf)
            min_l = min(b[3] for b in buf)
            first_o = buf[0][1]
            last_c = buf[-1][4]
            rng = max_h - min_l
            body = abs(last_c - first_o)
            f["bar_range_30s_current_atr"] = rng / atr
            f["bar_body_30s_current_atr"] = body / atr
            f["bar_body_pct_30s_current"] = (
                body / rng if rng > 0 else 0.5)
            f["bar_wickiness_30s_current"] = (
                (rng - body) / rng if rng > 0 else 0.0)
        else:
            f["bar_range_30s_current_atr"] = 0.0
            f["bar_body_30s_current_atr"] = 0.0
            f["bar_body_pct_30s_current"] = 0.5
            f["bar_wickiness_30s_current"] = 0.0

    def _ckp_1m_state(self, ev: EventState, f: dict) -> None:
        """§6.4 D — 5 features."""
        d = ev.signal_direction
        atr = max(ev.atr_at_signal, 1e-9)
        cur_px = self._current_1s_close()

        f["regime_1m_direction"] = int(self.regime_1m.regime)
        # Note: regime_1m_direction is constrained to {-1, 1} per
        # contract (regime never resets to 0 after warmup). For safety
        # we clamp 0 to signal_direction in case of edge.
        if f["regime_1m_direction"] == 0:
            f["regime_1m_direction"] = int(d)

        f["regime_1m_duration_bars"] = int(self.regime_1m.bars_in_regime)

        if self.sma20_1m.initialized:
            f["price_vs_sma20_1m_atr_checkpoint"] = (
                (cur_px - self.sma20_1m.value) / atr)
        else:
            f["price_vs_sma20_1m_atr_checkpoint"] = 0.0

        if self.regime_1m.ema3.initialized:
            f["price_vs_ema3_1m_atr_checkpoint"] = (
                (cur_px - self.regime_1m.ema3.value) / atr)
        else:
            f["price_vs_ema3_1m_atr_checkpoint"] = 0.0

        if (self.regime_1m.emaH_3.initialized
                and self.regime_1m.emaL_3.initialized):
            f["ema_spread_1m_atr_checkpoint"] = (
                self.regime_1m.emaH_3.value
                - self.regime_1m.emaL_3.value) / atr
        else:
            f["ema_spread_1m_atr_checkpoint"] = 0.0

    def _ckp_5m_state(self, ev: EventState, f: dict) -> None:
        """§6.4 E — 5 features."""
        d = ev.signal_direction
        atr = max(ev.atr_at_signal, 1e-9)

        f["regime_5m_aligned"] = (
            1 if self.regime_5m.regime == d else 0)
        f["regime_5m_direction"] = int(self.regime_5m.regime)
        f["regime_5m_duration_bars"] = int(
            self.regime_5m.bars_in_regime)

        if len(self._prev_ema3_5m) >= 6:
            f["ema3_slope_5m_atr"] = (
                self._prev_ema3_5m[-1] - self._prev_ema3_5m[0]) / atr
        else:
            f["ema3_slope_5m_atr"] = 0.0

        if (self.regime_5m.emaH_3.initialized
                and self.regime_5m.emaL_3.initialized):
            f["ema_spread_5m_atr"] = (
                self.regime_5m.emaH_3.value
                - self.regime_5m.emaL_3.value) / atr
        else:
            f["ema_spread_5m_atr"] = 0.0

    def _ckp_micro(self, ev: EventState, current_ts: int,
                      f: dict) -> None:
        """§6.4 F — 7 features. Last 12 1s bars at decision_time."""
        atr = max(ev.atr_at_signal, 1e-9)
        d = ev.signal_direction

        # Last 12 1s bars from _recent_1s. _recent_1s[-1] is the 1s bar
        # at ts_event = current_ts (just appended in _on_1s before
        # emit). We want the 12 bars ending at current_ts → those are
        # _recent_1s[-12:].
        bars = list(self._recent_1s)[-12:]
        n = len(bars)
        if n < 2:
            # Not enough history
            f["micro_same_dir_count_12s"] = 0
            f["micro_opp_dir_count_12s"] = 0
            f["micro_aligned"] = 0
            f["micro_opposing"] = 0
            f["micro_net_return_atr"] = 0.0
            f["micro_range_compression"] = 1.0
            f["micro_body_pct_avg"] = 0.5
            return

        # Count same/opposite dir moves (close-to-close)
        same_dir = 0
        opp_dir = 0
        for i in range(1, n):
            diff = bars[i][4] - bars[i - 1][4]  # close - prev close
            if diff == 0:
                continue
            move_sign = 1 if diff > 0 else -1
            if move_sign == d:
                same_dir += 1
            else:
                opp_dir += 1
        f["micro_same_dir_count_12s"] = int(same_dir)
        f["micro_opp_dir_count_12s"] = int(opp_dir)

        total = same_dir + opp_dir
        threshold = 7 / 12  # 0.583
        f["micro_aligned"] = (
            1 if total > 0 and same_dir / total >= threshold else 0)
        f["micro_opposing"] = (
            1 if total > 0 and opp_dir / total >= threshold else 0)

        f["micro_net_return_atr"] = (
            (bars[-1][4] - bars[0][4]) * d / atr)

        # Range compression: mean range last 6 / mean range prior 6
        if n >= 12:
            last6 = bars[-6:]
            prior6 = bars[-12:-6]
            last_r = sum(b[2] - b[3] for b in last6) / 6
            prior_r = sum(b[2] - b[3] for b in prior6) / 6
            f["micro_range_compression"] = (
                last_r / prior_r if prior_r > 0 else 1.0)
        else:
            f["micro_range_compression"] = 1.0

        # Body pct avg over last 12
        bodies = []
        for b in bars:
            r = b[2] - b[3]
            if r > 0:
                bodies.append(abs(b[4] - b[1]) / r)
        f["micro_body_pct_avg"] = (
            sum(bodies) / len(bodies) if bodies else 0.5)

    def _ckp_progress(self, ev: EventState, f: dict) -> None:
        """§6.5 A — 6 features (1s-granularity since-signal progress)."""
        atr = max(ev.atr_at_signal, 1e-9)
        d = ev.signal_direction
        cur_px = self._current_1s_close()
        sig_px = ev.bar1.c

        f["max_progress_since_signal_atr"] = ev.max_progress_atr
        f["max_pullback_since_signal_atr"] = ev.max_pullback_atr
        f["current_progress_atr"] = (cur_px - sig_px) * d / atr

        # current_pullback_from_local_peak: (max_progress_price - cur)
        # × d / atr; clipped at 0 (since-peak implies cur <= peak in
        # trade direction)
        if ev.max_progress_price is not None:
            pullback = (ev.max_progress_price - cur_px) * d / atr
            f["current_pullback_from_local_peak_atr"] = max(0.0, pullback)
        else:
            f["current_pullback_from_local_peak_atr"] = 0.0

        # Efficiency: max_progress / (max_progress + max_pullback)
        denom = ev.max_progress_atr + ev.max_pullback_atr
        f["progress_efficiency_since_signal"] = (
            ev.max_progress_atr / denom if denom > 1e-9 else 0.0)

        f["mfe_mae_ratio_so_far"] = (
            ev.max_progress_atr / ev.max_pullback_atr
            if ev.max_pullback_atr > 1e-9 else 0.0)

    def _ckp_continuation(self, ev: EventState, current_ts: int,
                            f: dict) -> None:
        """§6.5 B — 7 features (continuation + stall)."""
        f["continuation_count_since_signal"] = int(ev.continuation_count)
        f["consecutive_continuation_bars"] = int(ev.consec_continuation)
        f["bars_since_last_continuation"] = int(ev.bars_since_continuation)

        # New progress flags: did max_progress get achieved within the
        # window [decision_time - Xs, decision_time]?
        if ev.t_peak_ns is None:
            elapsed_since_peak_s = 0.0
        else:
            elapsed_since_peak_s = (current_ts - ev.t_peak_ns) / 1e9

        f["new_progress_in_last_30s_flag"] = (
            1 if elapsed_since_peak_s <= 30.0 else 0)
        f["new_progress_in_last_60s_flag"] = (
            1 if elapsed_since_peak_s <= 60.0 else 0)

        # Stall flags: 1 if the time since T_peak exceeds the threshold.
        # Per §15.7: if max_progress == 0, T_peak = signal_time, so
        # elapsed_since_peak = (current_ts - signal_time)/1e9 = T_d.
        f["stall_60s_flag"] = (
            1 if elapsed_since_peak_s > 60.0 else 0)
        f["stall_90s_flag"] = (
            1 if elapsed_since_peak_s > 90.0 else 0)

    def _ckp_extension(self, ev: EventState, f: dict) -> None:
        """§6.5 C — 2 features (kept phase 1)."""
        atr = max(ev.atr_at_signal, 1e-9)
        d = ev.signal_direction
        cur_px = self._current_1s_close()
        sig_px = ev.bar1.c

        # Alias of current_progress_atr
        f["extension_from_signal_atr"] = (cur_px - sig_px) * d / atr

        # From last pullback: (cur - min_fav_since_peak) × d / atr;
        # always >= 0 by construction (since min_fav is below/above cur
        # in the trade direction)
        if ev.min_fav_price_since_peak is not None:
            ext = (cur_px - ev.min_fav_price_since_peak) * d / atr
            f["extension_from_last_pullback_atr"] = max(0.0, ext)
        else:
            f["extension_from_last_pullback_atr"] = 0.0

    def _ckp_session_at_checkpoint(self, ev: EventState,
                                     current_ts: int,
                                     f: dict) -> None:
        """§6.6 — 7 features at decision_time."""
        atr = max(ev.atr_at_signal, 1e-9)
        dt_ct = pd.Timestamp(
            current_ts, unit="ns", tz="UTC").astimezone(CT)
        ct_min = dt_ct.hour * 60 + dt_ct.minute
        f["is_rth_checkpoint"] = 1 if 510 <= ct_min < 900 else 0
        f["hour_of_day_checkpoint"] = int(dt_ct.hour)
        f["minute_of_hour_checkpoint"] = int(dt_ct.minute)
        f["minutes_since_rth_open_checkpoint"] = int(ct_min - 510)

        cur_px = self._current_1s_close()
        if self._session_high > -1e17:
            f["distance_from_session_high_atr_checkpoint"] = (
                self._session_high - cur_px) / atr
        else:
            f["distance_from_session_high_atr_checkpoint"] = 0.0
        if self._session_low < 1e17:
            f["distance_from_session_low_atr_checkpoint"] = (
                cur_px - self._session_low) / atr
        else:
            f["distance_from_session_low_atr_checkpoint"] = 0.0
        if self._session_high > -1e17 and self._session_low < 1e17:
            mid = (self._session_high + self._session_low) / 2.0
            f["distance_from_session_mid_atr_checkpoint"] = (
                cur_px - mid) / atr
        else:
            f["distance_from_session_mid_atr_checkpoint"] = 0.0

    # --------------------------------------------------------------
    # Termination + output emission
    # --------------------------------------------------------------
    def _terminate_event(self, ev: EventState, reason: str,
                          exit_time: int, exit_price: float):
        if ev.terminated:
            return
        ev.terminated = True
        ev.regime_exit_time = exit_time
        ev.regime_exit_price = exit_price
        ev.regime_exit_reason = reason

        if reason == "regime_flip":
            self._diag["events_terminated_regime_flip"] += 1
        elif reason == "max_horizon_reached":
            self._diag["events_terminated_max_horizon"] += 1
        elif reason == "data_end":
            self._diag["events_terminated_data_end"] += 1

        # Mark any snapped checkpoints whose fill_time never arrived as
        # unfillable (fillable_at_T stays False by default). Windows on
        # existing trackers are censored beyond elapsed_s at exit_time.
        for T, cp in ev.checkpoints.items():
            if cp.dead_before_T:
                continue
            tracker = ev.forward_trackers.get(T)
            if tracker is None:
                # Either fill_time > exit_time (never arrived) OR fill
                # already resolved as unfillable. Either way, no tracker
                # → fillable_at_T remains False.
                continue
            # Tracker exists — censor any forward windows that extend
            # past exit_time.
            elapsed_s = (exit_time - tracker.fill_time) / 1e9
            if elapsed_s < 0:
                # Defensive — shouldn't happen since we only create
                # trackers when event is alive at fill_time.
                elapsed_s = 0.0
            tracker.on_termination_censor(elapsed_s)

        # Emit records for each checkpoint
        self._emit_event_records(ev)

        # Remove from active list (caller may still iterate; filter
        # in _update_active_events_on_1m via `not ev.terminated`)

    def _emit_event_records(self, ev: EventState):
        """One row per (event_id, T) to features table, and another to
        labels table. Label computation finalized here since all
        forward data is now available."""
        event_meta = {
            "event_id": ev.event_id,
            "signal_time": ev.signal_time,
            "signal_direction": ev.signal_direction,
            "regime_exit_time": ev.regime_exit_time,
            "regime_exit_price": ev.regime_exit_price,
            "regime_exit_reason": ev.regime_exit_reason,
            "event_total_duration_s":
                (ev.regime_exit_time - ev.signal_time) / 1e9,
        }

        for T in sorted(ev.checkpoints.keys()):
            cp = ev.checkpoints[T]
            if cp.dead_before_T:
                continue  # no feature row for dead checkpoints

            tracker = ev.forward_trackers.get(T)
            actual_fill_time = (
                tracker.fill_time if tracker is not None else None)

            # Feature row — merge root + checkpoint features + fill state
            frow = {
                **event_meta,
                "checkpoint_s": T,
                "decision_time":
                    ev.signal_time + T * 1_000_000_000,
                "decision_fill_time":
                    ev.signal_time + (T + 30) * 1_000_000_000,
                "alive_at_T": cp.alive_at_T,
                "dead_before_T": cp.dead_before_T,
                "fillable_at_T": cp.fillable_at_T,
                "fill_time_intended": cp.fill_time,
                "fill_time_actual": actual_fill_time,
                "fill_price": cp.fill_price,
                **ev.root_features,
                **cp.features,
            }
            self._feature_records.append(frow)

            lrow = self._build_label_row(ev, T, cp, tracker, event_meta)
            self._label_records.append(lrow)

        # Event summary row
        self._event_summary_records.append({
            **event_meta,
            "n_checkpoints": len([T for T, cp in ev.checkpoints.items()
                                   if not cp.dead_before_T]),
        })

    def _build_label_row(self, ev: EventState, T: int,
                           cp: CheckpointFeatures,
                           tracker: Optional[ForwardPathTracker],
                           event_meta: dict) -> dict:
        """Build one label row per checkpoint (§7).

        Unfillable checkpoints emit all forward labels as NaN/False; the
        regime-exit PnL block is still populated where possible (useful
        for stratification: "would this trade have exited on regime
        flip even if we could have filled?"). Forward-path labels
        require a tracker, which is only created on successful fill.
        """
        EPS = 1e-9
        lrow: dict = {
            "event_id": ev.event_id,
            "checkpoint_s": T,
            "terminated_reason": ev.regime_exit_reason,
            "terminated_time_s": event_meta["event_total_duration_s"],
            "event_total_duration_s":
                event_meta["event_total_duration_s"],
            "fillable_at_T": cp.fillable_at_T,
        }

        # §7.1 forward MFE/MAE grid + derived ratios + censoring flags
        for w in FWD_WINDOWS_S:
            if tracker is not None:
                mfe = tracker.peak_mfe_by_window[w]
                mae = tracker.peak_mae_by_window[w]
                cens = tracker.window_closed_censored[w]
            else:
                mfe, mae, cens = None, None, True
            lrow[f"mfe_{w}s_atr"] = mfe
            lrow[f"mae_{w}s_atr"] = mae
            lrow[f"mfe_{w}s_censored"] = 1 if cens else 0
            lrow[f"mae_{w}s_censored"] = 1 if cens else 0
            if tracker is not None and mfe is not None and mae is not None:
                lrow[f"mfe_mae_ratio_{w}s"] = mfe / max(mae, EPS)
            else:
                lrow[f"mfe_mae_ratio_{w}s"] = None

        # §7.2 bracket races
        for _, _, name in [(pt, sl, n) for pt, sl, n in BRACKETS]:
            if tracker is not None:
                lrow[name] = tracker.bracket_outcomes[name]
                lrow[f"bracket_resolution_time_s_{name}"] = (
                    tracker.bracket_resolution_time_s[name])
                lrow[f"bracket_resolution_price_{name}"] = (
                    tracker.bracket_resolution_price[name])
            else:
                lrow[name] = None
                lrow[f"bracket_resolution_time_s_{name}"] = None
                lrow[f"bracket_resolution_price_{name}"] = None

        # §7.3 regime-exit PnL (from execution_price at fill_time to
        # regime_exit_price). Only defined when fill occurred.
        if tracker is not None and ev.regime_exit_price is not None:
            ep = tracker.fill_price
            d = ev.signal_direction
            pnl_pts = (ev.regime_exit_price - ep) * d
            lrow["regime_exit_pnl_pts"] = pnl_pts
            lrow["regime_exit_pnl_atr"] = (
                pnl_pts / max(ev.atr_at_signal, EPS))
            lrow["regime_exit_pnl_dollars"] = (
                pnl_pts * NQ_MULT - COMMISSION)
            lrow["regime_exit_time_s"] = (
                (ev.regime_exit_time - tracker.fill_time) / 1e9)
        else:
            lrow["regime_exit_pnl_pts"] = None
            lrow["regime_exit_pnl_atr"] = None
            lrow["regime_exit_pnl_dollars"] = None
            lrow["regime_exit_time_s"] = None

        # §7.4 clean-path booleans (censored-as-0 per project policy)
        def _cp_flag(cond: Optional[bool]) -> int:
            return 1 if cond else 0

        if tracker is not None:
            mfe = {w: tracker.peak_mfe_by_window[w]
                    for w in FWD_WINDOWS_S}
            mae = {w: tracker.peak_mae_by_window[w]
                    for w in FWD_WINDOWS_S}
            ratio = {w: mfe[w] / max(mae[w], EPS) for w in FWD_WINDOWS_S}
            lrow["clean_path_120s"] = _cp_flag(
                mfe[120] >= 1.0 and ratio[120] > 1.0)
            lrow["clean_path_180s"] = _cp_flag(
                mfe[180] >= 1.0 and ratio[180] > 1.0)
            lrow["clean_path_300s"] = _cp_flag(
                mfe[300] >= 1.0 and ratio[300] > 1.0)
            lrow["clean_path_600s"] = _cp_flag(
                mfe[600] >= 1.0 and ratio[600] > 1.0)
            lrow["strong_followthrough_300s"] = _cp_flag(
                mfe[300] >= 1.5 and ratio[300] > 2.0)
            lrow["fast_fail_60s"] = _cp_flag(
                mae[60] >= 1.0 and mfe[60] < 0.5)
            lrow["stall_then_reverse_180s"] = _cp_flag(
                mfe[60] < 0.5 and mae[180] >= 1.0)
        else:
            for n in ("clean_path_120s", "clean_path_180s",
                       "clean_path_300s", "clean_path_600s",
                       "strong_followthrough_300s",
                       "fast_fail_60s", "stall_then_reverse_180s"):
                lrow[n] = 0

        return lrow

    # --------------------------------------------------------------
    # Output writing
    # --------------------------------------------------------------
    def _write_outputs(self):
        out_dir = Path(self._cfg.features_output).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        if self._feature_records:
            df_f = pd.DataFrame(self._feature_records)
            df_f.to_parquet(self._cfg.features_output, index=False)

        if self._label_records:
            df_l = pd.DataFrame(self._label_records)
            df_l.to_parquet(self._cfg.labels_output, index=False)

        if self._event_summary_records:
            df_e = pd.DataFrame(self._event_summary_records)
            df_e.to_parquet(
                self._cfg.events_summary_output, index=False)

        # QA log
        qa_lines = [
            "Collector v2 collection QA log",
            f"  feature rows: {len(self._feature_records):,}",
            f"  label rows:   {len(self._label_records):,}",
            f"  events:       {len(self._event_summary_records):,}",
            "",
            "Diagnostics:",
        ]
        for k, v in sorted(self._diag.items()):
            qa_lines.append(f"  {k}: {v:,}")

        # Fill-slippage audit (required while label semantics depend on
        # the 'first available 1s bar ≥ intended fill_time' rule).
        qa_lines.extend(self._fill_slippage_audit())

        Path(self._cfg.qa_log_output).write_text(
            "\n".join(qa_lines), encoding="utf-8")

    def _fill_slippage_audit(self) -> list[str]:
        """Diagnostic: exact vs delayed fills, slippage distribution,
        RTH vs ETH split. Emitted to the QA log."""
        if not self._feature_records:
            return ["", "(no feature rows — fill audit skipped)"]
        df = pd.DataFrame(self._feature_records)
        f = df[df["fillable_at_T"] == True].copy()
        total = len(df)
        fillable = len(f)

        lines = ["", "=" * 56, "Fill-semantics audit (WO3 rule):",
                  "-" * 56]
        lines.append(
            f"  Fillable: {fillable:,} / {total:,} "
            f"({100 * fillable / total:.1f}%)")
        lines.append(
            f"  Unfillable: {total - fillable:,} "
            f"({100 * (total - fillable) / total:.1f}%)")

        if fillable == 0:
            return lines

        slip_s = ((f["fill_time_actual"] - f["fill_time_intended"])
                  / 1e9)
        exact = int((slip_s == 0).sum())
        delayed = fillable - exact
        lines.append("")
        lines.append(f"  Exact-match fills (slip = 0s): {exact:,} "
                     f"({100 * exact / fillable:.1f}%)")
        lines.append(f"  Delayed fills (slip > 0s):     {delayed:,} "
                     f"({100 * delayed / fillable:.1f}%)")
        lines.append("")
        lines.append("  Slippage distribution (seconds):")
        bins = [(0, 0, "exact"), (0, 1, "0–1s"), (1, 5, "1–5s"),
                 (5, 15, "5–15s"), (15, 30, "15–30s"),
                 (30, 60, "30–60s")]
        for lo, hi, lbl in bins:
            if lo == hi:
                n = int((slip_s == lo).sum())
            else:
                n = int(((slip_s > lo) & (slip_s <= hi)).sum())
            pct = 100 * n / fillable
            lines.append(f"    {lbl:<12} {n:>6,}  ({pct:5.1f}%)")
        lines.append(f"    max slip: {slip_s.max():.1f}s")
        lines.append(f"    mean slip: {slip_s.mean():.2f}s")

        # RTH vs ETH split (using minutes_since_rth_open_checkpoint
        # and is_rth_checkpoint on the feature row)
        if "is_rth_checkpoint" in f.columns:
            rth = f[f["is_rth_checkpoint"] == 1]
            eth = f[f["is_rth_checkpoint"] == 0]
            lines.append("")
            lines.append("  By session (RTH = 08:30–15:00 CT):")
            for lbl, sub in [("RTH", rth), ("ETH", eth)]:
                if len(sub) == 0:
                    lines.append(f"    {lbl}: 0 rows")
                    continue
                sl = ((sub["fill_time_actual"]
                       - sub["fill_time_intended"]) / 1e9)
                ex = int((sl == 0).sum())
                lines.append(
                    f"    {lbl:<4} n={len(sub):>6,}  "
                    f"exact={ex:>6,} ({100*ex/len(sub):5.1f}%)  "
                    f"mean_slip={sl.mean():5.2f}s  "
                    f"max_slip={sl.max():5.1f}s")

        lines.append("-" * 56)
        lines.append(
            "  Forward labels and bracket races anchor off "
            "fill_time_actual / fill_price (the actual fill bar),")
        lines.append(
            "  NOT fill_time_intended. Audit this invariant via the "
            "parity harness (WO5).")
        return lines

    # --------------------------------------------------------------
    # Utilities
    # --------------------------------------------------------------
    def _current_1s_close(self) -> float:
        if self._recent_1s:
            return self._recent_1s[-1][4]
        return 0.0
