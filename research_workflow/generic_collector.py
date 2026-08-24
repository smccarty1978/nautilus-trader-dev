"""Canonical Flip Prediction Collector Strategy for NautilusTrader.
===================================================================
Executes live regime tracking, candidate generation, feature computation,
and forward outcome observation inside the NT event loop on streaming bars.
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from features.trackers.velocity import ArrivalVelocityTracker
from features.trackers.volume import ArrivalVolumeTracker
from features.trackers.pullback import PullbackTracker
from features.trackers.ohlcv_delta import OHLCVDeltaTracker
from features.trackers.price_levels import PriceLevelTracker
from features.trackers.rolling_5m_productivity import Rolling5mProductivityTracker
from features.trackers.structural_regime_geometry import StructuralRegimeGeometryTracker
from features.trackers.wick import WickTracker
from features.trackers.range_position import RangePositionTracker
from features.registry import resolve_runtime_feature_aliases
from backtests.nt_runtime.phase0 import authorize_execution
from utils.session_boundaries import is_in_session, session_close_ns
from research_workflow.execution_plan import CompiledExecutionPlan

from datetime import datetime, timezone
import pytz

NS = 1_000_000_000
CT = pytz.timezone("America/Chicago")

# Terminal dispositions. Every emitted candidate reaches exactly one of these.
DISPOSITION_POSITIVE = "LABELED_POSITIVE"
DISPOSITION_NEGATIVE = "LABELED_NEGATIVE"
DISPOSITION_CENSORED = "CENSORED"

# Why a candidate was censored rather than labeled.
CENSOR_SESSION_END = "SESSION_END"
CENSOR_DATA_END = "DATA_END"
PROGRESS_GAP_NS = 120 * NS
CANDIDATE_STEP_NS = 5 * NS
CANDIDATE_TIMEOUT_NS = 1800 * NS


class FastOHLCVRingBuffer:
    """Zero-allocation circular buffer for 1-second OHLCV rolling window statistics."""
    def __init__(self, capacity: int = 3600):
        self.capacity = capacity
        self.ts = np.zeros(capacity, dtype=np.int64)
        self.opens = np.zeros(capacity, dtype=np.float64)
        self.highs = np.zeros(capacity, dtype=np.float64)
        self.lows = np.zeros(capacity, dtype=np.float64)
        self.closes = np.zeros(capacity, dtype=np.float64)
        self.volumes = np.zeros(capacity, dtype=np.float64)
        self.deltas = np.zeros(capacity, dtype=np.float64)
        self.bear_vols = np.zeros(capacity, dtype=np.float64)
        self.head = 0
        self.count = 0

        self._rth_active = False
        self._rth_start_ts = None
        self._rth_vol_cum = 0.0
        self._rth_abs_delta_cum = 0.0

    def on_rth_open(self, ts: int):
        self._rth_active = True
        self._rth_start_ts = ts
        self._rth_vol_cum = 0.0
        self._rth_abs_delta_cum = 0.0

    def on_rth_close(self):
        self._rth_active = False

    def append(self, ts: int, o: float, h: float, l: float, c: float, v: float, d: float):
        idx = self.head
        self.ts[idx] = ts
        self.opens[idx] = o
        self.highs[idx] = h
        self.lows[idx] = l
        self.closes[idx] = c
        self.volumes[idx] = v
        self.deltas[idx] = d

        rng = h - l
        bull_ratio = min(max((c - l) / rng, 0.0), 1.0) if rng > 0 else 0.5
        self.bear_vols[idx] = v * (1.0 - bull_ratio)

        self.head = (self.head + 1) % self.capacity
        if self.count < self.capacity:
            self.count += 1

        if self._rth_active:
            self._rth_vol_cum += v
            self._rth_abs_delta_cum += abs(d)


class RegimeEngine:
    """Standardized 14-period Wilder ATR & Dual-EMA Regime Tracker."""
    ALPHA3 = 0.5
    ALPHA9 = 0.2
    ATR_P = 14

    def __init__(self) -> None:
        self.ema3_h: Optional[float] = None
        self.ema9_h: Optional[float] = None
        self.ema3_l: Optional[float] = None
        self.ema9_l: Optional[float] = None
        self.prev_c: Optional[float] = None
        self.atr_warmup: List[float] = []
        self.atr: Optional[float] = None
        self.regime: int = 0  # +1 = bullish, -1 = bearish, 0 = neutral

    def update(self, h: float, l: float, c: float) -> int:
        if self.ema3_h is None:
            self.ema3_h = self.ema9_h = h
            self.ema3_l = self.ema9_l = l
        else:
            self.ema3_h = self.ALPHA3 * h + (1 - self.ALPHA3) * self.ema3_h
            self.ema9_h = self.ALPHA9 * h + (1 - self.ALPHA9) * self.ema9_h
            self.ema3_l = self.ALPHA3 * l + (1 - self.ALPHA3) * self.ema3_l
            self.ema9_l = self.ALPHA9 * l + (1 - self.ALPHA9) * self.ema9_l

        tr = h - l if self.prev_c is None else max(h - l, abs(h - self.prev_c), abs(l - self.prev_c))
        self.prev_c = c

        if self.atr is None:
            self.atr_warmup.append(tr)
            if len(self.atr_warmup) == self.ATR_P:
                self.atr = sum(self.atr_warmup) / self.ATR_P
                self.atr_warmup = []
        else:
            self.atr = (self.atr * (self.ATR_P - 1) + tr) / self.ATR_P

        new_regime = self.regime
        if c > (self.ema3_h or 0) and c > (self.ema9_h or 0):
            new_regime = 1
        elif c < (self.ema3_l or 0) and c < (self.ema9_l or 0):
            new_regime = -1

        if new_regime != 0 and new_regime != self.regime:
            self.regime = new_regime

        return self.regime


class FlipPredictionCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    prevailing_regime: str = "bearish"       # 'bearish' (-1), 'bullish' (+1), or 'both'
    target_direction: str = "bullish"        # 'bullish' (+1), 'bearish' (-1), or 'both'
    horizon_seconds: int = 300               # forward horizon
    age_gate_seconds: int = 120              # minimum regime age before candidate declaration
    established_required: bool = True
    checkpoint_interval_seconds: int = 5
    running_mfe_atr_gte: float = 1.0
    new_progress_windows_gte: int = 2
    retained_mfe_ratio_gte: float = 0.5
    feature_list: Optional[List[str]] = None
    feature_requirements: dict = {}
    metadata_columns: tuple[str, ...] = ()
    phase0_manifest_path: str = ""
    feature_authority: str = "active"
    session: str = "RTH"                     # resolved via utils.session_boundaries
    session_end_censoring: bool = True       # from target_contract.censoring_policy


class FlipPredictionCollector(Strategy):
    """Canonical event-driven collector strategy for flip prediction research."""

    def __init__(self, config: FlipPredictionCollectorConfig) -> None:
        super().__init__(config)
        self.cfg = config
        # Benchmark-only ablation switch.  It is unset for all governed/runtime
        # executions and exists solely to measure marginal replay costs without
        # creating alternate production collectors.
        self._benchmark_mode = os.environ.get("NT_COLLECTOR_ABLATION", "")
        self._benchmark_bars_1s = 0
        self._benchmark_bars_1m = 0
        self.bars_1s_count = 0
        self.bars_1m_count = 0
        # Bind the two subscribed bar types once.  Converting ``bar_type.spec``
        # to a string for every 1s callback was a hot-loop tax introduced by
        # the generic dispatch path; equality against the immutable BarType is
        # both clearer and substantially cheaper.
        self._bar_type_1s = BarType.from_str(config.bar_type_1s)
        self._bar_type_1m = BarType.from_str(config.bar_type_1m)
        if not config.phase0_manifest_path:
            raise RuntimeError("phase-zero authorization missing; collection and fit are refused")
        phase0 = authorize_execution(Path(config.phase0_manifest_path), feature_authority=config.feature_authority)
        self._feature_authority = phase0.get("feature_authority", "active")
        requirements = config.feature_requirements if isinstance(config.feature_requirements, dict) else {}
        resolved_instances = requirements.get("resolved_instances", ())
        self._study_feature_aliases = tuple(dict.fromkeys(
            str(item.get("physical_alias")) for item in resolved_instances
            if item.get("physical_alias")
        )) or tuple(dict.fromkeys(requirements.get("aliases", ())))
        self._metadata_columns = tuple(config.metadata_columns)
        # V2-native studies declare a small explicit surface.  Keep this fast
        # path deliberately narrow: it is only enabled when every requested
        # alias is produced by the structural/rolling/arrival/context providers
        # below.  All other studies retain the historical full-surface path.
        self._compact_supported = {
            "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr",
            "prior_1m_regime_range_atr", "prior_5m_regime_efficiency",
            "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
            "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
            "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr",
            "arrival_velocity", "arrival_acceleration", "ema_slope",
        }
        self._compact_surface = bool(self._study_feature_aliases) and set(
            self._study_feature_aliases
        ).issubset(self._compact_supported)
        self.is_both_directions = config.prevailing_regime == "both"
        self.prevailing_dir = 0 if self.is_both_directions else (1 if config.prevailing_regime == "bullish" else -1)
        self.target_dir = 0 if self.is_both_directions else (1 if config.target_direction == "bullish" else -1)
        self.trade_dir = -self.prevailing_dir

        self._is_targeted_60 = bool(config.feature_list and len(config.feature_list) == 60)

        self.regime_engine = RegimeEngine()
        self.ohlcv_tracker = OHLCVDeltaTracker()
        self.price_level_tracker = PriceLevelTracker()
        self.structural_geometry_tracker = StructuralRegimeGeometryTracker()
        self.rolling_productivity_tracker = Rolling5mProductivityTracker(window_seconds=300)
        self.wick_tracker = WickTracker()
        self.range_position_tracker = RangePositionTracker()

        if self._is_targeted_60:
            self.ring = FastOHLCVRingBuffer(capacity=3600)
            self.velocity_tracker = None
            self.volume_tracker = None
        else:
            self.ring = None
            self.velocity_tracker = ArrivalVelocityTracker(maxlen=60)
            self.volume_tracker = ArrivalVolumeTracker(maxlen=60)

        self.highs_1s: deque[float] = deque(maxlen=60)
        self.lows_1s: deque[float] = deque(maxlen=60)
        self.closes_1s: deque[float] = deque(maxlen=60)
        self.short_ema_history: deque[float] = deque(maxlen=20)
        self.long_ema_history: deque[float] = deque(maxlen=20)
        self.bars_since_breach_1m: List[Any] = []
        self.breach_price: Optional[float] = None
        self.bars_in_regime: int = 0

        # 5m bar accumulator
        self._current_5m_open: Optional[float] = None
        self._current_5m_high: float = -float("inf")
        self._current_5m_low: float = float("inf")

        # Regime state tracking
        self.active_regime_dir: int = 0
        self.regime_start_ns: int = 0
        self.regime_start_close: float = 0.0
        self.regime_frozen_atr: float = 0.0
        self.highest_high_since_flip: float = -float("inf")
        self.lowest_low_since_flip: float = float("inf")
        self.mfe_progress_count: int = 0
        self.mfe_progress_last_extreme_ts: Optional[int] = None
        self.mfe_progress_previous_extreme: float = 0.0
        self.next_checkpoint_index: int = 0

        # Buffers for retro-accumulation across minute boundaries
        self.minute_1s_buffer: List[Tuple[int, float, float, float, float]] = []
        self.was_rth: bool = False
        self.last_close: Optional[float] = None
        # Latest observed event time, used to stamp when a run-end censoring occurred.
        self.last_ts_seen: Optional[int] = None

        # Telemetry & Output logs
        self.candidates_log: List[Dict[str, Any]] = []
        self.observations_log: List[Dict[str, Any]] = []
        self.pending_candidates: List[Dict[str, Any]] = []
        self._next_pending_horizon_ns: Optional[int] = None
        # Compile the declared surface after all providers exist.  The resulting
        # immutable plan is the only object consulted by the compact hot path.
        self._execution_plan = CompiledExecutionPlan.for_collector(
            self, self._study_feature_aliases
        )

    def _append_candidate(self, record: Dict[str, Any]) -> None:
        """Emit only the study-declared surface plus canonical key/metadata fields."""
        if self._benchmark_mode in {"checkpoint_only", "baseline", "structural", "rolling", "full_no_target"}:
            return
        aliases = set(self._study_feature_aliases or self.cfg.feature_list or ())
        # Causality evidence is a runtime metadata field, not a feature.  It is
        # required by the smoke validator to prove source availability for every
        # persisted candidate row.
        keep = {"observation_ts", "regime_start_ns", "checkpoint_index", "triggering_1s_ts_init"}
        keep.update(self._metadata_columns)
        keep.update(aliases)
        self.candidates_log.append({key: value for key, value in record.items() if key in keep})

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type_1s)
        self.subscribe_bars(self._bar_type_1m)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type == self._bar_type_1s:
            self._benchmark_bars_1s += 1
            self.bars_1s_count = self._benchmark_bars_1s
        elif bar.bar_type == self._bar_type_1m:
            self._benchmark_bars_1m += 1
            self.bars_1m_count = self._benchmark_bars_1m
        if self._benchmark_mode == "empty_generic":
            return
        if self._benchmark_mode == "regime_state" and bar.bar_type == self._bar_type_1s:
            return
        if bar.bar_type == self._bar_type_1s:
            self._handle_1s_bar(bar)
        elif bar.bar_type == self._bar_type_1m:
            self._handle_1m_bar(bar)

    def _handle_1m_bar(self, bar: Bar) -> None:
        ts_event = int(bar.ts_event)
        ts_avail = int(bar.ts_init)
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume)

        # 1. Update Wilder ATR & Dual-EMA Regime Tracker
        old_regime = self.regime_engine.regime
        new_regime = self.regime_engine.update(h, l, c)
        atr_val = self.regime_engine.atr or 0.0

        if self.regime_engine.ema3_h is not None:
            self.short_ema_history.append((self.regime_engine.ema3_h + (self.regime_engine.ema3_l or self.regime_engine.ema3_h)) / 2.0)
            self.long_ema_history.append((self.regime_engine.ema9_h + (self.regime_engine.ema9_l or self.regime_engine.ema9_h)) / 2.0)

        # 2. Check 5m boundary and dispatch completed 5m bar to Structural Tracker
        ts_pd = pd.Timestamp(ts_avail, tz="UTC").tz_convert("America/Chicago")
        minute_of_day = ts_pd.hour * 60 + ts_pd.minute

        if self._current_5m_open is None:
            self._current_5m_open = o
        self._current_5m_high = max(self._current_5m_high, h)
        self._current_5m_low = min(self._current_5m_low, l)

        if minute_of_day % 5 == 0:
            self.structural_geometry_tracker.on_5m_bar(
                close_ts=ts_avail,
                direction=self.active_regime_dir if self.active_regime_dir != 0 else new_regime,
                open_=self._current_5m_open,
                high=self._current_5m_high,
                low=self._current_5m_low,
                close=c,
                atr=atr_val,
            )
            self._current_5m_open = None
            self._current_5m_high = -float("inf")
            self._current_5m_low = float("inf")

        # 3. Handle session and RTH transitions for OHLCV Tracker
        is_rth_now = is_in_session(ts_avail, self.cfg.session)
        if not self._compact_surface:
            if is_rth_now and not self.was_rth:
                self.ohlcv_tracker.reset_rth(ts_avail)
                if self.ring:
                    self.ring.on_rth_open(ts_avail)
            elif not is_rth_now and self.was_rth:
                self.ohlcv_tracker.end_rth()
                if self.ring:
                    self.ring.on_rth_close()
            self.was_rth = is_rth_now

            for buf_ts, buf_h, buf_l, buf_v, buf_d in self.minute_1s_buffer:
                if old_regime != 0:
                    self.ohlcv_tracker.accumulate_regime(buf_ts, buf_h, buf_l, buf_v, buf_d)
                self.ohlcv_tracker.accumulate_rth(buf_v, buf_d)

        # 4. Handle regime transition (flips)
        if new_regime != old_regime and new_regime != 0:
            self._on_regime_flip(
                new_regime=new_regime,
                flip_ts=ts_avail,
                open_price=o,
                close_price=c,
                atr_val=atr_val,
            )
            if not self._compact_surface:
                self.ohlcv_tracker.reset_regime(ts_avail, o)
            self.structural_geometry_tracker.on_1m_flip(
                direction=new_regime,
                start_ns=ts_avail,
                start_price=o,
                atr_start=atr_val,
                prior_end_close=self.last_close or c,
            )
            self.bars_in_regime = 0
            self.bars_since_breach_1m = []
            self.breach_price = None
        else:
            self.bars_in_regime += 1

        if not self._compact_surface:
            for buf_ts, buf_h, buf_l, buf_v, buf_d in self.minute_1s_buffer:
                self.ohlcv_tracker.accumulate_regime_rth(buf_ts, buf_h, buf_l, buf_v, buf_d)
            self.minute_1s_buffer = []

            self.price_level_tracker.update_1m(ts_avail, o, h, l, c, is_rth_now)
            self.wick_tracker.update(o, h, l, c)
            self.range_position_tracker.update(h, l, c)
            self.bars_since_breach_1m.append(bar)

    def _track_pending(self, cand_record: Dict[str, Any], T: int) -> None:
        """Registers a freshly emitted candidate for terminal disposition.

        Deliberately a separate, narrow dict rather than the candidate record itself:
        ``horizon_end_ts``/``session_close_ts`` are resolution bookkeeping, and the output
        contract in ``OutputManager.persist_collection`` rejects columns the study never
        declared. They belong to the observation surface, not the feature surface.
        """
        if self._benchmark_mode in {"checkpoint_only", "baseline", "structural", "rolling", "full_no_target"}:
            return
        self.pending_candidates.append({
            "observation_ts": cand_record["observation_ts"],
            "regime_start_ns": cand_record["regime_start_ns"],
            "regime_direction": cand_record["regime_direction"],
            "checkpoint_index": cand_record["checkpoint_index"],
            "horizon_end_ts": T + int(self.cfg.horizon_seconds) * NS,
            "session_close_ts": (
                session_close_ns(T, self.cfg.session)
                if self.cfg.session_end_censoring else None
            ),
        })
        horizon_end = T + int(self.cfg.horizon_seconds) * NS
        if self._next_pending_horizon_ns is None or horizon_end < self._next_pending_horizon_ns:
            self._next_pending_horizon_ns = horizon_end

    def _emit_observation(
        self,
        cand: Dict[str, Any],
        disposition: str,
        flip_ts: Optional[int],
        censor_reason: Optional[str] = None,
        censored_at_ts: Optional[int] = None,
    ) -> None:
        """Records the single terminal disposition of one candidate.

        Every emitted candidate passes through here exactly once. A candidate that simply
        stopped being tracked -- which is what used to happen to anything still pending
        when the run ended -- has no row at all, and a population that silently loses its
        unresolved members is conditioned on the future.
        """
        cand_ts = cand["observation_ts"]
        time_to_flip_s = ((flip_ts - cand_ts) / NS) if flip_ts is not None else None

        self.observations_log.append({
            "observation_ts": cand_ts,
            "regime_start_ns": cand["regime_start_ns"],
            "regime_direction": cand["regime_direction"],
            "checkpoint_index": cand["checkpoint_index"],
            "flip_ts": flip_ts,
            "time_to_flip_seconds": time_to_flip_s,
            "target_flip_within_horizon": (
                1 if disposition == DISPOSITION_POSITIVE
                else 0 if disposition == DISPOSITION_NEGATIVE
                else None
            ),
            "disposition": disposition,
            "censored": int(disposition == DISPOSITION_CENSORED),
            "censor_reason": censor_reason,
            "horizon_end_ts": cand.get("horizon_end_ts"),
            "session_close_ts": cand.get("session_close_ts"),
            "resolved_at_ts": censored_at_ts if flip_ts is None else flip_ts,
        })

    def _sweep_elapsed_horizons(self, now_ts: int, final: bool = False) -> None:
        """Resolves pending candidates whose horizon has fully elapsed with no flip.

        Called on every completed 1s bar. Resolving at horizon expiry rather than at the
        next flip matters for two reasons: the label stops depending on an event outside
        the horizon, and the recorded ``flip_ts`` stops carrying a timestamp the candidate
        was never entitled to see.

        Boundary handling (causal audit pass 01). The horizon is **inclusive** of its
        endpoint, so a flip at exactly ``horizon_end`` is a positive. Candidates sit on a
        5s grid from a minute-aligned regime start and the horizon is 300s, so every 12th
        candidate's ``horizon_end`` falls exactly on a minute boundary -- which is when
        flips happen. Because a 1s bar closing at T is dispatched before the 1m bar
        closing at the same T, sweeping with ``>=`` here would resolve such a candidate
        NEGATIVE moments before the coincident flip was visible, systematically
        mislabelling roughly one candidate in twelve.

        So a candidate whose horizon ends exactly at ``now_ts`` is held for one more tick,
        giving the same-timestamp 1m flip its chance. ``final=True`` (run end) resolves
        those, because by then no further bar can arrive to change the answer.
        """
        if self._benchmark_mode in {"checkpoint_only", "baseline", "structural", "rolling", "full_no_target"}:
            return
        if not self.pending_candidates:
            self._next_pending_horizon_ns = None
            return
        if not final and self._next_pending_horizon_ns is not None and now_ts < self._next_pending_horizon_ns:
            return
        still_pending: List[Dict[str, Any]] = []
        for cand in self.pending_candidates:
            horizon_end = cand["horizon_end_ts"]
            if horizon_end > now_ts or (horizon_end == now_ts and not final):
                still_pending.append(cand)
                continue
            # Horizon fully elapsed without an opposing flip.
            if self._is_censored_by_session(cand):
                self._emit_observation(
                    cand, DISPOSITION_CENSORED, None,
                    censor_reason=CENSOR_SESSION_END, censored_at_ts=now_ts,
                )
            else:
                self._emit_observation(cand, DISPOSITION_NEGATIVE, None, censored_at_ts=horizon_end)
        self.pending_candidates = still_pending
        self._next_pending_horizon_ns = (
            min((c["horizon_end_ts"] for c in still_pending), default=None)
        )

    def _is_censored_by_session(self, cand: Dict[str, Any]) -> bool:
        """True when the candidate's horizon extends past its own session close.

        ``target_contract.censoring_policy.session_end_censoring`` declares this. Such a
        candidate cannot be labeled from in-session data: a 'no flip' verdict would rest
        on a window the session never covered, and a 'flip' verdict would rest on price
        action from the next session.
        """
        if not self.cfg.session_end_censoring:
            return False
        session_close = cand.get("session_close_ts")
        if session_close is None:
            return False
        return cand["horizon_end_ts"] > session_close

    def on_stop(self) -> None:
        """Disposes every still-pending candidate before the run ends.

        Without this the collector simply dropped them. The candidates were already in
        ``candidates.parquet``; their absence from ``observations.parquet`` is exactly the
        future-conditioned selection the censoring policy exists to prevent.
        """
        # Any candidate whose horizon completed within the observed data has a known
        # outcome and must be labeled, not censored -- including the boundary case the
        # sweep deferred by one tick.
        if self.last_ts_seen is not None:
            self._sweep_elapsed_horizons(self.last_ts_seen, final=True)

        for cand in self.pending_candidates:
            reason = (
                CENSOR_SESSION_END if self._is_censored_by_session(cand) else CENSOR_DATA_END
            )
            self._emit_observation(
                cand, DISPOSITION_CENSORED, None,
                censor_reason=reason, censored_at_ts=self.last_ts_seen,
            )
        self.pending_candidates = []

    def _on_regime_flip(self, new_regime: int, flip_ts: int, open_price: float, close_price: float, atr_val: float) -> None:
        # Resolve pending observations on opposing flip
        target_dir = -self.active_regime_dir if self.is_both_directions else self.target_dir
        if (self.active_regime_dir in (-1, 1)) and new_regime == target_dir:
            for cand in self.pending_candidates:
                cand_ts = cand["observation_ts"]
                within_horizon = cand_ts <= flip_ts <= cand["horizon_end_ts"]

                if self._is_censored_by_session(cand):
                    # The horizon reached past the session close, so this candidate is
                    # censored whether or not a flip happened to land inside it.
                    self._emit_observation(
                        cand, DISPOSITION_CENSORED, None,
                        censor_reason=CENSOR_SESSION_END, censored_at_ts=flip_ts,
                    )
                elif within_horizon:
                    self._emit_observation(cand, DISPOSITION_POSITIVE, flip_ts)
                else:
                    # Horizon already elapsed; the sweep should normally have caught it.
                    self._emit_observation(cand, DISPOSITION_NEGATIVE, None,
                                           censored_at_ts=cand["horizon_end_ts"])
            self.pending_candidates.clear()

        # Reset regime state
        self.active_regime_dir = new_regime
        self.regime_start_ns = flip_ts
        self.regime_start_close = open_price
        self.regime_frozen_atr = atr_val if atr_val > 0 else 0.0
        self.highest_high_since_flip = open_price
        self.lowest_low_since_flip = open_price
        self.mfe_progress_previous_extreme = 0.0
        self.mfe_progress_last_extreme_ts = None
        self.mfe_progress_count = 0
        self.next_checkpoint_index = 0

    def _handle_1s_bar(self, bar: Bar) -> None:
        ts_event = int(bar.ts_event)
        ts_avail = int(bar.ts_init)
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume)

        if not self._is_targeted_60:
            if self.velocity_tracker and self._benchmark_mode not in {"checkpoint_only", "baseline"}:
                self.velocity_tracker.update(c)
            if self.volume_tracker and not self._compact_surface:
                self.volume_tracker.update(v, o, c)
            if not self._compact_surface:
                self.highs_1s.append(h)
                self.lows_1s.append(l)
                self.closes_1s.append(c)

        if self._compact_surface and self._benchmark_mode not in {"checkpoint_only", "baseline"}:
            # The selected V2 surface does not consume OHLCV-delta, price-level,
            # wick, range-position, pullback, or volume snapshots.  Structural,
            # rolling, and arrival providers maintain their own causal state.
            # Do not materialize an unused OHLCV dictionary or buffer entry on
            # every 1s bar; this preserves the selected feature values while
            # removing legacy exploratory work from the hot loop.
            b_est = None
        else:
            b_est = self.ohlcv_tracker.update(ts_avail, o, h, l, c, v)
        if self._is_targeted_60 and self.ring:
            self.ring.append(ts_avail, o, h, l, c, v, b_est["bar_est_delta"])

        if not self._compact_surface:
            self.minute_1s_buffer.append((ts_avail, h, l, v, b_est["bar_est_delta"]))

        if self._compact_surface:
            for update in self._execution_plan.update_1s_callbacks:
                update(ts_avail, h, l, c)
        else:
            self.structural_geometry_tracker.on_1s(ts_avail, h, l, c)
            self.rolling_productivity_tracker.on_completed_1s(ts_avail, h, l, c)

        if self.active_regime_dir != 0:
            self.highest_high_since_flip = max(self.highest_high_since_flip, h)
            self.lowest_low_since_flip = min(self.lowest_low_since_flip, l)

            current_mfe = self._compute_running_mfe(self.active_regime_dir)
            if current_mfe > (self.mfe_progress_previous_extreme + 1e-12):
                if self.mfe_progress_last_extreme_ts is None or (ts_event - self.mfe_progress_last_extreme_ts) >= PROGRESS_GAP_NS:
                    self.mfe_progress_count += 1
                self.mfe_progress_last_extreme_ts = ts_event
                self.mfe_progress_previous_extreme = current_mfe

            while self.regime_start_ns > 0:
                T = self.regime_start_ns + (
                    self.next_checkpoint_index + 1
                ) * int(self.cfg.checkpoint_interval_seconds) * NS
                if T > ts_avail:
                    break
                if (T - self.regime_start_ns) > CANDIDATE_TIMEOUT_NS:
                    break

                if T < ts_avail:
                    # Missing 1s bar at checkpoint grid T (e.g. no trades during that second).
                    # Under strict 5s cadence, skip missing checkpoint. Do not back-stamp future bar.
                    self.next_checkpoint_index += 1
                    continue

                # Here T == ts_avail exactly (exact completed 1s bar boundary at checkpoint T)
                self._evaluate_checkpoint(T, price_at_T=c, direction=self.active_regime_dir, triggering_1s_ts_init=ts_avail)
                self.next_checkpoint_index += 1

        # Resolve any candidate whose forward horizon has now fully elapsed. Ordered
        # after checkpoint evaluation so a candidate declared at T is never swept by the
        # same bar that created it.
        self._sweep_elapsed_horizons(ts_avail)

        self.last_close = c
        self.last_ts_seen = ts_avail

    def _compute_running_mfe(self, direction: int) -> float:
        atr = self.regime_frozen_atr
        if atr <= 0:
            return 0.0
        if direction == 1:  # Bullish prevailing trend
            return max(0.0, self.highest_high_since_flip - self.regime_start_close) / atr
        else:  # Bearish prevailing trend
            return max(0.0, self.regime_start_close - self.lowest_low_since_flip) / atr

    def _compute_running_mae(self, direction: int) -> float:
        atr = self.regime_frozen_atr
        if atr <= 0:
            return 0.0
        if direction == 1:
            return max(0.0, self.regime_start_close - self.lowest_low_since_flip) / atr
        else:
            return max(0.0, self.highest_high_since_flip - self.regime_start_close) / atr

    def _get_context_features(self, T: int, atr: float) -> Dict[str, float]:
        ema_slope_short = 0.0
        if len(self.short_ema_history) >= 6:
            ema_slope_short = (self.short_ema_history[-1] - self.short_ema_history[-6]) / (5 * atr)

        ema_slope_long = 0.0
        if len(self.long_ema_history) >= 6:
            ema_slope_long = (self.long_ema_history[-1] - self.long_ema_history[-6]) / (5 * atr)

        ts_pd = pd.Timestamp(T, tz="UTC").tz_convert("America/Chicago")
        minutes_since_open = (ts_pd.hour - 8) * 60 + (ts_pd.minute - 30)
        # Canonical boundary, not a third inline re-derivation (this one previously
        # ended RTH at 15:00 while the accumulator above ended it at 15:15).
        is_rth = 1.0 if is_in_session(T, self.cfg.session) else 0.0

        return {
            "ema_slope_short": float(ema_slope_short),
            "ema_slope_long": float(ema_slope_long),
            "regime_age_bars": float(self.bars_in_regime),
            "is_rth": is_rth,
            "minutes_since_rth_open": float(minutes_since_open),
        }

    def _evaluate_checkpoint(
        self,
        T: int,
        price_at_T: float,
        direction: int,
        triggering_1s_ts_init: Optional[int] = None,
    ) -> None:
        if triggering_1s_ts_init is not None and triggering_1s_ts_init != T:
            raise RuntimeError(
                f"CAUSAL_TIMESTAMP_VIOLATION: triggering_1s_ts_init ({triggering_1s_ts_init}) != checkpoint T ({T})"
            )

        regime_age_s = (T - self.regime_start_ns) / NS
        atr = self.regime_frozen_atr
        if atr <= 0:
            return

        current_mfe = self._compute_running_mfe(direction)
        current_mae = self._compute_running_mae(direction)
        current_pnl = (direction * (price_at_T - self.regime_start_close)) / atr
        retained = (current_pnl / current_mfe) if current_mfe > 0 else 0.0

        # Established filter
        if self.cfg.established_required:
            if not (
                regime_age_s >= self.cfg.age_gate_seconds
                and current_mfe >= self.cfg.running_mfe_atr_gte
                and self.mfe_progress_count >= self.cfg.new_progress_windows_gte
                and retained >= self.cfg.retained_mfe_ratio_gte
            ):
                return

        # Declared-session gate, resolved through the canonical boundary module.
        # This previously read `510 <= minute_of_day < 900` (08:30-15:00), silently
        # disagreeing with the 08:30-15:15 window used elsewhere in this same file.
        if not is_in_session(T, self.cfg.session):
            return

        trade_dir = -direction

        if self._is_targeted_60 and self.ring:
            # 1. Structural features (27)
            structural_feats = self.structural_geometry_tracker.snapshot(
                checkpoint_ns=T,
                current_price=price_at_T,
                checkpoint_atr=atr,
                five_provenance_close_ts=self.structural_geometry_tracker._five_close_ts,
            )
            regime_exp_speed = structural_feats.get("regime_expansion_atr_per_min")

            # 2. Rolling features (8)
            rolling_feats = self.rolling_productivity_tracker.snapshot(
                checkpoint_ns=T,
                direction=direction,
                current_regime_start_atr=atr,
                regime_expansion_atr_per_min=regime_exp_speed,
            )

            # 3. Base 25 Features
            ot = self.ohlcv_tracker
            obs_ts = T
            
            if not ot._rth_active:
                rth_vol = rth_abs_delta = rth_elapsed = None
            else:
                rth_vol = ot._rth_vol_cum
                rth_abs_delta = ot._rth_abs_delta_cum
                rth_elapsed = (obs_ts - ot._rth_start_ts) / NS if ot._rth_start_ts else 0.0

            ring = self.ring
            n = ring.count
            head = ring.head
            if n < ring.capacity:
                ts_slice = ring.ts[:n]
                opens_slice = ring.opens[:n]
                highs_slice = ring.highs[:n]
                lows_slice = ring.lows[:n]
                closes_slice = ring.closes[:n]
                vols_slice = ring.volumes[:n]
                deltas_slice = ring.deltas[:n]
                bear_vol_slice = ring.bear_vols[:n]
            else:
                idx = np.arange(head, head + n) % ring.capacity
                ts_slice = ring.ts[idx]
                opens_slice = ring.opens[idx]
                highs_slice = ring.highs[idx]
                lows_slice = ring.lows[idx]
                closes_slice = ring.closes[idx]
                vols_slice = ring.volumes[idx]
                deltas_slice = ring.deltas[idx]
                bear_vol_slice = ring.bear_vols[idx]

            # Window 30s
            c30 = obs_ts - 30 * NS
            m30 = ts_slice > c30
            cnt30 = int(m30.sum())
            if ts_slice[0] <= c30 + NS and cnt30 > 0:
                wc30, wo30 = closes_slice[m30], opens_slice[m30]
                p_chg_30s = float(wc30[-1] - wo30[0])
                p_chg_atr_30s = (p_chg_30s / atr) if atr > 0 else None
            else:
                p_chg_30s = p_chg_atr_30s = None

            # Window 60s
            c60 = obs_ts - 60 * NS
            m60 = ts_slice > c60
            cnt60 = int(m60.sum())
            if ts_slice[0] <= c60 + NS and cnt60 > 0:
                wc60, wo60 = closes_slice[m60], opens_slice[m60]
                p_chg_60s = float(wc60[-1] - wo60[0])
                p_chg_atr_60s = (p_chg_60s / atr) if atr > 0 else None
            else:
                p_chg_60s = p_chg_atr_60s = None

            # Window 300s
            c300 = obs_ts - 300 * NS
            m300 = ts_slice > c300
            cnt300 = int(m300.sum())
            if ts_slice[0] <= c300 + NS and cnt300 > 0:
                est_bear_vol_300s = float(bear_vol_slice[m300].sum())
            else:
                est_bear_vol_300s = None

            # Window 1800s
            c1800 = obs_ts - 1800 * NS
            m1800 = ts_slice > c1800
            cnt1800 = int(m1800.sum())
            if ts_slice[0] <= c1800 + NS and cnt1800 > 0:
                w_h1800 = highs_slice[m1800]
                w_l1800 = lows_slice[m1800]
                w_c1800 = closes_slice[m1800]
                w_o1800 = opens_slice[m1800]
                w_v1800 = vols_slice[m1800]
                w_d1800 = deltas_slice[m1800]
                rng_pts_1800 = float(w_h1800.max() - w_l1800.min())
                est_delta_1800 = float(w_d1800.sum())
                up_m = w_c1800 > w_o1800
                dn_m = w_c1800 < w_o1800
                up_v = float(w_v1800[up_m].sum())
                dn_v = float(w_v1800[dn_m].sum())
                up_dn_ratio_1800 = up_v / max(dn_v, 1e-9)
                vol_max_1s_1800 = float(w_v1800.max())
            else:
                rng_pts_1800 = est_delta_1800 = up_dn_ratio_1800 = vol_max_1s_1800 = None

            plt = self.price_level_tracker
            raw_levels = plt._raw_levels()
            available_prices = {name: price for name, (price, family) in raw_levels.items() if price is not None}

            r_5m_low = available_prices.get("rolling_5m_low")
            r_15m_high = available_prices.get("rolling_15m_high")
            r_60m_high = available_prices.get("rolling_60m_high")
            r_15m_low = available_prices.get("rolling_15m_low")
            r_30m_low = available_prices.get("rolling_30m_low")
            r_30m_high = available_prices.get("rolling_30m_high")
            or_low_dev = available_prices.get("opening_range_30m_low_developing")
            or_low_fin = available_prices.get("opening_range_30m_low_final")
            pd_close = available_prices.get("prior_day_close")
            pd_low = available_prices.get("prior_day_low")

            tol = max(plt.tick_size, plt.touch_tolerance_ticks * plt.tick_size)
            n_levels_below = sum(1 for p in available_prices.values() if price_at_T > p + tol)
            if available_prices:
                lo = min(available_prices.values())
                hi = max(available_prices.values())
                w_pts = hi - lo
                full_env_w_atr = (w_pts / atr) if atr else None
                price_pos_env = ((price_at_T - lo) / w_pts) if w_pts > 0 else None
            else:
                full_env_w_atr = price_pos_env = None

            n_avail = len(available_prices)
            if n_avail > 0:
                if trade_dir == -1:
                    behind_prices = [p for p in available_prices.values() if p > price_at_T]
                else:
                    behind_prices = [p for p in available_prices.values() if p < price_at_T]
                pct_behind = len(behind_prices) / n_avail
            else:
                pct_behind = None

            cand_record = {
                "observation_ts": T,
                "regime_start_ns": self.regime_start_ns,
                "regime_direction": direction,
                "checkpoint_index": self.next_checkpoint_index,
                "regime_age_seconds": regime_age_s,
                "close": price_at_T,
                "atr": atr,
                "running_mfe_atr": current_mfe,
                "running_mae_atr": current_mae,
                "current_pnl_atr": current_pnl,
                "new_progress_windows": self.mfe_progress_count,
                "retained_mfe_ratio": retained,
                "triggering_1s_ts_init": triggering_1s_ts_init if triggering_1s_ts_init is not None else T,
            }

            all_computed_60 = {
                # Base 25:
                "rolling_5m_low_signed_distance_atr": ((price_at_T - r_5m_low) / atr) if (r_5m_low is not None and atr) else None,
                "rth_elapsed_seconds": rth_elapsed,
                "rolling_15m_high_signed_distance_atr": ((price_at_T - r_15m_high) / atr) if (r_15m_high is not None and atr) else None,
                "rolling_60m_high_signed_distance_atr": ((price_at_T - r_60m_high) / atr) if (r_60m_high is not None and atr) else None,
                "rolling_15m_low_signed_distance_atr": ((price_at_T - r_15m_low) / atr) if (r_15m_low is not None and atr) else None,
                "rolling_30m_low_signed_distance_atr": ((price_at_T - r_30m_low) / atr) if (r_30m_low is not None and atr) else None,
                "price_change_points_60s": p_chg_60s,
                "rolling_30m_high_signed_distance_atr": ((price_at_T - r_30m_high) / atr) if (r_30m_high is not None and atr) else None,
                "range_points_1800s": rng_pts_1800,
                "opening_range_30m_low_developing_signed_distance_points": (price_at_T - or_low_dev) if or_low_dev is not None else None,
                "est_bear_vol_sum_300s": est_bear_vol_300s,
                "full_level_envelope_width_atr": full_env_w_atr,
                "rth_vol_cum": rth_vol,
                "est_delta_sum_1800s": est_delta_1800,
                "price_change_atr_60s": p_chg_atr_60s,
                "prior_day_close_signed_distance_atr": ((price_at_T - pd_close) / atr) if (pd_close is not None and atr) else None,
                "up_down_vol_ratio_1800s": up_dn_ratio_1800,
                "price_change_atr_30s": p_chg_atr_30s,
                "pct_levels_behind_trade": pct_behind,
                "prior_day_low_signed_distance_points": (price_at_T - pd_low) if pd_low is not None else None,
                "opening_range_30m_low_final_signed_distance_points": (price_at_T - or_low_fin) if or_low_fin is not None else None,
                "vol_max_1s_1800s": vol_max_1s_1800,
                "price_position_in_full_envelope": price_pos_env,
                "rth_abs_delta_cum": rth_abs_delta,
                "n_levels_below": n_levels_below,

                # Structural 27:
                **structural_feats,

                # Rolling 8:
                **rolling_feats,
            }

            for col in (self._study_feature_aliases or self.cfg.feature_list or all_computed_60.keys()):
                cand_record[col] = all_computed_60.get(col, None)

            self._append_candidate(cand_record)
            self._track_pending(cand_record, T)
            return

        if self._compact_surface:
            # Exact compact V2 surface.  All stateful providers have already
            # consumed the completed input stream; only now, after the cheap
            # population gates pass, calculate the declared snapshot.
            if not self.structural_geometry_tracker.can_snapshot(
                T, self.structural_geometry_tracker._five_close_ts,
            ):
                return
            if self._benchmark_mode in {"checkpoint_only", "baseline"}:
                structural_feats, rolling_feats, velocity_feats = {}, {}, {}
            else:
                structural_feats = self.structural_geometry_tracker.snapshot(
                checkpoint_ns=T,
                current_price=price_at_T,
                checkpoint_atr=atr,
                five_provenance_close_ts=self.structural_geometry_tracker._five_close_ts,
                )
                regime_exp_speed = structural_feats.get("regime_expansion_atr_per_min")
                rolling_feats = self.rolling_productivity_tracker.snapshot(
                checkpoint_ns=T,
                direction=direction,
                current_regime_start_atr=atr,
                regime_expansion_atr_per_min=regime_exp_speed,
                )
                velocity_feats = (
                self.velocity_tracker.calculate(atr=atr)
                if self._execution_plan.calculate_velocity_at_checkpoint and self.velocity_tracker
                else {}
                )
            compact_feats = {
                **structural_feats,
                **rolling_feats,
                **velocity_feats,
                # Preserve the historical physical alias contract exactly.  The
                # old fallback exposed ``ema_slope_short`` but did not expose
                # the canonical ``ema_slope`` alias, so this selected column is
                # intentionally unavailable until its provider binding changes.
                "ema_slope": None,
            }
            cand_record = {
                "observation_ts": T,
                "regime_start_ns": self.regime_start_ns,
                "regime_direction": direction,
                "checkpoint_index": self.next_checkpoint_index,
                "regime_age_seconds": regime_age_s,
                "close": price_at_T,
                "atr": atr,
                "running_mfe_atr": current_mfe,
                "running_mae_atr": current_mae,
                "current_pnl_atr": current_pnl,
                "new_progress_windows": self.mfe_progress_count,
                "retained_mfe_ratio": retained,
                "triggering_1s_ts_init": triggering_1s_ts_init if triggering_1s_ts_init is not None else T,
            }
            for alias in self._study_feature_aliases:
                cand_record[alias] = compact_feats.get(alias)
            self._append_candidate(cand_record)
            self._track_pending(cand_record, T)
            return

        # Extract features causally from all trackers (general exploratory fallback)
        structural_feats = self.structural_geometry_tracker.snapshot(
            checkpoint_ns=T,
            current_price=price_at_T,
            checkpoint_atr=atr,
            five_provenance_close_ts=self.structural_geometry_tracker._five_close_ts,
        )
        regime_exp_speed = structural_feats.get("regime_expansion_atr_per_min")

        rolling_feats = self.rolling_productivity_tracker.snapshot(
            checkpoint_ns=T,
            direction=direction,
            current_regime_start_atr=atr,
            regime_expansion_atr_per_min=regime_exp_speed,
        )

        ohlcv_feats = self.ohlcv_tracker.calculate(atr=atr)
        price_feats = self.price_level_tracker.calculate(T, price_at_T, atr, direction=trade_dir)
        velocity_feats = self.velocity_tracker.calculate(atr=atr) if self.velocity_tracker else {}
        volume_feats = self.volume_tracker.calculate() if self.volume_tracker else {}
        pullback_1s_feats = PullbackTracker.calculate_1s(
            list(self.highs_1s), list(self.lows_1s), list(self.closes_1s), atr
        )
        touch_price = price_at_T
        breach_ref = self.breach_price or (self.short_ema_history[-1] if self.short_ema_history else price_at_T)
        pullback_1m_feats = PullbackTracker.calculate_1m(
            self.bars_since_breach_1m, breach_ref, touch_price, atr, trade_dir
        )
        context_feats = self._get_context_features(T, atr)
        wick_feats = self.wick_tracker.calculate()
        range_position_feats = self.range_position_tracker.calculate()

        merged_raw = {
            **ohlcv_feats,
            **price_feats,
            **structural_feats,
            **rolling_feats,
            **velocity_feats,
            **volume_feats,
            **pullback_1s_feats,
            **pullback_1m_feats,
            **context_feats,
            **wick_feats,
            **range_position_feats,
        }

        study_universe = self._study_feature_aliases or self.cfg.feature_list or resolve_runtime_feature_aliases()
        feats_to_log = {k: merged_raw.get(k, None) for k in study_universe}

        cand_record = {
            "observation_ts": T,
            "regime_start_ns": self.regime_start_ns,
            "regime_direction": direction,
            "checkpoint_index": self.next_checkpoint_index,
            "regime_age_seconds": regime_age_s,
            "close": price_at_T,
            "atr": atr,
            "running_mfe_atr": current_mfe,
            "running_mae_atr": current_mae,
            "current_pnl_atr": current_pnl,
            "new_progress_windows": self.mfe_progress_count,
            "retained_mfe_ratio": retained,
            "triggering_1s_ts_init": triggering_1s_ts_init if triggering_1s_ts_init is not None else T,
            **feats_to_log,
        }

        self._append_candidate(cand_record)
        self._track_pending(cand_record, T)

    def get_candidates_dataframe(self) -> pd.DataFrame:
        if not self.candidates_log:
            return pd.DataFrame()
        return pd.DataFrame(self.candidates_log)

    def get_observations_dataframe(self) -> pd.DataFrame:
        if not self.observations_log:
            return pd.DataFrame()
        return pd.DataFrame(self.observations_log)


# Canonical names for new studies.  The legacy class names remain available only
# inside this implementation module so historical behavior and old imports can
# be shimmed without making them active study identities.
GenericStudyCollector = FlipPredictionCollector
GenericStudyCollectorConfig = FlipPredictionCollectorConfig
