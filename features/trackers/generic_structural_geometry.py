"""Canonical compatibility adapter for structural regime geometry instances.

The public methods carry timeframe and completed-state data as parameters.  The
legacy tracker remains the exact state implementation while full cutover parity
is established; this adapter is the single staged provider surface used by the
matrix and later canonical definitions.
"""
from __future__ import annotations

from typing import Mapping

from features.trackers.structural_regime_geometry import StructuralRegimeGeometryTracker


class GenericStructuralGeometryProvider:
    def __init__(self) -> None:
        self._tracker = StructuralRegimeGeometryTracker()

    def on_completed_geometry_bar(self, *, timeframe: str, close_ts: int,
                                  high: float, low: float, close: float) -> None:
        if timeframe != "1s":
            raise ValueError("UNSUPPORTED_GEOMETRY_OBSERVATION_TIMEFRAME")
        self._tracker.on_1s(close_ts, high, low, close)

    def on_regime_transition(self, *, timeframe: str, direction: int, start_ns: int,
                             start_price: float, atr_start: float, prior_end_close: float) -> None:
        if timeframe != "1m":
            raise ValueError("UNSUPPORTED_REGIME_TIMEFRAME")
        self._tracker.on_1m_flip(direction, start_ns, start_price, atr_start, prior_end_close)

    def on_completed_regime_bar(self, *, timeframe: str, close_ts: int, direction: int,
                                open_: float, high: float, low: float, close: float, atr: float) -> None:
        if timeframe != "5m":
            raise ValueError("UNSUPPORTED_COMPLETED_REGIME_TIMEFRAME")
        self._tracker.on_5m_bar(close_ts=close_ts, direction=direction, open_=open_, high=high, low=low, close=close, atr=atr)

    def snapshot(self, *, checkpoint_ns: int, current_price: float, checkpoint_atr: float,
                 completed_reference_close_ts: int | None) -> Mapping[str, object]:
        return self._tracker.snapshot(checkpoint_ns, current_price, checkpoint_atr, completed_reference_close_ts)
