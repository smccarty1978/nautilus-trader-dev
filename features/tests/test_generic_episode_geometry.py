"""Synthetic causal evidence for generic episode/pullback geometry."""
from __future__ import annotations

import pytest

from features.trackers.generic_episode_geometry import GenericEpisodeGeometryProvider
from features.trackers.generic_ohlcv_delta import GenericOHLCVDeltaProvider
from features.trackers.generic_regime_geometry import GenericCompletedRegimeGeometryProvider
from features.registry import FeatureInstance, generate_physical_alias, validate_feature_instance


NS = 1_000_000_000


def test_deep_pullback_surface_names_are_registered_and_parameterized():
    names = {
        "pullback_max_depth_atr", "pullback_recovery_from_extreme_atr",
        "pullback_post_arm_seconds", "pullback_elapsed_seconds",
        "pullback_fraction_of_structural_move",
        "seconds_since_prevailing_directional_extreme", "prior_deep_pullback_count",
        "recovery_from_counter_regime_extreme_atr", "fraction_of_counter_regime_move_recovered",
        "trend_normalized_est_delta_sum", "trend_normalized_est_delta_sum_ratio",
        "regime_direction", "regime_alignment",
    }
    from features.registry import CANONICAL_FEATURE_DEFINITIONS
    assert names <= set(CANONICAL_FEATURE_DEFINITIONS)
    assert validate_feature_instance(FeatureInstance(
        "regime_age_min", {"timeframe": "1m", "context": "current", "bar_state": "completed"}
    ))["timeframe"] == "1m"
    assert validate_feature_instance(FeatureInstance(
        "regime_duration_min", {"timeframe": "5s", "context": "prior", "bar_state": "completed"}
    ))["timeframe"] == "5s"
    assert validate_feature_instance(FeatureInstance(
        "regime_efficiency", {"timeframe": "5m", "context": "current", "bar_state": "completed"}
    ))["context"] == "current"
    assert generate_physical_alias(FeatureInstance(
        "trend_normalized_est_delta_sum", {
            "window": "5s", "update_every": "1s", "direction_reference": "prevailing_1m",
        }
    )) == "trend_normalized_est_delta_sum_5s"
    assert generate_physical_alias(FeatureInstance(
        "trend_normalized_est_delta_sum_ratio", {
            "numerator_window": "60s", "denominator_window": "300s",
            "update_every": "1s", "direction_reference": "prevailing_1m",
        }
    )) == "trend_normalized_est_delta_sum_ratio_60s_vs_300s"


def test_pullback_max_depth_uses_completed_1s_wick_and_keeps_arm_atr_separate_from_candidate_atr():
    provider = GenericEpisodeGeometryProvider()
    provider.start_episode(start_ns=10 * NS, direction=1, favorable_extreme_price=100.0)
    # A completed wick to 94 arms against ATR_arm=5.0, even though it closes
    # recovered at 99.0.  No forming-bar API exists on this provider.
    assert provider.observe_completed_1s(
        close_ts=11 * NS, high=100.0, low=94.0, arm_atr=5.0, arm_threshold_atr=1.0,
    )
    values = provider.candidate_snapshot(
        candidate_ts=15 * NS, candidate_price=98.0, candidate_atr=2.0,
        structural_expansion_points=12.0,
    )
    assert values["arm_depth_atr"] == pytest.approx(1.2)
    assert values["pullback_max_depth_atr"] == pytest.approx(3.0)
    assert values["pullback_current_depth_atr"] == pytest.approx(1.0)
    assert values["pullback_recovery_from_extreme_atr"] == pytest.approx(2.0)
    assert values["pullback_post_arm_seconds"] == pytest.approx(4.0)
    assert values["pullback_elapsed_seconds"] == pytest.approx(5.0)
    assert values["pullback_fraction_of_structural_move"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("direction", "extreme", "high", "low", "candidate", "expected"),
    ((1, 100.0, 100.0, 94.0, 98.0, 1.0), (-1, 100.0, 106.0, 100.0, 102.0, 1.0)),
)
def test_pullback_direction_normalization_is_symmetric(direction, extreme, high, low, candidate, expected):
    provider = GenericEpisodeGeometryProvider()
    provider.start_episode(start_ns=NS, direction=direction, favorable_extreme_price=extreme)
    assert provider.observe_completed_1s(
        close_ts=2 * NS, high=high, low=low, arm_atr=5.0, arm_threshold_atr=1.0,
    )
    values = provider.candidate_snapshot(candidate_ts=3 * NS, candidate_price=candidate, candidate_atr=2.0)
    assert values["pullback_current_depth_atr"] == pytest.approx(expected)


def test_pullback_provider_rejects_forming_or_reordered_completed_observations():
    provider = GenericEpisodeGeometryProvider()
    provider.start_episode(start_ns=NS, direction=1, favorable_extreme_price=100.0)
    provider.observe_completed_1s(close_ts=2 * NS, high=100.0, low=94.0, arm_atr=5.0, arm_threshold_atr=1.0)
    with pytest.raises(ValueError, match="NON_MONOTONIC"):
        provider.observe_completed_1s(close_ts=2 * NS, high=100.0, low=90.0, arm_atr=5.0, arm_threshold_atr=1.0)
    with pytest.raises(ValueError, match="CANDIDATE_BEFORE"):
        provider.candidate_snapshot(candidate_ts=NS, candidate_price=98.0, candidate_atr=2.0)


def test_prior_5s_geometry_freezes_counter_regime_and_exposes_candidate_recovery_only_after_flip():
    provider = GenericCompletedRegimeGeometryProvider()
    provider.on_completed_bar(timeframe="5s", close_ts=5 * NS, direction=-1, open_=100.0, high=100.0, low=98.0, close=98.0, atr=2.0)
    provider.on_completed_bar(timeframe="5s", close_ts=10 * NS, direction=-1, open_=98.0, high=99.0, low=94.0, close=95.0, atr=2.0)
    provider.on_completed_bar(timeframe="5s", close_ts=15 * NS, direction=1, open_=95.0, high=97.0, low=95.0, close=97.0, atr=2.0)
    snapshot = provider.prior_snapshot(timeframe="5s", checkpoint_ns=15 * NS, candidate_price=97.0, candidate_atr=2.0)
    assert snapshot["available"] is True
    assert snapshot["prior_5s_regime_recovery_from_extreme_atr"] == pytest.approx(1.5)
    assert snapshot["prior_5s_regime_fraction_move_recovered"] == pytest.approx(0.5)
    assert provider.prior_snapshot(timeframe="5s", checkpoint_ns=14 * NS)["available"] is False


def test_trend_normalized_delta_ratios_use_completed_windows_and_null_zero_scale():
    provider = GenericOHLCVDeltaProvider(windows_seconds=(5, 60, 300), maxlen=400)
    for second in range(301):
        provider.update_completed_bar(
            close_ts=(second + 1) * NS, open_px=100.0, high=101.0, low=99.0,
            close=101.0, volume=10.0,
        )
    long = provider.trend_normalized_est_delta_sum(window="5s", prevailing_direction=1, atr=2.0)
    short = provider.trend_normalized_est_delta_sum(window="5s", prevailing_direction=-1, atr=2.0)
    assert long == pytest.approx(-short)
    assert provider.trend_normalized_est_delta_scale_ratio(
        numerator_window="5s", denominator_window="300s", prevailing_direction=1, atr=2.0,
    ) is not None
    zero = GenericOHLCVDeltaProvider(windows_seconds=(5, 300), maxlen=400)
    for second in range(301):
        zero.update_completed_bar(
            close_ts=(second + 1) * NS, open_px=100.0, high=100.0, low=100.0,
            close=100.0, volume=0.0,
        )
    assert zero.trend_normalized_est_delta_scale_ratio(
        numerator_window="5s", denominator_window="300s", prevailing_direction=1, atr=2.0,
    ) is None
