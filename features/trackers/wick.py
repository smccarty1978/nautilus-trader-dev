"""Causal 1m Wick Imbalance Tracker.

Computes wick imbalance on completed 1-minute bars:
  upper_wick = high - max(open, close)
  lower_wick = min(open, close) - low
  if high == low: feature = 0.0
  otherwise: feature = (upper_wick - lower_wick) / (high - low)

Only complete 1-minute bars passed to update() are incorporated.
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

    def calculate(self) -> Dict[str, float]:
        """Return current feature values dictionary."""
        val = self.latest_wick_imbalance if self.latest_wick_imbalance is not None else 0.0
        return {
            "latest_1m_wick_imbalance": float(val),
        }
