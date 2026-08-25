from features.trackers.rolling_5m_productivity import NS, Rolling5mProductivityTracker
from features.coverage import covers_feature_family


def _seed(tracker: Rolling5mProductivityTracker, *, direction: int = 1) -> None:
    for second in range(301):
        if direction == 1:
            tracker.on_completed_1s(second * NS + NS, 100.0 + second / 10, 99.0 + second / 10, 100.0 + second / 10)
        else:
            tracker.on_completed_1s(second * NS + NS, 101.0 - second / 10, 100.0 - second / 10, 100.0 - second / 10)


@covers_feature_family("rolling_productivity")
def test_bullish_snapshot_uses_exact_boundary_low_not_an_in_window_low():
    tracker = Rolling5mProductivityTracker()
    _seed(tracker)
    snap = tracker.snapshot(301 * NS, 1, 10.0, 0.2)
    assert snap["rolling_5m_productivity_available"]
    assert snap["rolling_5m_productivity_anchor_ns"] == NS
    assert snap["rolling_5m_productivity_anchor_price"] == 99.0
    assert snap["rolling_5m_max_progress_atr"] == 3.1
    assert snap["rolling_5m_current_progress_atr"] == 3.1


def test_bearish_snapshot_is_directional_mirror():
    tracker = Rolling5mProductivityTracker()
    _seed(tracker, direction=-1)
    snap = tracker.snapshot(301 * NS, -1, 10.0, 0.2)
    assert snap["rolling_5m_productivity_available"]
    assert snap["rolling_5m_productivity_anchor_price"] == 101.0
    assert snap["rolling_5m_max_progress_atr"] == 3.1
    assert snap["rolling_5m_current_progress_atr"] == 3.1


def test_missing_exact_boundary_is_unavailable_not_a_neighbour_search():
    tracker = Rolling5mProductivityTracker()
    for second in range(1, 301):
        tracker.on_completed_1s(second * NS + NS, 101.0, 99.0, 100.0)
    snap = tracker.snapshot(301 * NS, 1, 10.0, 0.2)
    assert not snap["rolling_5m_productivity_available"]
    assert snap["rolling_5m_productivity_unavailable_reason"] == "MISSING_EXACT_300S_BOUNDARY"


def test_interior_missing_second_makes_the_rolling_window_unavailable():
    tracker = Rolling5mProductivityTracker()
    for second in range(301):
        if second == 100:
            continue
        tracker.on_completed_1s(second * NS + NS, 101.0, 99.0, 100.0)
    snap = tracker.snapshot(301 * NS, 1, 10.0, 0.2)
    assert not snap["rolling_5m_productivity_available"]
    assert snap["rolling_5m_productivity_unavailable_reason"] == "INCOMPLETE_1S_WINDOW"


def test_checkpoint_requires_a_completed_1s_bar_at_t():
    tracker = Rolling5mProductivityTracker()
    _seed(tracker)
    snap = tracker.snapshot(302 * NS, 1, 10.0, 0.2)
    assert not snap["rolling_5m_productivity_available"]
    assert snap["rolling_5m_productivity_unavailable_reason"] == "MISSING_COMPLETED_CHECKPOINT_1S"


def test_invalid_regime_speed_is_explicitly_null_not_clamped():
    tracker = Rolling5mProductivityTracker()
    _seed(tracker)
    snap = tracker.snapshot(301 * NS, 1, 10.0, 0.0)
    assert snap["rolling_5m_productivity_available"]
    assert snap["rolling_5m_max_speed_vs_lifetime"] is None
    assert snap["rolling_5m_current_speed_vs_lifetime"] is None


def test_same_rolling_provider_accepts_a_second_supported_window():
    tracker = Rolling5mProductivityTracker(window_seconds=60)
    for second in range(61):
        tracker.on_completed_1s(second * NS + NS, 100.0 + second / 10, 99.0 + second / 10, 100.0 + second / 10)
    snap = tracker.snapshot(61 * NS, 1, 10.0, 0.2)
    assert snap["rolling_5m_productivity_available"]
    assert snap["rolling_5m_productivity_anchor_ns"] == NS


def test_v2_300s_instances_preserve_every_legacy_rolling_output_alias():
    from features.registry import LEGACY_FEATURE_INSTANCE_OVERRIDES
    tracker = Rolling5mProductivityTracker(); _seed(tracker)
    snapshot = tracker.snapshot(301 * NS, 1, 10.0, 0.2)
    aliases = {alias for alias, instance in LEGACY_FEATURE_INSTANCE_OVERRIDES.items()
               if instance.canonical_name.startswith("rolling_")}
    assert aliases <= set(snapshot)


def test_generic_rolling_provider_preserves_300s_values_and_accepts_60s():
    from features.trackers.generic_rolling_productivity import GenericRollingProductivityProvider

    legacy = Rolling5mProductivityTracker(); generic = GenericRollingProductivityProvider(300)
    for second in range(301):
        values = (second * NS + NS, 100.0 + second / 10, 99.0 + second / 10, 100.0 + second / 10)
        legacy.on_completed_1s(*values); generic.on_completed_1s(*values)
    old = legacy.snapshot(301 * NS, 1, 10.0, 0.2)
    new = generic.snapshot(301 * NS, 1, 10.0, 0.2)
    assert {"rolling_" + key.removeprefix("rolling_5m_"): value for key, value in old.items()
            if key.startswith("rolling_5m_")} == {key: value for key, value in new.items()
                                                 if key.startswith("rolling_")}

    sixty = GenericRollingProductivityProvider(60)
    for second in range(61):
        sixty.on_completed_1s(second * NS + NS, 100.0, 99.0, 100.0)
    assert sixty.snapshot(61 * NS, 1, 10.0, 0.2)["rolling_productivity_available"]
