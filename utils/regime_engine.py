"""Regime State Engine & Category Helper.

Extracted from strategies/pullback_5s/strategy.py to isolate pure calculations
from mutable runtime strategy state.
"""

from __future__ import annotations
import math
from typing import Optional
from collectors.collector_v2.aggregator import _OpenBucket

# Constants
IS_STALL_P33 = 0.044
IS_STALL_P67 = 0.304


def state_cat(hc_val: float, state_raw: str) -> str:
    """Classify the hC and raw state into stall categories."""
    if state_raw == "Healthy":
        return "Healthy"
    if state_raw == "DETER":
        return "DETER"
    if state_raw in ("HardStall", "SoftStall"):
        if hc_val >= IS_STALL_P67:
            return "HH-HardStall"
        if hc_val >= IS_STALL_P33:
            return "MH-HardStall"
        return "LH-HardStall"
    return "Other"


class LiteRegimeEngine:
    """Minimal 1m regime tracker replicating RegimeStateEngine exactly.

    Feeds on completed 1m buckets (from TimeframeAggregator). ATR is
    Wilder ATR(14). EMA3/EMA9 of bar H/L drive regime detection.
    """

    ALPHA3 = 2.0 / (3 + 1)
    ALPHA9 = 2.0 / (9 + 1)

    def __init__(self, atr_period: int = 14) -> None:
        self._atr_period = atr_period
        self._ema3_h: Optional[float] = None
        self._ema9_h: Optional[float] = None
        self._ema3_l: Optional[float] = None
        self._ema9_l: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._atr_warmup: list[float] = []
        self._atr: Optional[float] = None

        self.regime: int = 0
        self.bars_in_regime: int = 0
        from features.trackers.regime_dual_ema import DualEmaRegimeTracker
        self._tracker = DualEmaRegimeTracker(timeframe="1m", short_period=3, long_period=9, atr_period=atr_period)

    def update(self, bucket: _OpenBucket) -> None:
        h, l, c = bucket.high, bucket.low, bucket.close
        # Single authoritative implementation of the math: features.trackers.regime_dual_ema.
        upd = self._tracker.observe(h, l, c)
        self._ema3_h, self._ema9_h = upd.ema_short_high, upd.ema_long_high
        self._ema3_l, self._ema9_l = upd.ema_short_low, upd.ema_long_low
        self._prev_close = c
        self._atr = upd.atr
        self.regime = upd.regime
        self.bars_in_regime = upd.bars_in_regime

    @property
    def atr(self) -> Optional[float]:
        return self._atr
