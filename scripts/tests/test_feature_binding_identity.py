"""Parameterized FeatureInstance physical-identity is rendered by one shared path.

`compile_feature_contract` must produce the same physical output columns the runtime
resolver (`resolve_feature_instances` -> `generate_physical_alias`) emits, so two
instances of one canonical feature that differ only by a parameter stay distinct.
Generic infrastructure test -- no study-specific feature names beyond the minimal
registry fixtures needed to exercise a parameter axis.
"""
from __future__ import annotations

from pathlib import Path

from features.registry import (
    FeatureInstance,
    generate_physical_alias,
    resolve_feature_instances,
)
from research.engines.feature_binding_engine import compile_feature_contract
from research.schemas.study_spec import FeaturesSpec


def _windowed(window: str) -> dict:
    return {
        "feature": "trend_normalized_est_delta_sum",
        "parameters": {"window": window, "update_every": "1s", "direction_reference": "prevailing_1m"},
    }


def test_distinct_parameter_instances_render_distinct_output_columns():
    spec = FeaturesSpec.model_validate({
        "source": "canonical_verified_definition_universe",
        "instances": [_windowed("5s"), _windowed("60s"), _windowed("300s")],
    })
    contract = compile_feature_contract(spec)
    assert contract["feature_list"] == [
        "trend_normalized_est_delta_sum_5s",
        "trend_normalized_est_delta_sum_60s",
        "trend_normalized_est_delta_sum_300s",
    ]
    assert contract["feature_count"] == 3
    assert len(set(contract["feature_list"])) == 3


def test_contract_columns_equal_the_runtime_resolver_columns():
    instances = [_windowed("5s"), _windowed("60s"), _windowed("300s")]
    spec = FeaturesSpec.model_validate({"source": "canonical_verified_definition_universe", "instances": instances})
    contract = compile_feature_contract(spec)
    runtime = resolve_feature_instances(
        "canonical_verified_definition_universe",
        tuple(FeatureInstance(i["feature"], i["parameters"]) for i in instances),
    )
    assert sorted(contract["feature_list"]) == sorted(r["physical_alias"] for r in runtime)


def test_non_parameterized_feature_alias_is_unchanged():
    # A feature with no rendering rule keeps its bare canonical name (back-compat).
    assert generate_physical_alias(FeatureInstance("ema_slope", {})) == "ema_slope"
    assert generate_physical_alias(FeatureInstance("arrival_velocity", {"lookback": 20})) == "arrival_velocity"


def test_declared_canonical_identity_still_resolves_from_the_contract():
    from features.registry import resolve_feature_request

    spec = FeaturesSpec.model_validate({
        "source": "canonical_verified_definition_universe",
        "instances": [_windowed("5s"), _windowed("300s")],
    })
    contract = compile_feature_contract(spec)
    for r in contract["resolved_feature_instances"]:
        resolved = resolve_feature_request(r["canonical_name"], r["parameters"])
        assert resolved["provider"], f"{r['canonical_name']} has no provider binding"


def test_feature_list_and_instances_remain_mutually_exclusive():
    import pytest

    spec = FeaturesSpec.model_validate({
        "source": "canonical_verified_definition_universe",
        "instances": [_windowed("5s")],
        "feature_list": ["trend_normalized_est_delta_sum_5s"],
    })
    with pytest.raises(Exception, match="FEATURE_LIST_AND_INSTANCES_CONFLICT"):
        compile_feature_contract(spec)
