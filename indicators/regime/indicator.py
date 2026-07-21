"""Regime Detection Indicator.

Detects directional regime (bullish/bearish) using dual EMA band confirmation.
The regime is "sticky" - once established, it persists until the opposite
condition is fully met.

IMPORTANT: To avoid look-ahead bias, use check_entry_signal() BEFORE update().
The correct flow is:
    1. signal = indicator.check_entry_signal(bar, min_ctb)  # Uses PREVIOUS values
    2. if signal: capture entry_price, atr from signal dict
    3. indicator.update(bar)  # Now update with new bar
"""

from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.indicators import AverageTrueRange


class RegimeIndicators:
    """Regime detection indicators with configurable periods."""

    def __init__(
        self,
        short_period: int = 3,
        long_period: int = 9,
        atr_period: int = 14,
    ):
        self.short_period = short_period
        self.long_period = long_period
        self.atr_period = atr_period

        # Short EMAs
        self.short_ema_high = ExponentialMovingAverage(short_period)
        self.short_ema_low = ExponentialMovingAverage(short_period)
        self.short_ema_close = ExponentialMovingAverage(short_period)

        # Long EMAs
        self.long_ema_high = ExponentialMovingAverage(long_period)
        self.long_ema_low = ExponentialMovingAverage(long_period)

        # ATR
        self.atr = AverageTrueRange(atr_period)

        # State
        self.regime = 0  # -1, 0, +1
        self.regime_id = 0  # Increments on each regime change
        self.has_breached = False
        self.waiting_for_touch = False  # True after breach, False after touch recorded
        self.bars_since_breach = 0
        self.breach_count_in_regime = 0
        self.touch_number_in_regime = 0
        self.consecutive_trend_bars = 0

    def check_entry_signal(self, bar, min_ctb: int = 1) -> dict | None:
        """
        Check for entry signal using CURRENT indicator values (before update).

        MUST be called BEFORE update() to avoid look-ahead bias.

        Returns dict with entry details if signal triggered, None otherwise.
        """
        if not self.is_warmed_up:
            return None

        # Check all entry conditions using CURRENT (pre-update) values
        if self.regime == 0:
            return None
        if not self.has_breached:
            return None
        if self.bars_since_breach < 1:
            return None
        if not self.waiting_for_touch:
            return None
        if self.consecutive_trend_bars < min_ctb:
            return None

        # Check touch against CURRENT EMA value
        if not self._check_touch_internal(bar):
            return None

        # Signal triggered - return entry details using CURRENT values
        return {
            'direction': self.regime,
            'entry_price': self.short_ema_close.value,
            'atr': self.atr.value,
            'ctb': self.consecutive_trend_bars,
            'touch_number': self.touch_number_in_regime + 1,
            'bars_since_breach': self.bars_since_breach,
        }

    def consume_touch(self):
        """Mark touch as consumed after entry. Call after check_entry_signal() returns a signal."""
        self.waiting_for_touch = False
        self.touch_number_in_regime += 1

    def update(self, bar):
        """Update all indicators with new bar. Call AFTER check_entry_signal()."""
        h, l, c, o = float(bar.high), float(bar.low), float(bar.close), float(bar.open)

        # Update EMAs
        self.short_ema_high.update_raw(h)
        self.short_ema_low.update_raw(l)
        self.short_ema_close.update_raw(c)
        self.long_ema_high.update_raw(h)
        self.long_ema_low.update_raw(l)

        # Update ATR
        self.atr.update_raw(h, l, c)

        # Update regime
        self._update_regime(c)

        # Update breach
        self._update_breach(c)

        # Update CTB
        self._update_ctb(o, c)

    def _update_regime(self, close: float):
        """Update regime state."""
        prev_regime = self.regime

        short_h = self.short_ema_high.value
        short_l = self.short_ema_low.value
        long_h = self.long_ema_high.value
        long_l = self.long_ema_low.value

        if close > short_h and close > long_h:
            self.regime = 1
        elif close < short_l and close < long_l:
            self.regime = -1
        # else: regime stays (sticky)

        # Reset on regime change
        if self.regime != prev_regime and prev_regime != 0:
            self._reset_regime()

    def _reset_regime(self):
        """Reset tracking on regime change."""
        self.regime_id += 1  # New regime gets new ID
        self.has_breached = False
        self.waiting_for_touch = False
        self.bars_since_breach = 0
        self.breach_count_in_regime = 0
        self.touch_number_in_regime = 0
        self.consecutive_trend_bars = 0

    def _update_breach(self, close: float):
        """Update breach state."""
        short_h = self.short_ema_high.value
        short_l = self.short_ema_low.value

        breach_detected = False
        if self.regime == 1 and close > short_h:
            breach_detected = True
        elif self.regime == -1 and close < short_l:
            breach_detected = True

        if breach_detected:
            self.has_breached = True
            self.waiting_for_touch = True  # Enable one touch opportunity
            self.bars_since_breach = 0
            self.breach_count_in_regime += 1
        else:
            self.bars_since_breach += 1

    def _update_ctb(self, open_: float, close: float):
        """Update consecutive trend bars."""
        if self.regime == 1:
            if close > open_:
                self.consecutive_trend_bars += 1
            else:
                self.consecutive_trend_bars = 0
        elif self.regime == -1:
            if close < open_:
                self.consecutive_trend_bars += 1
            else:
                self.consecutive_trend_bars = 0

    def _check_touch_internal(self, bar) -> bool:
        """Check if bar touched short_ema_close (internal use)."""
        ema = self.short_ema_close.value

        if self.regime == 1:
            return float(bar.low) <= ema
        elif self.regime == -1:
            return float(bar.high) >= ema
        return False

    def check_touch(self, bar) -> bool:
        """Check if bar touched short_ema_close. DEPRECATED: use check_entry_signal()."""
        return self._check_touch_internal(bar)

    @property
    def entry_price(self) -> float:
        """Get entry price (short EMA close). DEPRECATED: use check_entry_signal()."""
        return self.short_ema_close.value

    @property
    def is_warmed_up(self) -> bool:
        """Check if all indicators have enough data."""
        return (
            self.long_ema_high.initialized and
            self.long_ema_low.initialized and
            self.atr.initialized
        )


class Regime5m:
    """5-minute regime for alignment filter."""

    def __init__(self, short_period: int = 3, long_period: int = 9):
        self.short_period = short_period
        self.long_period = long_period

        self.short_ema_high = ExponentialMovingAverage(short_period)
        self.short_ema_low = ExponentialMovingAverage(short_period)
        self.long_ema_high = ExponentialMovingAverage(long_period)
        self.long_ema_low = ExponentialMovingAverage(long_period)
        self.regime = 0
        self.bars_in_regime = 0

    def update(self, bar_5m):
        """Update with 5m bar."""
        h, l, c = float(bar_5m.high), float(bar_5m.low), float(bar_5m.close)

        # Update EMAs
        self.short_ema_high.update_raw(h)
        self.short_ema_low.update_raw(l)
        self.long_ema_high.update_raw(h)
        self.long_ema_low.update_raw(l)

        # Update regime
        prev_regime = self.regime

        if c > self.short_ema_high.value and c > self.long_ema_high.value:
            self.regime = 1
        elif c < self.short_ema_low.value and c < self.long_ema_low.value:
            self.regime = -1

        if self.regime != prev_regime:
            self.bars_in_regime = 0
        else:
            self.bars_in_regime += 1

    def is_aligned(self, regime_1m: int) -> bool:
        """Check if 1m regime aligns with 5m."""
        return self.regime == regime_1m

    @property
    def is_warmed_up(self) -> bool:
        """Check if all indicators have enough data."""
        return (
            self.long_ema_high.initialized and
            self.long_ema_low.initialized
        )
