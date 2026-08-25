"""NautilusTrader collector for structural snapshots at the accepted 5s grid."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy

from collectors.collector_v2.aggregator import TimeframeAggregator
from collectors.collector_v2.regime_engine import RegimeStateEngine
from collectors.collector_v2.registry import CompletedBarRegistry
from features.registry import bind_snapshot_anchor, resolve_runtime_family_aliases
from features.trackers.structural_regime_geometry import StructuralRegimeGeometryTracker
from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine

NS = 1_000_000_000
CT = ZoneInfo("America/Chicago")


def is_rth_decision(ts_ns: int) -> bool:
    """RTH decision checkpoints are [08:30, 15:00) America/Chicago."""
    dt = datetime.fromtimestamp(ts_ns / NS, tz=ZoneInfo("UTC")).astimezone(CT)
    minute = dt.hour * 60 + dt.minute
    return 8 * 60 + 30 <= minute < 15 * 60


class StructuralOnlyCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"


class StructuralOnlyCollector(Strategy):
    """Minimal NT collector, avoiding frozen-model loading while preserving regime timing."""

    def __init__(self, config: StructuralOnlyCollectorConfig):
        super().__init__(config)
        self._bar_1s, self._bar_1m = BarType.from_str(config.bar_type_1s), BarType.from_str(config.bar_type_1m)
        self._regime, self._direction = RegimeEngine(), 0
        self._last_close = None
        self.geometry_rows: list[dict] = []
        self._geometry = StructuralRegimeGeometryTracker()
        self._registry = CompletedBarRegistry(supported_timeframes=("5m",))
        self._engine_5m = RegimeStateEngine("5m", self._registry)
        self._aggregator = TimeframeAggregator(self._on_bucket_closed, timeframes=("5m",))
        for name in resolve_runtime_family_aliases({"structural_regime_geometry"}):
            bind_snapshot_anchor(name, "Codex_structural_regime_geometry_maturity", "at_5s_decision_ts")

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_1s); self.subscribe_bars(self._bar_1m)

    def _on_bucket_closed(self, timeframe, bucket) -> None:
        if timeframe != "5m": raise RuntimeError(f"unexpected timeframe {timeframe!r}")
        self._engine_5m.on_bar_closed(bucket); state = self._registry.get("5m")
        self._geometry.on_5m_bar(close_ts=state.close_ts, direction=state.regime, open_=state.open,
                                 high=state.high, low=state.low, close=state.close, atr=state.atr)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type == self._bar_1s: self._on_1s(bar)
        elif bar.bar_type == self._bar_1m: self._on_1m(bar)

    def _on_1s(self, bar: Bar) -> None:
        te, ti = int(bar.ts_event), int(bar.ts_init)
        if te >= ti: raise RuntimeError("1s source must be complete before availability")
        o, h, l, c, v = map(float, (bar.open, bar.high, bar.low, bar.close, bar.volume))
        # G4: a zero-volume or single-contract print cannot alter structural
        # extrema, the 5m ATR/regime state, or the structural current price.
        eligible = v > 1.0
        if eligible:
            # Price extrema became knowable at ts_init, not the bar-open ts_event.
            self._geometry.on_1s(ti, h, l, c)
            self._aggregator.on_1s_bar(te, o, h, l, c, v)
            self._last_close = c
        # Explicitly publish a 5m bucket ending at this decision timestamp after
        # its final completed 1s member and before the checkpoint snapshot.
        self._aggregator.finalize_through(ti)
        if ti % 5_000_000_000 != 0 or self._regime.atr is None: return
        if self._last_close is None: return
        self._registry.audit_provenance(ti); state = self._registry.get("5m")
        # Snapshot price shares the same G4 eligibility policy as every other
        # structural input: never let an excluded single-contract print enter a
        # current-expansion, distance, retention, or range-break feature.
        snap = self._geometry.snapshot(ti, float(self._last_close), float(self._regime.atr), None if state is None else state.close_ts)
        # State evolves continuously through ETH so RTH opens retain their
        # causal context, while this study's emitted population stays RTH-only.
        if not is_rth_decision(ti): return
        self.geometry_rows.append({"checkpoint_decision_ns": ti, "score_event_ns": te,
                                   "score_available_ns": ti, **snap})

    def _on_1m(self, bar: Bar) -> None:
        prior, previous_close = self._direction, self._last_close
        self._direction = self._regime.update(float(bar.high), float(bar.low), float(bar.close))
        if not (prior != 0 and self._direction != 0 and prior != self._direction): return
        if self._regime.atr is None: return
        start_ns = int(bar.ts_init); anchor = float(previous_close if previous_close is not None else bar.close)
        self._geometry.on_1m_flip(self._direction, start_ns, anchor, float(self._regime.atr), anchor)
