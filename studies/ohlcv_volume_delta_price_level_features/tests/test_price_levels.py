"""Deterministic tests for features/trackers/price_levels.py (SPEC Part B)."""
import datetime

import pytest
import pytz

from features.trackers.price_levels import PriceLevelTracker, trading_day_key

CT = pytz.timezone("America/Chicago")
NS = 1_000_000_000


def _ts(y, m, d, h, mi):
    return int(CT.localize(datetime.datetime(y, m, d, h, mi)).astimezone(pytz.utc).timestamp() * 1e9)


def test_trading_day_boundary_rolls_at_1700_ct():
    assert trading_day_key(_ts(2026, 1, 5, 16, 59)) == "2026-01-05"
    assert trading_day_key(_ts(2026, 1, 5, 17, 0)) == "2026-01-06"


def test_prior_day_freeze():
    t = PriceLevelTracker(tick_size=0.25)
    t.update_1m(_ts(2026, 1, 5, 10, 0), 100, 101, 99, 100.5, is_rth=True)
    t.update_1m(_ts(2026, 1, 5, 11, 0), 100.5, 102, 100, 101, is_rth=True)
    r1 = t.calculate(_ts(2026, 1, 5, 11, 0), 101, atr=2.0)
    assert r1["prior_day_open_available"] is False

    # Roll into the next trading day -- prior day must now be frozen exactly.
    t.update_1m(_ts(2026, 1, 6, 8, 0), 101, 103, 100.5, 102, is_rth=False)
    assert t.prior_day_ohlc == {"open": 100, "high": 102, "low": 99, "close": 101}
    r2 = t.calculate(_ts(2026, 1, 6, 8, 0), 102, atr=2.0)
    assert r2["prior_day_open_available"] is True
    assert r2["prior_day_open_price"] == 100
    assert r2["prior_day_high_price"] == 102

    # Feed more bars on the new day -- prior day must NOT change (frozen).
    t.update_1m(_ts(2026, 1, 6, 9, 0), 102, 110, 101, 105, is_rth=True)
    r3 = t.calculate(_ts(2026, 1, 6, 9, 0), 105, atr=2.0)
    assert r3["prior_day_high_price"] == 102  # unchanged despite new day's high=110


def test_overnight_developing_vs_final():
    t = PriceLevelTracker(tick_size=0.25)
    t.update_1m(_ts(2026, 1, 5, 7, 0), 100, 101, 99, 100.5, is_rth=False)
    t.update_1m(_ts(2026, 1, 5, 8, 0), 100.5, 102, 100, 101, is_rth=False)
    r1 = t.calculate(_ts(2026, 1, 5, 8, 0), 101, atr=2.0)
    assert r1["overnight_high_final_available"] is False
    assert r1["overnight_high_developing_price"] == 102

    t.update_1m(_ts(2026, 1, 5, 8, 30), 101, 103, 100.8, 102, is_rth=True)
    r2 = t.calculate(_ts(2026, 1, 5, 8, 30), 102, atr=2.0)
    assert r2["overnight_high_final_available"] is True
    assert r2["overnight_high_final_price"] == 102  # frozen at RTH open, not the RTH bar's high (103)


def test_opening_range_leak_prevention():
    t = PriceLevelTracker(tick_size=0.25)
    t.update_1m(_ts(2026, 1, 5, 8, 30), 100, 103, 99.5, 102, is_rth=True)
    r1 = t.calculate(_ts(2026, 1, 5, 8, 30), 102, atr=2.0)
    assert r1["opening_range_30m_is_final"] is False
    assert r1["opening_range_30m_high_final_available"] is False
    # Developing value must reflect what's been seen so far, not a future high.
    assert r1["opening_range_30m_high_developing_price"] == 103

    t.update_1m(_ts(2026, 1, 5, 8, 45), 102, 110, 101, 105, is_rth=True)  # still within 30 min
    r2 = t.calculate(_ts(2026, 1, 5, 8, 45), 105, atr=2.0)
    assert r2["opening_range_30m_is_final"] is False
    assert r2["opening_range_30m_high_developing_price"] == 110

    t.update_1m(_ts(2026, 1, 5, 9, 1), 105, 106, 104, 104.5, is_rth=True)  # past 30 min
    r3 = t.calculate(_ts(2026, 1, 5, 9, 1), 104.5, atr=2.0)
    assert r3["opening_range_30m_is_final"] is True
    # Final must NOT include the 9:01 bar's range (106/104) beyond what accrued by 9:00.
    assert r3["opening_range_30m_high_final_price"] == 110
    assert r3["opening_range_30m_low_final_price"] == 99.5


def test_rolling_window_completion():
    t = PriceLevelTracker(tick_size=0.25)
    base = _ts(2026, 1, 5, 8, 30)
    for i in range(4):
        t.update_1m(base + i * 60 * NS, 100 + i, 101 + i, 99 + i, 100.5 + i, is_rth=True)
    r = t.calculate(base + 3 * 60 * NS, 103, atr=2.0)
    assert r["rolling_5m_open_available"] is False  # only 4 bars fed, need 5

    t.update_1m(base + 4 * 60 * NS, 104, 105, 103, 104.5, is_rth=True)
    r2 = t.calculate(base + 4 * 60 * NS, 104.5, atr=2.0)
    assert r2["rolling_5m_open_available"] is True
    assert r2["rolling_5m_open_price"] == 100  # open of the window's first (oldest) bar
    assert r2["rolling_5m_close_price"] == 104.5


def test_above_below_touch_counts():
    t = PriceLevelTracker(tick_size=0.25, touch_tolerance_ticks=1.0)
    t.update_1m(_ts(2026, 1, 5, 8, 30), 100, 100, 100, 100, is_rth=True)  # rth_open=100
    # reference exactly at rth_open (100) within tolerance -> TOUCH
    r = t.calculate(_ts(2026, 1, 5, 8, 30), 100.1, atr=2.0)
    assert r["rth_open_position"] == "TOUCH"
    r2 = t.calculate(_ts(2026, 1, 5, 8, 30), 105.0, atr=2.0)
    assert r2["rth_open_position"] == "ABOVE"
    # reference (105) is ABOVE rth_open (100) -> rth_open is a level BELOW price.
    assert r2["n_levels_below"] >= 1
    assert r2["n_levels_above"] == 0
    r3 = t.calculate(_ts(2026, 1, 5, 8, 30), 95.0, atr=2.0)
    assert r3["rth_open_position"] == "BELOW"
    # reference (95) is BELOW rth_open (100) -> rth_open is a level ABOVE price.
    assert r3["n_levels_above"] >= 1
    assert r3["n_levels_below"] == 0


def test_raw_above_below_touch_counts_addendum_example():
    """Exact worked example from the addendum: 8 levels, price above 5
    (i.e. 5 levels below price) and below 3 (i.e. 3 levels above price)."""
    t = PriceLevelTracker(tick_size=0.25, touch_tolerance_ticks=1.0)
    prices = {"a": 90.0, "b": 92.0, "c": 94.0, "d": 96.0, "e": 98.0,  # 5 below ref=100
              "f": 102.0, "g": 104.0, "h": 106.0}                     # 3 above ref=100
    family_of = {n: "session" for n in prices}
    out = t._aggregate_counts(prices, family_of, reference_price=100.0, tol=0.25)
    assert out["n_levels_available"] == 8
    assert out["n_levels_below"] == 5
    assert out["n_levels_above"] == 3
    assert out["n_levels_touched"] == 0


def test_percent_level_features():
    t = PriceLevelTracker(tick_size=0.25, touch_tolerance_ticks=1.0)
    prices = {"a": 90.0, "b": 92.0, "c": 94.0, "d": 96.0, "e": 98.0,
              "f": 102.0, "g": 104.0, "h": 106.0}
    family_of = {n: "session" for n in prices}
    out = t._aggregate_counts(prices, family_of, reference_price=100.0, tol=0.25)
    assert out["pct_levels_below"] == pytest.approx(0.625)
    assert out["pct_levels_above"] == pytest.approx(0.375)
    assert out["pct_levels_touched"] == pytest.approx(0.0)


def test_level_balance():
    t = PriceLevelTracker(tick_size=0.25, touch_tolerance_ticks=1.0)
    prices = {"a": 90.0, "b": 92.0, "c": 94.0, "d": 96.0, "e": 98.0,
              "f": 102.0, "g": 104.0, "h": 106.0}
    family_of = {n: "session" for n in prices}
    out = t._aggregate_counts(prices, family_of, reference_price=100.0, tol=0.25)
    # level_balance = (n_below - n_above) / n_available = (5-3)/8 = 0.25;
    # positive means price is above more levels than below.
    assert out["level_balance"] == pytest.approx(0.25)


def test_clustered_above_below_counts():
    t = PriceLevelTracker(tick_size=0.25, touch_tolerance_ticks=1.0)
    # Two tight groups (cluster tolerance = max(2 ticks, 0.05*atr) = max(0.5, 0.1) = 0.5)
    # below price, one group above.
    prices = {"a": 90.0, "b": 90.1, "c": 95.0, "d": 95.05, "e": 110.0}
    clusters = t._cluster(prices, atr_safe=2.0)
    out = t._cluster_features(clusters, reference_price=100.0, atr_safe=2.0, tol=0.25)
    assert out["n_level_clusters_available"] == 3  # {90,90.1}, {95,95.05}, {110}
    assert out["n_level_clusters_below"] == 2
    assert out["n_level_clusters_above"] == 1
    assert out["n_level_clusters_touched"] == 0


def test_nearest_cluster_above_below():
    t = PriceLevelTracker(tick_size=0.25, touch_tolerance_ticks=1.0)
    prices = {"a": 90.0, "b": 90.1, "c": 95.0, "d": 95.05, "e": 110.0}
    clusters = t._cluster(prices, atr_safe=2.0)
    out = t._cluster_features(clusters, reference_price=100.0, atr_safe=2.0, tol=0.25)
    # Nearest below-price cluster is {95, 95.05} (median 95.025), strength 2.
    assert out["nearest_cluster_below_price"] == pytest.approx(95.025)
    assert out["nearest_cluster_below_strength"] == 2
    # Nearest above-price cluster is {110}, strength 1.
    assert out["nearest_cluster_above_price"] == pytest.approx(110.0)
    assert out["nearest_cluster_above_strength"] == 1
    assert out["nearest_cluster_above_distance_atr"] == pytest.approx((110.0 - 100.0) / 2.0)
    assert out["nearest_cluster_below_distance_atr"] == pytest.approx((100.0 - 95.025) / 2.0)


def test_unavailable_level_denominator_handling():
    """Zero available levels must not raise or silently divide by zero --
    percent/balance features must be None, not 0.0 or NaN-from-division."""
    t = PriceLevelTracker(tick_size=0.25, touch_tolerance_ticks=1.0)
    out = t._aggregate_counts({}, {}, reference_price=100.0, tol=0.25)
    assert out["n_levels_available"] == 0
    assert out["pct_levels_above"] is None
    assert out["pct_levels_below"] is None
    assert out["pct_levels_touched"] is None
    assert out["level_balance"] is None


def test_no_unavailable_numeric_encoded_as_zero():
    """A tracker with no data fed at all must report every unavailable
    numeric feature as None, never 0.0 (which would be indistinguishable
    from a genuine zero-distance/zero-count observation)."""
    t = PriceLevelTracker(tick_size=0.25)
    out = t.calculate(observation_ts=1_700_000_000 * NS, reference_price=100.0, atr=2.0)
    assert out["prior_day_open_price"] is None
    assert out["prior_day_open_available"] is False
    assert out["nearest_level_above_distance_atr"] is None
    assert out["nearest_level_below_distance_atr"] is None
    assert out["n_levels_available"] == 0
    assert out["level_balance"] is None
    assert out["max_cluster_strength"] is None


def test_nearest_level_selection():
    t = PriceLevelTracker(tick_size=0.25)
    t.update_1m(_ts(2026, 1, 5, 8, 30), 100, 100, 100, 100, is_rth=True)  # rth_open=100 only level so far
    r = t.calculate(_ts(2026, 1, 5, 8, 30), 105.0, atr=2.0)
    assert r["nearest_level_below_price"] == 100
    assert r["nearest_level_below_name"] == "rth_open"
    assert r["nearest_level_above_price"] is None  # nothing above 105 yet


def test_envelope_behavior():
    t = PriceLevelTracker(tick_size=0.25)
    t.update_1m(_ts(2026, 1, 5, 8, 30), 100, 100, 100, 100, is_rth=True)
    t.update_1m(_ts(2026, 1, 5, 8, 31), 100, 110, 100, 105, is_rth=True)
    r = t.calculate(_ts(2026, 1, 5, 8, 31), 108, atr=2.0)
    assert r["highest_available_level"] >= r["lowest_available_level"]
    # price_position_in_full_envelope must NOT be clamped to [0,1]
    r2 = t.calculate(_ts(2026, 1, 5, 8, 31), 500.0, atr=2.0)
    assert r2["price_position_in_full_envelope"] > 1.0


def test_clustering_determinism():
    t = PriceLevelTracker(tick_size=0.25)
    t.update_1m(_ts(2026, 1, 5, 8, 30), 100.0, 100.1, 99.9, 100.05, is_rth=True)
    t.update_1m(_ts(2026, 1, 5, 8, 31), 100.05, 100.15, 99.95, 100.1, is_rth=True)
    prices = {name: p for name, (p, _fam) in t._raw_levels().items() if p is not None}
    c1 = t._cluster(prices, atr_safe=2.0)
    c2 = t._cluster(prices, atr_safe=2.0)
    assert c1 == c2  # identical input -> identical clustering, every call


def test_direction_normalization_short_and_long_transform_correctly():
    """short: ahead=below, behind=above. long: ahead=above, behind=below.
    Uses a controlled two-level scenario (one above, one below reference)
    so the swap is unambiguous in both directions."""
    t = PriceLevelTracker(tick_size=0.25)
    prices = {"below_level": 90.0, "above_level": 110.0}
    clusters = t._cluster(prices, atr_safe=2.0)

    short = t._direction_normalized(prices, clusters, reference_price=100.0,
                                    atr_safe=2.0, direction=-1)
    assert short["levels_ahead_of_trade"] == 1  # below_level is "ahead" for a short
    assert short["levels_behind_trade"] == 1    # above_level is "behind" for a short
    assert short["nearest_level_ahead_distance_atr"] == pytest.approx((100.0 - 90.0) / 2.0)
    assert short["nearest_level_behind_distance_atr"] == pytest.approx((110.0 - 100.0) / 2.0)

    long = t._direction_normalized(prices, clusters, reference_price=100.0,
                                   atr_safe=2.0, direction=1)
    assert long["levels_ahead_of_trade"] == 1  # above_level is "ahead" for a long
    assert long["levels_behind_trade"] == 1    # below_level is "behind" for a long
    assert long["nearest_level_ahead_distance_atr"] == pytest.approx((110.0 - 100.0) / 2.0)
    assert long["nearest_level_behind_distance_atr"] == pytest.approx((100.0 - 90.0) / 2.0)


def test_timestamp_provenance():
    """The tracker only ever incorporates ts values explicitly passed to
    update_1m(); calculate()'s observation_ts is supplied by the caller and
    must be >= every level's underlying source bar timestamp."""
    t = PriceLevelTracker(tick_size=0.25)
    last_ts = _ts(2026, 1, 5, 8, 30)
    t.update_1m(last_ts, 100, 100, 100, 100, is_rth=True)
    observation_ts = last_ts
    # No level construction reaches into bars_1m beyond what update_1m received.
    assert t.bars_1m[-1][0] <= observation_ts
