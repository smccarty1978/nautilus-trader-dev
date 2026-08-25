from __future__ import annotations

import pytest

from features.calendar_aggregation import forming_calendar_bar_from_completed_seconds
from features.registry import (
    CANONICAL_FEATURE_DEFINITIONS, FeatureDefinition, FeatureInstance, FeatureInstanceError,
    derive_instance_input_requirements, generate_physical_alias, resolve_feature_instances,
    resolve_source_universe, validate_canonical_feature_name, validate_feature_instance,
)


def test_completed_calendar_instance_defaults_to_completed_semantics():
    completed = FeatureInstance("regime_efficiency", {"timeframe": "1m", "context": "prior"})
    assert validate_feature_instance(completed)["bar_state"] == "completed"


def test_instances_require_declared_legacy_compatible_parameter_combinations_before_cutover():
    with pytest.raises(FeatureInstanceError, match="MISSING_REQUIRED_FEATURE_PARAMETER"):
        validate_feature_instance(FeatureInstance("regime_efficiency", {}))
    with pytest.raises(FeatureInstanceError, match="UNSUPPORTED_FEATURE_PARAMETER_COMBINATION"):
        validate_feature_instance(FeatureInstance("regime_duration_min", {"timeframe": "5m", "context": "current"}))
    with pytest.raises(FeatureInstanceError, match="UNSUPPORTED_FEATURE_PARAMETER_VALUE"):
        validate_feature_instance(FeatureInstance("regime_efficiency", {"timeframe": "1m", "context": "prior", "regime": "next"}))


def test_live_legacy_provider_does_not_advertise_generic_timeframes_before_cutover():
    with pytest.raises(FeatureInstanceError, match="UNSUPPORTED_TIMEFRAME_PARAMETER"):
        validate_feature_instance(FeatureInstance("regime_efficiency", {"timeframe": "3m", "context": "prior"}))


def test_ambiguous_high_frequency_calendar_request_fails_closed():
    with pytest.raises(FeatureInstanceError, match="AMBIGUOUS_TEMPORAL_SEMANTICS"):
        validate_feature_instance(FeatureInstance("regime_efficiency", {"timeframe": "1m", "update_every": "1s"}))


def test_regime_geometry_does_not_advertise_unimplemented_forming_support():
    with pytest.raises(FeatureInstanceError, match="FORMING_BAR_UNSUPPORTED"):
        validate_feature_instance(FeatureInstance(
            "regime_efficiency", {"timeframe": "1m", "context": "prior", "bar_state": "forming", "update_every": "1s"},
        ))


def test_forming_calendar_snapshot_excludes_future_completed_second():
    ns = 1_000_000_000
    bars = [
        {"ts_event": 0, "ts_init": ns, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1},
        {"ts_event": ns, "ts_init": 2 * ns, "open": 2, "high": 3, "low": 2, "close": 3, "volume": 1},
        {"ts_event": 2 * ns, "ts_init": 3 * ns, "open": 3, "high": 99, "low": 0, "close": 99, "volume": 1},
    ]
    snapshot = forming_calendar_bar_from_completed_seconds(bars, timeframe_seconds=60, as_of_ns=2 * ns)
    assert snapshot == {"open": 1.0, "high": 3.0, "low": 1.0, "close": 3.0, "volume": 2.0, "bucket_start_ns": 0, "as_of_ns": 2 * ns}


def test_rolling_window_is_not_a_forming_calendar_bar():
    rolling = FeatureInstance("rolling_retention_ratio", {"window": "60s", "update_every": "1s"})
    assert derive_instance_input_requirements(rolling)["window_type"] == "rolling"
    assert "calendar_timeframe" not in derive_instance_input_requirements(rolling)


def test_cross_timeframe_instances_validate_each_bar_state_and_derive_both_completed_streams():
    instance = FeatureInstance("move_outside_completed_range", {
        "source_timeframe": "1m", "reference_timeframe": "5m", "context": "current",
        "source_bar_state": "completed", "reference_bar_state": "completed",
    })
    requirements = derive_instance_input_requirements(instance)
    assert requirements["required_streams"] == ["completed_1m", "completed_5m"]
    with pytest.raises(FeatureInstanceError, match="FORMING_BAR_UNSUPPORTED"):
        validate_feature_instance(FeatureInstance("move_outside_completed_range", {
            "source_timeframe": "1m", "reference_timeframe": "5m", "context": "current",
            "source_bar_state": "forming", "reference_bar_state": "completed",
        }))
    with pytest.raises(FeatureInstanceError, match="UNSUPPORTED_FEATURE_PARAMETER_VALUE"):
        validate_feature_instance(FeatureInstance("move_outside_completed_range", {
            "source_timeframe": "5m", "reference_timeframe": "1m", "context": "current",
            "source_bar_state": "completed", "reference_bar_state": "completed",
        }))
    with pytest.raises(FeatureInstanceError, match="UNSUPPORTED_TIMEFRAME_PARAMETER"):
        validate_feature_instance(FeatureInstance("move_outside_completed_range", {
            "source_timeframe": "3m", "reference_timeframe": "5m", "context": "current",
            "source_bar_state": "completed", "reference_bar_state": "completed",
        }))


def test_rolling_instance_rejects_unsupported_update_cadence():
    with pytest.raises(FeatureInstanceError, match="UNSUPPORTED_UPDATE_CADENCE"):
        validate_feature_instance(FeatureInstance(
            "rolling_retention_ratio", {"window": "60s", "update_every": "5s"},
        ))


def test_legacy_aliases_and_new_window_alias_are_deterministic():
    assert generate_physical_alias(FeatureInstance("regime_efficiency", {"timeframe": "5m", "context": "prior"})) == "prior_5m_regime_efficiency"
    assert generate_physical_alias(FeatureInstance("rolling_retention_ratio", {"window": "60s", "update_every": "1s"})) == "rolling_60s_retention_ratio"


def test_canonical_temporal_name_is_rejected_without_exception():
    with pytest.raises(FeatureInstanceError, match="FEATURE_NAME_EMBEDS_TEMPORAL_INSTANCE"):
        validate_canonical_feature_name(FeatureDefinition(name="foo_5m"))


def test_canonical_period_name_is_rejected_without_exception():
    with pytest.raises(FeatureInstanceError, match="FEATURE_NAME_EMBEDS_TEMPORAL_INSTANCE"):
        validate_canonical_feature_name(FeatureDefinition(name="ema_20"))


def test_explicit_instances_and_collection_universe_share_canonical_status():
    aliases = resolve_source_universe("canonical_verified_definition_universe")
    instances = (
        FeatureInstance("regime_efficiency", {"timeframe": "1m", "context": "prior"}),
        FeatureInstance("regime_efficiency", {"timeframe": "5m", "context": "prior"}),
    )
    from features.registry import canonical_definition_status
    if canonical_definition_status("regime_efficiency") == "verified":
        resolved = resolve_feature_instances("canonical_verified_definition_universe", instances)
        assert [item["physical_alias"] for item in resolved] == ["prior_1m_regime_efficiency", "prior_5m_regime_efficiency"]
        assert {item["canonical_name"] for item in resolved} <= set(aliases)
    else:
        # A provider edit invalidates its old hash-pinned promotion evidence;
        # the resolver must refuse to reuse that approval.
        with pytest.raises(FeatureInstanceError, match="UNVERIFIED_CANONICAL_FEATURE"):
            resolve_feature_instances("canonical_verified_definition_universe", instances)


def test_collection_resolver_is_deterministic_and_not_cache_backed():
    first = resolve_source_universe("canonical_verified_definition_universe")
    second = resolve_source_universe("canonical_verified_definition_universe")
    assert first == second
    assert first is not second
