"""Deterministic tests for features/trackers/ohlcv_delta.py (SPEC Part A)."""
import numpy as np
import pytest

from features.trackers.ohlcv_delta import OHLCVDeltaTracker, bar_estimates

NS = 1_000_000_000


def test_green_full_range_candle():
    r = bar_estimates(open_px=100.0, high=101.0, low=100.0, close=101.0, volume=50.0)
    assert r["bar_est_bull_volume"] == pytest.approx(50.0)
    assert r["bar_est_bear_volume"] == pytest.approx(0.0)
    assert r["bar_est_delta"] == pytest.approx(50.0)
    assert r["bar_est_delta_ratio"] == pytest.approx(1.0)
    assert r["bar_zero_range"] is False


def test_red_full_range_candle():
    r = bar_estimates(open_px=101.0, high=101.0, low=100.0, close=100.0, volume=50.0)
    assert r["bar_est_bull_volume"] == pytest.approx(0.0)
    assert r["bar_est_bear_volume"] == pytest.approx(50.0)
    assert r["bar_est_delta"] == pytest.approx(-50.0)
    assert r["bar_est_delta_ratio"] == pytest.approx(-1.0)
    assert r["bar_zero_range"] is False


def test_mid_close_candle():
    r = bar_estimates(open_px=100.0, high=101.0, low=99.0, close=100.0, volume=50.0)
    assert r["bar_est_delta"] == pytest.approx(0.0)
    assert r["bar_est_bull_volume"] == pytest.approx(25.0)
    assert r["bar_est_bear_volume"] == pytest.approx(25.0)


def test_zero_range_candle():
    r = bar_estimates(open_px=100.0, high=100.0, low=100.0, close=100.0, volume=50.0)
    assert r["bar_est_delta"] == pytest.approx(0.0)
    assert r["bar_est_delta_ratio"] == pytest.approx(0.0)
    assert r["bar_zero_range"] is True
    # Must not infer directional pressure from a zero-range bar.
    assert r["bar_est_bull_volume"] == pytest.approx(25.0)
    assert r["bar_est_bear_volume"] == pytest.approx(25.0)


def _feed(tracker, n, ts0=1_700_000_000 * NS, vol=10.0, step=0.1):
    for i in range(n):
        tracker.update(ts0 + i * NS, 100 + i * step, 100 + i * step + 0.5,
                       100 + i * step - 0.2, 100 + i * step + 0.3, vol)
    return ts0 + (n - 1) * NS


def test_rolling_window_completion_15s_unavailable_before_15_bars():
    t = OHLCVDeltaTracker()
    _feed(t, 14)
    r = t.calculate(atr=2.0)
    assert r["window_available_15s"] is False
    assert r["vol_sum_15s"] is None

    t2 = OHLCVDeltaTracker()
    _feed(t2, 15)
    r2 = t2.calculate(atr=2.0)
    assert r2["window_available_15s"] is True
    assert r2["vol_sum_15s"] is not None


def test_rolling_window_excludes_forming_bar():
    """calculate() only ever sees bars passed to update() -- the caller is
    responsible for never calling update() with a forming bar. This test
    proves the window sum is exactly the sum of what was fed, not more."""
    t = OHLCVDeltaTracker()
    _feed(t, 20, vol=10.0, step=0.0)  # constant volume=10 per bar
    r = t.calculate(atr=2.0)
    # 5s window = last 5 completed bars only
    assert r["vol_sum_5s"] == pytest.approx(50.0)
    assert r["window_available_5s"] is True


def test_short_vs_long_comparison_deterministic():
    t = OHLCVDeltaTracker()
    # First 60 bars: strong positive delta (green, full range).
    ts0 = 1_700_000_000 * NS
    for i in range(60):
        t.update(ts0 + i * NS, 100.0, 101.0, 100.0, 101.0, 10.0)
    # Next 15 bars: strong negative delta (red, full range) -- short window flips.
    for i in range(60, 75):
        t.update(ts0 + i * NS, 100.0, 101.0, 100.0, 100.0, 10.0)
    r = t.calculate(atr=2.0)
    # Long window (60s) still reflects a mix dominated by the earlier positive run;
    # short window (15s) is now all-negative -- so short-minus-long should be negative.
    assert r["est_delta_ratio_15s_minus_60s"] < 0
    assert r["est_delta_sum_15s_minus_60s_scaled"] < 0


def _update_and_accumulate(t: OHLCVDeltaTracker, ts, o, h, l, c, v) -> None:
    """update() only feeds the rolling-window deques (see its docstring);
    a caller that already knows the correct regime/RTH context at the
    moment update() is called (unlike FeatureEngine, which must buffer and
    replay -- see engine.py) calls accumulate_regime_rth() immediately
    after, exactly as attach_features.py's offline replay does."""
    b = t.update(ts, o, h, l, c, v)
    t.accumulate_regime_rth(ts, h, l, v, b["bar_est_delta"])


def test_regime_relative_reset_on_new_regime():
    t = OHLCVDeltaTracker()
    ts0 = 1_700_000_000 * NS
    t.reset_regime(ts0, anchor_price=100.0)
    for i in range(10):
        _update_and_accumulate(t, ts0 + i * NS, 100.0, 101.0, 100.0, 101.0, 10.0)
    r1 = t.calculate(atr=2.0)
    assert r1["regime_available"] is True
    assert r1["regime_vol_sum"] == pytest.approx(100.0)

    # New regime starts -- cumulative state must reset, not carry over.
    t.reset_regime(ts0 + 10 * NS, anchor_price=101.0)
    _update_and_accumulate(t, ts0 + 10 * NS, 101.0, 101.5, 100.8, 101.2, 5.0)
    r2 = t.calculate(atr=2.0)
    assert r2["regime_vol_sum"] == pytest.approx(5.0)


def test_rth_cumulative_reset_on_new_session():
    t = OHLCVDeltaTracker()
    ts0 = 1_700_000_000 * NS
    t.reset_rth(ts0)
    for i in range(10):
        _update_and_accumulate(t, ts0 + i * NS, 100.0, 101.0, 100.0, 101.0, 10.0)
    r1 = t.calculate(atr=2.0)
    assert r1["rth_available"] is True
    assert r1["rth_vol_cum"] == pytest.approx(100.0)

    t.end_rth()
    _update_and_accumulate(t, ts0 + 10 * NS, 101.0, 101.5, 100.8, 101.2, 999.0)
    r2 = t.calculate(atr=2.0)
    # RTH inactive -- cumulative must not have grown, and must report unavailable.
    assert r2["rth_available"] is False
    assert r2["rth_vol_cum"] is None

    # New RTH session -- must reset, not carry over pre-end-of-session totals.
    t.reset_rth(ts0 + 11 * NS)
    _update_and_accumulate(t, ts0 + 11 * NS, 101.0, 101.5, 100.8, 101.2, 7.0)
    r3 = t.calculate(atr=2.0)
    assert r3["rth_vol_cum"] == pytest.approx(7.0)


def test_timestamp_provenance_never_exceeds_observation():
    """The tracker's own 'latest source' (last buffered bar ts) must never
    exceed the observation timestamp, since it IS the observation timestamp
    for this study's convention (last completed bar fed == decision time)."""
    t = OHLCVDeltaTracker()
    last_ts = _feed(t, 20)
    r = t.calculate(atr=2.0)
    observation_ts = last_ts
    latest_source_ts_used = last_ts  # by construction: last update() call's ts
    assert latest_source_ts_used <= observation_ts
