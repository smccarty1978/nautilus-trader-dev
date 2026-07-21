import pytest
from utils.regime_engine import LiteRegimeEngine, state_cat

class MockBucket:
    def __init__(self, high: float, low: float, close: float, close_ts: int = 0):
        self.high = high
        self.low = low
        self.close = close
        self.close_ts = close_ts

def test_state_cat_healthy():
    assert state_cat(0.75, "Healthy") == "Healthy"
    assert state_cat(0.01, "Healthy") == "Healthy"

def test_state_cat_deter():
    assert state_cat(0.50, "DETER") == "DETER"

def test_state_cat_hard_soft_stall():
    # HardStall / SoftStall should classify based on hC thresholds
    # Thresholds: P67 = 0.304, P33 = 0.044
    assert state_cat(0.35, "HardStall") == "HH-HardStall"
    assert state_cat(0.304, "SoftStall") == "HH-HardStall"
    
    assert state_cat(0.20, "HardStall") == "MH-HardStall"
    assert state_cat(0.044, "SoftStall") == "MH-HardStall"
    
    assert state_cat(0.02, "HardStall") == "LH-HardStall"
    assert state_cat(0.0, "SoftStall") == "LH-HardStall"

def test_state_cat_other():
    assert state_cat(0.50, "UnrecognizedState") == "Other"

def test_lite_regime_engine_ema_init():
    engine = LiteRegimeEngine(atr_period=2)
    # First update: EMA should initialize to first bar values
    bucket1 = MockBucket(high=100.0, low=90.0, close=95.0)
    engine.update(bucket1)
    
    assert engine._ema3_h == 100.0
    assert engine._ema9_h == 100.0
    assert engine._ema3_l == 90.0
    assert engine._ema9_l == 90.0
    assert engine._prev_close == 95.0
    assert engine.regime == 0

def test_lite_regime_engine_transitions():
    engine = LiteRegimeEngine(atr_period=2)
    
    # Bar 1: Initialize
    engine.update(MockBucket(high=100.0, low=90.0, close=95.0))
    
    # Bar 2: Close exceeds EMA high limits (which will adjust slightly)
    # EMA3_H = 0.5 * 110 + 0.5 * 100 = 105
    # EMA9_H = 0.2 * 110 + 0.8 * 100 = 102
    # Close = 106 (> 105 and > 102) -> Regime +1
    engine.update(MockBucket(high=110.0, low=95.0, close=106.0))
    assert engine.regime == 1
    assert engine.bars_in_regime == 1
    
    # Bar 3: Continues in regime +1
    engine.update(MockBucket(high=115.0, low=100.0, close=110.0))
    assert engine.regime == 1
    assert engine.bars_in_regime == 2
    
    # Bar 4: Drop close below EMA low limits
    # EMAs will drag up, let's force a massive drop
    # Close = 70.0 -> Regime -1
    engine.update(MockBucket(high=100.0, low=60.0, close=70.0))
    assert engine.regime == -1
    assert engine.bars_in_regime == 1

def test_lite_regime_engine_atr():
    # Wilder ATR(3)
    engine = LiteRegimeEngine(atr_period=3)
    
    # Bar 1: TR = 10.0
    engine.update(MockBucket(high=100.0, low=90.0, close=95.0))
    assert engine.atr is None
    
    # Bar 2: TR = max(10, |102-95|=7, |92-95|=3) = 10.0
    engine.update(MockBucket(high=102.0, low=92.0, close=98.0))
    assert engine.atr is None
    
    # Bar 3: TR = max(10, |105-98|=7, |95-98|=3) = 10.0
    # Warmup ends: ATR = mean(10, 10, 10) = 10.0
    engine.update(MockBucket(high=105.0, low=95.0, close=100.0))
    assert engine.atr == 10.0
    
    # Bar 4: TR = 16.0 (High=110.0, Low=94.0, Close=105.0, prev_close=100.0)
    # Wilder update: ATR = (10.0 * 2 + 16.0) / 3 = 12.0
    engine.update(MockBucket(high=110.0, low=94.0, close=105.0))
    assert pytest.approx(engine.atr) == 12.0
