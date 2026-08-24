"""Completed-stream median-center and regime-sequence V2 building blocks.

The existing ``MedianCenterTracker`` remains the legacy compatibility adapter.
This module isolates the two reusable computations which account for its
time-encoded physical names: a trailing median-center series and completed
regime-sequence aggregation.  Both are parameterized; neither consumes a
forming higher-timeframe bar.
"""
from __future__ import annotations

from collections import deque
from typing import Iterable, Mapping, Sequence

import numpy as np

from features.trackers.median_center import MedianCenterTracker


class GenericMedianCenterProvider:
    def __init__(self, *, retained_seconds: int = 3600) -> None:
        if retained_seconds <= 0:
            raise ValueError("retained_seconds must be positive")
        self._timestamps: deque[int] = deque(maxlen=retained_seconds)
        self._closes: deque[float] = deque(maxlen=retained_seconds)

    def update_completed_bar(self, *, close_ts: int, close: float) -> None:
        if self._timestamps and close_ts <= self._timestamps[-1]:
            raise ValueError("NON_MONOTONIC_COMPLETED_BAR")
        self._timestamps.append(int(close_ts))
        self._closes.append(float(close))

    def median(self, *, lookback: int, as_of_ns: int) -> float | None:
        if lookback <= 0 or lookback > self._timestamps.maxlen:
            raise ValueError("UNSUPPORTED_HISTORY_LOOKBACK")
        if self._timestamps and as_of_ns < self._timestamps[-1]:
            raise ValueError("CAUSAL_SNAPSHOT_ORDER_VIOLATION")
        if len(self._closes) < lookback:
            return None
        return float(np.median(list(self._closes)[-lookback:]))

    def slope(self, *, lookback: int, sample_lookback: int, as_of_ns: int) -> float | None:
        if (lookback <= 0 or sample_lookback <= 0 or lookback > self._timestamps.maxlen
                or sample_lookback > lookback):
            raise ValueError("UNSUPPORTED_HISTORY_LOOKBACK")
        if self._timestamps and as_of_ns < self._timestamps[-1]:
            raise ValueError("CAUSAL_SNAPSHOT_ORDER_VIOLATION")
        if len(self._closes) < lookback:
            return None
        y = list(self._closes)[-sample_lookback:]
        x = np.arange(sample_lookback, dtype=float)
        denominator = sample_lookback * float((x * x).sum()) - float(x.sum()) ** 2
        return None if denominator == 0 else float((sample_lookback * float((x * y).sum()) - float(x.sum()) * float(sum(y))) / denominator)


class GenericRegimeSequenceProvider:
    """Pure completed-regime sequence operations used by sequence aliases."""

    @staticmethod
    def directional_efficiency(*, regimes: Sequence[Mapping[str, float]], lookback: int,
                               current_price: float) -> float | None:
        if lookback <= 0 or len(regimes) < lookback:
            return None
        selected = list(regimes)[-lookback:]
        total = sum(abs(float(regime["net_aligned_move"])) for regime in selected)
        return abs(current_price - float(selected[0]["start_price"])) / (total + 1e-8)


class GenericMedianCenterCompatibilityProvider:
    """Canonical adapter for every legacy median/sequence physical alias.

    It has one provider/state machine; time windows and sequence counts remain
    query parameters of the underlying completed-bar operations.  The adapter
    is intentionally thin so legacy availability, session reset, and null
    behavior are exercised verbatim by the full parity matrix during cutover.
    """

    def __init__(self) -> None:
        self._tracker = MedianCenterTracker()

    def update_completed_1s(self, bar: object, *, regime: int, atr: float) -> None:
        self._tracker.update_1s(bar, regime, atr)

    def on_completed_1m(self, bar: object, regime: object) -> None:
        self._tracker.update_1m(bar, regime)

    def snapshot(self, *, current_regime: int, atr: float, touch_bar: object) -> Mapping[str, object]:
        return self._tracker.calculate(current_regime, atr, touch_bar)
