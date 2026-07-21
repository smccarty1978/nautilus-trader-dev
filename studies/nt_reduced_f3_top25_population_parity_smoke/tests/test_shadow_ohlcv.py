"""Unit tests for shadow_ohlcv.ShadowOHLCVCalculator (diagnostic-only cross-
check tool) and for OHLCVDeltaTracker <-> shadow equivalence on deterministic
synthetic bars. Required by the OHLCVDeltaTracker first-divergence audit
before any targeted or full rerun."""
from __future__ import annotations

import sys
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1] / "implementation"
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.trackers.ohlcv_delta import OHLCVDeltaTracker, NS  # noqa: E402
from shadow_ohlcv import ShadowOHLCVCalculator  # noqa: E402

TOL = 1e-9


def _feed_both(bars, atr=10.0):
    """bars: list of (ts, o, h, l, c, v). Feeds identical calls to a live
    tracker and a shadow, unconditionally (A1-A3 only, no regime/RTH)."""
    live = OHLCVDeltaTracker()
    shadow = ShadowOHLCVCalculator()
    for ts, o, h, l, c, v in bars:
        live.update(ts, o, h, l, c, v)
        shadow.update(ts, o, h, l, c, v)
    return live, shadow


def test_shadow_equals_direct_hand_computation_60s_window():
    """Deterministic 70-second synthetic series: price rises by exactly 1.0
    point per second (close - open each bar), volume constant at 100.
    price_change_points_60s over the last 60s window (bars 11..70, strictly
    after cutoff=70-60=10) must equal close[70] - open[11]."""
    bars = []
    for i in range(1, 71):
        ts = i * NS
        o = 100.0 + (i - 1)
        c = 100.0 + i
        bars.append((ts, o, o + 0.5, o - 0.5, c, 100.0))
    live, shadow = _feed_both(bars)

    f_live = live.calculate(atr=10.0)
    f_shadow = shadow.calculate(observation_ts=70 * NS, atr=10.0)

    expected = (100.0 + 70) - (100.0 + 10)  # close[70] - open[11]
    assert abs(f_live["price_change_points_60s"] - expected) < TOL
    assert abs(f_shadow["price_change_points_60s"] - expected) < TOL
    assert abs(f_live["price_change_points_60s"] - f_shadow["price_change_points_60s"]) < TOL

    expected_vol_sum = 100.0 * 60
    assert abs(f_live["vol_sum_60s"] - expected_vol_sum) < TOL
    assert abs(f_shadow["vol_sum_60s"] - expected_vol_sum) < TOL


def test_tracker_equals_shadow_on_deterministic_synthetic_bars_all_windows():
    """Randomized-looking but fixed/deterministic 2000-bar series (exceeds
    the largest 1800s window); tracker and shadow must agree on every
    windowed feature to float tolerance."""
    import math
    bars = []
    price = 19000.0
    for i in range(1, 2001):
        ts = i * NS
        drift = math.sin(i / 37.0) * 2.0
        o = price
        c = price + drift
        h = max(o, c) + abs(math.cos(i / 11.0))
        l = min(o, c) - abs(math.sin(i / 13.0))
        v = 50.0 + (i % 23)
        bars.append((ts, o, h, l, c, v))
        price = c
    live, shadow = _feed_both(bars)

    f_live = live.calculate(atr=25.0)
    f_shadow = shadow.calculate(observation_ts=2000 * NS, atr=25.0)

    checked = 0
    for W in (5, 15, 30, 60, 120, 300, 900, 1800):
        for key in ("vol_sum", "est_delta_sum", "est_abs_delta_sum", "price_change_points",
                    "range_points", "est_bear_vol_sum", "est_bull_vol_sum"):
            name = f"{key}_{W}s"
            a, b = f_live[name], f_shadow[name]
            assert a is not None and b is not None, f"{name} unexpectedly unavailable"
            assert abs(a - b) < 1e-6, f"{name}: live={a} shadow={b}"
            checked += 1
    assert checked == 8 * 7


def test_cutoff_boundary_bar_exactly_on_cutoff_is_excluded():
    """A bar whose ts equals the cutoff (obs_ts - W*NS) exactly must NOT be
    included in that window -- ohlcv_delta.py's own convention is `ts > cutoff`
    (strict), matching a bar's ts being its CLOSE time covering (ts-1s, ts]."""
    W = 60
    obs_ts = 1000 * NS
    cutoff_ts = obs_ts - W * NS  # bar at exactly this ts must be excluded
    bars = [
        (cutoff_ts, 100.0, 100.5, 99.5, 100.0, 10.0),  # excluded (== cutoff)
        (cutoff_ts + NS, 100.0, 100.5, 99.5, 101.0, 10.0),  # included (first eligible)
    ]
    # pad up to obs_ts with 1-second bars so the window is "full_available"
    ts_cursor = cutoff_ts + NS
    full_bars = list(bars)
    price = 101.0
    while ts_cursor < obs_ts:
        ts_cursor += NS
        full_bars.append((ts_cursor, price, price + 0.5, price - 0.5, price, 10.0))
    live, shadow = _feed_both(full_bars)
    f_live = live.calculate(atr=10.0)
    f_shadow = shadow.calculate(observation_ts=obs_ts, atr=10.0)
    # vol_sum_60s should count exactly W bars (cutoff_ts+1 .. obs_ts inclusive),
    # NOT W+1 (which would happen if the cutoff-ts bar were wrongly included).
    assert abs(f_live["vol_sum_60s"] - 10.0 * W) < TOL
    assert abs(f_shadow["vol_sum_60s"] - 10.0 * W) < TOL


def test_duplicate_timestamp_detection():
    shadow = ShadowOHLCVCalculator()
    shadow.update(1 * NS, 100.0, 101.0, 99.0, 100.5, 10.0)
    shadow.update(1 * NS, 100.5, 101.5, 99.5, 100.0, 10.0)  # duplicate ts
    assert shadow.update_count_by_ts[1 * NS] == 2


def test_out_of_order_timestamp_detection():
    shadow = ShadowOHLCVCalculator()
    shadow.update(5 * NS, 100.0, 101.0, 99.0, 100.5, 10.0)
    shadow.update(3 * NS, 100.5, 101.5, 99.5, 100.0, 10.0)  # goes backward
    assert shadow.out_of_order_count == 1


def test_separate_instances_do_not_share_state():
    a = ShadowOHLCVCalculator()
    b = ShadowOHLCVCalculator()
    a.update(1 * NS, 100.0, 101.0, 99.0, 100.5, 10.0)
    assert len(b.ts) == 0
    assert a.ts is not b.ts


def test_rth_cumulative_reset_and_fresh_sum():
    shadow = ShadowOHLCVCalculator()
    shadow.reset_rth(0)
    shadow.update(1 * NS, 100.0, 101.0, 99.0, 100.5, 10.0)
    shadow.accumulate_regime_rth(1 * NS, 101.0, 99.0, 10.0, 2.0)
    shadow.update(2 * NS, 100.5, 101.0, 99.0, 100.0, 20.0)
    shadow.accumulate_regime_rth(2 * NS, 101.0, 99.0, 20.0, -3.0)
    out = shadow.calculate(observation_ts=2 * NS, atr=10.0)
    assert out["rth_vol_cum"] == 30.0
    assert out["rth_abs_delta_cum"] == 5.0

    shadow.end_rth()
    shadow.reset_rth(3 * NS)  # new session -- must fully clear prior cum state
    shadow.update(3 * NS, 100.0, 101.0, 99.0, 100.5, 5.0)
    out2 = shadow.calculate(observation_ts=3 * NS, atr=10.0)
    assert out2["rth_vol_cum"] == 0.0
    assert out2["rth_abs_delta_cum"] == 0.0


def test_regime_reset_clears_prior_regime_log():
    shadow = ShadowOHLCVCalculator()
    shadow.reset_regime(0, anchor_price=100.0)
    shadow.update(1 * NS, 100.0, 105.0, 95.0, 101.0, 10.0)
    shadow.accumulate_regime_rth(1 * NS, 105.0, 95.0, 10.0, 1.0)
    out = shadow.calculate(observation_ts=1 * NS, atr=10.0)
    assert out["regime_vol_sum"] == 10.0

    shadow.reset_regime(2 * NS, anchor_price=101.0)
    shadow.update(2 * NS, 101.0, 102.0, 100.0, 101.5, 8.0)
    out2 = shadow.calculate(observation_ts=2 * NS, atr=10.0)
    assert out2["regime_vol_sum"] == 0.0


def test_shadow_flags_observation_ts_not_matching_last_bar():
    shadow = ShadowOHLCVCalculator()
    shadow.update(5 * NS, 100.0, 101.0, 99.0, 100.5, 10.0)
    out = shadow.calculate(observation_ts=5 * NS, atr=10.0)
    assert out["shadow_obs_ts_matches_last_bar"] is True

    shadow.update(7 * NS, 100.5, 101.5, 99.5, 100.0, 10.0)
    stale_out = shadow.calculate(observation_ts=5 * NS, atr=10.0)  # stale obs_ts
    assert stale_out["shadow_obs_ts_matches_last_bar"] is False
    # causal filtering must still exclude the bar AFTER observation_ts=5
    assert stale_out["shadow_n_bars_future_of_obs_ts_dropped"] == 1
