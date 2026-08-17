import pytest
import numpy as np
import warnings
from features.registry import resolve_feature_name, FEATURE_REGISTRY
from features.trackers.velocity import ArrivalVelocityTracker
from features.trackers.volume import ArrivalVolumeTracker
from features.trackers.pullback import PullbackTracker
from features.engine import FeatureEngine
from features.collector import FeatureCollector

class MockBar:
    def __init__(self, open_px: float, high: float, low: float, close: float, volume: float, ts_event: int, ts_init: int = 0):
        self.open = open_px
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.ts_event = ts_event
        self.ts_init = ts_init if ts_init > 0 else ts_event

class MockIndicator:
    def __init__(self, value: float):
        self.value = value

class MockRegime:
    def __init__(
        self,
        regime_id: int,
        regime: int,
        has_breached: bool,
        atr: float,
        short_ema: float,
        long_ema: float,
        regime_high: float = 0.0,
        regime_low: float = 0.0,
    ):
        self.regime_id = regime_id
        self.regime = regime
        self.has_breached = has_breached
        self.atr = MockIndicator(atr)
        self.short_ema_close = MockIndicator(short_ema)
        self.long_ema_close = MockIndicator(long_ema)
        self.regime_high = regime_high
        self.regime_low = regime_low

def test_resolve_feature_name_warning():
    # Assert that a DeprecationWarning is raised for legacy aliases
    with pytest.deprecated_call():
        resolved = resolve_feature_name("bars_in_regime")
        assert resolved == "regime_age_bars"

    with pytest.deprecated_call():
        resolved = resolve_feature_name("pb_depth_atr")
        assert resolved == "pullback_depth_atr"

    # Assert no warning for canonical name
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        resolved = resolve_feature_name("arrival_vel_5s")
        assert resolved == "arrival_vel_5s"

def test_arrival_velocity_tracker():
    tracker = ArrivalVelocityTracker(maxlen=60)
    res = tracker.calculate(atr=1.5)
    assert res['arrival_vel_5s'] == 0.0
    
    for val in np.linspace(100.0, 105.0, 30):
        tracker.update(val)
        
    res = tracker.calculate(atr=1.0)
    assert res['arrival_vel_5s'] > 0.0
    assert res['arrival_vel_30s'] > 0.0

def test_arrival_volume_tracker_prior_sum():
    tracker = ArrivalVolumeTracker(maxlen=60)
    
    # Feed 25 volume updates
    for i in range(25):
        tracker.update(volume=10.0, open_px=100.0, close_px=100.5)
        
    res = tracker.calculate()
    # Confirm relative volume logic computes correctly with the fixed 5-bar prior sum
    assert res['rvol_5s'] == 1.0

def test_pullback_tracker_1s():
    highs = [102.0] * 30
    lows = [98.0] * 30
    closes = list(np.linspace(100.0, 101.5, 30))
    
    res = PullbackTracker.calculate_1s(highs, lows, closes, atr=2.0)
    assert res['consecutive_up_1s'] == 29.0
    assert res['range_30s_atr'] == 2.0

def test_pullback_tracker_1m():
    bar1 = MockBar(open_px=100.0, high=102.0, low=98.0, close=101.0, volume=100.0, ts_event=1000)
    bar2 = MockBar(open_px=101.0, high=103.0, low=99.0, close=102.0, volume=100.0, ts_event=2000)
    bar3 = MockBar(open_px=102.0, high=104.0, low=100.0, close=103.0, volume=100.0, ts_event=3000)
    
    bars = [bar1, bar2, bar3]
    res = PullbackTracker.calculate_1m(
        bars_since_breach=bars,
        breach_price=105.0,
        touch_price=103.0,
        atr=2.0,
        direction=1
    )
    assert res['pullback_bars_1m'] == 3.0
    assert res['pullback_depth_atr'] == 1.0

def test_feature_engine_snapshot_immutability():
    engine = FeatureEngine()
    
    for i in range(60):
        bar = MockBar(open_px=100.0, high=101.0, low=99.0, close=100.5, volume=10.0, ts_event=i * 1e9)
        engine.update_1s(bar)
        
    regime = MockRegime(regime_id=1, regime=1, has_breached=True, atr=1.5, short_ema=100.2, long_ema=99.8)
    for i in range(5):
        m_bar = MockBar(open_px=100.0, high=102.0, low=98.0, close=100.5, volume=100.0, ts_event=(i+1) * 6e10)
        engine.update_1m(m_bar, regime)
        
    snap_context = {
        "touch_bar": MockBar(open_px=100.0, high=101.0, low=99.0, close=100.1, volume=15.0, ts_event=3600e9),
        "regime": regime,
        "direction": 1
    }
    
    snap1 = engine.snapshot(feature_set="all", snap_context=snap_context)
    snap2 = engine.snapshot(feature_set="all", snap_context=snap_context)
    
    # Assert deep copies are returned and changing one does not affect the engine or subsequent snapshots
    assert snap1 == snap2
    snap1['arrival_vel_5s'] = 999.0
    assert snap2['arrival_vel_5s'] != 999.0

def test_prefix_invariance():
    # Verify that a feature computed at time T is invariant to future updates
    engine1 = FeatureEngine()
    engine2 = FeatureEngine()
    
    bars = [MockBar(open_px=100.0, high=101.0, low=99.0, close=100.0 + (i/10.0), volume=10.0, ts_event=i * 1e9) for i in range(100)]
    regime = MockRegime(regime_id=1, regime=1, has_breached=True, atr=1.5, short_ema=100.2, long_ema=99.8)
    
    # Engine 1 gets fed only up to index 60
    for bar in bars[:60]:
        engine1.update_1s(bar)
    engine1.update_1m(bars[59], regime)
    
    # Engine 2 gets fed all 100 bars
    for bar in bars:
        engine2.update_1s(bar)
    engine2.update_1m(bars[59], regime)
    
    snap_context = {
        "touch_bar": bars[59],
        "regime": regime,
        "direction": 1
    }
    
    # Snapshot taken at bar index 59 should match exactly between both engines
    snap1 = engine1.snapshot(feature_set=["arrival_vel_5s", "pullback_depth_atr"], snap_context=snap_context)
    snap2 = engine2.snapshot(feature_set=["arrival_vel_5s", "pullback_depth_atr"], snap_context=snap_context)
    
    assert snap1 == snap2

def test_warmup_requirements():
    engine = FeatureEngine()
    
    # Update with less than 30 bars (insufficient warmup)
    for i in range(10):
        bar = MockBar(open_px=100.0, high=101.0, low=99.0, close=100.5, volume=10.0, ts_event=i * 1e9)
        engine.update_1s(bar)
        
    regime = MockRegime(regime_id=1, regime=1, has_breached=True, atr=1.5, short_ema=100.2, long_ema=99.8)
    snap_context = {
        "touch_bar": MockBar(open_px=100.0, high=101.0, low=99.0, close=100.1, volume=15.0, ts_event=10 * 1e9),
        "regime": regime,
        "direction": 1
    }
    
    # Snapshot should return empty dict due to lack of warmup
    assert engine.snapshot(feature_set="all", snap_context=snap_context) == {}

def test_feature_collector_composition():
    # Verify the refactored FeatureCollector behaves identically using the composed engine
    collector = FeatureCollector()
    
    for i in range(60):
        bar = MockBar(open_px=100.0, high=101.0, low=99.0, close=100.5, volume=10.0, ts_event=i * 1e9)
        collector.update_1s(bar)
        
    regime = MockRegime(regime_id=1, regime=1, has_breached=True, atr=1.5, short_ema=100.2, long_ema=99.8)
    for i in range(5):
        m_bar = MockBar(open_px=100.0, high=102.0, low=98.0, close=100.5, volume=100.0, ts_event=(i+1) * 6e10)
        collector.update_1m(m_bar, regime)
        
    touch_bar = MockBar(open_px=100.0, high=101.0, low=99.0, close=100.1, volume=15.0, ts_event=3600e9)
    features = collector.get_features(touch_bar, regime, direction=1)
    
    assert features is not None
    assert 'arrival_vel_5s' in features
    assert 'regime_age_bars' in features
    # Emitting legacy alias key names should warn and map to canonical
    assert 'bars_in_regime' not in features


def test_ohlcv_delta_regime_transition_buffers_and_replays_correctly():
    """Regression test for a fixed bug: OHLCVDeltaTracker's regime-relative
    accumulation used to happen inline inside update_1s(), before update_1m()
    could confirm whether the bars just processed belong to the old or a
    newly-transitioning regime (NT dispatches a whole minute's 1s bars before
    its parent 1m bar). FeatureEngine must now buffer each minute's 1s bars
    and replay them into OHLCVDeltaTracker only after update_1m() resolves
    the correct regime, so a transitioning minute's bars land in the NEW
    regime's accumulator, not the old one, and never leak into both/neither."""
    NS = 1_000_000_000
    engine = FeatureEngine(buffer_size_1s=200, buffer_size_1m=50)
    ts0 = 1_700_000_000 * NS

    def feed_minute(start_i, vol):
        for i in range(60):
            bar = MockBar(100.0, 101.0, 99.0, 100.5, vol, ts0 + (start_i + i) * NS)
            engine.update_1s(bar)

    regime1 = MockRegime(regime_id=1, regime=1, has_breached=False, atr=2.0, short_ema=100, long_ema=99)

    # Minute 1 precedes the first declared regime start at its close, so its
    # buffered bars must be discarded rather than backfilled into that regime.
    feed_minute(0, vol=10.0)
    m1 = MockBar(100.0, 101.0, 99.0, 100.5, 600.0, ts0 + 60 * NS, ts_init=ts0 + 60 * NS)
    engine.update_1m(m1, regime1)
    assert engine._ohlcv_delta_tracker._regime_vol_sum == pytest.approx(0.0)

    # Minute 2 occurs after that start, so it accumulates normally.
    feed_minute(60, vol=10.0)
    m2 = MockBar(100.0, 101.0, 99.0, 100.5, 600.0, ts0 + 120 * NS, ts_init=ts0 + 120 * NS)
    engine.update_1m(m2, regime1)
    assert engine._ohlcv_delta_tracker._regime_vol_sum == pytest.approx(600.0)

    # Minute 3: a NEW regime is confirmed by the 1m bar that closes THIS
    # minute. The 60 1s bars just fed completed before the parent 1m close,
    # so they belong to the OLD regime. The new regime starts at that close
    # and must begin with an empty completed-1s accumulator.
    feed_minute(120, vol=25.0)
    regime2 = MockRegime(regime_id=2, regime=-1, has_breached=False, atr=2.0, short_ema=99, long_ema=100)
    m3 = MockBar(105.0, 106.0, 104.0, 105.5, 1500.0, ts0 + 180 * NS, ts_init=ts0 + 180 * NS)
    engine.update_1m(m3, regime2)
    assert engine._ohlcv_delta_tracker._regime_vol_sum == pytest.approx(0.0)
    assert engine._ohlcv_delta_tracker._regime_anchor_price == pytest.approx(105.0)  # new regime bar's OPEN


def test_wick_tracker():
    from features.trackers.wick import WickTracker, compute_wick_imbalance

    # Test flat bar (high == low)
    assert compute_wick_imbalance(100.0, 100.0, 100.0, 100.0) == 0.0

    # Test bullish bar with upper wick 2.0, lower wick 1.0, range 5.0
    # open 101.0, high 105.0, low 100.0, close 103.0
    # upper_wick = 105 - max(101, 103) = 2.0
    # lower_wick = min(101, 103) - 100 = 1.0
    # feature = (2.0 - 1.0) / 5.0 = 0.2
    val = compute_wick_imbalance(101.0, 105.0, 100.0, 103.0)
    assert val == pytest.approx(0.2)

    # Test bearish bar with upper wick 1.0, lower wick 3.0, range 6.0
    # open 104.0, high 105.0, low 99.0, close 101.0
    # upper_wick = 105 - max(104, 101) = 1.0
    # lower_wick = min(104, 101) - 99 = 2.0
    # feature = (1.0 - 2.0) / 6.0 = -1/6
    val2 = compute_wick_imbalance(104.0, 105.0, 99.0, 101.0)
    assert val2 == pytest.approx(-1.0 / 6.0)

    # Test tracker update & calculate.
    # Before any completed 1m bar the feature is UNAVAILABLE, not zero: 0.0 is a real
    # reading (balanced wick, or a zero-range bar) and the two must stay distinguishable.
    # See scripts/tests/test_wick_availability.py for the full four-state matrix.
    tracker = WickTracker()
    assert tracker.calculate()["latest_1m_wick_imbalance"] is None
    tracker.update(101.0, 105.0, 100.0, 103.0)
    assert tracker.calculate()["latest_1m_wick_imbalance"] == pytest.approx(0.2)

