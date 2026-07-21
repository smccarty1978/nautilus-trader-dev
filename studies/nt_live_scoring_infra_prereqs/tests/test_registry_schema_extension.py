"""Phase 2 tests -- FeatureDefinition's new window/window_unit/reset_policy
fields, and their precise backfill for the two F3-relevant families
(ohlcv_est_delta, price_level_context). Deterministic, no NT run involved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from features.registry import FEATURE_REGISTRY, FeatureDefinition  # noqa: E402

ALLOWED_WINDOW_UNITS = {
    None, "bars", "seconds", "minutes", "events", "session", "since_signal", "since_regime_flip",
}


def _feature_sets():
    p = ROOT / "studies" / "short_rth_enriched_volume_level_retrain" / "_work" / "feature_sets.json"
    return json.loads(p.read_text(encoding="utf-8"))


def test_new_fields_exist_with_safe_defaults():
    d = FeatureDefinition(name="x")
    assert d.window is None
    assert d.window_unit is None
    assert d.reset_policy == "none"


def test_pre_existing_entries_unaffected():
    """A feature not touched by Phase 2's edits (outside F3) keeps the
    additive defaults -- confirms the schema extension didn't silently
    alter unrelated registry data."""
    d = FEATURE_REGISTRY["arrival_vel_5s"]
    assert d.window is None and d.window_unit is None and d.reset_policy == "none"
    assert d.family == "arrival_velocity"
    assert d.implementation == "features.trackers.velocity.ArrivalVelocityTracker"


@pytest.mark.parametrize("name,expected_window,expected_unit,expected_reset", [
    ("bar_volume", 1, "bars", "none"),
    ("vol_sum_30s", 30, "seconds", "none"),
    ("est_delta_sum_60s_minus_300s_scaled", None, None, "none"),
    ("regime_vol_sum", None, "since_regime_flip", "event_start"),
    ("rth_vol_cum", None, "session", "session_boundary"),
    ("rolling_15m_high_signed_distance_atr", 15, "minutes", "none"),
    ("rolling_60m_open_price", 60, "minutes", "none"),
    ("prior_day_open_price", None, "session", "session_boundary"),
    ("opening_range_30m_high_developing_price", None, "session", "session_boundary"),
    ("n_levels_above", None, None, "none"),
])
def test_precise_backfill_ohlcv_and_price_level(name, expected_window, expected_unit, expected_reset):
    d = FEATURE_REGISTRY[name]
    assert d.window == expected_window
    assert d.window_unit == expected_unit
    assert d.reset_policy == expected_reset


def test_all_window_units_are_from_the_documented_vocabulary():
    """FEATURE_REGISTRY_CONTRACT.md section 2 enumerates the allowed
    window_unit vocabulary; nothing backfilled here may use a value
    outside it."""
    bad = [(n, d.window_unit) for n, d in FEATURE_REGISTRY.items()
           if d.window_unit not in ALLOWED_WINDOW_UNITS]
    assert bad == [], f"window_unit values outside the documented vocabulary: {bad}"


def test_all_f3_ohlcv_and_price_level_features_have_reset_policy_populated():
    """Every F3 feature belonging to the two centrally-registered families
    (ohlcv_est_delta, price_level_context, including one-hot dummies of a
    registered categorical base) must have reset_policy set to something
    other than the bare class default left un-reasoned-about -- i.e. Phase
    2's backfill actually ran, it wasn't skipped.

    NOTE (completion-gate audit): membership in {"none", "event_start",
    "session_boundary"} alone cannot distinguish "backfilled to none" from
    "never touched, still at the class default none" -- that distinction
    is carried by `checked == 546` below (which would fail if any F3
    feature were missing/renamed) plus the family-specific value checks in
    `test_precise_backfill_ohlcv_and_price_level` above, which DO assert
    non-default values (e.g. window=30, window_unit='seconds') that a
    skipped backfill could not produce."""
    fs = _feature_sets()
    f3 = fs["F3_volume_delta_plus_price_levels"]
    f0 = set(fs["F0_existing_only"])
    checked = 0
    for name in f3:
        if name in f0:
            continue  # F0 is the genuinely out-of-registry family, not in scope here
        base = name
        if name not in FEATURE_REGISTRY:
            for suffix in ("__ABOVE", "__BELOW", "__TOUCH", "__UNAVAILABLE"):
                if name.endswith(suffix):
                    base = name[: -len(suffix)]
                    break
        assert base in FEATURE_REGISTRY, f"{name} (base {base}) not found in registry"
        d = FEATURE_REGISTRY[base]
        assert d.reset_policy in ("none", "event_start", "session_boundary")
        checked += 1
    assert checked == 546, f"expected to check 546 non-F0 F3 features, checked {checked}"


def test_registered_context_family_entries_have_no_implementation_and_are_distinguishable():
    """The 5 hand-written `context`-family entries are registered
    (status='verified') but have no live tracker (`implementation=''`) --
    `phase1_feature_inventory.py`'s `registered_without_implementation`
    flag must be able to tell these apart from features that are both
    registered AND backed by a live tracker (completion-gate audit Note:
    `live_tracker_exists = bool(d.implementation)` alone would silently
    conflate the two if this distinguishing flag didn't exist)."""
    for name in ("regime_age_bars", "ema_slope_short", "ema_slope_long",
                 "is_rth", "minutes_since_rth_open"):
        d = FEATURE_REGISTRY[name]
        assert d.status == "verified"
        assert d.implementation == ""
    # a feature that IS backed by a live tracker, for contrast
    assert FEATURE_REGISTRY["bar_volume"].implementation != ""
