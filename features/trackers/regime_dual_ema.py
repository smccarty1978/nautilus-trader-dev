"""The one authoritative dual-EMA regime tracker (``tracker.regime.dual_ema``).

Accepted semantics (unchanged from the collector_v2 ``RegimeStateEngine`` and the generic
collector's ``RegimeEngine``, which now both delegate here):

* EMA(short=3) and EMA(long=9) of completed-bar HIGH and LOW, alpha = 2/(n+1); the first
  completed bar seeds every EMA with its own high/low.
* Wilder ATR(period=14): true range with the previous close; the first ``period`` true
  ranges are averaged to seed, then ``atr = (atr*(p-1) + tr)/p``.
* Regime: +1 if close > EMA_short_high and close > EMA_long_high; -1 if close < EMA_short_low
  and close < EMA_long_low; otherwise the previous regime carries forward (sticky). 0 until
  the first determinate bar.

Parameters are identity: ``timeframe`` and ``instrument`` name the completed-bar stream the
tracker is fed (the tracker never aggregates or reads bars itself), ``short_period``,
``long_period`` and ``atr_period`` are the formula parameters. Nothing here depends on a
study, a session, or a runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

SEMANTICS_VERSION = "dual_ema_hl_sticky_wilder_atr_v1"


@dataclass(frozen=True)
class RegimeUpdate:
    regime: int
    previous_regime: int
    flipped: bool
    atr: Optional[float]
    bars_in_regime: int
    ema_short_high: float
    ema_long_high: float
    ema_short_low: float
    ema_long_low: float


class DualEmaRegimeTracker:
    """Completed-bar dual-EMA regime state. Feed one completed bar per ``update``."""

    def __init__(self, *, timeframe: str = "1m", instrument: Optional[str] = None,
                 short_period: int = 3, long_period: int = 9, atr_period: int = 14) -> None:
        if short_period < 1 or long_period < 1 or atr_period < 1:
            raise ValueError("periods must be >= 1")
        self.timeframe, self.instrument = str(timeframe), instrument
        self.short_period, self.long_period, self.atr_period = int(short_period), int(long_period), int(atr_period)
        self.alpha_short = 2.0 / (self.short_period + 1)
        self.alpha_long = 2.0 / (self.long_period + 1)
        self.ema3_h: Optional[float] = None
        self.ema9_h: Optional[float] = None
        self.ema3_l: Optional[float] = None
        self.ema9_l: Optional[float] = None
        self.prev_c: Optional[float] = None
        self.atr: Optional[float] = None
        self._tr_warmup: List[float] = []
        self.regime: int = 0
        self.bars_in_regime: int = 0
        self.bars_processed: int = 0

    # -- identity -----------------------------------------------------------------
    def identity(self) -> dict:
        return {"capability": "tracker.regime.dual_ema", "semantics_version": SEMANTICS_VERSION, "timeframe": self.timeframe,
                "instrument": self.instrument, "short_period": self.short_period, "long_period": self.long_period, "atr_period": self.atr_period}

    # -- update -------------------------------------------------------------------
    def update(self, high: float, low: float, close: float) -> int:
        """Ingest one completed bar; returns the (sticky) regime. Compatible with the legacy ``RegimeEngine.update``."""
        return self.observe(high, low, close).regime

    def observe(self, high: float, low: float, close: float) -> RegimeUpdate:
        h, l, c = float(high), float(low), float(close)
        if self.ema3_h is None:
            self.ema3_h = self.ema9_h = h
            self.ema3_l = self.ema9_l = l
        else:
            a3, a9 = self.alpha_short, self.alpha_long
            self.ema3_h = a3 * h + (1 - a3) * self.ema3_h
            self.ema9_h = a9 * h + (1 - a9) * self.ema9_h
            self.ema3_l = a3 * l + (1 - a3) * self.ema3_l
            self.ema9_l = a9 * l + (1 - a9) * self.ema9_l

        tr = h - l if self.prev_c is None else max(h - l, abs(h - self.prev_c), abs(l - self.prev_c))
        self.prev_c = c
        if self.atr is None:
            self._tr_warmup.append(tr)
            if len(self._tr_warmup) == self.atr_period:
                self.atr = sum(self._tr_warmup) / self.atr_period
                self._tr_warmup = []
        else:
            self.atr = (self.atr * (self.atr_period - 1) + tr) / self.atr_period

        previous = self.regime
        new_regime = previous
        if c > self.ema3_h and c > self.ema9_h:
            new_regime = 1
        elif c < self.ema3_l and c < self.ema9_l:
            new_regime = -1
        flipped = False
        if new_regime != 0:
            if new_regime == previous:
                self.bars_in_regime += 1
            else:
                flipped = previous != 0
                self.bars_in_regime = 1
                self.regime = new_regime
        self.bars_processed += 1
        return RegimeUpdate(self.regime, previous, flipped, self.atr, self.bars_in_regime, self.ema3_h, self.ema9_h, self.ema3_l, self.ema9_l)


__all__ = ["DualEmaRegimeTracker", "RegimeUpdate", "SEMANTICS_VERSION"]
