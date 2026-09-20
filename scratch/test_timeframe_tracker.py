import sys
sys.path.insert(0, '.')
import math
import numpy as np
import pandas as pd
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

class SingleTimeframeRegimeTracker:
    """Tracks completed-bar dual EMA regime, regime geometry, and history for one timeframe."""
    
    def __init__(self, timeframe: str):
        self.timeframe = timeframe
        self.tracker = DualEmaRegimeTracker(timeframe=timeframe)
        
        # Active regime state
        self.direction = 0
        self.start_ts = None
        self.start_price = None
        self.start_atr = None
        self.current_atr = None
        self.mfe_price = None
        self.mfe_ts = None
        self.mae_price = None
        self.mae_ts = None
        self.new_extreme_count = 0
        self.bars_in_regime = 0
        self.last_close_ts = None
        self.last_close_price = None
        
        # History for lookbacks: list of (close_ts, high, low, close, mfe_price, mae_price, atr)
        self.bar_history = []
        
        # Prior regime state
        self.prior_regime = None
        
        # Attempt tracking for failed_new_extreme_attempt_count
        self.failed_new_extreme_attempt_count = 0
        self._in_approach = False
        
    def on_bar(self, close_ts: int, open_: float, high: float, low: float, close: float):
        up = self.tracker.observe(high, low, close)
        self.last_close_ts = close_ts
        self.last_close_price = close
        atr = up.atr if up.atr is not None and math.isfinite(up.atr) else 10.0
        self.current_atr = atr
        
        if up.flipped:
            # Complete prior regime
            if self.direction != 0 and self.start_ts is not None:
                dur_sec = max(0.0, (close_ts - self.start_ts) / 1e9)
                mfe_atr = max(0.0, self.direction * (self.mfe_price - self.start_price) / max(self.start_atr, 1e-6))
                mae_atr = max(0.0, -self.direction * (self.mae_price - self.start_price) / max(self.start_atr, 1e-6))
                self.prior_regime = {
                    'direction': self.direction,
                    'start_ts': self.start_ts,
                    'end_ts': close_ts,
                    'start_price': self.start_price,
                    'end_close': self.last_close_price,
                    'mfe_price': self.mfe_price,
                    'mae_price': self.mae_price,
                    'start_atr': self.start_atr,
                    'max_mfe_atr': mfe_atr,
                    'max_mae_atr': mae_atr,
                    'duration_sec': dur_sec,
                    'total_range': abs(self.mfe_price - self.mae_price)
                }
            
            # Start new regime
            self.direction = up.regime
            self.start_ts = close_ts
            self.start_price = open_
            self.start_atr = atr
            self.mfe_price = high if up.regime == 1 else low
            self.mfe_ts = close_ts
            self.mae_price = low if up.regime == 1 else high
            self.mae_ts = close_ts
            self.new_extreme_count = 1
            self.bars_in_regime = 1
            self.bar_history = [(close_ts, high, low, close, self.mfe_price, self.mae_price, atr)]
            self.failed_new_extreme_attempt_count = 0
            self._in_approach = False
        elif self.direction != 0:
            # Continuation of existing regime
            self.bars_in_regime += 1
            is_new_mfe = False
            if self.direction == 1:
                if high > self.mfe_price:
                    self.mfe_price = high
                    self.mfe_ts = close_ts
                    self.new_extreme_count += 1
                    is_new_mfe = True
                if low < self.mae_price:
                    self.mae_price = low
                    self.mae_ts = close_ts
            else:
                if low < self.mfe_price:
                    self.mfe_price = low
                    self.mfe_ts = close_ts
                    self.new_extreme_count += 1
                    is_new_mfe = True
                if high > self.mae_price:
                    self.mae_price = high
                    self.mae_ts = close_ts
                    
            # Failed extreme attempt tracking:
            dist_to_mfe = abs(close - self.mfe_price) / max(atr, 1e-6)
            if dist_to_mfe <= 0.50 and not is_new_mfe:
                if not self._in_approach:
                    self.failed_new_extreme_attempt_count += 1
                    self._in_approach = True
            elif dist_to_mfe > 0.75:
                self._in_approach = False
                
            self.bar_history.append((close_ts, high, low, close, self.mfe_price, self.mae_price, atr))
            if len(self.bar_history) > 500:
                self.bar_history = self.bar_history[-500:]

print('SingleTimeframeRegimeTracker defined cleanly.')
