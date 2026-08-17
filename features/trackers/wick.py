"""Causal 1m Wick Imbalance Tracker.

Computes wick imbalance on completed 1-minute bars:
  upper_wick = high - max(open, close)
  lower_wick = min(open, close) - low
  if high == low: feature = 0.0
  otherwise: feature = (upper_wick - lower_wick) / (high - low)

Only complete 1-minute bars passed to update() are incorporated.

Availability
------------
Before any completed 1m bar has been observed the feature is **unavailable**, and
``calculate()`` reports ``None`` for it. It previously reported ``0.0``, which made
three different states indistinguishable in the emitted surface:

  * no completed 1m bar yet          -- the feature does not exist yet
  * a completed zero-range bar       -- 0.0 by the formula's ``high == low`` branch
  * a completed perfectly balanced bar -- 0.0 because upper and lower wicks are equal

Only the first is unavailability. The latter two are real observations that the frozen
formula defines as 0.0, and they remain 0.0. ``None`` is the correct representation for
the first because the registry declares ``null_policy='allow'`` for this feature; the
tracker must not manufacture an in-range value to fill a gap the contract already
permits to be empty.
"""
from __future__ import annotations

from typing import Dict, Optional


def compute_wick_imbalance(open_px: float, high: float, low: float, close: float) -> float:
    """Compute normalized wick imbalance for a single OHLC bar."""
    rng = high - low
    if rng <= 0.0:
        return 0.0
    upper_wick = high - max(open_px, close)
    lower_wick = min(open_px, close) - low
    return (upper_wick - lower_wick) / rng


class WickTracker:
    """Stateful tracker for latest completed 1m bar wick imbalance."""

    def __init__(self) -> None:
        self.latest_wick_imbalance: Optional[float] = None
        self.bar_count: int = 0

    def update(self, open_px: float, high: float, low: float, close: float) -> float:
        """Update tracker with a COMPLETED 1m bar.
        
        Do NOT call with a forming bar.
        """
        val = compute_wick_imbalance(open_px, high, low, close)
        self.latest_wick_imbalance = val
        self.bar_count += 1
        return val

    @property
    def is_available(self) -> bool:
        """True once at least one completed 1m bar has been incorporated."""
        return self.bar_count > 0

    def calculate(self) -> Dict[str, Optional[float]]:
        """Return current feature values dictionary.

        Returns ``None`` for the feature while it is unavailable (no completed 1m bar
        yet). See the module docstring for why this is not ``0.0``.
        """
        if not self.is_available:
            return {"latest_1m_wick_imbalance": None}
        return {
            "latest_1m_wick_imbalance": float(self.latest_wick_imbalance),
        }
