# Regime Detection Indicator

## Purpose

Detects directional regime (bullish/bearish) using dual EMA band confirmation. The regime is "sticky" - once established, it persists until the opposite condition is fully met.

---

## Indicators Required

| Indicator | Input | Period | Purpose |
|-----------|-------|--------|---------|
| short_ema_high | bar.high | short_period (default 3) | Upper band - bullish breach level |
| short_ema_low | bar.low | short_period (default 3) | Lower band - bearish breach level |
| short_ema_close | bar.close | short_period (default 3) | Entry level (pullback target) |
| long_ema_high | bar.high | long_period (default 9) | Bullish regime confirmation |
| long_ema_low | bar.low | long_period (default 9) | Bearish regime confirmation |
| atr | bar | atr_period (default 14, Wilder) | Position sizing, PT/SL |

### Configuration

```python
class RegimeConfig:
    short_period: int = 3      # Fast EMA period
    long_period: int = 9       # Slow EMA period
    atr_period: int = 14       # ATR period
```

---

## Regime Logic

### Definition

```python
# Bullish regime (+1)
if close > short_ema_high AND close > long_ema_high:
    regime = +1

# Bearish regime (-1)
if close < short_ema_low AND close < long_ema_low:
    regime = -1

# Neutral (0) - ONLY during warmup
# Once regime established, it's STICKY until opposite condition fully met
```

### Key Behaviors

1. **Sticky**: Regime stays until OPPOSITE condition is met
   - Being in bullish and dropping below short_ema_high does NOT flip regime
   - Must drop below BOTH short_ema_low AND long_ema_low to flip to bearish

2. **No neutral after warmup**: Once first regime established, always +1 or -1

3. **Regime change bar can be breach bar**: Don't return early on regime change

---

## Breach Logic

A breach occurs when price closes beyond the short EMA band in the direction of the regime.

```python
# Bullish breach (while in bullish regime)
bullish_breach = (regime == +1) AND (close > short_ema_high)

# Bearish breach (while in bearish regime)
bearish_breach = (regime == -1) AND (close < short_ema_low)
```

### Breach Tracking

```python
if breach_detected:
    has_breached = True
    bars_since_breach = 0
    breach_count_in_regime += 1
else:
    bars_since_breach += 1
```

---

## Touch Logic

A touch occurs when price pulls back to the short_ema_close level.

```python
# Bullish touch (looking for pullback to enter long)
bullish_touch = (bar.low <= short_ema_close)

# Bearish touch (looking for pullback to enter short)
bearish_touch = (bar.high >= short_ema_close)
```

### Touch Counting

```python
# Touch number resets ONLY on regime change
# Does NOT reset on new breaches within same regime

if regime_changed:
    touch_number_in_regime = 0

if touch_detected:
    touch_number_in_regime += 1
```

---

## Consecutive Trend Bars (CTB)

Counts consecutive bars moving in the trend direction.

```python
# Bullish: count consecutive green bars (close > open)
# Bearish: count consecutive red bars (close < open)

if regime == +1:
    if bar.close > bar.open:
        consecutive_trend_bars += 1
    else:
        consecutive_trend_bars = 0

elif regime == -1:
    if bar.close < bar.open:
        consecutive_trend_bars += 1
    else:
        consecutive_trend_bars = 0
```

---

## Implementation (NT Strategy)

```python
from nautilus_trader.indicators.average.ema import ExponentialMovingAverage
from nautilus_trader.indicators.atr import AverageTrueRange

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
        self.has_breached = False
        self.bars_since_breach = 0
        self.breach_count_in_regime = 0
        self.touch_number_in_regime = 0
        self.consecutive_trend_bars = 0

    def update(self, bar):
        """Update all indicators with new bar."""
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
        self.has_breached = False
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
            self.atr.initialized
        )
```

---

## Validation

### Manual Verification

For any bar, verify:
1. EMA values match expected (compare to TradingView or pandas calculation)
2. Regime flips only when both conditions met
3. Breach count increments correctly
4. Touch number resets only on regime change
5. CTB resets on opposite color bar

### Test Cases

```python
# Test: Regime should be sticky
# Setup: Bullish regime established
# Action: Close drops below short_ema_high but stays above short_ema_low
# Expected: Regime stays +1

# Test: Regime change bar is also breach bar
# Setup: Bearish regime
# Action: Close > short_ema_high AND close > long_ema_high
# Expected: Regime flips to +1, breach detected, bars_since_breach = 0

# Test: Touch counting
# Setup: Bullish regime, 2 touches occurred
# Action: New breach, then another touch
# Expected: touch_number_in_regime = 3 (not reset on breach)
```

---

## 5-Minute Regime

Same logic applied to 5-minute bars for higher timeframe confirmation.

```python
class Regime5m:
    """5-minute regime for alignment filter."""

    def __init__(self, short_period: int = 3, long_period: int = 9):
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
```
