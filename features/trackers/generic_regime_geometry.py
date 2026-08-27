"""Timeframe-agnostic completed-bar regime geometry building block.

This provider is deliberately separate from the live legacy adapter until every
legacy family has parity/promotion evidence.  It accepts a completed regime
state from any timeframe and never reads a forming bar.
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

    def complete(self, end_ns: int, end_close: float) -> dict:
        return {"direction": self.direction, "start_ns": self.start_ns, "end_ns": end_ns,
                "start_price": self.start_price, "end_close": end_close,
                "atr_start": self.atr_start, "high": self.high, "low": self.low,
                "high_ns": self.high_ns, "low_ns": self.low_ns}


class GenericCompletedRegimeGeometryProvider:
    """One completed-bar algorithm parameterized by timeframe input."""

    def __init__(self) -> None:
        self._current: dict[str, _Regime] = {}
        self._prior: dict[str, dict] = {}
        self._close_ts: dict[str, int] = {}

    def on_regime_transition(self, *, timeframe: str, direction: int, start_ns: int,
                             start_price: float, atr_start: float, prior_end_close: float) -> None:
        """Start a supplied timeframe regime; geometry observations follow separately."""
        if not timeframe or direction not in (-1, 1) or not math.isfinite(atr_start) or atr_start <= 0.0:
            raise ValueError("regime transition requires timeframe, direction, and positive ATR")
        current = self._current.get(timeframe)
        if current is not None:
            self._prior[timeframe] = current.complete(start_ns, prior_end_close)
        self._current[timeframe] = _Regime(direction, start_ns, start_price, atr_start)
        self._close_ts[timeframe] = start_ns

    def on_geometry_bar(self, *, timeframe: str, close_ts: int, high: float, low: float, close: float) -> None:
        """Feed a completed causal geometry observation to an active regime."""
        current = self._current.get(timeframe)
        if current is None:
            return
        current.update(close_ts, high, low, close)
        self._close_ts[timeframe] = close_ts

    def on_completed_bar(self, *, timeframe: str, close_ts: int, direction: int,
                         open_: float, high: float, low: float, close: float, atr: float) -> None:
        if not timeframe or direction not in (-1, 1) or not math.isfinite(atr) or atr <= 0.0:
            raise ValueError("completed timeframe state requires a timeframe, direction, and positive ATR")
        self._close_ts[timeframe] = close_ts
        current = self._current.get(timeframe)
        if current is None or current.direction != direction:
            self.on_regime_transition(
                timeframe=timeframe, direction=direction, start_ns=close_ts,
                start_price=open_, atr_start=atr,
                prior_end_close=(close if current is None or current.last_close is None else current.last_close),
            )
        self.on_geometry_bar(timeframe=timeframe, close_ts=close_ts, high=high, low=low, close=close)

    def prior_snapshot(
        self, *, timeframe: str, checkpoint_ns: int,
        candidate_price: float | None = None, candidate_atr: float | None = None,
    ) -> dict:
        prior = self._prior.get(timeframe)
        close_ts = self._close_ts.get(timeframe)
        if prior is None:
            return {"available": False, "unavailable_reason": "NO_COMPLETED_PRIOR_REGIME"}
        if close_ts is None or close_ts > checkpoint_ns:
            return {"available": False, "unavailable_reason": "FORMING_OR_MISSING_COMPLETED_STATE"}
        duration = (prior["end_ns"] - prior["start_ns"]) / (60 * NS)
        rng = prior["high"] - prior["low"]
        net = prior["direction"] * (prior["end_close"] - prior["start_price"])
        fav = prior["high"] - prior["start_price"] if prior["direction"] == 1 else prior["start_price"] - prior["low"]
        rng_atr, net_atr = _ratio(rng, prior["atr_start"]), _ratio(net, prior["atr_start"])
        prefix = f"prior_{timeframe}_regime"
        result = {"available": True, "completed_close_ts": close_ts,
                f"{prefix}_duration_min": duration,
                f"{prefix}_range_atr": rng_atr,
                f"{prefix}_net_directional_move_atr": net_atr,
                f"{prefix}_mfe_atr": _ratio(fav, prior["atr_start"]),
                f"{prefix}_range_atr_per_min": _ratio(rng_atr, duration) if rng_atr is not None else None,
                f"{prefix}_net_move_atr_per_min": _ratio(abs(net_atr), duration) if net_atr is not None else None,
                f"{prefix}_efficiency": _ratio(abs(net), rng)}
        if (candidate_price is None) != (candidate_atr is None):
            raise ValueError("candidate_price and candidate_atr must be supplied together")
        if candidate_price is not None:
            if not math.isfinite(candidate_atr) or candidate_atr <= 0.0:
                raise ValueError("candidate_atr must be finite and positive")
            extreme = prior["high"] if prior["direction"] == 1 else prior["low"]
            counter_move = (
                prior["high"] - prior["start_price"]
                if prior["direction"] == 1 else prior["start_price"] - prior["low"]
            )
            recovered = (
                extreme - float(candidate_price)
                if prior["direction"] == 1 else float(candidate_price) - extreme
            )
            recovered = max(0.0, recovered)
            result.update({
                f"{prefix}_recovery_from_extreme_atr": recovered / candidate_atr,
                f"{prefix}_fraction_move_recovered": _ratio(recovered, counter_move),
            })
        return result
