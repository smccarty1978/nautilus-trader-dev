"""Causal 1m Close-Position-in-Prior-5-Bar-Range Tracker.

Computes, for the latest completed 1-minute bar t, where its close sits within
the high/low range of the five 1m bars immediately preceding it:

    prev5_high = max(high[t-5:t])
    prev5_low  = min(low[t-5:t])
    value = (close[t] - prev5_low) / (prev5_high - prev5_low)

Bar t itself is excluded from the reference range -- only its close is
positioned against the prior five bars. If ``prev5_high == prev5_low`` (a
flat prior range) the feature is undefined and reports ``None``.

Only complete 1-minute bars passed to ``update()`` are incorporated; a
forming/incomplete bar must never be passed in.

Availability
------------
Before five prior completed bars exist, there is no reference range to
position against, so the feature is **unavailable** (``None``) -- this is
distinct from a flat-range ``None``, but both surface identically per the
registry's ``null_policy='allow'`` for this feature (warmup=6: five prior
bars plus the current bar).
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Optional, Tuple


def compute_range_position(
    close: float, prev5_high: float, prev5_low: float
) -> Optional[float]:
    """Compute close position within [prev5_low, prev5_high]. None if the range is flat."""
    if prev5_high == prev5_low:
        return None
    return (close - prev5_low) / (prev5_high - prev5_low)


class RangePositionTracker:
    """Stateful tracker for latest completed 1m bar's close position in the prior 5-bar range."""

    def __init__(self, lookback: int = 5) -> None:
        self.lookback = lookback
        # Holds (high, low) of the `lookback` completed bars preceding the current one.
        self._history: Deque[Tuple[float, float]] = deque(maxlen=lookback)
        self.latest_value: Optional[float] = None
        self.bar_count: int = 0

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        """Update tracker with a COMPLETED 1m bar.

        Do NOT call with a forming bar.
        """
        if len(self._history) < self.lookback:
            value: Optional[float] = None
        else:
            prev5_high = max(h for h, _ in self._history)
            prev5_low = min(l for _, l in self._history)
            value = compute_range_position(close, prev5_high, prev5_low)

        self.latest_value = value
        self.bar_count += 1
        self._history.append((high, low))
        return value

    @property
    def is_available(self) -> bool:
        """True once 5 prior completed bars plus the current bar have been observed.

        Distinct from the computed value being non-``None``: a flat prior range is
        available (the window is satisfied) but still reports ``None`` by formula.
        """
        return self.bar_count >= self.lookback + 1

    def calculate(self) -> Dict[str, Optional[float]]:
        """Return current feature values dictionary.

        Reports ``None`` while unavailable (fewer than 5 prior completed bars)
        or while the prior 5-bar range is flat. See module docstring.
        """
        return {"latest_1m_close_position_prev5_range": self.latest_value}
