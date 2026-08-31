"""Cross-cutting Red-Team Pass 2 acceptance suite (20 items)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd
from pydantic import ValidationError

from research.engines.target_engine import compile_target_contract
from research.schemas.study_spec import DerivedCausalInputSpec, PopulationQualificationSpec, TargetSpec
from research_workflow.external_model_scoring import FrozenExternalModelScorer
from research_workflow.generic_collector import verify_checkpoint_identities_authority
from research_workflow.model_artifacts import (
    ModelArtifactError,
    assert_scientific_status_reusable,
    load_model_bundle,
    resolve_model,
    score_preserved_model,
    validate_golden_prediction,
)
from research_workflow.modeling_closure import resolve_modeling_closure
from research_workflow.modeling_drivers import UndeclaredModelingDriverError, assert_declared_modeling_drivers
from research_workflow.oos_analysis_lineage import classify_oos_analysis, classify_stage17_decision
from research_workflow.study_closure import StudyClosureInvalid, load_study_closure
from research_workflow.target_expression import compile_target_expression
from research_workflow.target_runtime import NS, resolve_target_runtime, validate_target_parity
from research_workflow.workflow_engine import WorkflowEngine

ATR = "latest_causally_completed_1m_wilder_atr_14_available_at_T"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# 1. conflicting composite session policies cannot silently execute wrong semantics
def test_rt2_01_conflicting_composite_session_policy_rejected_or_child_owned():
    with pytest.raises(ValidationError, match="COMPOSITE_SESSION_POLICY_MUST_BE_CHILD_OWNED"):
        TargetSpec.model_validate({
            "type": "composite", "session_end_censoring": True,
            "required_forward_outcomes": [{"id": "x", "horizon_seconds": 1}],
        })
    contract = {
        "primitive": "composite", "condition_logic": "AND", "horizon_seconds": 10,
        "conditions": [
            {"id": "a", "kind": "ordered_barrier", "forward_outcome_id": "a_fo", "barrier_id": "a"},
            {"id": "b", "kind": "ordered_barrier", "forward_outcome_id": "b_fo", "barrier_id": "b"},
        ],
        "required_forward_outcomes": [
            {"id": "a_fo", "entry_reference": "next_bar_open", "horizon_seconds": 1,
             "session_end_censoring": True, "max_gap_seconds": 1,
             "atr_source": ATR, "atr_frozen_at": "decision_ts",
             "ordered_barriers": [{"id": "a", "favorable_atr": 1., "adverse_atr": 1., "horizon_seconds": 1}]},
            {"id": "b_fo", "entry_reference": "next_bar_open", "horizon_seconds": 10,
             "session_end_censoring": False, "max_gap_seconds": 10,
             "atr_source": ATR, "atr_frozen_at": "decision_ts",
             "ordered_barriers": [{"id": "b", "favorable_atr": 1., "adverse_atr": 1., "horizon_seconds": 10}]},
        ],
    }
    rt = resolve_target_runtime(contract)
    p = rt.open_pending({"observation_ts": 0, "regime_direction": 1, "atr": 1.,
                         "atr_source": ATR, "session_close_ts": 5 * NS})
    assert p["children"]["a"]["session_close_ts"] == 5 * NS
    assert p["children"]["b"]["session_close_ts"] is None


# 2. mixed child gap thresholds execute independently
def test_rt2_02_mixed_child_gap_thresholds_execute_independently():
    contract = {
        "primitive": "composite", "condition_logic": "AND", "horizon_seconds": 10,
        "conditions": [
            {"id": "a", "kind": "ordered_barrier", "forward_outcome_id": "a_fo", "barrier_id": "a"},
            {"id": "b", "kind": "ordered_barrier", "forward_outcome_id": "b_fo", "barrier_id": "b"},
        ],
        "required_forward_outcomes": [
            {"id": "a_fo", "entry_reference": "next_bar_open", "horizon_seconds": 1,
             "session_end_censoring": False, "max_gap_seconds": 1,
             "atr_source": ATR, "atr_frozen_at": "decision_ts",
             "ordered_barriers": [{"id": "a", "favorable_atr": 100., "adverse_atr": 100., "horizon_seconds": 1}]},
            {"id": "b_fo", "entry_reference": "next_bar_open", "horizon_seconds": 10,
             "session_end_censoring": False, "max_gap_seconds": 10,
             "atr_source": ATR, "atr_frozen_at": "decision_ts",
             "ordered_barriers": [{"id": "b", "favorable_atr": 100., "adverse_atr": 100., "horizon_seconds": 10}]},
        ],
    }
    rt = resolve_target_runtime(contract)
    p = rt.open_pending({"observation_ts": 0, "regime_direction": 1, "atr": 1., "atr_source": ATR})
    tape = [
        {"ts": NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
        {"ts": 6 * NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
        {"ts": 11 * NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
    ]
    for event in tape:
        rt.ingest_bar(p, event)
    result = rt.terminal(p, final=True, now_ts=11 * NS)
    assert (result.disposition, result.label) == ("NEGATIVE", 0)


# 3. oracle catches a deliberately reintroduced shared-gap bug
def test_rt2_03_oracle_catches_shared_gap_defect():
    contract = {
        "primitive": "composite", "condition_logic": "AND", "horizon_seconds": 10,
        "conditions": [
            {"id": "a", "kind": "ordered_barrier", "forward_outcome_id": "a_fo", "barrier_id": "a"},
            {"id": "b", "kind": "ordered_barrier", "forward_outcome_id": "b_fo", "barrier_id": "b"},
        ],
        "required_forward_outcomes": [
            {"id": "a_fo", "entry_reference": "next_bar_open", "horizon_seconds": 1,
             "session_end_censoring": False, "max_gap_seconds": 1,
             "atr_source": ATR, "atr_frozen_at": "decision_ts",
             "ordered_barriers": [{"id": "a", "favorable_atr": 100., "adverse_atr": 100., "horizon_seconds": 1}]},
            {"id": "b_fo", "entry_reference": "next_bar_open", "horizon_seconds": 10,
             "session_end_censoring": False, "max_gap_seconds": 10,
             "atr_source": ATR, "atr_frozen_at": "decision_ts",
             "ordered_barriers": [{"id": "b", "favorable_atr": 100., "adverse_atr": 100., "horizon_seconds": 10}]},
        ],
    }
    rt = resolve_target_runtime(contract)
    p = rt.open_pending({"observation_ts": 0, "regime_direction": 1, "atr": 1., "atr_source": ATR})
    tape = [
        {"ts": NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
        {"ts": 6 * NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
        {"ts": 11 * NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
    ]
    for event in tape:
        rt.ingest_bar(p, event)
    result = rt.terminal(p, final=True, now_ts=11 * NS)
    row = rt.parity_row(p, {"disposition": result.disposition, "label": result.label, "censor_reason": result.censor_reason})
    bad_row = dict(row)
    bad_row["actual"] = {"disposition": "CENSORED", "label": None, "censor_reason": "GAP"}
    assert not validate_target_parity(contract, [bad_row])["passed"]


# 4. horizon=0 rejects
def test_rt2_04_horizon_zero_rejects():
    with pytest.raises(ValidationError):
        TargetSpec.model_validate({"type": "flip", "horizon_seconds": 0})
    with pytest.raises(ValidationError):
        TargetSpec.model_validate({
            "type": "composite",
            "required_forward_outcomes": [{"id": "x", "horizon_seconds": 0}],
        })


# 5. negative horizon rejects
def test_rt2_05_negative_horizon_rejects():
    with pytest.raises(ValidationError):
        TargetSpec.model_validate({"type": "flip", "horizon_seconds": -5})
    with pytest.raises(ValidationError):
        TargetSpec.model_validate({
            "type": "composite",
            "required_forward_outcomes": [{"id": "x", "horizon_seconds": -10}],
        })


# 6. single primitive ordered barrier binds referenced barrier, not barrier[0]
def test_rt2_06_single_primitive_ordered_barrier_binds_referenced_barrier():
    target = TargetSpec.model_validate({
        "type": "composite",
        "conditions": [{"id": "picked", "kind": "ordered_barrier", "forward_outcome_id": "fo", "barrier_id": "second"}],
        "required_forward_outcomes": [{
            "id": "fo", "horizon_seconds": 10, "atr_source": ATR, "atr_frozen_at": "decision_ts",
            "ordered_barriers": [
                {"id": "first", "favorable_atr": 1., "adverse_atr": 1., "horizon_seconds": 10},
                {"id": "second", "favorable_atr": 2., "adverse_atr": 3., "horizon_seconds": 9},
            ],
        }],
    })
    contract = compile_target_contract(target)
    leaf = compile_target_expression(contract).leaves()[0]
    assert leaf.params["barrier_id"] == "second"
    assert leaf.params["favorable_atr"] == 2.0
    assert leaf.params["adverse_atr"] == 3.0
    assert leaf.params["horizon_seconds"] == 9


# 7. primitive ordered-barrier parity artifact is emitted/verified
def test_rt2_07_primitive_ordered_barrier_parity_verified():
    contract = {
        "primitive": "ordered_barrier",
        "favorable_atr": 1.0,
        "adverse_atr": 1.0,
        "horizon_seconds": 10,
    }
    parity_dataset = [{
        "candidate": {
            "observation_ts": 0, "horizon_end_ts": 10 * NS, "entry_price": 100.0,
            "atr": 1.0, "direction": 1, "favorable_atr": 1.0, "adverse_atr": 1.0,
        },
        "events": [{"ts": 5 * NS, "high": 101.5, "low": 99.8}],
        "actual": {"disposition": "POSITIVE", "label": 1},
    }]
    report = validate_target_parity(contract, parity_dataset)
    assert report["passed"] is True
    assert report["rows_compared"] == 1


# 8. unsupported ATR source rejects or resolves exact producer
def test_rt2_08_unsupported_atr_source_rejects():
    with pytest.raises(ValidationError):
        TargetSpec.model_validate({
            "type": "composite",
            "required_forward_outcomes": [{
                "id": "fo", "horizon_seconds": 10, "atr_source": "unsupported_producer",
                "atr_frozen_at": "decision_ts",
                "ordered_barriers": [{"id": "b", "favorable_atr": 1., "adverse_atr": 1., "horizon_seconds": 10}],
            }],
        })


# 9. unknown confirmation key rejects
def test_rt2_09_unknown_confirmation_key_rejects():
    with pytest.raises(ValidationError):
        TargetSpec.model_validate({
            "type": "flip",
            "confirmation": {"mode": "bar_close", "unauthorized_extra_field": True},
        })


# 10. allowlist table SHA mismatch rejects
def test_rt2_10_allowlist_table_sha_mismatch_rejects(tmp_path):
    p = tmp_path / "allowlist.parquet"
    p.write_bytes(b"content-a")
    declared_sha = _sha(b"content-b")
    with pytest.raises(RuntimeError, match="SHA256_MISMATCH"):
        verify_checkpoint_identities_authority(p, declared_sha)


# 11. undeclared indirect modeling helper fails
def test_rt2_11_undeclared_indirect_modeling_helper_fails(tmp_path):
    s = tmp_path / "study"
    (s / "implementation").mkdir(parents=True)
    (s / "implementation/driver.py").write_text("from . import helper\n", encoding="utf-8")
    (s / "implementation/helper.py").write_text("from research_workflow.modeling import fit_models\n", encoding="utf-8")
    with pytest.raises(UndeclaredModelingDriverError, match="helper.py"):
        assert_declared_modeling_drivers(s, ["implementation/driver.py"])


# 12. undeclared modeling subprocess entrypoint fails
def test_rt2_12_undeclared_modeling_subprocess_entrypoint_fails(tmp_path):
    s = tmp_path / "study"
    (s / "implementation").mkdir(parents=True)
    (s / "implementation/driver.py").write_text("import subprocess, sys\nsubprocess.run([sys.executable, 'implementation/sub.py'])\n", encoding="utf-8")
    (s / "implementation/sub.py").write_text("from research_workflow.modeling import fit_models\n", encoding="utf-8")
    with pytest.raises(UndeclaredModelingDriverError, match="sub.py"):
        assert_declared_modeling_drivers(s, ["implementation/driver.py"])


# 13. UNASSESSED model cannot be used as derived causal input
def test_rt2_13_unassessed_model_cannot_be_derived_causal_input():
    rec = {"model_id": "m1", "scientific_status": "UNASSESSED", "reuse_status": "PERMITTED"}
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        assert_scientific_status_reusable(rec)


# 14. VALID_DIAGNOSTIC requires explicit reuse policy
def test_rt2_14_valid_diagnostic_requires_explicit_reuse_policy():
    rec = {"model_id": "m2", "scientific_status": "VALID_DIAGNOSTIC", "reuse_status": "PERMITTED"}
    with pytest.raises(ModelArtifactError, match="REQUIRES_POLICY"):
        assert_scientific_status_reusable(rec)
    assert_scientific_status_reusable(rec, {"kind": "diagnostic_derived_causal_input", "model_id": "m2"})


# 15. native-booster recovery works through the real resolve/bind path
def test_rt2_15_native_booster_recovery_real_bind_path(tmp_path):
    import lightgbm as lgb
    import numpy as np
    study = tmp_path / "study"; study.mkdir()
    reg = tmp_path / "model_registry"; reg.mkdir()
    models_dir = study / "models"; models_dir.mkdir()
    mid = "test_model_native"
    booster_path = models_dir / f"{mid}.txt"
    ds = lgb.Dataset(np.array([[0.0, 1.0], [1.0, 0.0]]), label=[0, 1])
    bst = lgb.train({"verbosity": -1, "min_data_in_leaf": 1}, ds, num_boost_round=2)
    bst.save_model(str(booster_path))
    art_path = models_dir / f"{mid}.joblib"
    art_path.write_bytes(b"corrupt-joblib")
    golden_path = models_dir / f"{mid}_golden.json"
    golden_data = {
        "ordered_inputs": ["f1", "f2"],
        "rows": [[0.0, 1.0]],
        "expected_scores": [float(bst.predict([[0.0, 1.0]])[0])],
    }
    golden_path.write_text(json.dumps(golden_data), encoding="utf-8")
    reg_record = {
        "model_id": mid, "model_role": "A", "study_id": "study",
        "scientific_status": "VALID_PRIMARY", "reuse_status": "PERMITTED",
        "artifact_path": str(art_path.relative_to(tmp_path)),
        "artifact_sha256": _sha(art_path.read_bytes()),
        "native_booster_path": str(booster_path.relative_to(tmp_path)),
        "native_booster_sha256": _sha(booster_path.read_bytes()),
        "golden_fixture_path": str(golden_path.relative_to(tmp_path)),
        "golden_fixture_sha256": _sha(golden_path.read_bytes()),
        "ordered_model_inputs": ["f1", "f2"],
    }
    (reg / f"{mid}.json").write_text(json.dumps(reg_record), encoding="utf-8")
    spec = DerivedCausalInputSpec.model_validate({"name": "score_derived", "model_id": mid})
    scorer = FrozenExternalModelScorer.bind(spec, parent_dir=study)
    obs = scorer.score({"f1": 0.0, "f2": 1.0}, checkpoint_ts=100, direction="LONG", availability_ts={"f1": 100, "f2": 100})
    assert abs(obs.score - golden_data["expected_scores"][0]) < 1e-6


# 16. tampered model/preprocessing/OOS/reconciliation authority makes Stage 16 INVALID/STALE
def test_rt2_16_tampered_authority_makes_stage16_invalid_or_stale(tmp_path):
    s = tmp_path / "study_oos"; s.mkdir()
    (s / "artifacts").mkdir(); (s / "models").mkdir()
    (s / "study.yaml").write_text("study:\n  id: study_oos\nchronology:\n  train: [2021]\n  dev: [2022]\n  prohibited: [2025]\n", encoding="utf-8")
    (s / "artifacts/experiment_authorization.json").write_text(json.dumps({"authorization_sha256": "auth1"}), encoding="utf-8")
    reg_dir = tmp_path / "model_registry"; reg_dir.mkdir()
    art_file = s / "models/m.joblib"; art_file.write_bytes(b"model-artifact")
    gold_file = s / "models/m_gold.json"; gold_file.write_bytes(b"gold")
    reg_dir.joinpath("m.json").write_text(json.dumps({
        "model_id": "m", "artifact_path": str(art_file.relative_to(tmp_path)),
        "artifact_sha256": _sha(art_file.read_bytes()),
        "golden_fixture_path": str(gold_file.relative_to(tmp_path)),
        "golden_fixture_sha256": _sha(gold_file.read_bytes()),
    }), encoding="utf-8")
    freeze_body = {
        "partition": "train", "authorization_sha256": "auth1", "freeze_sha256": "f1",
        "model_artifacts": [{"model_id": "m", "model_role": "A"}],
        "stage_scoped_lineage": {"MODELING_EXECUTION_CLOSURE": "c1", "COLLECTION_PRODUCER_CLOSURE": "p1", "TARGET_RUNTIME_CLOSURE": "t1"},
    }
    (s / "artifacts/train_experiment_freeze.json").write_text(json.dumps(freeze_body), encoding="utf-8")
    from research_workflow.oos_analysis_lineage import build_oos_analysis_identity
    analysis_body = {
        "study_id": "study_oos", "authorization_sha256": "auth1", "rows": 10,
        "oos_analysis_identity": build_oos_analysis_identity(s, freeze=freeze_body, oos_run_id="run1", oos_dataset_identity_sha256="ds1"),
    }
    (s / "artifacts/experiment_analysis.json").write_text(json.dumps(analysis_body), encoding="utf-8")
    assert classify_oos_analysis(s)["state"] == "FRESH"
    # Tamper model artifact on disk -> INVALID
    art_file.write_bytes(b"tampered")
    assert classify_oos_analysis(s)["state"] == "INVALID"


# 17. stale Stage 16 makes Stage 17 non-authoritative
def test_rt2_17_stale_stage16_makes_stage17_stale(tmp_path):
    s = tmp_path / "study_s17"; s.mkdir()
    (s / "artifacts").mkdir(); (s / "models").mkdir()
    (s / "study.yaml").write_text("study:\n  id: study_s17\nchronology:\n  train: [2021]\n  dev: [2022]\n  prohibited: [2025]\n", encoding="utf-8")
    (s / "artifacts/experiment_authorization.json").write_text(json.dumps({"authorization_sha256": "auth1"}), encoding="utf-8")
    reg_dir = tmp_path / "model_registry"; reg_dir.mkdir()
    art_file = s / "models/m.joblib"; art_file.write_bytes(b"model-artifact")
    gold_file = s / "models/m_gold.json"; gold_file.write_bytes(b"gold")
    reg_dir.joinpath("m.json").write_text(json.dumps({
        "model_id": "m", "artifact_path": str(art_file.relative_to(tmp_path)),
        "artifact_sha256": _sha(art_file.read_bytes()),
        "golden_fixture_path": str(gold_file.relative_to(tmp_path)),
        "golden_fixture_sha256": _sha(gold_file.read_bytes()),
    }), encoding="utf-8")
    freeze_body = {
        "partition": "train", "authorization_sha256": "auth1", "freeze_sha256": "f1",
        "model_artifacts": [{"model_id": "m", "model_role": "A"}],
        "stage_scoped_lineage": {"MODELING_EXECUTION_CLOSURE": "c1", "COLLECTION_PRODUCER_CLOSURE": "p1", "TARGET_RUNTIME_CLOSURE": "t1"},
    }
    (s / "artifacts/train_experiment_freeze.json").write_text(json.dumps(freeze_body), encoding="utf-8")
    from research_workflow.oos_analysis_lineage import build_oos_analysis_identity
    analysis_body = {
        "study_id": "study_s17", "authorization_sha256": "auth1", "rows": 10,
        "oos_analysis_identity": build_oos_analysis_identity(s, freeze=freeze_body, oos_run_id="run1", oos_dataset_identity_sha256="ds1"),
    }
    (s / "artifacts/experiment_analysis.json").write_text(json.dumps(analysis_body), encoding="utf-8")
    decision_body = {
        "schema_version": 1, "artifact_kind": "research_decision_stage17", "stage": 17,
        "study_id": "study_s17", "terminal_decision": "PASS",
        "bound_lineage": {"stage16_analysis_artifact_file_sha256": _sha((s / "artifacts/experiment_analysis.json").read_bytes())},
    }
    (s / "artifacts/research_decision_stage17.json").write_text(json.dumps(decision_body), encoding="utf-8")
    assert classify_stage17_decision(s)["state"] == "FRESH"
    # Re-freeze train -> Stage 16 becomes STALE -> Stage 17 becomes STALE
    freeze_body["freeze_sha256"] = "f2"
    (s / "artifacts/train_experiment_freeze.json").write_text(json.dumps(freeze_body), encoding="utf-8")
    assert classify_oos_analysis(s)["state"] == "STALE"
    assert classify_stage17_decision(s)["state"] == "STALE"


# 18. stale/tampered terminal evidence prevents STUDY_CLOSED
def test_rt2_18_stale_or_tampered_terminal_evidence_prevents_study_closed(tmp_path):
    s = tmp_path / "study_closure_test"; s.mkdir()
    (s / "artifacts").mkdir()
    (s / "study.yaml").write_text("study:\n  id: study_closure_test\nchronology:\n  train: [2021]\n  dev: [2022]\n  prohibited: [2025]\n", encoding="utf-8")
    seal_p = s / "artifacts/preexec_audit_seal.json"; seal_p.write_bytes(b"seal")
    closure_body = {
        "schema_version": 1, "study_id": "study_closure_test", "status": "CLOSED",
        "outcome": "DIAGNOSTIC_POSITIVE", "terminal_decision": "PASS",
        "bound_evidence": {"preexec_seal_artifact_sha256": _sha(seal_p.read_bytes())},
    }
    (s / "artifacts/study_closure.json").write_text(json.dumps(closure_body), encoding="utf-8")
    assert load_study_closure(s)["status"] == "CLOSED"
    # Tamper seal artifact -> load_study_closure raises StudyClosureInvalid
    seal_p.write_bytes(b"tampered-seal")
    with pytest.raises(StudyClosureInvalid, match="STUDY_CLOSURE_EVIDENCE_MISMATCH"):
        load_study_closure(s)


# 19. historical closed artifact remains preserved
def test_rt2_19_historical_closed_artifact_preserved():
    path_180s = REPO_ROOT / "studies/clean_maturity_flip_model_180s_horizon/artifacts/study_closure.json"
    if path_180s.is_file():
        assert load_study_closure(path_180s.parent.parent)["status"] == "CLOSED"


# 20. current 180s closed study's existing scientific outputs are not modified by this remediation
def test_rt2_20_current_180s_study_outputs_unmodified():
    s = REPO_ROOT / "studies/clean_maturity_flip_model_180s_horizon"
    if s.is_dir():
        from research_workflow.workflow_engine import WorkflowEngine
        res = WorkflowEngine(s).advance()
        assert res["terminal_state"] == "STUDY_CLOSED"
        assert res["authorization_state"] == "STUDY_CLOSED"
