from features.trackers.structural_regime_geometry import NS, StructuralRegimeGeometryTracker


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
