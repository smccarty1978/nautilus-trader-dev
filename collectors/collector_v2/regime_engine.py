"""RegimeStateEngine — per-TF regime/ATR/EMA state.

One instance per timeframe. Owned by the strategy. Receives
"bucket closed" events from TimeframeAggregator and:

  1. Updates EMA3/EMA9 of high & low
  2. Updates Wilder ATR(period)
  3. Recomputes regime per the existing SimpleRegimeTracker rules
  4. Writes a frozen CompletedBarState to the CompletedBarRegistry

After update, registry.audit_provenance(any_decision_ts >=
state.close_ts) will pass.

Regime rules (matching legacy SimpleRegimeTracker):
  - long  if close > EMA3_high AND close > EMA9_high
  - short if close < EMA3_low AND close < EMA9_low
  - else  carry forward (sticky)
"""

from __future__ import annotations
from collections import deque
from typing import Optional

from .aggregator import _OpenBucket
from .registry import CompletedBarRegistry, CompletedBarState


class RegimeStateEngine:
    """Per-TF regime/ATR/EMA state machine. Bound to a registry on
    construction. Single-direction feed: aggregator → engine →
    registry."""

    ALPHA3 = 2.0 / (3 + 1)
    ALPHA9 = 2.0 / (9 + 1)

    def __init__(
        self,
        timeframe: str,
        registry: CompletedBarRegistry,
        atr_period: int = 14,
    ):
        self._tf = timeframe
        self._registry = registry
        self._atr_period = atr_period

        self._ema3_h: Optional[float] = None
        self._ema9_h: Optional[float] = None
        self._ema3_l: Optional[float] = None
        self._ema9_l: Optional[float] = None

        # ATR state
        self._prev_close: Optional[float] = None
        self._atr: Optional[float] = None
        self._tr_warmup: deque = deque(maxlen=atr_period)

        self._regime: int = 0
        self._bars_in_regime: int = 0
        from features.trackers.regime_dual_ema import DualEmaRegimeTracker
        self._tracker = DualEmaRegimeTracker(timeframe=timeframe, short_period=3, long_period=9, atr_period=atr_period)

    @property
    def timeframe(self) -> str:
        return self._tf

    @property
    def n_bars_processed(self) -> int:
        return self._registry.n_updates(self._tf)

    def on_bar_closed(self, completed: _OpenBucket) -> None:
        """Called by aggregator when a TF bucket completes. Updates
        all state and writes a frozen CompletedBarState."""
        h, l, c = completed.high, completed.low, completed.close
        # Single authoritative implementation of the math: features.trackers.regime_dual_ema.
        upd = self._tracker.observe(h, l, c)
        self._ema3_h, self._ema9_h = upd.ema_short_high, upd.ema_long_high
        self._ema3_l, self._ema9_l = upd.ema_short_low, upd.ema_long_low
        self._prev_close = c
        self._atr = upd.atr
        self._regime = upd.regime
        self._bars_in_regime = upd.bars_in_regime

        # ---- Write CompletedBarState ----
        state = CompletedBarState(
            timeframe=self._tf,
            open_ts=completed.open_ts,
            close_ts=completed.close_ts,
            open=completed.open,
            high=completed.high,
            low=completed.low,
            close=completed.close,
            volume=completed.volume,
            regime=self._regime,
            bars_in_regime=self._bars_in_regime,
            atr=float("nan") if self._atr is None else self._atr,
            ema3_h=self._ema3_h,
            ema9_h=self._ema9_h,
            ema3_l=self._ema3_l,
            ema9_l=self._ema9_l,
        )
        self._registry.update(self._tf, state)
