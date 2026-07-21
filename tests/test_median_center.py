import pytest
import numpy as np
from dataclasses import dataclass
from features.engine import FeatureEngine
from features.trackers.median_center import MedianCenterTracker

@dataclass
class MockBar:
    open: float
    high: float
    low: float
    close: float
    volume: float
    ts_init: int


class MockRegime:
    def __init__(self, regime: int, regime_id: int, atr: float):
        self.regime = regime
        self.regime_id = regime_id
        self.atr = type('MockAtr', (object,), {'value': atr})()
        self.short_ema_close = type('MockEMA', (object,), {'value': 100.0})()
        self.long_ema_close = type('MockEMA', (object,), {'value': 100.0})()
        self.has_breached = False


def test_slope_calculation():
    tracker = MedianCenterTracker()
    # Test linear sequence: y = 2x + 5. The slope should be exactly 2.0.
    y = [2 * x + 5 for x in range(10)]
    slope = tracker._calculate_slope(y, 10)
    assert pytest.approx(slope, 1e-6) == 2.0


def test_median_center_tracker_1s():
    tracker = MedianCenterTracker()
    
    # Feed 10 sequential 1s bars
    for i in range(10):
        bar = MockBar(open=100.0, high=102.0, low=98.0, close=100.0 + i, volume=10.0, ts_init=i * 1_000_000_000)
        tracker.update_1s(bar, current_regime=1, current_atr=2.0)
        
    assert len(tracker.prices_1s) == 10
    assert list(tracker.prices_1s) == [100.0 + i for i in range(10)]
    assert tracker.median_5m_history[-1] == np.median([100.0 + i for i in range(10)])


def test_regime_flip_tracking():
    tracker = MedianCenterTracker()
    
    # 1. Start regime 1 at ts = 0
    # Feed 5 bars under regime 1
    for i in range(5):
        ts = i * 1_000_000_000
        bar = MockBar(open=100.0, high=105.0, low=95.0, close=100.0 + i, volume=10.0, ts_init=ts)
        tracker.update_1s(bar, current_regime=1, current_atr=2.0)
        
    # regime flip occurs at ts = 5000000000 (after 5 bars)
    # call on_regime_change
    tracker.on_regime_change(new_regime=-1, flip_ts=5_000_000_000)
    
    assert len(tracker.completed_regimes) == 1
    completed = tracker.completed_regimes[0]
    
    assert completed["direction"] == 1
    assert completed["start_time"] == 0
    assert completed["end_time"] == 5_000_000_000
    assert completed["duration"] == 5.0
    assert completed["start_price"] == 100.0
    assert completed["end_price"] == 104.0
    assert completed["net_aligned_move"] == 4.0
    assert completed["MFE"] == 5.0  # high of 105.0 - start_price of 100.0
    assert completed["MAE"] == 5.0  # start_price of 100.0 - low of 95.0
    assert completed["regime_center"] == np.median([100.0, 101.0, 102.0, 103.0, 104.0])
    assert completed["volume"] == 50.0


def test_feature_engine_snapshot_integration():
    engine = FeatureEngine()
    
    # Feed 40 1s bars
    for i in range(40):
        bar = MockBar(open=100.0, high=102.0, low=98.0, close=100.0 + i, volume=10.0, ts_init=i * 1_000_000_000)
        engine.update_1s(bar)
        
    # Create mock regime and touch bar
    regime = MockRegime(regime=1, regime_id=1, atr=2.0)
    touch_bar = MockBar(open=100.0 + 40, high=100.0 + 41, low=100.0 + 39, close=100.0 + 40, volume=10.0, ts_init=40 * 1_000_000_000)
    
    # We must call update_1m once so engine has self.last_regime and self.last_atr set
    engine.update_1m(touch_bar, regime)
    
    snap_context = {
        "touch_bar": touch_bar,
        "regime": regime,
        "direction": 1
    }
    
    snapshot = engine.snapshot(feature_set="all", snap_context=snap_context)
    
    # Verify some F0 features are present in the snapshot
    assert "aligned_price_minus_center_5m" in snapshot
    assert "ordering_state" in snapshot
    assert "seconds_in_current_ordering" in snapshot
    assert "price_cross_count_5m" in snapshot
    assert "activity_regime_count_30m" in snapshot
    assert "seq_3r_alternation_rate" in snapshot
