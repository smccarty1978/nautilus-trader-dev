"""NautilusTrader-only Phase A causal feature/fact collector."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy

from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine

from .phase_a_adapter import BullishFadeAdapter, load_ordered_features
from .phase_a_candidate import CausalBullishCandidateTracker
from .phase_a_core import SourceProvenance

NS = 1_000_000_000
CT = ZoneInfo("America/Chicago")


def minute_bucket_from_close(ts_init: int) -> int:
    return (ts_init - 1) // (60 * NS)


def is_rth_decision(ts_ns: int) -> bool:
    dt = datetime.fromtimestamp(ts_ns / NS, tz=ZoneInfo("UTC")).astimezone(CT)
    minute = dt.hour * 60 + dt.minute
    return 8 * 60 + 30 <= minute < 15 * 60


def is_rth_minute_bar(ts_init: int) -> bool:
    """Classify the contained minute interval, not its exclusive close."""
    return is_rth_decision(ts_init - NS)


class PhaseABullishCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    repo_root: str = ""


class PhaseABullishCollector(Strategy):
    """Collects checkpoints and flip facts; never constructs future labels."""

    def __init__(self, config: PhaseABullishCollectorConfig):
        super().__init__(config)
        root = Path(config.repo_root)
        self._bar_1s = BarType.from_str(config.bar_type_1s)
        self._bar_1m = BarType.from_str(config.bar_type_1m)
        self._features = BullishFadeAdapter(load_ordered_features(root))
        self._regime = RegimeEngine()
        self._regime_direction = 0
        self._was_rth = False
        self.checkpoint_rows: list[dict] = []
        self.missing_rows: list[dict] = []
        self.flip_rows: list[dict] = []
        self.observation_end_ns: Optional[int] = None
        self._candidate = CausalBullishCandidateTracker(
            self._on_checkpoint, self.missing_rows.append, is_rth_decision
        )

        self._last_1s_event: Optional[int] = None
        self._last_1s_init: Optional[int] = None
        self._last_1m_init: Optional[int] = None
        self._last_1m_event: Optional[int] = None
        self._last_close: Optional[float] = None
        self._minute_bucket: Optional[int] = None
        self._minute_buffer: list[tuple[int, float, float, float, float]] = []

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_1s)
        self.subscribe_bars(self._bar_1m)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type == self._bar_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bar_1m:
            self._on_1m(bar)

    def _on_1s(self, bar: Bar) -> None:
        te, ti = int(bar.ts_event), int(bar.ts_init)
        if not te < ti:
            raise RuntimeError("catalog 1s bar violates open/close timestamp contract")
        o, h, l, c, v = map(float, (bar.open, bar.high, bar.low, bar.close, bar.volume))
        estimate = self._features.engine.update_1s(te, o, h, l, c, v)
        self._last_1s_event, self._last_1s_init, self._last_close = te, ti, c
        self.observation_end_ns = ti

        bucket = minute_bucket_from_close(ti)
        if self._minute_bucket is None:
            self._minute_bucket = bucket
        if bucket != self._minute_bucket:
            # The authoritative 1m callback should have flushed the prior
            # bucket. Never attribute stale bars to a new minute.
            self._minute_buffer = []
            self._minute_bucket = bucket
        self._minute_buffer.append((te, h, l, v, float(estimate["bar_est_delta"])))

        # Exact availability dispatch: completed 1s update first, snapshot
        # second, coincident 1m update later due to registration order.
        self._candidate.on_completed_1s(te, ti, h, l, c)

    def _on_1m(self, bar: Bar) -> None:
        ti = int(bar.ts_init)
        prev = self._regime_direction
        new = self._regime.update(float(bar.high), float(bar.low), float(bar.close))
        self._regime_direction = new
        flip = prev != 0 and new != 0 and new != prev
        minute_is_rth = is_rth_minute_bar(ti)
        boundary_is_rth = is_rth_decision(ti)

        if flip:
            self._features.engine.reset_regime(ti, float(bar.open))
        entering_rth = boundary_is_rth and not self._was_rth

        expected = minute_bucket_from_close(ti)
        if self._minute_bucket == expected:
            for te, h, l, v, delta in self._minute_buffer:
                # Regime accumulation always receives the completed buffer.
                # At 08:30, RTH is still inactive here, so the ending pre-open
                # minute is not admitted. At 15:00 it is still active, so the
                # final 14:59 minute is admitted before end_rth below.
                self._features.engine.accumulate_regime_rth(te, h, l, v, delta)
        if entering_rth:
            self._features.engine.reset_rth(ti)
        if not boundary_is_rth and self._was_rth:
            self._features.engine.end_rth()
        self._was_rth = boundary_is_rth
        self._features.engine.update_1m(
            ti, float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), minute_is_rth,
        )
        self._last_1m_init = ti
        self._last_1m_event = int(bar.ts_event)
        self._minute_buffer = []
        self._minute_bucket = None

        if flip:
            anchor = self._last_close if self._last_close is not None else float(bar.close)
            atr_raw = self._regime.atr
            atr = float(atr_raw) if atr_raw is not None else None
            self.flip_rows.append({
                "confirm_flip_ns": ti,
                "new_direction": int(new),
                "flip_close": anchor,
                "atr_at_regime_start": atr,
            })
            self._candidate.on_regime_flip(ti, int(new), anchor, atr)

    def _on_checkpoint(self, row: dict) -> None:
        if not row["established_regime_gate"] or not row["decision_rth"]:
            return
        if self._last_close is None or self._last_1s_event is None or self._last_1s_init is None:
            return
        provenance = SourceProvenance(
            self._last_1s_event, self._last_1s_init,
            self._last_1m_event, self._last_1m_init,
        )
        atr_checkpoint = float(self._regime.atr)
        vector, null_mask, any_bad = self._features.snapshot(
            row["checkpoint_decision_ns"], self._last_close, atr_checkpoint, provenance
        )
        out = {
            **row,
            "atr_at_regime_start": row["atr_val"],
            "atr_at_checkpoint": atr_checkpoint,
            "reference_price": self._last_close,
            "max_source_ts_event_1s": provenance.max_source_ts_event_1s,
            "max_source_ts_init_1s": provenance.max_source_ts_init_1s,
            "max_source_ts_event_1m": provenance.max_source_ts_event_1m,
            "max_source_ts_init_1m": provenance.max_source_ts_init_1m,
            "feature_complete": not any_bad,
            "suppression_reason": "feature_unavailable" if any_bad else None,
        }
        out.update(zip(self._features.features, vector))
        out.update({f"{name}__is_null": bool(null_mask.get(name, False))
                    for name in self._features.features})
        self.checkpoint_rows.append(out)
