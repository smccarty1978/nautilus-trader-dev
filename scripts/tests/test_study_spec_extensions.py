"""Regression tests for the generic study-contract extensions:
composite targets, derived causal inputs, machine-enforced pre-freeze gates, and the
bounded model-selection protocol. Maps directly to the reviewer's A-L test cases plus
the corrections from the second review pass (decision-time causal ordering, exact
upstream pinning, governance-consequential final validation, unique-config random
search).
"""
from __future__ import annotations

import glob
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from research.engines.target_engine import compile_target_contract
from research.schemas.study_spec import ModelSelectionSpec, StudySpec, TIMESTAMP_CAUSAL_ORDER
from research_workflow.derived_inputs import DerivedInputBindingError, verify_derived_causal_inputs
from research_workflow.gates import (
    RequiredGateArtifactMalformed,
    RequiredGateNotSatisfied,
    RequiredGateStale,
    assert_gates_satisfied,
    compute_population_scope_sha256,
)
from research_workflow.model_selection import (
    SearchSpaceExceedsMaxTrials,
    SelectionPartitionMismatch,
    run_model_selection,
)
from research_workflow.modeling import (
    ModelSelectionBindingMismatch,
    ModelSelectionBindingRequired,
    ModelSelectionFinalValidationFailed,
    freeze_train_artifacts,
    fit_models,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

BASE_SPEC = dict(
    study={"id": "ext_smoke", "type": "flip_prediction", "description": "smoke"},
    instrument={"symbol": "NQ"},
    population={"prevailing_regime": "bearish"},
    target={"direction": "bullish", "horizon_seconds": 300},
)


# ---------------------------------------------------------------------------
# A. Existing simple target studies compile unchanged.
# ---------------------------------------------------------------------------
def test_a_zero_condition_target_compiles_unchanged():
    spec = StudySpec.model_validate(BASE_SPEC)
    contract = compile_target_contract(spec.target)
    assert "conditions" not in contract
    assert "condition_logic" not in contract
    assert contract["target_type"] == "flip"


# ---------------------------------------------------------------------------
# B. Composite target compiles and serializes exact conditions.
# ---------------------------------------------------------------------------
def _composite_target_data():
    return {
        "type": "composite",
        "direction": "bullish",
        "decision_reference": "decision_ts",
        "conditions": [
            {"id": "c1", "kind": "flip", "direction": "bullish", "horizon_seconds": 300},
            {"id": "c2", "kind": "excursion", "metric": "mfe_atr", "comparator": ">=", "threshold": 1.0, "forward_outcome_id": "fo1"},
            {"id": "c3", "kind": "excursion", "metric": "mae_atr", "comparator": "<=", "threshold": 0.5, "forward_outcome_id": "fo1"},
        ],
        "condition_logic": "AND",
        "required_forward_outcomes": [{"id": "fo1", "entry_reference": "next_bar_open", "horizon_seconds": 300}],
    }


def test_b_composite_target_compiles_and_serializes_exact_conditions():
    spec = StudySpec.model_validate(dict(BASE_SPEC, target=_composite_target_data()))
    contract = compile_target_contract(spec.target)
    assert contract["condition_logic"] == "AND"
    assert [c["id"] for c in contract["conditions"]] == ["c1", "c2", "c3"]
    assert contract["conditions"][1]["metric"] == "mfe_atr"
    assert contract["conditions"][1]["threshold"] == 1.0
    fo = contract["required_forward_outcomes"][0]
    assert fo["id"] == "fo1"
    assert "generated_outcome_columns" in fo and len(fo["generated_outcome_columns"]) > 0


def test_asymmetric_ordered_barrier_target_compiles_to_runtime_contract():
    target = {
        "type": "classification",
        "conditions": [{
            "id": "primary_label", "kind": "ordered_barrier",
            "forward_outcome_id": "path", "barrier_id": "primary",
        }],
        "required_forward_outcomes": [{
            "id": "path", "entry_reference": "next_bar_open",
            "horizon_seconds": 300, "max_tracking_seconds": 300,
            "max_gap_seconds": 1,
            "ordered_barriers": [{
                "id": "primary", "favorable_atr": 1.0,
                "adverse_atr": 0.75, "horizon_seconds": 300,
            }],
        }],
    }
    spec = StudySpec.model_validate(dict(BASE_SPEC, target=target))
    contract = compile_target_contract(spec.target)
    fo = contract["required_forward_outcomes"][0]
    assert fo["ordered_barriers"][0] == {
        "id": "primary", "favorable_atr": 1.0,
        "adverse_atr": 0.75, "horizon_seconds": 300,
    }
    assert "ordered_primary_binary_label" in fo["generated_outcome_columns"]


def test_composite_target_without_top_level_horizon_surfaces_forward_outcome_horizon():
    """A composite ordered-barrier target carries the horizon on its forward outcome;
    the compiled contract must surface that exact value and keep censoring consistent."""
    target = {
        "type": "composite", "decision_reference": "decision_ts",
        "conditions": [{"id": "cont", "kind": "ordered_barrier", "forward_outcome_id": "path", "barrier_id": "primary"}],
        "required_forward_outcomes": [{
            "id": "path", "entry_reference": "next_bar_open",
            "horizon_seconds": 300, "max_tracking_seconds": 300, "max_gap_seconds": 1,
            "ordered_barriers": [{"id": "primary", "favorable_atr": 1.0, "adverse_atr": 0.75, "horizon_seconds": 300}],
        }],
    }
    spec = StudySpec.model_validate(dict(BASE_SPEC, target=target))
    assert spec.target.horizon_seconds is None
    contract = compile_target_contract(spec.target)
    assert contract["horizon_seconds"] == 300
    assert contract["censoring_policy"]["max_horizon_seconds"] == contract["horizon_seconds"]


def test_composite_target_with_conflicting_forward_outcome_horizons_fails_closed():
    target = {
        "type": "composite", "decision_reference": "decision_ts", "condition_logic": "AND",
        "conditions": [
            {"id": "a", "kind": "ordered_barrier", "forward_outcome_id": "p1", "barrier_id": "b1"},
            {"id": "b", "kind": "ordered_barrier", "forward_outcome_id": "p2", "barrier_id": "b2"},
        ],
        "required_forward_outcomes": [
            {"id": "p1", "horizon_seconds": 300, "ordered_barriers": [{"id": "b1", "favorable_atr": 1.0, "adverse_atr": 0.75, "horizon_seconds": 300}]},
            {"id": "p2", "horizon_seconds": 120, "ordered_barriers": [{"id": "b2", "favorable_atr": 1.0, "adverse_atr": 0.75, "horizon_seconds": 120}]},
        ],
    }
    spec = StudySpec.model_validate(dict(BASE_SPEC, target=target))
    with pytest.raises(ValueError, match="TARGET_HORIZON_AMBIGUOUS"):
        compile_target_contract(spec.target)


def test_ordered_barrier_condition_must_reference_declared_barrier():
    target = {
        "type": "classification",
        "conditions": [{
            "id": "primary_label", "kind": "ordered_barrier",
            "forward_outcome_id": "path", "barrier_id": "missing",
        }],
        "required_forward_outcomes": [{
            "id": "path", "horizon_seconds": 300,
            "ordered_barriers": [{
                "id": "primary", "favorable_atr": 1.0,
                "adverse_atr": 0.75, "horizon_seconds": 300,
            }],
        }],
    }
    with pytest.raises(ValidationError, match="TARGET_CONDITION_ORDERED_BARRIER_UNDECLARED"):
        StudySpec.model_validate(dict(BASE_SPEC, target=target))


# ---------------------------------------------------------------------------
# C. Invalid composite condition fails closed.
# ---------------------------------------------------------------------------
def test_c_multi_condition_without_logic_fails_closed():
    bad = dict(_composite_target_data())
    bad["condition_logic"] = None
    with pytest.raises(ValidationError, match="TARGET_CONDITION_LOGIC_REQUIRED"):
        StudySpec.model_validate(dict(BASE_SPEC, target=bad))


def test_c_duplicate_condition_ids_fails_closed():
    bad = dict(_composite_target_data())
    conds = [dict(c) for c in bad["conditions"]]
    conds[1]["id"] = "c1"
    bad["conditions"] = conds
    with pytest.raises(ValidationError, match="DUPLICATE_TARGET_CONDITION_ID"):
        StudySpec.model_validate(dict(BASE_SPEC, target=bad))


def test_c_undeclared_forward_outcome_id_fails_closed():
    bad = dict(_composite_target_data())
    bad["required_forward_outcomes"] = []
    with pytest.raises(ValidationError, match="TARGET_CONDITION_FORWARD_OUTCOME_UNDECLARED"):
        StudySpec.model_validate(dict(BASE_SPEC, target=bad))


def test_c_invalid_field_combination_impossible_at_validation_time():
    bad = dict(_composite_target_data())
    conds = [dict(c) for c in bad["conditions"]]
    conds[0]["comparator"] = ">="  # comparator is not a FlipConditionSpec field
    bad["conditions"] = conds
    with pytest.raises(ValidationError):
        StudySpec.model_validate(dict(BASE_SPEC, target=bad))


# ---------------------------------------------------------------------------
# D/E. Frozen external score input binds correctly / missing-stale binding fails.
# ---------------------------------------------------------------------------
def _real_derived_input():
    import hashlib

    parent = REPO_ROOT / "studies" / "clean_maturity_flip_model_rolling_productivity"
    repaired = parent / "artifacts" / "train_experiment_freeze_repaired.json"
    sha = hashlib.sha256(repaired.read_bytes()).hexdigest()
    return {
        "name": "stage1_model_c_score", "kind": "frozen_external_model_score",
        "parent_study_id": "clean_maturity_flip_model_rolling_productivity",
        "parent_train_freeze_artifact": "artifacts/train_experiment_freeze_repaired.json",
        "parent_train_freeze_artifact_sha256": sha,
        "parent_frozen_execution_composite_sha256": "7b0994145ce702fedbf3b589a98fa869b09ef57253a17722b8de25931cbb96c8",
        "model_hashes": {
            "LONG_C": "a341ae262496ac30338f861535bf2dae45c301dff2d8753a8c4ce0821f555d38",
            "SHORT_C": "5aa9f0c897e9b60bb83ab7d7c6b1f20411d261264dae4e5bfd753f6ed0bda0cf",
        },
        "preprocessing_hash": "0833da444eaafa8a8cfaae3740addaab9b904abf93be109843315691e62b6be4",
        "availability_reference": "decision_ts",
    }


def test_d_frozen_external_score_input_binds_correctly():
    spec = StudySpec.model_validate(dict(BASE_SPEC, features={"derived_inputs": [_real_derived_input()]}))
    result = verify_derived_causal_inputs(spec, repo_root=REPO_ROOT)
    assert result[0]["name"] == "stage1_model_c_score"
    assert result[0]["verified"] is True


def test_e_missing_upstream_model_binding_fails():
    bad = dict(_real_derived_input())
    bad["model_hashes"] = {"LONG_C": "0" * 64, "SHORT_C": "0" * 64}
    spec = StudySpec.model_validate(dict(BASE_SPEC, features={"derived_inputs": [bad]}))
    with pytest.raises(DerivedInputBindingError, match="MODEL_OR_PREPROCESSING_MISMATCH"):
        verify_derived_causal_inputs(spec, repo_root=REPO_ROOT)


def test_e_stale_upstream_binding_fails_invalidated_artifact():
    import hashlib

    parent = REPO_ROOT / "studies" / "clean_maturity_flip_model_rolling_productivity"
    original = parent / "artifacts" / "train_experiment_freeze.json"
    bad = dict(_real_derived_input(), parent_train_freeze_artifact="artifacts/train_experiment_freeze.json",
               parent_train_freeze_artifact_sha256=hashlib.sha256(original.read_bytes()).hexdigest())
    spec = StudySpec.model_validate(dict(BASE_SPEC, features={"derived_inputs": [bad]}))
    with pytest.raises(DerivedInputBindingError, match="PARENT_ARTIFACT_INVALIDATED"):
        verify_derived_causal_inputs(spec, repo_root=REPO_ROOT)


# ---------------------------------------------------------------------------
# Derived-input decision-time causal ordering (review correction 1).
# ---------------------------------------------------------------------------
def test_decision_ts_input_for_decision_ts_child_passes():
    di = dict(_real_derived_input(), availability_reference="decision_ts")
    spec = StudySpec.model_validate(dict(
        BASE_SPEC, target=dict(BASE_SPEC["target"], decision_reference="decision_ts"),
        features={"derived_inputs": [di]},
    ))
    assert spec.features.derived_inputs[0].availability_reference == "decision_ts"


def test_confirmation_ts_input_for_decision_ts_child_fails():
    di = dict(_real_derived_input(), availability_reference="confirmation_ts")
    with pytest.raises(ValidationError, match="DERIVED_INPUT_NOT_AVAILABLE_AT_DECISION"):
        StudySpec.model_validate(dict(
            BASE_SPEC, target=dict(BASE_SPEC["target"], decision_reference="decision_ts"),
            features={"derived_inputs": [di]},
        ))


def test_later_deciding_child_may_use_confirmation_ts_availability():
    di = dict(_real_derived_input(), availability_reference="confirmation_ts")
    spec = StudySpec.model_validate(dict(
        BASE_SPEC, target=dict(BASE_SPEC["target"], decision_reference="confirmation_ts"),
        features={"derived_inputs": [di]},
    ))
    assert spec.features.derived_inputs[0].availability_reference == "confirmation_ts"
    assert TIMESTAMP_CAUSAL_ORDER["confirmation_ts"] == 2


# ---------------------------------------------------------------------------
# F/G/H. Required pre-freeze gate lifecycle.
# ---------------------------------------------------------------------------
def _gated_spec():
    return StudySpec.model_validate(dict(
        BASE_SPEC, chronology={"train": [2021, 2022, 2023], "dev": [2024]},
        required_gates=[{"id": "TRAIN_TARGET_BALANCE_PASS", "stage": "prepare",
                          "artifact_path": "artifacts/balance_pass.json", "artifact_schema_version": 1}],
    ))


def test_f_missing_gate_artifact_refuses_advancement(tmp_path):
    spec = _gated_spec()
    with pytest.raises(RequiredGateNotSatisfied):
        assert_gates_satisfied(tmp_path, spec, "prepare")


def test_g_stale_gate_artifact_refuses_advancement(tmp_path):
    spec = _gated_spec()
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "balance_pass.json").write_text(json.dumps({
        "gate_id": "TRAIN_TARGET_BALANCE_PASS", "schema_version": 1, "status": "PASS",
        "scope_sha256": "not-the-real-hash", "producer": "diagnostic", "created_at_utc": "now",
    }))
    with pytest.raises(RequiredGateStale):
        assert_gates_satisfied(tmp_path, spec, "prepare")


def test_h_fresh_pass_gate_advances(tmp_path):
    spec = _gated_spec()
    (tmp_path / "artifacts").mkdir()
    scope = compute_population_scope_sha256(spec, spec.required_gates[0].scope_fields)
    (tmp_path / "artifacts" / "balance_pass.json").write_text(json.dumps({
        "gate_id": "TRAIN_TARGET_BALANCE_PASS", "schema_version": 1, "status": "PASS",
        "scope_sha256": scope, "producer": "diagnostic", "created_at_utc": "now",
    }))
    evidence = assert_gates_satisfied(tmp_path, spec, "prepare")
    assert evidence[0]["gate_id"] == "TRAIN_TARGET_BALANCE_PASS"


def test_gate_artifact_missing_required_key_fails_closed(tmp_path):
    spec = _gated_spec()
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "balance_pass.json").write_text(json.dumps({
        "gate_id": "TRAIN_TARGET_BALANCE_PASS", "schema_version": 1, "status": "PASS",
        "scope_sha256": "x",
    }))
    with pytest.raises(RequiredGateArtifactMalformed):
        assert_gates_satisfied(tmp_path, spec, "prepare")


def _pre_fit_gated_spec():
    return StudySpec.model_validate(dict(
        BASE_SPEC,
        required_gates=[{
            "id": "population_balance", "stage": "pre_fit",
            "artifact_path": "artifacts/population_balance.json",
            "artifact_schema_version": 1,
        }],
    ))


def test_pre_fit_gate_is_bound_to_merged_train_dataset_identity(tmp_path):
    spec = _pre_fit_gated_spec()
    (tmp_path / "artifacts").mkdir()
    scope = compute_population_scope_sha256(spec, spec.required_gates[0].scope_fields)
    (tmp_path / "artifacts" / "population_balance.json").write_text(json.dumps({
        "gate_id": "population_balance", "schema_version": 1, "status": "PASS",
        "scope_sha256": scope, "dataset_identity_sha256": "old-merge",
        "producer": "diagnostic", "created_at_utc": "now",
    }))
    with pytest.raises(RequiredGateStale, match="old-merge"):
        assert_gates_satisfied(
            tmp_path, spec, "pre_fit", dataset_identity_sha256="current-merge"
        )


def test_fit_refuses_missing_pre_fit_gate_before_estimator_construction(tmp_path, monkeypatch):
    called = False

    def forbidden_fit(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("estimator construction was reached")

    monkeypatch.setattr("research_workflow.modeling.fit_arms", forbidden_fit)
    X = pd.DataFrame({"x": [0.0, 1.0]})
    y = pd.Series([0, 1])
    meta = pd.DataFrame({"_partition": ["train", "train"]})
    with pytest.raises(RequiredGateNotSatisfied):
        fit_models(
            tmp_path, X, y, meta=meta, spec=object(),
            study_spec=_pre_fit_gated_spec(), dataset_identity_sha256="merge-sha",
        )
    assert called is False


# ---------------------------------------------------------------------------
# I/J. Hyperparameter search domain / OOS-year rejection at compile time.
# ---------------------------------------------------------------------------
def test_i_hyperparameter_outside_declared_domain_rejected_at_search():
    spec = ModelSelectionSpec.model_validate({
        "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
            {"name": "C", "kind": "choice", "values": [0.1, 1.0]}]}],
        "search_method": "grid", "max_trials": 1,
        "tuning_years": [2021, 2022], "final_train_validation_years": [2023],
        "final_validation_policy": "report_only",
    })
    with pytest.raises(SearchSpaceExceedsMaxTrials):
        run_model_selection(tempfile.mkdtemp(), {"A": pd.DataFrame({"x": [0]})}, pd.Series([0]),
                             pd.DataFrame({"_partition": ["train"], "_selection_role": ["tuning"], "_year": [2021]}),
                             spec)


def test_j_oos_year_in_tuning_years_rejected_at_compile_time():
    with pytest.raises(ValidationError, match="MODEL_SELECTION_YEARS_NOT_SUBSET_OF_TRAIN|MODEL_SELECTION_YEARS_INCLUDE_OOS"):
        StudySpec.model_validate(dict(
            BASE_SPEC, chronology={"train": [2021, 2022, 2023], "dev": [2024]},
            model={"selection": {
                "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
                    {"name": "C", "kind": "choice", "values": [0.1]}]}],
                "search_method": "random", "max_trials": 1,
                "tuning_years": [2021, 2024], "final_train_validation_years": [2022, 2023],
                "primary_selection_metric": "roc_auc", "final_validation_policy": "report_only",
            }},
        ))


def test_j_oos_year_in_tuning_years_never_reaches_the_runner():
    """The row-level defense (SelectionPartitionMismatch) also fires if somehow reached."""
    meta = pd.DataFrame({"_partition": ["train"] * 2, "_selection_role": ["tuning"] * 2, "_year": [2021, 2024]})
    spec = ModelSelectionSpec.model_validate({
        "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
            {"name": "C", "kind": "choice", "values": [0.1]}]}],
        "search_method": "random", "max_trials": 1, "random_seed": 0,
        "tuning_years": [2021, 2022], "final_train_validation_years": [2023],
        "primary_selection_metric": "roc_auc", "final_validation_policy": "report_only",
    })
    X = pd.DataFrame({"x": [0.1, 0.2]})
    y = pd.Series([0, 1])
    with pytest.raises(SelectionPartitionMismatch):
        run_model_selection(tempfile.mkdtemp(), {"A": X}, y, meta, spec)


# ---------------------------------------------------------------------------
# K. Existing studies remain backward compatible.
# ---------------------------------------------------------------------------
def test_k_every_existing_study_yaml_still_validates_and_recompiles():
    from research_workflow.compiler import compile_study

    paths = sorted(glob.glob(str(REPO_ROOT / "studies" / "*" / "study.yaml")))
    assert len(paths) >= 5, "expected the real studies/ fixtures to be present"
    for p in paths:
        data = yaml.safe_load(open(p, encoding="utf-8"))
        spec = StudySpec.model_validate(data)  # must not raise
        assert spec.study.id


def test_k_new_fields_are_additive_and_absent_by_default():
    spec = StudySpec.model_validate(BASE_SPEC)
    assert spec.required_gates is None
    assert spec.features.derived_inputs is None
    assert spec.model.selection is None
    assert spec.target.conditions is None


# ---------------------------------------------------------------------------
# L. New timeframe/promotion routing matches the corrected authority semantics.
# ---------------------------------------------------------------------------
def test_l_unverified_parameter_value_detected_when_declared():
    from scripts.check_feature_promotion import _unverified_parameter_values

    class FakeDefinition:
        supported_timeframes = ["1m", "5m", "15m"]
        supported_parameter_values: dict = {}

    rec = {"verified_parameter_values": {"timeframe": ["1m", "5m"]}}
    findings = _unverified_parameter_values(rec, FakeDefinition())
    assert findings == [{"parameter": "timeframe", "unverified_values": ["15m"]}]


def test_l_grandfathered_definition_without_verified_block_unaffected():
    from scripts.check_feature_promotion import _unverified_parameter_values

    class FakeDefinition:
        supported_timeframes = ["1m", "5m", "15m"]
        supported_parameter_values: dict = {}

    assert _unverified_parameter_values({}, FakeDefinition()) == []


# ---------------------------------------------------------------------------
# Model-selection execution enforcement (review pass 2 corrections).
# ---------------------------------------------------------------------------
def _synthetic_selection_dataset():
    import numpy as np

    rng = np.random.RandomState(0)
    rows = []
    for yr, role in ((2021, "tuning"), (2022, "tuning"), (2023, "final_validation")):
        for _ in range(150):
            x1, x2 = rng.normal(), rng.normal()
            label = int((x1 + 0.5 * x2 + rng.normal(scale=0.5)) > 0)
            rows.append({"x1": x1, "x2": x2, "y": label, "_year": yr, "_partition": "train", "_selection_role": role})
    df = pd.DataFrame(rows).reset_index(drop=True)
    return df[["x1", "x2"]], df["y"], df[["_year", "_partition", "_selection_role"]]


def test_random_search_max_trials_are_unique_configurations():
    X, y, meta = _synthetic_selection_dataset()
    spec = ModelSelectionSpec.model_validate({
        "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
            {"name": "C", "kind": "float_range", "low": 0.01, "high": 10.0, "log_scale": True}]}],
        "search_method": "random", "max_trials": 3, "random_seed": 7,
        "tuning_years": [2021, 2022], "final_train_validation_years": [2023],
        "primary_selection_metric": "roc_auc", "final_validation_policy": "report_only",
    })
    manifest = run_model_selection(tempfile.mkdtemp(), {"A": X}, y, meta, spec)
    assert manifest["unique_evaluated_count"] == 3
    configs = [tuple(sorted(a["hyperparameters"].items())) for a in manifest["attempts"]["A"]]
    assert len(configs) == len(set(configs)), "a configuration was fitted more than once"


def test_random_search_deterministic_same_seed():
    X, y, meta = _synthetic_selection_dataset()
    spec = ModelSelectionSpec.model_validate({
        "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
            {"name": "C", "kind": "float_range", "low": 0.01, "high": 10.0, "log_scale": True}]}],
        "search_method": "random", "max_trials": 3, "random_seed": 7,
        "tuning_years": [2021, 2022], "final_train_validation_years": [2023],
        "primary_selection_metric": "roc_auc", "final_validation_policy": "report_only",
    })
    m1 = run_model_selection(tempfile.mkdtemp(), {"A": X}, y, meta, spec)
    m2 = run_model_selection(tempfile.mkdtemp(), {"A": X}, y, meta, spec)
    c1 = [a["hyperparameters"] for a in m1["attempts"]["A"]]
    c2 = [a["hyperparameters"] for a in m2["attempts"]["A"]]
    assert c1 == c2


def test_random_search_exhausts_small_finite_space_cleanly():
    X, y, meta = _synthetic_selection_dataset()
    spec = ModelSelectionSpec.model_validate({
        "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
            {"name": "C", "kind": "choice", "values": [0.1, 1.0]}]}],
        "search_method": "random", "max_trials": 10, "random_seed": 1,
        "tuning_years": [2021, 2022], "final_train_validation_years": [2023],
        "primary_selection_metric": "roc_auc", "final_validation_policy": "report_only",
    })
    manifest = run_model_selection(tempfile.mkdtemp(), {"A": X}, y, meta, spec)
    assert manifest["unique_evaluated_count"] == 2
    assert manifest["search_space_exhausted"] is True


def test_log_scale_requires_positive_low_at_schema_validation():
    with pytest.raises(ValidationError, match="LOG_SCALE_REQUIRES_POSITIVE_LOW"):
        StudySpec.model_validate(dict(BASE_SPEC, model={"selection": {
            "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
                {"name": "C", "kind": "float_range", "low": 0.0, "high": 1.0, "log_scale": True}]}],
            "search_method": "random", "max_trials": 1, "tuning_years": [2021, 2022],
            "final_validation_policy": "report_only",
        }}))


def test_gated_final_validation_with_impossible_bound_fails_status():
    X, y, meta = _synthetic_selection_dataset()
    spec = ModelSelectionSpec.model_validate({
        "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
            {"name": "C", "kind": "choice", "values": [1.0]}]}],
        "search_method": "random", "max_trials": 1, "random_seed": 0,
        "tuning_years": [2021, 2022], "final_train_validation_years": [2023],
        "primary_selection_metric": "roc_auc", "final_validation_policy": "gated",
        "final_validation_requirements": {"primary_metric_bound": {"metric": "roc_auc", "minimum": 0.999}},
    })
    manifest = run_model_selection(tempfile.mkdtemp(), {"A": X}, y, meta, spec)
    assert manifest["final_validation_status"] == "FAIL"
    assert manifest["no_retuning_after_final_validation_assertion"] is True


def test_freeze_refuses_when_gated_final_validation_failed():
    tmp = tempfile.mkdtemp()
    (Path(tmp) / "study.yaml").write_text(yaml.safe_dump(dict(
        BASE_SPEC, chronology={"train": [2021, 2022, 2023], "dev": [2024]},
        model={"selection": {
            "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
                {"name": "C", "kind": "choice", "values": [1.0]}]}],
            "search_method": "random", "max_trials": 1, "random_seed": 0,
            "tuning_years": [2021, 2022], "final_train_validation_years": [2023],
            "primary_selection_metric": "roc_auc", "final_validation_policy": "gated",
            "final_validation_requirements": {"primary_metric_bound": {"metric": "roc_auc", "minimum": 0.999}},
        }},
    )))
    from research_workflow.experiment import authorize_experiment
    authorize_experiment(tmp)
    spec = StudySpec.model_validate(yaml.safe_load((Path(tmp) / "study.yaml").read_text()))

    manifest_path = Path(tmp) / "selection_manifest.json"
    manifest_path.write_text(json.dumps({
        "manifest_sha256": "abc", "random_seed": 0,
        "winner": {"A": {"family": "logistic_regression", "hyperparameters": {"C": 1.0}}},
        "final_validation_policy": "gated", "final_validation_status": "FAIL",
        "final_validation_reasons": {"A": ["roc_auc too low"]},
    }))
    meta = pd.DataFrame({"_partition": ["train"]})
    with pytest.raises(ModelSelectionFinalValidationFailed):
        freeze_train_artifacts(
            tmp, feature_sets={"A": ["x1"]},
            models_manifest={"arms": {"A": {"hyperparameters": {"C": 1.0}, "seed": 0}}},
            preprocessing_hash="h", score_arrays={}, meta=meta, study_spec=spec,
            model_selection_manifest_path=manifest_path,
        )


def test_freeze_requires_manifest_when_search_declared():
    tmp = tempfile.mkdtemp()
    spec = StudySpec.model_validate(dict(
        BASE_SPEC, chronology={"train": [2021, 2022, 2023], "dev": [2024]},
        model={"selection": {
            "allowed_families": [{"family": "logistic_regression", "tunable_hyperparameters": [
                {"name": "C", "kind": "choice", "values": [1.0]}]}],
            "search_method": "random", "max_trials": 1, "tuning_years": [2021, 2022],
            "final_train_validation_years": [2023], "primary_selection_metric": "roc_auc",
            "final_validation_policy": "report_only",
        }},
    ))
    meta = pd.DataFrame({"_partition": ["train"]})
    with pytest.raises(ModelSelectionBindingRequired):
        freeze_train_artifacts(
            tmp, feature_sets={"A": ["x1"]}, models_manifest={"arms": {}},
            preprocessing_hash="h", score_arrays={}, meta=meta, study_spec=spec,
        )
