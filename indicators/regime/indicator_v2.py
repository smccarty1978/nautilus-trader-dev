"""Regime Detection Indicator v2 - With Energy Features.

Adds breach energy metrics for ML feature extraction:
- EMA Slopes (trend strength/momentum)
- ATR Ratio (volatility expansion)
- Breach Velocity (move sharpness)
- RVOL (volume conviction)
"""

from collections import deque

from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.indicators import AverageTrueRange


class RegimeIndicatorsV2:
    """
    Regime detection with Energy feature tracking.

    Energy Features (captured at entry time):
    - ema_slope_short: Normalized slope of short EMA (momentum)
    - ema_slope_long: Normalized slope of long EMA (trend strength)
    - atr_ratio: ATR(14) / ATR(200) - volatility expansion
    - breach_velocity: ATR-normalized price move per bar during breach
    - rvol_breach: Relative volume during breach vs 20-bar average
    """

    def __init__(
        self,
        short_period: int = 3,
        long_period: int = 9,
        atr_period: int = 14,
        atr_long_period: int = 200,
        slope_lookback: int = 5,
        volume_baseline_period: int = 20,
    ):
        self.short_period = short_period
        self.long_period = long_period
        self.atr_period = atr_period
        self.atr_long_period = atr_long_period
        self.slope_lookback = slope_lookback
        self.volume_baseline_period = volume_baseline_period

        # Short EMAs
        self.short_ema_high = ExponentialMovingAverage(short_period)
        self.short_ema_low = ExponentialMovingAverage(short_period)
        self.short_ema_close = ExponentialMovingAverage(short_period)

        # Long EMAs
        self.long_ema_high = ExponentialMovingAverage(long_period)
        self.long_ema_low = ExponentialMovingAverage(long_period)
        self.long_ema_close = ExponentialMovingAverage(long_period)

        # ATR - short and long term
        self.atr = AverageTrueRange(atr_period)
        self.atr_long = AverageTrueRange(atr_long_period)

        # EMA History Buffers (for slope calculation)
        # Need slope_lookback + 1 values to calculate slope over slope_lookback bars
        self.short_ema_buffer = deque(maxlen=slope_lookback + 1)
        self.long_ema_buffer = deque(maxlen=slope_lookback + 1)

        # Volume tracking
        self.volume_buffer = deque(maxlen=volume_baseline_period)
        self.current_bar_volume = 0.0

        # Regime State
        self.regime = 0  # -1, 0, +1
        self.regime_id = 0
        self.has_breached = False
        self.waiting_for_touch = False
        self.bars_since_breach = 0
        self.breach_count_in_regime = 0
        self.touch_number_in_regime = 0
        self.consecutive_trend_bars = 0
        self.bars_in_regime = 0

        # New properties for ML features
        self.is_currently_breaching = False  # True when close beyond EMA
        self.regime_high = 0.0  # Running max(high) since regime start
        self.regime_low = float('inf')  # Running min(low) since regime start
        self._breach_ended = False  # Track when breach ends for bars_since_breach

        # Breach Energy State
        self.breach_start_price = 0.0
        self.breach_start_bar = 0
        self.breach_cumulative_volume = 0.0
        self.breach_bars = 0
        self.max_extension_from_ema = 0.0
        self._bar_count = 0

    def update(self, bar):
        """Update all indicators with new bar."""
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        o = float(bar.open)
        v = float(bar.volume) if hasattr(bar, 'volume') else 0.0

        self._bar_count += 1
        self.current_bar_volume = v

        # Update EMAs
        self.short_ema_high.update_raw(h)
        self.short_ema_low.update_raw(l)
        self.short_ema_close.update_raw(c)
        self.long_ema_high.update_raw(h)
        self.long_ema_low.update_raw(l)
        self.long_ema_close.update_raw(c)

        # Update EMA buffers for slope calculation
        if self.short_ema_close.initialized:
            self.short_ema_buffer.append(self.short_ema_close.value)
        if self.long_ema_close.initialized:
            self.long_ema_buffer.append(self.long_ema_close.value)

        # Update ATR
        self.atr.update_raw(h, l, c)
        self.atr_long.update_raw(h, l, c)

        # Update volume buffer
        self.volume_buffer.append(v)

        # Update regime
        self._update_regime(c)

        # Update breach (and track energy)
        self._update_breach(c, v)

        # Update CTB
        self._update_ctb(o, c)

        # Track bars in regime
        self.bars_in_regime += 1

        # Track regime high/low for pullback depth calculation
        self.regime_high = max(self.regime_high, h)
        self.regime_low = min(self.regime_low, l)

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
        self.regime_id += 1
        self.has_breached = False
        self.waiting_for_touch = False
        self.bars_since_breach = 0
        self.breach_count_in_regime = 0
        self.touch_number_in_regime = 0
        self.consecutive_trend_bars = 0
        self.bars_in_regime = 0

        # Reset new ML feature properties
        self.is_currently_breaching = False
        self.regime_high = 0.0
        self.regime_low = float('inf')
        self._breach_ended = False

        # Reset breach energy state
        self.breach_start_price = 0.0
        self.breach_start_bar = 0
        self.breach_cumulative_volume = 0.0
        self.breach_bars = 0
        self.max_extension_from_ema = 0.0

    def _update_breach(self, close: float, volume: float):
        """Update breach state and track energy metrics."""
        short_h = self.short_ema_high.value
        short_l = self.short_ema_low.value

        breach_detected = False
        if self.regime == 1 and close > short_h:
            breach_detected = True
        elif self.regime == -1 and close < short_l:
            breach_detected = True

        # Track is_currently_breaching (true when close is beyond EMA)
        self.is_currently_breaching = breach_detected

        if breach_detected:
            if not self.has_breached:
                # First breach in this regime - capture start state
                self.breach_start_price = close
                self.breach_start_bar = self._bar_count
                self.breach_cumulative_volume = volume
                self.breach_bars = 1
                self.max_extension_from_ema = abs(close - self.short_ema_close.value)
            else:
                # Continuing breach - accumulate energy
                self.breach_cumulative_volume += volume
                self.breach_bars += 1
                extension = abs(close - self.short_ema_close.value)
                self.max_extension_from_ema = max(self.max_extension_from_ema, extension)

            self.has_breached = True
            self.waiting_for_touch = True
            self._breach_ended = False  # Still breaching
            self.breach_count_in_regime += 1
        else:
            # Breach ended (pullback started) - start counting bars_since_breach
            if self.has_breached and not self._breach_ended:
                # First bar after breach ended
                self._breach_ended = True
                self.bars_since_breach = 1
            elif self._breach_ended:
                # Continue counting bars since breach ended
                self.bars_since_breach += 1

            if self.has_breached:
                # Still accumulate volume during pullback
                self.breach_cumulative_volume += volume
                self.breach_bars += 1

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

    # =========================================================================
    # ENERGY FEATURE PROPERTIES
    # =========================================================================

    @property
    def ema_slope_short(self) -> float:
        """
        Normalized slope of short EMA over lookback period.

        Calculation: (current - N bars ago) / (N * ATR)
        Positive = upward momentum, Negative = downward momentum
        """
        if len(self.short_ema_buffer) < self.slope_lookback + 1:
            return 0.0
        if not self.atr.initialized or self.atr.value <= 0:
            return 0.0

        current = self.short_ema_buffer[-1]
        past = self.short_ema_buffer[0]  # slope_lookback bars ago

        return (current - past) / (self.slope_lookback * self.atr.value)

    @property
    def ema_slope_long(self) -> float:
        """
        Normalized slope of long EMA over lookback period.

        Captures the underlying trend strength (slower, more stable).
        """
        if len(self.long_ema_buffer) < self.slope_lookback + 1:
            return 0.0
        if not self.atr.initialized or self.atr.value <= 0:
            return 0.0

        current = self.long_ema_buffer[-1]
        past = self.long_ema_buffer[0]

        return (current - past) / (self.slope_lookback * self.atr.value)

    @property
    def atr_ratio(self) -> float:
        """
        Volatility expansion ratio: ATR(14) / ATR(200).

        > 1.0 = expanding volatility (breakout conditions)
        < 1.0 = contracting volatility (consolidation)
        """
        if not self.atr_long.initialized or self.atr_long.value <= 0:
            return 1.0
        return self.atr.value / self.atr_long.value

    @property
    def breach_velocity(self) -> float:
        """
        ATR-normalized price distance per bar during breach.

        Calculation: (current_price - breach_start_price) / (breach_bars * ATR)

        High velocity = "Snap" breach (impulsive, high conviction)
        Low velocity = "Grind" breach (slow, potentially fading)
        """
        if self.breach_bars <= 0:
            return 0.0
        if not self.atr.initialized or self.atr.value <= 0:
            return 0.0

        # Use max extension from EMA as the "distance covered"
        # This captures the peak energy of the move
        return self.max_extension_from_ema / (self.breach_bars * self.atr.value)

    @property
    def rvol_breach(self) -> float:
        """
        Relative volume during breach vs baseline.

        Calculation: avg_breach_volume / avg_baseline_volume

        > 1.0 = above average volume (conviction)
        < 1.0 = below average volume (weak move)
        """
        if self.breach_bars <= 0:
            return 1.0

        avg_breach_vol = self.breach_cumulative_volume / self.breach_bars

        if len(self.volume_buffer) < self.volume_baseline_period:
            return 1.0

        avg_baseline_vol = sum(self.volume_buffer) / len(self.volume_buffer)

        if avg_baseline_vol <= 0:
            return 1.0

        return avg_breach_vol / avg_baseline_vol

    @property
    def volume_baseline(self) -> float:
        """Average volume over baseline period."""
        if len(self.volume_buffer) == 0:
            return 0.0
        return sum(self.volume_buffer) / len(self.volume_buffer)

    # =========================================================================
    # EXISTING METHODS (preserved for compatibility)
    # =========================================================================

    def check_touch(self, bar) -> bool:
        """Check if bar touched short_ema_close."""
        ema = self.short_ema_close.value

        if self.regime == 1:
            return float(bar.low) <= ema
        elif self.regime == -1:
            return float(bar.high) >= ema
        return False

    @property
    def entry_price(self) -> float:
        """Get entry price (short EMA close)."""
        return self.short_ema_close.value

    @property
    def is_warmed_up(self) -> bool:
        """Check if all indicators have enough data."""
        return (
            self.long_ema_high.initialized and
            self.long_ema_low.initialized and
            self.atr.initialized and
            len(self.short_ema_buffer) >= self.slope_lookback + 1
        )

    @property
    def is_fully_warmed_up(self) -> bool:
        """Check if ALL indicators including ATR(200) are warmed up."""
        return (
            self.is_warmed_up and
            self.atr_long.initialized
        )

    def get_energy_snapshot(self) -> dict:
        """
        Get current Energy feature values.

        Call this at entry time to capture features for ML.
        """
        return {
            'ema_slope_short': self.ema_slope_short,
            'ema_slope_long': self.ema_slope_long,
            'atr_ratio': self.atr_ratio,
            'breach_velocity': self.breach_velocity,
            'rvol_breach': self.rvol_breach,
            'max_extension_atr': self.max_extension_from_ema / self.atr.value if self.atr.value > 0 else 0.0,
            'breach_bars': self.breach_bars,
            'breach_cumulative_volume': self.breach_cumulative_volume,
        }
