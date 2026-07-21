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

    def update(self, bucket: _OpenBucket) -> None:
        h, l, c = bucket.high, bucket.low, bucket.close

        # EMA update
        if self._ema3_h is None:
            self._ema3_h = h
            self._ema9_h = h
            self._ema3_l = l
            self._ema9_l = l
        else:
            a3, a9 = self.ALPHA3, self.ALPHA9
            self._ema3_h = a3 * h + (1 - a3) * self._ema3_h
            self._ema9_h = a9 * h + (1 - a9) * self._ema9_h
            self._ema3_l = a3 * l + (1 - a3) * self._ema3_l
            self._ema9_l = a9 * l + (1 - a9) * self._ema9_l

        # Wilder ATR(14)
        if self._prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))
        self._prev_close = c
        if self._atr is None:
            self._atr_warmup.append(tr)
            if len(self._atr_warmup) == self._atr_period:
                self._atr = sum(self._atr_warmup) / self._atr_period
                self._atr_warmup = []
        else:
            self._atr = (self._atr * (self._atr_period - 1) + tr) / self._atr_period

        # Regime detection (exact match to RegimeStateEngine)
        new_regime = self.regime
        if c > self._ema3_h and c > self._ema9_h:
            new_regime = 1
        elif c < self._ema3_l and c < self._ema9_l:
            new_regime = -1

        if new_regime == 0:
            pass  # indeterminate — keep sticky regime
        elif new_regime == self.regime:
            self.bars_in_regime += 1
        else:
            self.bars_in_regime = 1
            self.regime = new_regime

    @property
    def atr(self) -> Optional[float]:
        return self._atr
