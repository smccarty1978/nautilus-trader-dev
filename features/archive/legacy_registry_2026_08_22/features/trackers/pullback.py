from typing import Dict, List, Optional
import numpy as np

class PullbackTracker:
    """Tracks micro and macro pullback structure features on 1s and 1m bar lists."""

    @staticmethod
    def calculate_1s(highs: List[float], lows: List[float], closes: List[float], atr: float) -> Dict[str, float]:
        h = highs
        l = lows
        c = closes
        n = len(c)

        if n < 30:
            return {
                'higher_lows_count_1s': 0.0, 'lower_highs_count_1s': 0.0,
                'swing_count_1s': 0.0, 'pullback_linearity_1s': 0.0,
                'consecutive_down_1s': 0.0, 'consecutive_up_1s': 0.0,
                'range_30s_atr': 0.0, 'close_vs_range_30s': 0.5,
            }

        higher_lows = sum(1 for i in range(-29, 0) if l[i] > l[i-1])
        lower_highs = sum(1 for i in range(-29, 0) if h[i] < h[i-1])

        swings = 0
        for i in range(-28, 0):
            prev_dir = 1 if c[i-1] > c[i-2] else -1
            curr_dir = 1 if c[i] > c[i-1] else -1
            if curr_dir != prev_dir:
                swings += 1

        x = np.arange(30)
        y = np.array(c[-30:])
        if np.std(y) > 0:
            try:
                corr = np.corrcoef(x, y)[0, 1]
                r_squared = corr ** 2 if not np.isnan(corr) else 0.0
            except Exception:
                r_squared = 0.0
        else:
            r_squared = 0.0

        consec_down = 0
        for i in range(-1, -31, -1):
            if i - 1 >= -n and c[i] < c[i-1]:
                consec_down += 1
            else:
                break

        consec_up = 0
        for i in range(-1, -31, -1):
            if i - 1 >= -n and c[i] > c[i-1]:
                consec_up += 1
            else:
                break

        range_30s = max(h[-30:]) - min(l[-30:])
        close_vs_range = (c[-1] - min(l[-30:])) / range_30s if range_30s > 0 else 0.5

        return {
            'higher_lows_count_1s': float(higher_lows),
            'lower_highs_count_1s': float(lower_highs),
            'swing_count_1s': float(swings),
            'pullback_linearity_1s': float(r_squared),
            'consecutive_down_1s': float(consec_down),
            'consecutive_up_1s': float(consec_up),
            'range_30s_atr': float(range_30s / atr if atr > 0 else 0.0),
            'close_vs_range_30s': float(close_vs_range),
        }

    @staticmethod
    def calculate_1m(
        bars_since_breach: List,
        breach_price: float,
        touch_price: float,
        atr: float,
        direction: int,
    ) -> Dict[str, float]:
        if len(bars_since_breach) == 0:
            return {
                'higher_lows_count_1m': 0.0, 'lower_highs_count_1m': 0.0,
                'swing_count_1m': 0.0, 'pullback_depth_atr': 0.0,
                'pullback_bars_1m': 0.0, 'pullback_efficiency_1m': 0.0,
                'retracement_pct': 0.0, 'clean_pullback_score_1m': 0.0,
            }

        highs = [float(b.high) for b in bars_since_breach]
        lows = [float(b.low) for b in bars_since_breach]
        closes = [float(b.close) for b in bars_since_breach]

        higher_lows = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
        lower_highs = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i-1])

        swings = 0
        for i in range(2, len(closes)):
            prev_dir = 1 if closes[i-1] > closes[i-2] else -1
            curr_dir = 1 if closes[i] > closes[i-1] else -1
            if curr_dir != prev_dir:
                swings += 1

        if direction == 1:
            pullback_depth = breach_price - touch_price
        else:
            pullback_depth = touch_price - breach_price

        bars = len(bars_since_breach)
        efficiency = pullback_depth / bars if bars > 0 else 0.0
        retracement = pullback_depth / atr if atr > 0 else 0.0

        if direction == 1:
            orderly_count = higher_lows
        else:
            orderly_count = lower_highs

        clean_score = (orderly_count - swings) / bars if bars > 0 else 0.0

        return {
            'higher_lows_count_1m': float(higher_lows),
            'lower_highs_count_1m': float(lower_highs),
            'swing_count_1m': float(swings),
            'pullback_depth_atr': float(pullback_depth / atr if atr > 0 else 0.0),
            'pullback_bars_1m': float(bars),
            'pullback_efficiency_1m': float(efficiency / atr if atr > 0 else 0.0),
            'retracement_pct': float(retracement),
            'clean_pullback_score_1m': float(clean_score),
        }
