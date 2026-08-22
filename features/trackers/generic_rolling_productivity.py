"""Time-agnostic rolling-productivity output adapter.

The legacy tracker already maintains an arbitrary positive second duration; this
adapter removes only its historical ``rolling_5m_`` output spelling.  Its input
is always a completed 1s stream, and update cadence is owned by the caller.
"""
from __future__ import annotations

from features.trackers.rolling_5m_productivity import Rolling5mProductivityTracker


class GenericRollingProductivityProvider:
    """One rolling formula parameterized by ``window_seconds``."""

    def __init__(self, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self._legacy = Rolling5mProductivityTracker(window_seconds=window_seconds)

    def on_completed_1s(self, close_ts: int, high: float, low: float, close: float) -> None:
        self._legacy.on_completed_1s(close_ts, high, low, close)

    def snapshot(self, checkpoint_ns: int, direction: int, current_regime_start_atr: float,
                 regime_expansion_atr_per_min: float | None) -> dict:
        legacy = self._legacy.snapshot(
            checkpoint_ns, direction, current_regime_start_atr, regime_expansion_atr_per_min,
        )
        return {
            ("rolling_" + key.removeprefix("rolling_5m_") if key.startswith("rolling_5m_") else key): value
            for key, value in legacy.items()
        }
