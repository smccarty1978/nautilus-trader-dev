from features.trackers.structural_regime_geometry import NS, StructuralRegimeGeometryTracker
from features.coverage import covers_feature_family


def _seed(tracker):
    # Completed bearish 1m predecessor: high=110, low=90 at 20s.
    tracker.on_1m_flip(-1, 0, 100.0, 10.0, 100.0)
    tracker.on_1s(10 * NS, 110.0, 95.0, 96.0)
    tracker.on_1s(20 * NS, 105.0, 90.0, 92.0)
    # New bullish regime freezes predecessor low 90 at 20s.
    tracker.on_1m_flip(1, 60 * NS, 92.0, 10.0, 92.0)
    tracker.on_1s(70 * NS, 100.0, 91.0, 99.0)
    tracker.on_1s(80 * NS, 110.0, 95.0, 105.0)
    # Prior and current completed 5m regimes.
    tracker.on_5m_bar(close_ts=300 * NS, direction=-1, open_=105.0, high=110.0, low=90.0, close=92.0, atr=10.0)
    tracker.on_5m_bar(close_ts=600 * NS, direction=1, open_=92.0, high=112.0, low=91.0, close=106.0, atr=10.0)
    tracker.on_5m_bar(close_ts=900 * NS, direction=-1, open_=106.0, high=108.0, low=96.0, close=97.0, atr=10.0)


@covers_feature_family("structural_regime_geometry")
def test_prior_extreme_is_frozen_and_current_expansion_is_causal():
    t = StructuralRegimeGeometryTracker(); _seed(t)
    snap = t.snapshot(900 * NS, 105.0, 11.0, 900 * NS)
    assert snap['structural_available']
    assert snap['structural_origin_price'] == 90.0
    assert snap['structural_origin_ns'] == 20 * NS
    assert snap['structural_max_expansion_atr'] == 2.0
    assert snap['structural_current_expansion_atr'] == 1.5
    assert snap['structural_giveback_atr'] == 0.5
    assert snap['structural_retention_ratio'] == 0.75


def test_past_snapshot_is_not_revised_by_later_prices():
    t = StructuralRegimeGeometryTracker(); _seed(t)
    before = t.snapshot(900 * NS, 105.0, 11.0, 900 * NS)
    t.on_1s(910 * NS, 140.0, 100.0, 130.0)
    after = t.snapshot(910 * NS, 130.0, 11.0, 900 * NS)
    assert before['structural_max_expansion_atr'] == 2.0
    assert after['structural_max_expansion_atr'] == 5.0


def test_forming_5m_state_is_refused():
    t = StructuralRegimeGeometryTracker(); _seed(t)
    snap = t.snapshot(899 * NS, 105.0, 11.0, 900 * NS)
    assert not snap['structural_available']
    assert snap['structural_unavailable_reason'] == 'FORMING_OR_MISSING_5M_STATE'


@covers_feature_family("structural_regime_geometry")
def test_current_5m_regime_mfe_so_far_is_causal_and_distinct_from_prior():
    """current_5m_regime_mfe_atr = running favorable extreme of the in-progress 5m
    regime (completed-5m bars only), never the eventual completed-regime MFE."""
    t = StructuralRegimeGeometryTracker(); _seed(t)
    snap = t.snapshot(900 * NS, 105.0, 11.0, 900 * NS)
    # Current bearish 5m regime: start_price 106, running low 96, atr_start 10.
    assert snap['current_5m_regime_mfe_atr'] == 1.0
    # Distinct from the frozen completed prior 5m regime (bullish: 92 -> high 112).
    assert snap['prior_5m_regime_mfe_atr'] == 2.0
    # And distinct from net displacement to the last completed close (97).
    assert snap['current_5m_directional_displacement_atr'] == 0.9
    # No future / no forming: a later 1s tick cannot revise a completed-5m quantity.
    t.on_1s(910 * NS, 200.0, 50.0, 60.0)
    later = t.snapshot(910 * NS, 60.0, 11.0, 900 * NS)
    assert later['current_5m_regime_mfe_atr'] == snap['current_5m_regime_mfe_atr']
    # A new completed 5m regime resets the running extreme.
    t.on_5m_bar(close_ts=1200 * NS, direction=1, open_=97.0, high=101.0, low=95.0, close=100.0, atr=10.0)
    after = t.snapshot(1200 * NS, 100.0, 11.0, 1200 * NS)
    assert after['current_5m_regime_mfe_atr'] == 0.4  # (101 - 97) / 10, bullish


def test_prior_regime_formula_is_prefix_and_timeframe_invariant():
    """The same completed-regime algorithm powers the legacy 1m and 5m aliases."""
    t = StructuralRegimeGeometryTracker()
    record = {"start_ns": 10 * NS, "end_ns": 130 * NS, "direction": 1,
              "start_price": 100.0, "high": 120.0, "low": 98.0, "end_close": 116.0,
              "atr_start": 10.0}
    one = t._completed("prior_1m_regime", record)
    five = t._completed("prior_5m_regime", record)
    assert {key.removeprefix("prior_1m_regime"): value for key, value in one.items()} == {
        key.removeprefix("prior_5m_regime"): value for key, value in five.items()
    }


def test_v2_regime_instances_preserve_every_legacy_structural_output_alias():
    from features.registry import LEGACY_FEATURE_INSTANCE_OVERRIDES
    t = StructuralRegimeGeometryTracker(); _seed(t)
    snapshot = t.snapshot(900 * NS, 105.0, 11.0, 900 * NS)
    legacy_structural = {alias for alias, instance in LEGACY_FEATURE_INSTANCE_OVERRIDES.items()
                         if instance.canonical_name in {"regime_duration_min", "regime_range_atr", "regime_net_directional_move_atr", "regime_mfe_atr", "regime_range_atr_per_min", "regime_net_move_atr_per_min", "regime_efficiency", "regime_age_min", "regime_directional_displacement_atr", "distance_to_completed_range_high_atr", "distance_to_completed_range_low_atr", "move_outside_completed_range", "structural_max_expansion_atr", "structural_current_expansion_atr", "structural_giveback_atr", "structural_retention_ratio", "structural_expansion_atr_per_min", "regime_expansion_atr_per_min"}}
    assert legacy_structural <= set(snapshot)


def test_generic_completed_bar_provider_supports_3m_without_a_3m_branch():
    """A new completed timeframe uses the same direct-stream state machine.

    There is deliberately no historical parity target for 3m.  The proof here
    is causal provenance plus the same completed-regime invariants used by the
    legacy 5m path.
    """
    from features.trackers.generic_regime_geometry import GenericCompletedRegimeGeometryProvider
    t = GenericCompletedRegimeGeometryProvider()
    t.on_completed_bar(timeframe="3m", close_ts=180 * NS, direction=-1,
                       open_=110.0, high=112.0, low=100.0, close=102.0, atr=6.0)
    t.on_completed_bar(timeframe="3m", close_ts=360 * NS, direction=1,
                       open_=102.0, high=114.0, low=101.0, close=112.0, atr=6.0)
    snap = t.prior_snapshot(timeframe="3m", checkpoint_ns=360 * NS)
    assert snap["available"]
    assert snap["completed_close_ts"] == 360 * NS
    assert snap["prior_3m_regime_duration_min"] == 3.0
    assert snap["prior_3m_regime_range_atr"] == 2.0
    assert snap["prior_3m_regime_efficiency"] == 8.0 / 12.0

    forming = t.prior_snapshot(timeframe="3m", checkpoint_ns=359 * NS)
    assert not forming["available"]
    assert forming["unavailable_reason"] == "FORMING_OR_MISSING_COMPLETED_STATE"


def test_generic_provider_matches_both_legacy_observation_modes():
    """The generic provider accepts either completed 1s geometry or direct bars."""
    from features.trackers.generic_regime_geometry import GenericCompletedRegimeGeometryProvider

    legacy = StructuralRegimeGeometryTracker()
    generic = GenericCompletedRegimeGeometryProvider()
    legacy.on_1m_flip(-1, 0, 100.0, 10.0, 100.0)
    generic.on_regime_transition(timeframe="1m", direction=-1, start_ns=0,
                                 start_price=100.0, atr_start=10.0, prior_end_close=100.0)
    for ts, high, low, close in ((10, 110.0, 95.0, 96.0), (20, 105.0, 90.0, 92.0)):
        legacy.on_1s(ts * NS, high, low, close)
        generic.on_geometry_bar(timeframe="1m", close_ts=ts * NS, high=high, low=low, close=close)
    legacy.on_1m_flip(1, 60 * NS, 92.0, 10.0, 92.0)
    generic.on_regime_transition(timeframe="1m", direction=1, start_ns=60 * NS,
                                 start_price=92.0, atr_start=10.0, prior_end_close=92.0)
    old = legacy._completed("prior_1m_regime", legacy._prior_one)
    new = generic.prior_snapshot(timeframe="1m", checkpoint_ns=60 * NS)
    assert {key: value for key, value in new.items() if key.startswith("prior_")} == old

    direct = GenericCompletedRegimeGeometryProvider()
    for close_ts, direction, open_, high, low, close in (
        (300, -1, 105.0, 110.0, 90.0, 92.0), (600, 1, 92.0, 112.0, 91.0, 106.0),
    ):
        direct.on_completed_bar(timeframe="5m", close_ts=close_ts * NS, direction=direction,
                                open_=open_, high=high, low=low, close=close, atr=10.0)
    old_5m = StructuralRegimeGeometryTracker()
    old_5m.on_5m_bar(close_ts=300 * NS, direction=-1, open_=105.0, high=110.0, low=90.0, close=92.0, atr=10.0)
    old_5m.on_5m_bar(close_ts=600 * NS, direction=1, open_=92.0, high=112.0, low=91.0, close=106.0, atr=10.0)
    assert {key: value for key, value in direct.prior_snapshot(timeframe="5m", checkpoint_ns=600 * NS).items()
            if key.startswith("prior_")} == old_5m._completed("prior_5m_regime", old_5m._prior_five)
