"""Global, future-independent Phase B dual-model NT collector."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy

from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine

from .phase_a_core import SourceProvenance
from .phase_a_strategy import is_rth_decision, is_rth_minute_bar, minute_bucket_from_close
from .phase_b_adapter import load_phase_b_adapters, vector_sha256

NS = 1_000_000_000


@dataclass
class PrevailingDomain:
    direction: int
    start_ns: int
    anchor: float
    atr: float
    favorable_extreme: float = 0.0
    adverse_extreme: float = 0.0
    progress_count: int = 0
    previous_extreme: float = 0.0
    last_extreme_ns: Optional[int] = None

    def update(self, ts_event: int, high: float, low: float) -> None:
        favorable = high if self.direction == 1 else low
        adverse = low if self.direction == 1 else high
        self.favorable_extreme = max(
            self.favorable_extreme,
            max(0.0, self.direction * (favorable - self.anchor)) / self.atr,
        )
        self.adverse_extreme = max(
            self.adverse_extreme,
            max(0.0, -self.direction * (adverse - self.anchor)) / self.atr,
        )
        if self.favorable_extreme > self.previous_extreme + 1e-12:
            if self.last_extreme_ns is None or ts_event - self.last_extreme_ns >= 120 * NS:
                self.progress_count += 1
            self.last_extreme_ns = ts_event
            self.previous_extreme = self.favorable_extreme

    def snapshot(self, decision_ns: int, close: float) -> dict:
        age = (decision_ns - self.start_ns) / NS
        progress = self.direction * (close - self.anchor) / self.atr
        retained = progress / self.favorable_extreme if self.favorable_extreme > 0 else math.nan
        established = (
            age >= 120
            and self.favorable_extreme >= 1.0
            and self.progress_count >= 2
            and math.isfinite(retained)
            and retained >= 0.5
        )
        return {
            "regime_age_s": age,
            "running_mfe_atr": self.favorable_extreme,
            "running_mae_atr": self.adverse_extreme,
            "current_progress_atr": progress,
            "new_progress_windows": self.progress_count,
            "retained_mfe_ratio": retained,
            "established_regime_gate": bool(established),
        }


class PhaseBCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    repo_root: str = ""


class PhaseBCollector(Strategy):
    def __init__(self, config: PhaseBCollectorConfig):
        super().__init__(config)
        root = Path(config.repo_root)
        self._bar_1s = BarType.from_str(config.bar_type_1s)
        self._bar_1m = BarType.from_str(config.bar_type_1m)
        (
            self._bull_adapter,
            self._bull_scorer,
            self._bear_adapter,
            self._bear_scorer,
        ) = load_phase_b_adapters(root, is_rth_minute_bar)
        self._regime = RegimeEngine()
        self._direction = 0
        self._domain: Optional[PrevailingDomain] = None
        self._was_rth = False
        self.rows: list[dict] = []
        self.flips: list[dict] = []
        self.missing: list[dict] = []
        self.observation_end_ns: Optional[int] = None
        self._last_1s_event = self._last_1s_init = None
        self._last_1m_event = self._last_1m_init = None
        self._last_close: Optional[float] = None
        self._minute_bucket = None
        self._minute_buffer: list[tuple[int, float, float, float, float]] = []
        self._last_grid_ns: Optional[int] = None

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
        if te >= ti:
            raise RuntimeError("1s source must be completed before availability")
        o, h, l, c, v = map(float, (bar.open, bar.high, bar.low, bar.close, bar.volume))
        estimate = self._bull_adapter.engine.update_1s(te, o, h, l, c, v)
        atr = float(self._regime.atr) if self._regime.atr is not None else math.nan
        self._bear_adapter.engine.update_1s(te, o, h, l, c, v, self._direction, atr)
        if self._domain is not None:
            self._domain.update(te, h, l)
        self._last_1s_event, self._last_1s_init, self._last_close = te, ti, c
        self.observation_end_ns = ti

        bucket = minute_bucket_from_close(ti)
        if self._minute_bucket is None:
            self._minute_bucket = bucket
        if bucket != self._minute_bucket:
            self._minute_buffer = []
            self._minute_bucket = bucket
        self._minute_buffer.append((te, h, l, v, float(estimate["bar_est_delta"])))

        if ti % (5 * NS) == 0:
            if self._last_grid_ns is not None and ti > self._last_grid_ns + 5 * NS:
                for missing_t in range(self._last_grid_ns + 5 * NS, ti, 5 * NS):
                    if is_rth_decision(missing_t):
                        self.missing.append({
                            "checkpoint_decision_ns": missing_t,
                            "suppression_reason": "missing_dispatch_bar",
                        })
            self._last_grid_ns = ti
            if is_rth_decision(ti) and self._regime.atr is not None:
                self._emit(ti)

    def _on_1m(self, bar: Bar) -> None:
        ti = int(bar.ts_init)
        prev = self._direction
        self._direction = self._regime.update(
            float(bar.high), float(bar.low), float(bar.close)
        )
        flip = prev != 0 and self._direction != 0 and prev != self._direction
        boundary_rth = is_rth_decision(ti)
        entering_rth = boundary_rth and not self._was_rth
        expected = minute_bucket_from_close(ti)
        if self._minute_bucket == expected:
            for te, h, l, v, delta in self._minute_buffer:
                self._bull_adapter.engine.accumulate_regime_rth(te, h, l, v, delta)
        if entering_rth:
            self._bull_adapter.engine.reset_rth(ti)
        if not boundary_rth and self._was_rth:
            self._bull_adapter.engine.end_rth()
        self._was_rth = boundary_rth
        if flip:
            self._bull_adapter.engine.reset_regime(ti, float(bar.open))
            self._bear_adapter.engine.declare_regime_start(ti)
        self._bull_adapter.engine.update_1m(
            ti, float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), is_rth_minute_bar(ti),
        )
        self._last_1m_event, self._last_1m_init = int(bar.ts_event), ti
        self._minute_buffer, self._minute_bucket = [], None
        if flip:
            anchor = self._last_close if self._last_close is not None else float(bar.close)
            atr = float(self._regime.atr) if self._regime.atr is not None else None
            self.flips.append({
                "confirm_flip_ns": ti,
                "new_direction": int(self._direction),
                "flip_close": anchor,
                "atr_at_regime_start": atr,
            })
            self._domain = (
                PrevailingDomain(self._direction, ti, anchor, atr)
                if atr is not None and atr > 0
                else None
            )

    def _score_side(self, adapter, scorer, decision_ns, provenance, bearish=False):
        if bearish:
            # The strict Bearish training attachment freezes the normalization
            # ATR at the prevailing regime's confirmed start.
            bear_atr = (
                self._domain.atr
                if self._domain is not None
                else float(self._regime.atr)
            )
            vector, nulls, bad = adapter.snapshot(
                decision_ns, self._last_1s_event, self._last_close,
                bear_atr, self._direction, provenance,
            )
        else:
            vector, nulls, bad = adapter.snapshot(
                decision_ns, self._last_close, float(self._regime.atr), provenance
            )
        probability = (
            None if bad else scorer.fast_probability.probability(vector)
        )
        return {
            "feature_complete": not bad,
            "suppression_reason": "feature_unavailable" if bad else None,
            "raw_score": probability,
            "probability": probability,
            "feature_vector_sha256": None if bad else vector_sha256(vector),
            "vector": vector,
            "nulls": nulls,
        }

    def _emit(self, decision_ns: int) -> None:
        provenance = SourceProvenance(
            self._last_1s_event, self._last_1s_init,
            self._last_1m_event, self._last_1m_init,
        )
        bull = self._score_side(
            self._bull_adapter, self._bull_scorer, decision_ns, provenance
        )
        bear = self._score_side(
            self._bear_adapter, self._bear_scorer, decision_ns, provenance, bearish=True
        )
        domain = self._domain.snapshot(decision_ns, self._last_close) if self._domain else {}
        dt = datetime.fromtimestamp(decision_ns / NS, tz=ZoneInfo("UTC")).astimezone(
            ZoneInfo("America/Chicago")
        )
        age_s = domain.get("regime_age_s")
        base = {
            "timestamp_ns": decision_ns,
            "checkpoint_decision_ns": decision_ns,
            "checkpoint_availability_ns": decision_ns,
            "instrument_id": "NQ.XCME",
            "study_year": dt.year,
            "study_month": dt.month,
            "session": "RTH",
            "reference_price": self._last_close,
            "checkpoint_reference_price": self._last_close,
            "atr_at_checkpoint": float(self._regime.atr),
            "atr_at_score": float(self._regime.atr),
            "confirmed_regime_direction": int(self._direction),
            "prevailing_regime": int(self._direction),
            "is_regime_confirmed": bool(self._direction != 0),
            "regime_start_ns": self._domain.start_ns if self._domain else None,
            "regime_age_seconds": age_s,
            "regime_age_bars": None if age_s is None else int(age_s // 60),
            **domain,
            "bullish_in_domain": bool(
                self._direction == 1 and domain.get("established_regime_gate", False)
            ),
            "bearish_in_domain": bool(
                self._direction == -1 and domain.get("established_regime_gate", False)
            ),
            "max_source_ts_event_1s": provenance.max_source_ts_event_1s,
            "max_source_ts_init_1s": provenance.max_source_ts_init_1s,
            "max_source_ts_event_1m": provenance.max_source_ts_event_1m,
            "max_source_ts_init_1m": provenance.max_source_ts_init_1m,
        }
        for prefix, result, adapter in (
            ("bullish", bull, self._bull_adapter),
            ("bearish", bear, self._bear_adapter),
        ):
            for key in ("feature_complete", "suppression_reason", "raw_score",
                        "probability", "feature_vector_sha256"):
                base[f"{prefix}_{key}"] = result[key]
            base[f"{prefix}_model_id"] = (
                "BULLISH_STRICT_top25_gbt_v2"
                if prefix == "bullish"
                else "LONG_STRICT_top25_gbt_v2"
            )
            base[f"{prefix}_score_available"] = result["feature_complete"]
            base[f"{prefix}_unavailable_reason"] = result["suppression_reason"]
            base[f"{prefix}_feature_vector_hash"] = result["feature_vector_sha256"]
            base[f"{prefix}_percentile"] = None
            base[f"{prefix}_decile"] = None
            base[f"{prefix}_is_top_10"] = None
            base[f"{prefix}_is_top_5"] = None
            base[f"{prefix}_is_top_2_5"] = None
            base[f"{prefix}_rank_unavailable_reason"] = (
                "NO_PRE_STUDY_FROZEN_RANK_REFERENCE"
            )
            for name, value in zip(adapter.features, result["vector"]):
                base[f"{prefix}__{name}"] = value
                base[f"{prefix}__{name}__is_null"] = bool(result["nulls"].get(name))
        self.rows.append(base)
