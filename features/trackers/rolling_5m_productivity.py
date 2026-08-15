"""Causal five-minute productivity features from completed one-second bars.

The tracker deliberately requires the exact completed one-second boundary at
``checkpoint - 300s``.  It never substitutes a neighbouring observation or
searches for an in-window extreme to construct its anchor.
"""
from __future__ import annotations

from collections import deque
import math
from dataclasses import dataclass
from typing import Deque


NS = 1_000_000_000
DEFAULT_WINDOW_SECONDS = 300


@dataclass(frozen=True)
class _CompletedSecond:
    close_ts: int
    high: float
    low: float
    close: float


def _ratio(numerator: float, denominator: float) -> float | None:
    if not (math.isfinite(numerator) and math.isfinite(denominator)):
        return None
    return numerator / denominator if denominator > 0.0 else None


class Rolling5mProductivityTracker:
    """Tracks an exact 300-second completed-bar productivity window."""

    def __init__(self, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window_ns = window_seconds * NS
        self._bars: Deque[_CompletedSecond] = deque()
        self._last_close_ts: int | None = None

    def on_completed_1s(self, close_ts: int, high: float, low: float, close: float) -> None:
        """Accept one fully completed 1s bar, keyed by its availability time."""
        values = (high, low, close)
        if close_ts <= 0 or not all(math.isfinite(value) for value in values) or high < low:
            raise ValueError("completed 1s bar must have finite OHLC and high >= low")
        if self._last_close_ts is not None and close_ts <= self._last_close_ts:
            raise ValueError("completed 1s bars must arrive in strictly increasing close_ts order")
        self._bars.append(_CompletedSecond(close_ts, high, low, close))
        self._last_close_ts = close_ts
        retained_from = close_ts - self._window_ns
        while self._bars and self._bars[0].close_ts < retained_from:
            self._bars.popleft()

    def snapshot(
        self,
        checkpoint_ns: int,
        direction: int,
        current_regime_start_atr: float,
        regime_expansion_atr_per_min: float | None,
    ) -> dict:
        """Return features using only completed 1s bars in ``[T-300s, T]``."""
        out = {
            "rolling_5m_productivity_available": False,
            "rolling_5m_productivity_unavailable_reason": None,
            "rolling_5m_productivity_anchor_ns": checkpoint_ns - self._window_ns,
            "rolling_5m_productivity_anchor_price": None,
        }
        if direction not in (-1, 1):
            out["rolling_5m_productivity_unavailable_reason"] = "INVALID_DIRECTION"
            return out
        if not math.isfinite(current_regime_start_atr) or current_regime_start_atr <= 0.0:
            out["rolling_5m_productivity_unavailable_reason"] = "INVALID_CURRENT_1M_START_ATR"
            return out
        if not self._bars or self._bars[-1].close_ts != checkpoint_ns:
            out["rolling_5m_productivity_unavailable_reason"] = "MISSING_COMPLETED_CHECKPOINT_1S"
            return out

        anchor_ts = checkpoint_ns - self._window_ns
        bars = tuple(bar for bar in self._bars if anchor_ts <= bar.close_ts <= checkpoint_ns)
        if not bars or bars[0].close_ts != anchor_ts:
            out["rolling_5m_productivity_unavailable_reason"] = "MISSING_EXACT_300S_BOUNDARY"
            return out
        expected_count = self._window_ns // NS + 1
        if len(bars) != expected_count or any(
            bar.close_ts != anchor_ts + offset * NS for offset, bar in enumerate(bars)
        ):
            out["rolling_5m_productivity_unavailable_reason"] = "INCOMPLETE_1S_WINDOW"
            return out

        anchor = bars[0].low if direction == 1 else bars[0].high
        maximum = max(bar.high for bar in bars) - anchor if direction == 1 else anchor - min(bar.low for bar in bars)
        current = bars[-1].close - anchor if direction == 1 else anchor - bars[-1].close
        max_progress = _ratio(maximum, current_regime_start_atr)
        current_progress = _ratio(current, current_regime_start_atr)
        if max_progress is None or current_progress is None or max_progress <= 0.0:
            out["rolling_5m_productivity_unavailable_reason"] = "NONPOSITIVE_PROGRESS_DENOMINATOR"
            return out

        duration_min = self._window_ns / (60 * NS)
        max_speed = max_progress / duration_min
        current_speed = current_progress / duration_min
        out.update({
            "rolling_5m_productivity_available": True,
            "rolling_5m_productivity_anchor_price": anchor,
            "rolling_5m_max_progress_atr": max_progress,
            "rolling_5m_current_progress_atr": current_progress,
            "rolling_5m_giveback_atr": max_progress - current_progress,
            "rolling_5m_retention_ratio": current_progress / max_progress,
            "rolling_5m_max_speed_atr_per_min": max_speed,
            "rolling_5m_current_speed_atr_per_min": current_speed,
            "rolling_5m_max_speed_vs_lifetime": _ratio(max_speed, regime_expansion_atr_per_min)
            if regime_expansion_atr_per_min is not None else None,
            "rolling_5m_current_speed_vs_lifetime": _ratio(current_speed, regime_expansion_atr_per_min)
            if regime_expansion_atr_per_min is not None else None,
        })
        return out
