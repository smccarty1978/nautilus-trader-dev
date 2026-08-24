"""Deterministic V2 provider parameter-domain and legacy-parity tests."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from features.trackers.generic_arrival import GenericArrivalVelocityProvider, GenericArrivalVolumeProvider
from features.trackers.generic_bar_geometry import GenericRangeATRProvider, GenericRangePositionProvider, GenericWickImbalanceProvider
from features.trackers.generic_context import GenericContextProvider
from features.trackers.generic_median_center import GenericMedianCenterProvider
from features.trackers.generic_ohlcv_delta import GenericOHLCVDeltaProvider
from features.trackers.generic_price_levels import GenericPriceLevelProvider
from features.trackers.generic_pullback import GenericPullbackProvider
from features.trackers.ohlcv_delta import OHLCVDeltaTracker
from features.trackers.price_levels import PriceLevelTracker
from features.trackers.pullback import PullbackTracker


NS = 1_000_000_000


@dataclass
class Bar:
    high: float
    low: float
    close: float


def test_ohlcv_delta_default_windows_are_legacy_identical_and_45s_is_generic():
    legacy = OHLCVDeltaTracker()
    generic = GenericOHLCVDeltaProvider(windows_seconds=(5, 45), maxlen=100)
    for second in range(60):
        values = dict(close_ts=(second + 1) * NS, open_px=100.0 + second,
                      high=101.0 + second, low=99.0 + second,
                      close=100.5 + second, volume=10.0 + second)
        legacy.update(values["close_ts"], values["open_px"], values["high"], values["low"], values["close"], values["volume"])
        generic.update_completed_bar(**values)
    old = legacy.calculate(atr=2.0)
    new = generic.snapshot(atr=2.0)
    for metric in ("vol_sum_5s", "est_delta_sum_5s", "range_atr_5s", "window_available_5s"):
        assert new[metric] == old[metric]
    assert new["window_available_45s"] is True
    assert new["vol_sum_45s"] is not None


def test_ohlcv_delta_requires_completed_bar_close_timestamp_not_raw_open_timestamp():
    provider = GenericOHLCVDeltaProvider(windows_seconds=(5,))
    with pytest.raises(TypeError, match="ts_event"):
        provider.update_completed_bar(ts_event=0, open_px=100.0, high=101.0, low=99.0, close=100.5, volume=10.0)


def test_ohlcv_delta_rejects_out_of_order_completed_availability():
    provider = GenericOHLCVDeltaProvider(windows_seconds=(5,))
    for timestamp in (NS, 2 * NS):
        provider.update_completed_bar(close_ts=timestamp, open_px=100.0, high=101.0, low=99.0, close=100.5, volume=10.0)
    with pytest.raises(ValueError, match="NON_MONOTONIC_COMPLETED_BAR"):
        provider.update_completed_bar(close_ts=NS, open_px=100.0, high=101.0, low=99.0, close=100.5, volume=10.0)


def test_price_level_default_window_is_legacy_identical_and_7m_is_generic():
    legacy = PriceLevelTracker()
    generic = GenericPriceLevelProvider(rolling_windows_min=(5, 7))
    start = 1_700_000_000 * NS
    for minute in range(10):
        args = dict(ts_avail=start + (minute + 1) * 60 * NS, open_px=100.0 + minute,
                    high=101.0 + minute, low=99.0 + minute, close=100.5 + minute, is_rth=False)
        legacy.update_1m(**args)
        generic.update_completed_bar(**args)
    old = legacy.calculate(start + 10 * 60 * NS, 110.0, 2.0)
    new = generic.snapshot(observation_ts=start + 10 * 60 * NS, reference_price=110.0, atr=2.0)
    assert new["rolling_5m_high_signed_distance_atr"] == old["rolling_5m_high_signed_distance_atr"]
    assert new["rolling_7m_high_available"] is True


def test_price_level_provider_rejects_a_snapshot_before_its_latest_completed_bar():
    provider = GenericPriceLevelProvider()
    provider.update_completed_bar(ts_avail=60 * NS, open_px=100.0, high=101.0, low=99.0, close=100.5, is_rth=False)
    provider.update_completed_bar(ts_avail=120 * NS, open_px=101.0, high=102.0, low=100.0, close=101.5, is_rth=False)
    with pytest.raises(ValueError, match="CAUSAL_SNAPSHOT_ORDER_VIOLATION"):
        provider.snapshot(observation_ts=60 * NS, reference_price=101.0, atr=2.0)
    with pytest.raises(ValueError, match="STALE_COMPLETED_INPUT_STREAM"):
        provider.snapshot(observation_ts=180 * NS, reference_price=101.0, atr=2.0)


def test_arrival_velocity_and_volume_accept_nonlegacy_windows():
    velocity = GenericArrivalVelocityProvider(max_lookback_bars=20)
    volume = GenericArrivalVolumeProvider(max_lookback_bars=20)
    for index in range(20):
        velocity.update_completed_bar(close=100.0 + index)
        volume.update_completed_bar(volume=10.0 + index, open_px=100.0 + index, close_px=100.0 + 2.0 * index)
    assert velocity.velocity(lookback=7, atr=2.0) == pytest.approx(0.5)
    assert velocity.metric(kind="acceleration", atr=2.0, short_lookback=5, long_lookback=7) == pytest.approx(0.0)
    assert volume.relative_volume(aggregation_lookback=7, baseline_lookback=7) > 1.0
    assert volume.volume_price_correlation(lookback=7) == pytest.approx(1.0)


def test_generic_pullback_reproduces_legacy_30s_trailing_values_and_event_scope():
    bars = [Bar(high=102.0, low=98.0, close=100.0 + index / 10.0) for index in range(30)]
    old = PullbackTracker.calculate_1s([bar.high for bar in bars], [bar.low for bar in bars], [bar.close for bar in bars], 2.0)
    new = GenericPullbackProvider.geometry(bars=bars, atr=2.0, scope="trailing", window=30)
    assert new["consecutive_up"] == old["consecutive_up_1s"]
    assert new["range_atr"] == old["range_30s_atr"]
    event = GenericPullbackProvider.geometry(
        bars=bars[-3:], atr=2.0, scope="since_breach", direction=1,
        breach_price=105.0, touch_price=103.0,
    )
    assert event["depth_atr"] == 1.0


def test_generic_median_context_and_bar_geometry_parameterize_legacy_singletons():
    median = GenericMedianCenterProvider(retained_seconds=20)
    for second in range(10):
        median.update_completed_bar(close_ts=(second + 1) * NS, close=100.0 + second)
    assert median.median(lookback=7, as_of_ns=10 * NS) == pytest.approx(106.0)
    assert median.slope(lookback=10, sample_lookback=5, as_of_ns=10 * NS) == pytest.approx(1.0)
    assert GenericContextProvider.ema_slope(values=[100.0, 101.0, 102.0], lookback=2, atr=2.0) == pytest.approx(0.5)
    assert GenericWickImbalanceProvider().latest_completed_bar(open_px=101.0, high=105.0, low=100.0, close=103.0) == pytest.approx(0.2)
    position = GenericRangePositionProvider(lookback=2)
    assert position.update_completed_bar(high=2.0, low=0.0, close=1.0) is None
    assert position.update_completed_bar(high=3.0, low=1.0, close=2.0) is None
    assert position.update_completed_bar(high=4.0, low=2.0, close=1.5) == pytest.approx(0.5)
    assert GenericRangeATRProvider.calculate(highs=[105.0, 103.0], lows=[99.0, 100.0], atr=2.0) == pytest.approx(3.0)


def test_generic_observation_lookbacks_fail_closed_outside_retained_history():
    velocity = GenericArrivalVelocityProvider(max_lookback_bars=5)
    with pytest.raises(ValueError, match="UNSUPPORTED_HISTORY_LOOKBACK"):
        velocity.velocity(lookback=6, atr=1.0)
    volume = GenericArrivalVolumeProvider(max_lookback_bars=5)
    with pytest.raises(ValueError, match="UNSUPPORTED_HISTORY_LOOKBACK"):
        volume.relative_volume(aggregation_lookback=3, baseline_lookback=3)
    median = GenericMedianCenterProvider(retained_seconds=5)
    with pytest.raises(ValueError, match="UNSUPPORTED_HISTORY_LOOKBACK"):
        median.slope(lookback=6, sample_lookback=2, as_of_ns=0)


def test_generic_warmup_is_null_and_volume_zero_is_not_coerced_to_neutral():
    median = GenericMedianCenterProvider(retained_seconds=10)
    for second in range(5):
        median.update_completed_bar(close_ts=(second + 1) * NS, close=100.0 + second)
    assert median.median(lookback=10, as_of_ns=5 * NS) is None
    with pytest.raises(ValueError, match="NON_MONOTONIC_COMPLETED_BAR"):
        median.update_completed_bar(close_ts=4 * NS, close=200.0)
    provider = GenericArrivalVolumeProvider(max_lookback_bars=20)
    for index in range(15):
        provider.update_completed_bar(volume=10.0, open_px=100.0, close_px=101.0)
    for index in range(5):
        provider.update_completed_bar(volume=0.0, open_px=100.0, close_px=101.0)
    snapshot = provider.snapshot()
    assert snapshot["rvol_5s"] == 0.0
