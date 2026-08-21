"""NT-only checkpoint collector for the clean A/B/C feature comparison.

All state advances on completed bars.  The collector emits feature snapshots and
runtime 1m regime intervals; it does not inspect any future interval or load a
scored/canonical feature table.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy

from collectors.collector_v2.aggregator import CompletedMinuteFiveMinuteAggregator
from collectors.collector_v2.regime_engine import RegimeStateEngine
from collectors.collector_v2.registry import CompletedBarRegistry
from features.engine import FeatureEngine
from features.registry import FEATURE_REGISTRY, bind_snapshot_anchor
from features.trackers.structural_regime_geometry import StructuralRegimeGeometryTracker
from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.phase0 import authorize_execution


NS = 1_000_000_000
CT = ZoneInfo("America/Chicago")
STUDY_ID = "Codex_clean_maturity_flip_rolling_5m_productivity"
ROLLING_FEATURES = tuple(
    name for name, definition in FEATURE_REGISTRY.items()
    if definition.family == "rolling_5m_productivity"
)
STRUCTURAL_FEATURES = tuple(
    name for name, definition in FEATURE_REGISTRY.items()
    if definition.family == "structural_regime_geometry"
)
BASELINE_CANDIDATES = tuple(
    name for name, definition in FEATURE_REGISTRY.items()
    if definition.status == "verified"
    and definition.dtype in {"float64", "float32", "int64", "int32"}
    and definition.implementation.startswith("features.")
)


# Terminal dispositions for the generic candidates/observations output interface
# (backtests/nt_runtime/output_manager.py's reconcile_candidate_dispositions requires
# every emitted candidate to reach exactly one of these -- an undisposed candidate is
# treated as silent survivorship, not a missing record). This bookkeeping is additive:
# it does not change flip_within_300s or which checkpoints qualify as candidates.
DISPOSITION_LABELED_POSITIVE = "LABELED_POSITIVE"
DISPOSITION_LABELED_NEGATIVE = "LABELED_NEGATIVE"
DISPOSITION_CENSORED = "CENSORED"
CENSOR_DATA_GAP = "DATA_GAP"
CENSOR_RUN_END = "RUN_END"


def is_rth_decision(ts_ns: int) -> bool:
    """RTH checkpoints are [08:30, 15:00) in America/Chicago."""
    dt = datetime.fromtimestamp(ts_ns / NS, tz=ZoneInfo("UTC")).astimezone(CT)
    return 8 * 60 + 30 <= dt.hour * 60 + dt.minute < 15 * 60


@dataclass(frozen=True)
class _Value:
    value: float


class _FeatureRegimeAdapter:
    """Explicit adapter from the frozen 1m state engine to FeatureEngine's API."""

    def __init__(self, engine: RegimeEngine) -> None:
        self.regime_id = 0
        self.regime = 0
        self.has_breached = False
        self.regime_high = 0.0
        self.regime_low = 0.0
        self.atr = _Value(0.0)
        self.short_ema_close = _Value(0.0)
        self.long_ema_close = _Value(0.0)
        self._source = engine

    def update(self, high: float, low: float, prior_direction: int) -> None:
        source = self._source
        direction = source.regime
        if direction != 0 and direction != prior_direction:
            self.regime_id += 1
            self.regime_high, self.regime_low = high, low
        else:
            self.regime_high = max(self.regime_high, high)
            self.regime_low = min(self.regime_low, low)
        self.regime = direction
        self.atr = _Value(float(source.atr or 0.0))
        # The source regime is evaluated against H/L EMAs.  Select the active
        # side's values so the generic engine receives the exact state that
        # governs this direction; no close-EMA proxy is invented.
        short = source.ema3_h if direction == 1 else source.ema3_l
        long = source.ema9_h if direction == 1 else source.ema9_l
        self.short_ema_close, self.long_ema_close = _Value(float(short or 0.0)), _Value(float(long or 0.0))


class CleanFlipCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    phase0_manifest_path: str = ""
    authorized_years: tuple[int, ...] = (2021, 2022, 2023, 2024)


class CleanFlipCollector(Strategy):
    """Collects clean registry, structural, and rolling blocks at 5s decisions."""

    def __init__(self, config: CleanFlipCollectorConfig):
        super().__init__(config)
        authorize_execution(Path(config.phase0_manifest_path))
        if set(config.authorized_years) - {2021, 2022, 2023, 2024}:
            raise RuntimeError("collector config contains forbidden collection years")
        self._authorized_years = set(config.authorized_years)
        self._bar_1s = BarType.from_str(config.bar_type_1s)
        self._bar_1m = BarType.from_str(config.bar_type_1m)
        self._regime = RegimeEngine()
        self._feature_regime = _FeatureRegimeAdapter(self._regime)
        self._features = FeatureEngine(rolling_productivity_window_seconds=300)
        self._geometry = StructuralRegimeGeometryTracker()
        self._registry = CompletedBarRegistry(supported_timeframes=("5m",))
        self._engine_5m = RegimeStateEngine("5m", self._registry)
        self._five_from_1m = CompletedMinuteFiveMinuteAggregator(self._on_bucket_closed)
        self._last_eligible_close: float | None = None
        self._last_seen_1s_event_ns: int | None = None
        self._last_seen_1s_decision_ns: int | None = None
        self._last_seen_1m_init_ns: int | None = None
        self._was_rth_decision = False
        self._current_regime_start_atr: float | None = None
        self._current_regime_start_ns: int | None = None
        self._current_regime_anchor: float | None = None
        self._running_mfe_atr = 0.0
        self._last_progress_extreme_ns: int | None = None
        self._progress_windows = 0
        self._pending_labels: deque[dict] = deque()
        self._flip_times_ns: deque[int] = deque()
        self.feature_rows: list[dict] = []
        self.regime_rows: list[dict] = []
        self._next_checkpoint_index = 0
        self.candidates_log: list[dict] = []
        self.observations_log: list[dict] = []
        
        # Telemetry counters
        self.telemetry_total_checkpoints = 0
        self.telemetry_rth_gate_pass = 0
        self.telemetry_age_gate_pass = 0
        self.telemetry_mfe_gate_pass = 0
        self.telemetry_progress_gate_pass = 0
        self.telemetry_retention_gate_pass = 0
        self.telemetry_declared_population_eligible = 0
        self.telemetry_candidates_emitted = 0
        self.telemetry_declared_contract_exclusions = 0
        self.telemetry_implementation_only_exclusions = 0

        for name in (*BASELINE_CANDIDATES, *STRUCTURAL_FEATURES, *ROLLING_FEATURES):
            bind_snapshot_anchor(name, STUDY_ID, "at_5s_decision_ts")

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_1s)
        self.subscribe_bars(self._bar_1m)

    def _on_bucket_closed(self, timeframe, bucket) -> None:
        if timeframe != "5m":
            raise RuntimeError(f"unexpected timeframe {timeframe!r}")
        self._engine_5m.on_bar_closed(bucket)
        state = self._registry.get("5m")
        self._geometry.on_5m_bar(
            close_ts=state.close_ts, direction=state.regime, open_=state.open,
            high=state.high, low=state.low, close=state.close, atr=state.atr,
        )

    def on_bar(self, bar: Bar) -> None:
        year = datetime.fromtimestamp(int(bar.ts_init) / NS, tz=ZoneInfo("UTC")).year
        if year not in self._authorized_years:
            raise RuntimeError(f"forbidden collection year: {year}")
        if bar.bar_type == self._bar_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bar_1m:
            self._on_1m(bar)

    def _has_expected_open_second(self, start_ns: int, end_ns: int) -> bool:
        if start_ns > end_ns:
            return False
        # Convert start/end to datetime to get date range
        dt_start = pd.to_datetime(start_ns, unit='ns', utc=True)
        dt_end = pd.to_datetime(end_ns, unit='ns', utc=True)
        
        calendar = mcal.get_calendar("CME_Equity")
        schedule = calendar.schedule(
            start_date=(dt_start.date() - timedelta(days=1)).isoformat(),
            end_date=(dt_end.date() + timedelta(days=1)).isoformat(),
            market_times="all"
        )
        
        for session_day, row in schedule.iterrows():
            open_ns = int(row.market_open.value)
            close_ns = int(row.market_close.value)
            
            intervals = [(open_ns, close_ns - NS)]
            if session_day.date() <= date(2021, 6, 25) and "break_start" in schedule.columns:
                break_start = int(row.break_start.value)
                break_end = int(row.break_end.value)
                if open_ns < break_start < break_end < close_ns:
                    intervals = [(open_ns, break_start - NS), (break_end, close_ns - NS)]
                    
            for s_ns, e_ns in intervals:
                overlap_start = max(s_ns, start_ns)
                overlap_end = min(e_ns, end_ns)
                if overlap_start <= overlap_end:
                    return True
        return False

    def _on_1s(self, bar: Bar) -> None:
        event_ns, decision_ns = int(bar.ts_event), int(bar.ts_init)
        if event_ns >= decision_ns:
            raise RuntimeError("1s source must be complete before availability")
            
        # Data integrity checks
        if self._last_seen_1s_event_ns is not None:
            if event_ns == self._last_seen_1s_event_ns:
                raise RuntimeError(f"Duplicate 1s timestamp detected: {event_ns}")
            if event_ns < self._last_seen_1s_event_ns:
                raise RuntimeError(f"Out-of-order 1s timestamp detected: {event_ns} < {self._last_seen_1s_event_ns}")
                
        high, low, close, open_ = float(bar.high), float(bar.low), float(bar.close), float(bar.open)
        if high < low or high < open_ or high < close or low > open_ or low > close:
            raise RuntimeError(f"Invalid OHLC values detected: O={open_}, H={high}, L={low}, C={close}")

        rth_now = is_rth_decision(decision_ns)
        self._was_rth_decision = rth_now
        self._last_seen_1s_event_ns = event_ns
        self._last_seen_1s_decision_ns = decision_ns
        
        self._features.update_1s(bar)
        self._geometry.on_1s(decision_ns, high, low, close)
        self._update_established_state(decision_ns, high, low, close)
        self._last_eligible_close = close
        
        if decision_ns % (5 * NS) != 0 or self._last_eligible_close is None:
            return
            
        self.telemetry_total_checkpoints += 1
        
        # Telemetry: Check RTH session boundary
        if not rth_now:
            self.telemetry_declared_contract_exclusions += 1
            return
        self.telemetry_rth_gate_pass += 1
        
        # Telemetry: check regime start
        if self._current_regime_start_atr is None:
            self.telemetry_declared_contract_exclusions += 1
            return
            
        self._registry.audit_provenance(decision_ns)
        five_state = self._registry.get("5m")
        structural = self._geometry.snapshot(
            decision_ns, self._last_eligible_close, float(self._regime.atr or 0.0),
            None if five_state is None else five_state.close_ts,
        )
        
        # Telemetry: check eligibility gates
        age_pass = (decision_ns - self._current_regime_start_ns) > 120 * NS
        if age_pass:
            self.telemetry_age_gate_pass += 1
            
        mfe_pass = self._running_mfe_atr >= 1.0
        if mfe_pass:
            self.telemetry_mfe_gate_pass += 1
            
        progress_pass = self._progress_windows >= 2
        if progress_pass:
            self.telemetry_progress_gate_pass += 1
            
        retention_pass = self._retained_mfe_ratio(close) >= 0.5
        if retention_pass:
            self.telemetry_retention_gate_pass += 1
            
        eligible = age_pass and mfe_pass and progress_pass and retention_pass
        if eligible:
            self.telemetry_declared_population_eligible += 1
        else:
            return
            
        base_and_rolling = self._features.snapshot(
            (*BASELINE_CANDIDATES, *ROLLING_FEATURES),
            {"touch_bar": bar, "regime": self._feature_regime, "direction": self._regime.regime,
             "rolling_productivity": {
                 "checkpoint_ns": decision_ns,
                 "current_regime_start_atr": self._current_regime_start_atr,
                 "regime_expansion_atr_per_min": structural.get("regime_expansion_atr_per_min"),
             }},
        )
        if not base_and_rolling:
            raise RuntimeError("FEATURE_READINESS_SCOPE_ESCALATION")
            
        age_seconds = decision_ns - self._current_regime_start_ns
        pending = {
            "checkpoint_decision_ns": decision_ns,
            "checkpoint_event_ns": event_ns,
            "prevailing_direction": self._regime.regime,
            "regime_start_ns": self._current_regime_start_ns,
            "atr_at_regime_start": self._current_regime_start_atr,
            "current_5m_completed_close_ts": None if five_state is None else five_state.close_ts,
            "rolling_5m_crosses_rth_boundary": is_rth_decision(decision_ns - 300 * NS) != is_rth_decision(decision_ns),
            "current_5m_regime_started_rth": (
                None if structural.get("current_5m_regime_start_ns") is None
                else is_rth_decision(structural["current_5m_regime_start_ns"])
            ),
            "regime_age_seconds": age_seconds / NS,
            "running_mfe_atr": self._running_mfe_atr,
            "new_progress_windows": self._progress_windows,
            "retained_mfe_ratio": self._retained_mfe_ratio(close),
            "observation_ts": decision_ns,
            "checkpoint_index": self._next_checkpoint_index,
            **base_and_rolling, **structural,
        }
        self._next_checkpoint_index += 1
        self.telemetry_candidates_emitted += 1
        self.candidates_log.append(dict(pending))
        self._pending_labels.append({"row": pending, "target_observable": True})

    def _on_1m(self, bar: Bar) -> None:
        decision_ns = int(bar.ts_init)
        if int(bar.ts_event) + 60 * NS != decision_ns:
            raise RuntimeError("1m source must be complete exactly at its availability timestamp")
            
        if self._last_seen_1m_init_ns is not None:
            if decision_ns == self._last_seen_1m_init_ns:
                raise RuntimeError(f"Duplicate 1m timestamp detected: {decision_ns}")
            if decision_ns < self._last_seen_1m_init_ns:
                raise RuntimeError(f"Out-of-order 1m timestamp detected: {decision_ns} < {self._last_seen_1m_init_ns}")
            if decision_ns != self._last_seen_1m_init_ns + 60 * NS:
                if self._has_expected_open_second(self._last_seen_1m_init_ns + NS, decision_ns - 61 * NS):
                    raise RuntimeError(f"Unexpected gap in 1m reference bars: {self._last_seen_1m_init_ns} to {decision_ns}")
                
        high_1m, low_1m, close_1m, open_1m = float(bar.high), float(bar.low), float(bar.close), float(bar.open)
        if high_1m < low_1m or high_1m < open_1m or high_1m < close_1m or low_1m > open_1m or low_1m > close_1m:
            raise RuntimeError(f"Invalid OHLC values detected in 1m bar: O={open_1m}, H={high_1m}, L={low_1m}, C={close_1m}")

        self._last_seen_1m_init_ns = decision_ns
        
        prior_direction = self._regime.regime
        direction = self._regime.update(float(bar.high), float(bar.low), float(bar.close))
        self._feature_regime.update(float(bar.high), float(bar.low), prior_direction)
        self._features.update_1m(bar, self._feature_regime)
        self._five_from_1m.on_completed_1m(
            int(bar.ts_event), float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), float(bar.volume),
        )
        incomplete_5m = self._five_from_1m.consume_incomplete_close_ts()
        if incomplete_5m:
            self._registry = CompletedBarRegistry(supported_timeframes=("5m",))
            self._engine_5m = RegimeStateEngine("5m", self._registry)
            self._geometry.on_5m_gap(max(incomplete_5m))
        if direction == 0 or direction == prior_direction or self._regime.atr is None:
            self._resolve_pending_labels(decision_ns)
            return
        start_ns = decision_ns
        if self._current_regime_start_ns is not None:
            self.regime_rows.append({
                "regime_start_ns": self._current_regime_start_ns,
                "regime_end_ns": start_ns,
                "prevailing_direction": prior_direction,
            })
        self._current_regime_start_ns = start_ns
        self._current_regime_start_atr = float(self._regime.atr)
        anchor = float(self._last_eligible_close if self._last_eligible_close is not None else bar.close)
        self._current_regime_anchor = anchor
        self._running_mfe_atr = 0.0
        self._last_progress_extreme_ns = None
        self._progress_windows = 0
        self._flip_times_ns.append(start_ns)
        self._geometry.on_1m_flip(direction, start_ns, anchor, float(self._regime.atr), anchor)
        self._resolve_pending_labels(decision_ns)

    def _update_established_state(self, decision_ns: int, high: float, low: float, close: float) -> None:
        """Advance the frozen established-regime gate from completed 1s bars."""
        if (self._current_regime_start_atr is None or self._current_regime_anchor is None
                or self._regime.regime not in (-1, 1)):
            return
        favorable = (high - self._current_regime_anchor if self._regime.regime == 1
                     else self._current_regime_anchor - low)
        candidate = max(0.0, favorable / self._current_regime_start_atr)
        if candidate > self._running_mfe_atr + 1e-12:
            if (self._last_progress_extreme_ns is None
                    or decision_ns - self._last_progress_extreme_ns >= 120 * NS):
                self._progress_windows += 1
            self._running_mfe_atr = candidate
            self._last_progress_extreme_ns = decision_ns

    def _retained_mfe_ratio(self, close: float) -> float:
        if (self._current_regime_start_atr is None or self._current_regime_anchor is None
                or self._running_mfe_atr <= 0.0):
            return 0.0
        current = (close - self._current_regime_anchor if self._regime.regime == 1
                   else self._current_regime_anchor - close) / self._current_regime_start_atr
        return current / self._running_mfe_atr

    def _is_established(self, decision_ns: int, close: float) -> bool:
        if self._current_regime_start_ns is None:
            return False
        return (decision_ns - self._current_regime_start_ns > 120 * NS
                and self._running_mfe_atr >= 1.0
                and self._progress_windows >= 2
                and self._retained_mfe_ratio(close) >= 0.5)

    def _invalidate_pending_horizons(self, gap_start_ns: int, gap_end_ns: int) -> None:
        """A target window crossing an unavailable 1s interval is not labelled false."""
        for pending in getattr(self, "_pending_labels", ()):
            checkpoint = pending["row"]["checkpoint_decision_ns"]
            if checkpoint <= gap_end_ns and checkpoint + 300 * NS >= gap_start_ns:
                pending["target_observable"] = False

    def _resolve_pending_labels(self, available_ns: int) -> None:
        """Resolve only horizons whose full (T, T+300s] interval is in the past."""
        while self._pending_labels:
            pending = self._pending_labels[0]
            row = pending["row"]
            checkpoint = row["checkpoint_decision_ns"]
            if (available_ns <= checkpoint + 300 * NS
                    or getattr(self, "_last_seen_1m_init_ns", -1) <= checkpoint + 300 * NS):
                break
            self._pending_labels.popleft()
            if pending["target_observable"]:
                row["flip_within_300s"] = int(any(
                    checkpoint < flip_ns <= checkpoint + 300 * NS
                    for flip_ns in self._flip_times_ns
                ))
                self.feature_rows.append(row)
                self.observations_log.append({
                    "observation_ts": row["observation_ts"],
                    "regime_start_ns": row["regime_start_ns"],
                    "checkpoint_index": row["checkpoint_index"],
                    "disposition": (DISPOSITION_LABELED_POSITIVE if row["flip_within_300s"]
                                    else DISPOSITION_LABELED_NEGATIVE),
                    "censor_reason": None,
                    "flip_within_300s": row["flip_within_300s"],
                })
            else:
                # A target window crossing an unavailable 1s interval is never labelled
                # false (see _invalidate_pending_horizons) -- it is honestly reported as
                # censored, not silently dropped, so this candidate still reaches exactly
                # one terminal disposition.
                self.observations_log.append({
                    "observation_ts": row["observation_ts"],
                    "regime_start_ns": row["regime_start_ns"],
                    "checkpoint_index": row["checkpoint_index"],
                    "disposition": DISPOSITION_CENSORED,
                    "censor_reason": CENSOR_DATA_GAP,
                    "flip_within_300s": None,
                })
        while self._flip_times_ns and self._pending_labels and self._flip_times_ns[0] <= self._pending_labels[0]["row"]["checkpoint_decision_ns"]:
            self._flip_times_ns.popleft()

    def on_stop(self) -> None:
        """Every candidate must reach exactly one terminal disposition before the run
        ends. Any candidate whose (T, T+300s] horizon had not yet elapsed when data ran
        out is honestly censored at run end, mirroring the data-gap censoring path
        above -- it is not evaluated as a real observed non-flip."""
        while self._pending_labels:
            pending = self._pending_labels.popleft()
            row = pending["row"]
            self.observations_log.append({
                "observation_ts": row["observation_ts"],
                "regime_start_ns": row["regime_start_ns"],
                "checkpoint_index": row["checkpoint_index"],
                "disposition": DISPOSITION_CENSORED,
                "censor_reason": CENSOR_RUN_END,
                "flip_within_300s": None,
            })

    def get_candidates_dataframe(self) -> pd.DataFrame:
        if not self.candidates_log:
            return pd.DataFrame()
        df = pd.DataFrame(self.candidates_log)
        
        # default metadata columns
        declared_metadata = [
            "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index",
            "regime_age_seconds", "close", "atr", "running_mfe_atr", "running_mae_atr",
            "current_pnl_atr", "new_progress_windows", "retained_mfe_ratio", "triggering_1s_ts_init",
        ]
        
        from features.registry import FEATURE_REGISTRY
        registered_feats = set(FEATURE_REGISTRY.keys())
        
        allowed_cols = [c for c in df.columns if c in declared_metadata or c in registered_feats]
        return df[allowed_cols]

    def get_observations_dataframe(self) -> pd.DataFrame:
        if not self.observations_log:
            return pd.DataFrame()
        return pd.DataFrame(self.observations_log)
