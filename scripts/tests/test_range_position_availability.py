"""Targeted tests for latest_1m_close_position_prev5_range (YM prerequisite Task D).

    prev5_high = max(high[t-5:t]); prev5_low = min(low[t-5:t])
    value = (close[t] - prev5_low) / (prev5_high - prev5_low)

Bar t is excluded from the reference range. If prev5_high == prev5_low the
feature is undefined (None). No clipping is applied -- a breakout beyond the
prior range legitimately produces a value outside [0, 1].
"""
from __future__ import annotations

import pytest

from features.registry import FEATURE_REGISTRY, resolve_feature_name
from features.trackers.range_position import RangePositionTracker, compute_range_position

FEATURE = "latest_1m_close_position_prev5_range"


def _feed_five_prior(tracker: RangePositionTracker, high: float, low: float) -> None:
    """Feed exactly 5 prior bars with a fixed (high, low), leaving the tracker ready
    to compute a value on the 6th (current) bar."""
    for _ in range(5):
        tracker.update(high=high, low=low, close=(high + low) / 2)


# ---------------------------------------------------------------------------
# Formula: the five required reference points
# ---------------------------------------------------------------------------

def test_close_at_prior_low_is_zero():
    t = RangePositionTracker()
    _feed_five_prior(t, high=110.0, low=100.0)
    val = t.update(high=105.0, low=101.0, close=100.0)
    assert val == pytest.approx(0.0)


def test_close_at_prior_high_is_one():
    t = RangePositionTracker()
    _feed_five_prior(t, high=110.0, low=100.0)
    val = t.update(high=112.0, low=105.0, close=110.0)
    assert val == pytest.approx(1.0)


def test_close_at_midpoint_is_half():
    t = RangePositionTracker()
    _feed_five_prior(t, high=110.0, low=100.0)
    val = t.update(high=106.0, low=104.0, close=105.0)
    assert val == pytest.approx(0.5)


def test_breakout_above_prior_high_is_not_clipped():
    t = RangePositionTracker()
    _feed_five_prior(t, high=110.0, low=100.0)
    val = t.update(high=125.0, low=118.0, close=120.0)
    assert val == pytest.approx(2.0)
    assert val > 1.0


def test_breakout_below_prior_low_is_not_clipped():
    t = RangePositionTracker()
    _feed_five_prior(t, high=110.0, low=100.0)
    val = t.update(high=92.0, low=88.0, close=90.0)
    assert val == pytest.approx(-1.0)
    assert val < 0.0


def test_flat_prior_range_is_none():
    t = RangePositionTracker()
    _feed_five_prior(t, high=100.0, low=100.0)
    val = t.update(high=101.0, low=99.0, close=100.5)
    assert val is None
    assert t.calculate()[FEATURE] is None


# ---------------------------------------------------------------------------
# Reference-range construction rules
# ---------------------------------------------------------------------------

def test_current_bar_excluded_from_reference_range():
    """Bar t's own extreme high/low must not widen the prior-5 range."""
    t = RangePositionTracker()
    _feed_five_prior(t, high=110.0, low=100.0)
    # If bar t (high=200, low=50) leaked into the range, close=105 would no longer
    # sit at (105-100)/10 = 0.5 -- it would be diluted toward the middle of [50, 200].
    val = t.update(high=200.0, low=50.0, close=105.0)
    assert val == pytest.approx(0.5)


def test_exactly_five_preceding_bars_used_sixth_prior_bar_dropped():
    """A 6th-back bar must not influence the range once 5 more recent bars exist."""
    t = RangePositionTracker()
    # Oldest bar (will be evicted): extreme range that would change the answer if kept.
    t.update(high=500.0, low=-500.0, close=0.0)
    # Five bars that become the actual reference range for the upcoming current bar.
    _feed_five_prior(t, high=110.0, low=100.0)
    val = t.update(high=112.0, low=105.0, close=105.0)
    assert val == pytest.approx(0.5)


def test_fewer_than_five_prior_bars_is_none():
    t = RangePositionTracker()
    for i in range(4):
        val = t.update(high=110.0, low=100.0, close=105.0)
        assert val is None
    assert t.is_available is False


def test_incomplete_or_future_bar_never_observed():
    """A bar not yet passed to update() cannot influence the current value.

    Two trackers fed identical history diverge only after one receives a 6th,
    'future' bar the other has not seen yet -- the value read before that update
    must be identical regardless of what is fed afterward.
    """
    t_a = RangePositionTracker()
    t_b = RangePositionTracker()
    _feed_five_prior(t_a, high=110.0, low=100.0)
    _feed_five_prior(t_b, high=110.0, low=100.0)

    val_a = t_a.update(high=112.0, low=105.0, close=106.0)
    snapshot_before_future = t_b.calculate()[FEATURE]
    # t_b has not yet observed the 6th (current) bar.
    assert snapshot_before_future is None

    val_b = t_b.update(high=112.0, low=105.0, close=106.0)
    assert val_a == pytest.approx(val_b)


# ---------------------------------------------------------------------------
# compute_range_position helper
# ---------------------------------------------------------------------------

def test_compute_range_position_matches_tracker():
    assert compute_range_position(close=105.0, prev5_high=110.0, prev5_low=100.0) == pytest.approx(0.5)
    assert compute_range_position(close=100.0, prev5_high=100.0, prev5_low=100.0) is None


# ---------------------------------------------------------------------------
# Runtime feature emission (FeatureEngine integration)
# ---------------------------------------------------------------------------

class MockBar:
    def __init__(self, open_px, high, low, close, volume, ts_event, ts_init=0):
        self.open = open_px
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.ts_event = ts_event
        self.ts_init = ts_init if ts_init > 0 else ts_event


class MockIndicator:
    def __init__(self, value):
        self.value = value


class MockRegime:
    def __init__(self, regime_id, regime, has_breached, atr, short_ema, long_ema,
                 regime_high=0.0, regime_low=0.0):
        self.regime_id = regime_id
        self.regime = regime
        self.has_breached = has_breached
        self.atr = MockIndicator(atr)
        self.short_ema_close = MockIndicator(short_ema)
        self.long_ema_close = MockIndicator(long_ema)
        self.regime_high = regime_high
        self.regime_low = regime_low


def test_runtime_emission_via_feature_engine():
    from features.engine import FeatureEngine

    engine = FeatureEngine()
    independent = RangePositionTracker()

    for i in range(60):
        bar = MockBar(open_px=100.0, high=101.0, low=99.0, close=100.5, volume=10.0, ts_event=i * 1e9)
        engine.update_1s(bar)

    regime = MockRegime(regime_id=1, regime=1, has_breached=True, atr=1.5, short_ema=100.2, long_ema=99.8)

    m_bars = []
    for i in range(7):
        m_bar = MockBar(
            open_px=100.0 + i, high=102.0 + i, low=98.0 + i, close=100.5 + i,
            volume=100.0, ts_event=(i + 1) * 6e10,
        )
        m_bars.append(m_bar)
        engine.update_1m(m_bar, regime)
        independent.update(float(m_bar.high), float(m_bar.low), float(m_bar.close))

    snap_context = {
        "touch_bar": MockBar(open_px=100.0, high=101.0, low=99.0, close=100.1, volume=15.0, ts_event=3600e9),
        "regime": regime,
        "direction": 1,
    }
    snap = engine.snapshot(feature_set="all", snap_context=snap_context)

    assert FEATURE in snap
    assert snap[FEATURE] == pytest.approx(independent.calculate()[FEATURE])


# ---------------------------------------------------------------------------
# Registry identity/order
# ---------------------------------------------------------------------------

def test_registry_entry_identity_and_metadata():
    assert FEATURE in FEATURE_REGISTRY
    fdef = FEATURE_REGISTRY[FEATURE]
    assert fdef.name == FEATURE
    assert resolve_feature_name(FEATURE) == FEATURE
    assert fdef.status == "provisional"
    assert fdef.source_timeframe == "1m"
    assert fdef.update_anchor == "completed_1m_bar"
    assert fdef.null_policy == "allow"
    assert fdef.warmup == 6
    assert fdef.implementation == "features.trackers.range_position.RangePositionTracker"


def test_registry_key_matches_dict_position_after_wick_imbalance():
    """New feature was appended after latest_1m_wick_imbalance, not inserted mid-dict."""
    keys = list(FEATURE_REGISTRY.keys())
    assert keys.index(FEATURE) == keys.index("latest_1m_wick_imbalance") + 1
