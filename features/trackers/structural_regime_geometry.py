"""Causal structural geometry tracker used by the maturity feasibility study.

It keeps mutable current-regime state plus immutable completed-regime records and
never performs a path or future-regime lookup. Callers own stream ordering.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

NS = 1_000_000_000


def _ratio(n: float, d: float) -> float | None:
    return n / d if math.isfinite(n) and math.isfinite(d) and d > 0.0 else None


@dataclass
class _Regime:
    direction: int
    start_ns: int
    start_price: float
    atr_start: float
    high: float = -math.inf
    low: float = math.inf
    high_ns: int = -1
    low_ns: int = -1
    last_close: Optional[float] = None

    def update(self, ts_ns: int, high: float, low: float, close: float) -> None:
        if high > self.high:
            self.high, self.high_ns = high, ts_ns
        if low < self.low:
            self.low, self.low_ns = low, ts_ns
        self.last_close = close

    def complete(self, end_ns: int, end_close: float) -> dict | None:
        if not (math.isfinite(self.high) and math.isfinite(self.low)):
            return None
        return {"direction": self.direction, "start_ns": self.start_ns, "end_ns": end_ns,
                "start_price": self.start_price, "end_close": end_close,
                "atr_start": self.atr_start, "high": self.high, "low": self.low,
                "high_ns": self.high_ns, "low_ns": self.low_ns}


class StructuralRegimeGeometryTracker:
    """Causal 1m structural and completed-5m geometry state."""

    def __init__(self) -> None:
        self._one: Optional[_Regime] = None
        self._prior_one: Optional[dict] = None
        self._origin_price: Optional[float] = None
        self._origin_ns: Optional[int] = None
        self._five: Optional[_Regime] = None
        self._prior_five: Optional[dict] = None
        self._five_close_ts: Optional[int] = None

    def on_1s(self, ts_ns: int, high: float, low: float, close: float) -> None:
        if self._one is not None:
            self._one.update(ts_ns, high, low, close)

    def on_1m_flip(self, direction: int, start_ns: int, start_price: float,
                   atr_start: float, prior_end_close: float) -> None:
        if self._one is not None:
            self._prior_one = self._one.complete(start_ns, prior_end_close)
        self._origin_price = self._origin_ns = None
        if self._prior_one is not None:
            key = "low" if direction == 1 else "high"
            self._origin_price, self._origin_ns = self._prior_one[key], self._prior_one[f"{key}_ns"]
        self._one = _Regime(direction, start_ns, start_price, atr_start)

    def on_5m_bar(self, *, close_ts: int, direction: int, open_: float, high: float,
                  low: float, close: float, atr: float) -> None:
        """Consume a state produced by a fully completed 5m bar only."""
        self._five_close_ts = close_ts
        if direction == 0 or not math.isfinite(atr) or atr <= 0.0:
            return
        if self._five is None or self._five.direction != direction:
            if self._five is not None:
                self._prior_five = self._five.complete(close_ts, self._five.last_close or close)
            self._five = _Regime(direction, close_ts, open_, atr)
        self._five.update(close_ts, high, low, close)

    def on_5m_gap(self, close_ts: int) -> None:
        """Invalidate 5m state after an incomplete bucket rather than bridge it."""
        self._five = None
        self._prior_five = None
        self._five_close_ts = close_ts

    @staticmethod
    def _completed(prefix: str, r: dict) -> dict:
        duration = (r["end_ns"] - r["start_ns"]) / (60 * NS)
        rng, net = r["high"] - r["low"], r["direction"] * (r["end_close"] - r["start_price"])
        fav = r["high"] - r["start_price"] if r["direction"] == 1 else r["start_price"] - r["low"]
        ar, nm = _ratio(rng, r["atr_start"]), _ratio(net, r["atr_start"])
        return {f"{prefix}_duration_min": duration, f"{prefix}_range_atr": ar,
                f"{prefix}_net_directional_move_atr": nm, f"{prefix}_mfe_atr": _ratio(fav, r["atr_start"]),
                f"{prefix}_range_atr_per_min": _ratio(ar, duration) if ar is not None else None,
                # This is a speed, while net_directional_move_atr retains the signed
                # directional displacement needed to interpret the completed regime.
                f"{prefix}_net_move_atr_per_min": _ratio(abs(nm), duration) if nm is not None else None,
                f"{prefix}_efficiency": _ratio(abs(net), rng)}

    def snapshot(self, checkpoint_ns: int, current_price: float, checkpoint_atr: float,
                 five_provenance_close_ts: int | None) -> dict:
        """Read-only feature snapshot; unavailable values are never invented."""
        out = {"structural_available": False, "structural_unavailable_reason": None,
               "structural_origin_price": self._origin_price, "structural_origin_ns": self._origin_ns,
               "structural_current_1m_start_ns": None if self._one is None else self._one.start_ns,
               "structural_current_1m_direction": None if self._one is None else self._one.direction,
               "current_5m_completed_close_ts": self._five_close_ts,
               "current_5m_regime_start_ns": None if self._five is None else self._five.start_ns,
               "five_registry_close_ts": five_provenance_close_ts}
        if self._one is None or self._prior_one is None or self._origin_price is None:
            out["structural_unavailable_reason"] = "NO_COMPLETED_PRIOR_1M_REGIME"; return out
        if self._five is None or self._prior_five is None:
            out["structural_unavailable_reason"] = "NO_COMPLETED_PRIOR_5M_REGIME"; return out
        if five_provenance_close_ts is None or five_provenance_close_ts > checkpoint_ns:
            out["structural_unavailable_reason"] = "FORMING_OR_MISSING_5M_STATE"; return out
        r = self._one
        if not math.isfinite(r.atr_start) or r.atr_start <= 0.0:
            out["structural_unavailable_reason"] = "INVALID_1M_START_ATR"; return out
        extreme = r.high if r.direction == 1 else r.low
        maximum = r.direction * (extreme - self._origin_price) / r.atr_start
        current = r.direction * (current_price - self._origin_price) / r.atr_start
        age = (checkpoint_ns - r.start_ns) / (60 * NS)
        structural_age = (checkpoint_ns - self._origin_ns) / (60 * NS)
        if maximum <= 0.0 or age <= 0.0 or structural_age <= 0.0:
            out["structural_unavailable_reason"] = "NONPOSITIVE_STRUCTURAL_DENOMINATOR"; return out
        out.update({"structural_max_expansion_atr": maximum,
                    "structural_current_expansion_atr": current,
                    "structural_giveback_atr": maximum-current,
                    "structural_retention_ratio": current/maximum,
                    "structural_expansion_atr_per_min": maximum/structural_age,
                    "regime_expansion_atr_per_min": maximum/age,
                    "structural_max_expansion_checkpoint_atr": _ratio(r.direction*(extreme-self._origin_price), checkpoint_atr),
                    "structural_current_expansion_checkpoint_atr": _ratio(r.direction*(current_price-self._origin_price), checkpoint_atr)})
        out.update(self._completed("prior_1m_regime", self._prior_one))
        f, f_age, f_range = self._five, (checkpoint_ns-self._five.start_ns)/(60*NS), self._five.high-self._five.low
        f_range_atr = _ratio(f_range, f.atr_start)
        out.update({"current_5m_regime_age_min": f_age,
                    "current_5m_regime_range_atr": f_range_atr,
                    "current_5m_directional_displacement_atr": _ratio(f.direction*(f.last_close-f.start_price), f.atr_start),
                    "current_5m_regime_range_atr_per_min": _ratio(f_range_atr, f_age) if f_range_atr is not None else None,
                    "distance_to_completed_5m_high_atr": _ratio(f.high-current_price, f.atr_start),
                    "distance_to_completed_5m_low_atr": _ratio(current_price-f.low, f.atr_start),
                    "current_1m_move_outside_completed_5m_range": float(current_price > f.high or current_price < f.low),
                    "current_5m_regime_range_checkpoint_atr": _ratio(f_range, checkpoint_atr)})
        out.update(self._completed("prior_5m_regime", self._prior_five))
        out["structural_available"] = True
        return out
