"""Comprehensive Tests for Config-Driven Study Factory.
======================================================
Tests StudySpec validation, compiler fit decisions, feature registry binding,
baseline/lineage invariant enforcement, and CLI commands.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml
from pydantic import ValidationError

from research.schemas.study_spec import StudySpec
from research.study_types.flip_prediction import FlipPredictionCompiler
from research.study_types.bespoke import BespokeStudyCompiler
from research.study_types.base import FitDecision
from research.engines.feature_binding_engine import FeatureBindingError
from research.engines.lineage_engine import LineageViolationError, validate_lineage
from research.engines.baseline_engine import BaselineDriftError, validate_baseline
from scripts.create_study import create_study
from scripts.compile_study import compile_study
from scripts.describe_study_diff import describe_diff


@pytest.fixture
def valid_flip_yaml_dict():
    return {
        "study": {
            "id": "test_flip_study",
            "type": "flip_prediction",
            "risk_tier": 2,
            "description": "Test symmetric flip prediction study",
        },
        "instrument": {
            "symbol": "NQ",
            "venue": "XCME",
        },
        "population": {
            "type": "regime_state",
            "prevailing_regime": "bearish",
            "session": "RTH",
            "qualification": {
                "age_gate_seconds": 300,
                "established": True,
            },
        },
        "target": {
            "type": "flip",
            "event": "confirmed_flip",
            "direction": "bullish",
            "horizon_seconds": 300,
            "confirmation": {
                "mode": "bar_close",
                "confirmation_bars": 1,
            },
        },
        "features": {
            "source_key": "velocity_test_v1",
            "instances": [
                {"feature": "arrival_velocity", "parameters": {"lookback": 5}},
                {"feature": "arrival_velocity", "parameters": {"lookback": 10}},
                {"feature": "arrival_velocity", "parameters": {"lookback": 20}},
            ],
            "timing_contract": "verified",
        },
        "model": {
            "mode": "scoring",
            "family": "HistGradientBoostingClassifier",
            "params": {"learning_rate": 0.05, "max_iter": 100},
        },
        "chronology": {
            "train": [2021, 2022, 2023, 2024],
            "dev": [2025],
            "prohibited": [2026],
        },
        "execution": {
            "runtime": "nautilustrader",
            "strategy_class": "strategies.flip_prediction_collector.FlipPredictionCollector",
            "bounded": True,
        },
    }


def test_valid_flip_prediction_compiles(valid_flip_yaml_dict):
    spec = StudySpec.model_validate(valid_flip_yaml_dict)
    compiler = FlipPredictionCompiler()
    fit = compiler.evaluate_fit(spec)
    assert fit == FitDecision.STUDY_TYPE_MATCH

    res = compiler.compile(spec)
    assert res.study_id == "test_flip_study"
    assert res.custom_code_allowed is False
    assert res.nt_strategy_class == "strategies.flip_prediction_collector.FlipPredictionCollector"
    assert len(res.spec_sha256) == 64
    assert res.contracts["feature_contract"]["feature_count"] == 3
    assert res.contracts["timestamp_contract"]["raw_timestamp_semantic"] == "OPEN_STAMPED"


def test_flip_prediction_overreach_parity_operation_rejected(valid_flip_yaml_dict):
    # Parity operations cannot masquerade as canonical flip_prediction
    overreach_dict = valid_flip_yaml_dict.copy()
    overreach_dict["study"]["type"] = "flip_prediction"
    overreach_dict["operation"] = {
        "kind": "runtime_population_parity",
        "reconciliation_target": "candidate_population",
    }
    spec = StudySpec.model_validate(overreach_dict)
    compiler = FlipPredictionCompiler()
    
    # Fit evaluation must return BESPOKE_REQUIRED
    fit = compiler.evaluate_fit(spec)
    assert fit == FitDecision.BESPOKE_REQUIRED

    # Direct compilation under flip_prediction must fail closed
    with pytest.raises(ValueError, match="STUDY_TYPE_MISMATCH"):
        compiler.compile(spec)


def test_valid_bespoke_compiles_with_justification(valid_flip_yaml_dict):
    bespoke_dict = valid_flip_yaml_dict.copy()
    bespoke_dict["study"]["type"] = "bespoke"
    bespoke_dict["operation"] = {
        "kind": "runtime_population_parity",
        "reconciliation_target": "candidate_population",
    }
    bespoke_dict["bespoke"] = {
        "reason": "Live runtime candidate and score reconciliation against offline reference.",
        "unsupported_contract_element": "offline_vs_live_candidate_score_reconciliation",
        "canonical_type_considered": "flip_prediction",
        "reusable_extension_considered": "Planned for future population_parity canonical study type.",
        "custom_scope": ["implementation/reconcile.py"],
    }
    spec = StudySpec.model_validate(bespoke_dict)
    compiler = BespokeStudyCompiler()
    fit = compiler.evaluate_fit(spec)
    assert fit == FitDecision.BESPOKE_REQUIRED

    res = compiler.compile(spec)
    assert res.study_type == "bespoke"
    assert res.custom_code_allowed is True
    assert res.contracts["bespoke_justification"]["unsupported_contract_element"] == "offline_vs_live_candidate_score_reconciliation"
    assert res.contracts["execution_contract"]["runtime"] == "nautilustrader"


def test_bespoke_inherits_and_enforces_global_invariants(valid_flip_yaml_dict):
    import copy

    # 1. Bespoke cannot use non-NautilusTrader runtime
    bad_runtime = copy.deepcopy(valid_flip_yaml_dict)
    bad_runtime["study"]["type"] = "bespoke"
    bad_runtime["execution"]["runtime"] = "custom_pandas"
    bad_runtime["bespoke"] = {
        "reason": "Custom backtesting pipeline testing non-NT execution.",
        "unsupported_contract_element": "non_nt_runtime",
    }
    with pytest.raises(ValidationError, match="Input should be 'nautilustrader'"):
        StudySpec.model_validate(bad_runtime)

    # 2. Bespoke cannot violate chronology disjointness
    bad_chrono = copy.deepcopy(valid_flip_yaml_dict)
    bad_chrono["study"]["type"] = "bespoke"
    bad_chrono["chronology"]["train"] = [2021, 2026]
    bad_chrono["chronology"]["prohibited"] = [2026]
    bad_chrono["bespoke"] = {
        "reason": "Testing bespoke model with overlapping prohibited year.",
        "unsupported_contract_element": "chronology_override",
    }
    with pytest.raises(ValidationError, match="Chronology error"):
        StudySpec.model_validate(bad_chrono)

    # 3. Bespoke with unregistered feature fails feature contract compilation
    bad_feat = copy.deepcopy(valid_flip_yaml_dict)
    bad_feat["study"]["type"] = "bespoke"
    bad_feat["features"]["feature_list"] = ["unregistered_feature_abc"]
    bad_feat["features"]["instances"] = None
    bad_feat["bespoke"] = {
        "reason": "Testing bespoke features not in registry.",
        "unsupported_contract_element": "unregistered_features",
    }
    spec_bad_feat = StudySpec.model_validate(bad_feat)
    compiler = BespokeStudyCompiler()
    with pytest.raises(FeatureBindingError, match="FEATURE_NOT_REGISTERED"):
        compiler.compile(spec_bad_feat)


def test_bespoke_missing_justification_fails(valid_flip_yaml_dict):
    bespoke_dict = valid_flip_yaml_dict.copy()
    bespoke_dict["study"]["type"] = "bespoke"
    # Missing bespoke block
    with pytest.raises(ValidationError, match="BESPOKE_JUSTIFICATION_MISSING"):
        StudySpec.model_validate(bespoke_dict)

    # Empty reason
    bespoke_dict["bespoke"] = {
        "reason": "",
        "unsupported_contract_element": "some_element",
    }
    with pytest.raises(ValidationError, match="BESPOKE_JUSTIFICATION_MISSING"):
        StudySpec.model_validate(bespoke_dict)


def test_unsupported_runtime_rejected(valid_flip_yaml_dict):
    invalid_dict = valid_flip_yaml_dict.copy()
    invalid_dict["execution"]["runtime"] = "pandas_backtester"
    with pytest.raises(ValidationError, match="Input should be 'nautilustrader'"):
        StudySpec.model_validate(invalid_dict)


def test_unregistered_feature_fails_compilation(valid_flip_yaml_dict):
    bad_feat_dict = valid_flip_yaml_dict.copy()
    bad_feat_dict["features"]["feature_list"] = ["unregistered_bogus_feature_xyz"]
    bad_feat_dict["features"]["instances"] = None
    spec = StudySpec.model_validate(bad_feat_dict)
    compiler = FlipPredictionCompiler()
    with pytest.raises(FeatureBindingError, match="FEATURE_NOT_REGISTERED"):
        compiler.compile(spec)


def test_feature_hash_drift_fails_compilation(valid_flip_yaml_dict):
    bad_hash_dict = valid_flip_yaml_dict.copy()
    bad_hash_dict["features"]["feature_list_sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
    spec = StudySpec.model_validate(bad_hash_dict)
    compiler = FlipPredictionCompiler()
    with pytest.raises(FeatureBindingError, match="FEATURE_LIST_HASH_DRIFT"):
        compiler.compile(spec)


def test_chronology_overlap_fails_validation(valid_flip_yaml_dict):
    bad_chrono = valid_flip_yaml_dict.copy()
    # Prohibited year 2026 inside train
    bad_chrono["chronology"]["train"] = [2021, 2022, 2026]
    bad_chrono["chronology"]["prohibited"] = [2026]
    with pytest.raises(ValidationError, match="Chronology error"):
        StudySpec.model_validate(bad_chrono)


def test_frozen_lineage_mutation_fails(valid_flip_yaml_dict, tmp_path):
    # Setup a parent study in tmp_path
    parent_dict = valid_flip_yaml_dict.copy()
    parent_dict["study"]["id"] = "parent_study_v1"
    parent_dict["model"]["family"] = "HistGradientBoostingClassifier"
    parent_spec = StudySpec.model_validate(parent_dict)

    parent_dir = tmp_path / "parent_study_v1"
    parent_dir.mkdir(parents=True, exist_ok=True)
    with open(parent_dir / "compiled_study.json", "w") as f:
        json.dump({
            "study_id": "parent_study_v1",
            "spec": parent_spec.model_dump(),
        }, f)

    # Candidate study that freezes model but changes model family
    child_dict = valid_flip_yaml_dict.copy()
    child_dict["study"]["id"] = "child_study_v2"
    child_dict["model"]["family"] = "LogisticRegression"
    child_dict["lineage"] = {
        "parent_study": "parent_study_v1",
        "frozen": ["model"],
    }
    child_spec = StudySpec.model_validate(child_dict)

    with pytest.raises(LineageViolationError, match="UNAUTHORIZED_MODEL_CHANGE"):
        validate_lineage(child_spec, studies_root=tmp_path)


def test_create_and_compile_study_cli(valid_flip_yaml_dict, tmp_path):
    yaml_path = tmp_path / "study.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(valid_flip_yaml_dict, f)

    studies_root = tmp_path / "studies"
    exit_code = create_study(yaml_path, output_dir=studies_root)
    assert exit_code == 0

    study_dir = studies_root / "test_flip_study"
    assert (study_dir / "SPEC.md").exists()
    assert (study_dir / "TASK_PACKET.json").exists()
    assert (study_dir / "compiled_study.json").exists()
    assert (study_dir / "config" / "population_contract.json").exists()
    assert (study_dir / "config" / "target_contract.json").exists()
    assert (study_dir / "config" / "feature_contract.json").exists()
    assert (study_dir / "config" / "timestamp_contract.json").exists()
    assert (study_dir / "tests" / "test_study_contracts.py").exists()

    # Verify compile_study on created directory
    compile_code = compile_study(study_dir)
    assert compile_code == 0


def test_describe_study_diff(valid_flip_yaml_dict):
    spec_a = StudySpec.model_validate(valid_flip_yaml_dict)
    
    dict_b = valid_flip_yaml_dict.copy()
    dict_b["study"]["id"] = "test_flip_study_b"
    dict_b["model"]["family"] = "LogisticRegression"
    dict_b["target"]["horizon_seconds"] = 600
    dict_b["chronology"]["dev"] = [2026]  # mutated dev year
    dict_b["chronology"]["prohibited"] = [2025]
    spec_b = StudySpec.model_validate(dict_b)

    diff_str = describe_diff(spec_a, spec_b)
    assert "Model Family: HistGradientBoostingClassifier -> LogisticRegression" in diff_str
    assert "Target Horizon: 300s -> 600s" in diff_str
    assert "Dev Chronology: [2025] -> [2026]" in diff_str
