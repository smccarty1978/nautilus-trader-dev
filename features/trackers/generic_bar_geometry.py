"""Small completed-bar geometry building blocks for singleton legacy aliases."""
from __future__ import annotations

from collections import deque


class GenericRangeATRProvider:
    """Shared completed-input range normalisation primitive.

    Window coverage and event/trailing scope are instance/input requirements;
    the mathematical building block is always ``(max(high)-min(low)) / ATR``.
    This is the canonical merge point for the legacy OHLCV and pullback
    ``range_atr`` aliases.
    """

    @staticmethod
    def calculate(*, highs: list[float], lows: list[float], atr: float) -> float | None:
        if not highs or not lows or len(highs) != len(lows) or atr <= 0:
            return None
        return (max(float(value) for value in highs) - min(float(value) for value in lows)) / float(atr)
from typing import Optional

from features.trackers.wick import compute_wick_imbalance


class GenericWickImbalanceProvider:
    def latest_completed_bar(self, *, open_px: float, high: float, low: float, close: float) -> float:
        return compute_wick_imbalance(open_px, high, low, close)


class GenericRangePositionProvider:
    def __init__(self, *, lookback: int) -> None:
        if lookback <= 0:
            raise ValueError("lookback must be positive")
        self._lookback = lookback
        self._history: deque[tuple[float, float]] = deque(maxlen=lookback)

    def update_completed_bar(self, *, high: float, low: float, close: float) -> Optional[float]:
        if len(self._history) < self._lookback:
            result = None
        else:
            upper = max(value[0] for value in self._history)
            lower = min(value[1] for value in self._history)
            result = None if upper == lower else (close - lower) / (upper - lower)
        self._history.append((high, low))
        return result
