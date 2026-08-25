"""Generic completed-bar pullback geometry.

The provider accepts either a trailing window or an explicitly delimited
event/breach sequence.  That distinction is an instance ``scope`` parameter,
not a duplicate physical feature name.  It contains no bar-type branches.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import numpy as np


def _fields(bars: Iterable[object]) -> tuple[list[float], list[float], list[float]]:
    items = list(bars)
    def value(item: object, name: str) -> float:
        return float(item[name]) if isinstance(item, Mapping) else float(getattr(item, name))
    return ([value(item, "high") for item in items], [value(item, "low") for item in items],
            [value(item, "close") for item in items])


class GenericPullbackProvider:
    """Compute common geometry over supplied completed-bar observations."""

    @staticmethod
    def geometry(*, bars: Sequence[object], atr: float, scope: str,
                 window: int | None = None, direction: int | None = None,
                 breach_price: float | None = None, touch_price: float | None = None) -> Mapping[str, float]:
        if scope not in {"trailing", "since_breach"}:
            raise ValueError("UNKNOWN_PULLBACK_SCOPE")
        selected = list(bars if window is None else bars[-window:])
        highs, lows, closes = _fields(selected)
        count = len(closes)
        # A trailing instance's window is also its legacy warm-up contract:
        # before W completed observations it emits the established neutral
        # values rather than a partial-window calculation.
        if scope == "trailing" and window is not None and count < window:
            return {"higher_lows_count": 0.0, "lower_highs_count": 0.0, "swing_count": 0.0,
                    "linearity": 0.0, "consecutive_down": 0.0, "consecutive_up": 0.0,
                    "range_atr": 0.0, "close_vs_range": 0.5}
        if not count:
            return {"higher_lows_count": 0.0, "lower_highs_count": 0.0, "swing_count": 0.0,
                    "linearity": 0.0, "consecutive_down": 0.0, "consecutive_up": 0.0}
        higher_lows = sum(1 for index in range(1, count) if lows[index] > lows[index - 1])
        lower_highs = sum(1 for index in range(1, count) if highs[index] < highs[index - 1])
        swings = sum(
            1 for index in range(2, count)
            if (1 if closes[index - 1] > closes[index - 2] else -1)
            != (1 if closes[index] > closes[index - 1] else -1)
        )
        x = np.arange(count)
        linearity = 0.0 if count < 2 or np.std(closes) == 0 else float(np.corrcoef(x, closes)[0, 1] ** 2)
        down = up = 0
        for index in range(count - 1, 0, -1):
            if closes[index] < closes[index - 1]:
                down += 1
            else:
                break
        for index in range(count - 1, 0, -1):
            if closes[index] > closes[index - 1]:
                up += 1
            else:
                break
        result: dict[str, float] = {
            "higher_lows_count": float(higher_lows), "lower_highs_count": float(lower_highs),
            "swing_count": float(swings), "linearity": linearity,
            "consecutive_down": float(down), "consecutive_up": float(up),
        }
        if scope == "trailing":
            range_points = max(highs) - min(lows)
            result.update({"range_atr": range_points / atr if atr > 0 else 0.0,
                           "close_vs_range": (closes[-1] - min(lows)) / range_points if range_points else 0.5})
        else:
            if direction not in (-1, 1) or breach_price is None or touch_price is None:
                raise ValueError("since_breach requires direction, breach_price, and touch_price")
            depth = breach_price - touch_price if direction == 1 else touch_price - breach_price
            result.update({"depth_atr": depth / atr if atr > 0 else 0.0,
                           "bars": float(count),
                           "efficiency_atr": (depth / count) / atr if atr > 0 else 0.0,
                           "retracement_atr": depth / atr if atr > 0 else 0.0,
                           "clean_score": ((higher_lows if direction == 1 else lower_highs) - swings) / count})
        return result
