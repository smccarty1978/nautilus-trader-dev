"""RT-13 -- a governed OOS analysis artifact binds its full lineage and can go STALE.

``analyze_results`` bound only study_id / authorization_sha256 / rows, so the artifact
stayed apparently authoritative after the exact TRAIN freeze / model / OOS run changed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import research_workflow.analysis as analysis_mod
from research_workflow.analysis import analyze_results
from research_workflow.experiment import authorize_experiment
from research_workflow.oos_analysis_lineage import classify_oos_analysis


@pytest.fixture(autouse=True)
def _stub_oos_gate(monkeypatch):
    """assert_oos_open's TRAIN-freeze / closure gate is exercised by its own tests and is
    DO-NOT-TOUCH here. Stub it to hand analyze_results the freeze payload so these tests
    isolate the RT-13 lineage-identity + classifier logic."""

    def _fake(study_path):
        return json.loads((Path(study_path) / "artifacts" / "train_experiment_freeze.json").read_text())

    monkeypatch.setattr(analysis_mod, "assert_oos_open", _fake)


def _study(tmp_path: Path) -> Path:
    s = tmp_path / "s"
    s.mkdir()
    (s / "study.yaml").write_text(
        "study:\n  id: s\nchronology:\n  train: [2021]\n  dev: [2022]\n  prohibited: [2025, 2026]\n"
    )
    (s / "artifacts").mkdir()
    (s / "audit").mkdir()
    authorize_experiment(s)
    return s


def _freeze(s: Path, *, internal="freeze-v1", modeling="modeling-closure-v1"):
    auth = json.loads((s / "artifacts" / "experiment_authorization.json").read_text())
    reg_dir = s.parent / "model_registry"
    reg_dir.mkdir(exist_ok=True)
    art_file = s / "models" / "m-123.joblib"
    art_file.parent.mkdir(exist_ok=True)
    art_file.write_bytes(b"dummy-model-artifact")
    gold_file = s / "models" / "m-123_golden.json"
    gold_file.write_bytes(b"dummy-golden")
    import hashlib
    reg_dir.joinpath("m-123.json").write_text(json.dumps({
        "model_id": "m-123",
        "artifact_path": str(art_file.relative_to(s.parent)),
        "artifact_sha256": hashlib.sha256(art_file.read_bytes()).hexdigest(),
        "golden_fixture_path": str(gold_file.relative_to(s.parent)),
        "golden_fixture_sha256": hashlib.sha256(gold_file.read_bytes()).hexdigest(),
    }))
    (s / "artifacts" / "train_experiment_freeze.json").write_text(json.dumps({
        "partition": "train",
        "authorization_sha256": auth["authorization_sha256"],
        "freeze_sha256": internal,
        "model_artifacts": [{"model_id": "m-123", "model_role": "A"}],
        "stage_scoped_lineage": {
            "COLLECTION_PRODUCER_CLOSURE": "collection-v1",
            "TARGET_RUNTIME_CLOSURE": "target-v1",
            "MODELING_EXECUTION_CLOSURE": modeling,
        },
    }))


_FRAME = pd.DataFrame({
    "target": [0, 1, 0, 1, 1, 0, 1, 0],
    "score_A": [0.1, 0.9, 0.2, 0.8, 0.7, 0.3, 0.6, 0.4],
    "regime_direction": [1, 1, -1, -1, 1, -1, 1, -1],
})


def _run_analysis(s):
    return analyze_results(
        s, _FRAME, score_columns={"A": "score_A"}, target_column="target",
        oos_run_id="oos-run-001",
    )


def test_fresh_after_generation(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    _run_analysis(s)
    verdict = classify_oos_analysis(s)
    assert verdict["state"] == "FRESH", verdict


def test_none_when_no_artifact(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    assert classify_oos_analysis(s) is None


def test_identity_block_has_the_required_bindings(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    result = _run_analysis(s)
    ident = result["oos_analysis_identity"]
    for k in ("study_id", "train_experiment_freeze_sha256", "model_ids",
              "modeling_execution_closure_sha256", "oos_authorization_sha256",
              "oos_run_id", "oos_dataset_identity_sha256",
              "analysis_implementation_sha256", "identity_sha256"):
        assert ident.get(k), f"missing binding: {k}"
    assert ident["model_ids"] == ["m-123"]


def test_stale_when_train_freeze_bytes_change(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    _run_analysis(s)
    _freeze(s, internal="freeze-v2")  # re-freeze
    verdict = classify_oos_analysis(s)
    assert verdict["state"] == "STALE"
    assert any("freeze" in r.lower() for r in verdict["reasons"])


def test_stale_when_modeling_closure_moves(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    _run_analysis(s)
    _freeze(s, modeling="modeling-closure-v2")
    verdict = classify_oos_analysis(s)
    assert verdict["state"] == "STALE"
    assert any("modeling execution closure" in r for r in verdict["reasons"])


def test_invalid_when_freeze_deleted(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    _run_analysis(s)
    (s / "artifacts" / "train_experiment_freeze.json").unlink()
    assert classify_oos_analysis(s)["state"] == "INVALID"


def test_invalid_when_identity_block_edited(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    _run_analysis(s)
    art = s / "artifacts" / "experiment_analysis.json"
    body = json.loads(art.read_text())
    body["oos_analysis_identity"]["model_ids"] = ["tampered"]
    art.write_text(json.dumps(body))
    assert classify_oos_analysis(s)["state"] == "INVALID"


def test_workflow_state_surfaces_the_classification(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    _run_analysis(s)
    _freeze(s, internal="freeze-v2")
    from research_workflow.workflow_engine import WorkflowEngine

    # _state() is the common state assembler advance() returns; it must carry the RT-13
    # classification so a STALE analysis is never presented as authoritative.
    state = WorkflowEngine(s)._state("COMPLETE")
    assert state["oos_analysis_state"]["state"] == "STALE"


def test_workflow_state_none_without_analysis(tmp_path):
    s = _study(tmp_path)
    _freeze(s)
    from research_workflow.workflow_engine import WorkflowEngine

    assert WorkflowEngine(s)._state("COMPLETE")["oos_analysis_state"] is None


# --------------------------------------------------------------------------- #
# Fix 3 -- TRAIN-only Stage 17 decisions must be anchored, never blindly FRESH
# --------------------------------------------------------------------------- #
def _stage17(s: Path, body: dict) -> None:
    (s / "artifacts" / "research_decision_stage17.json").write_text(json.dumps(
        {"schema_version": 1, "artifact_kind": "research_decision_stage17", "stage": 17,
         "study_id": s.name, "terminal_decision": "PASS", **body}))


def test_stage17_empty_bound_lineage_is_invalid(tmp_path):
    from research_workflow.oos_analysis_lineage import classify_stage17_decision
    s = _study(tmp_path)
    _freeze(s)
    _stage17(s, {"bound_lineage": {}})
    v = classify_stage17_decision(s)
    assert v["state"] == "INVALID" and "empty bound_lineage" in v["reasons"][0]
    _stage17(s, {})  # no bound_lineage key at all
    assert classify_stage17_decision(s)["state"] == "INVALID"


def test_train_only_stage17_missing_required_anchor_is_invalid(tmp_path):
    from research_workflow.oos_analysis_lineage import classify_stage17_decision
    s = _study(tmp_path)
    _freeze(s, internal="freeze-x", modeling="mec-x")
    # everything but modeling_execution_closure
    _stage17(s, {"bound_lineage": {
        "train_freeze_sha256": "freeze-x", "model_ids": ["m-123"],
        "authorization_sha256": "a"}})
    v = classify_stage17_decision(s)
    assert v["state"] == "INVALID" and "modeling_execution_closure" in v["reasons"][0]


def test_train_only_stage17_with_minimum_anchors_is_fresh(tmp_path):
    from research_workflow.oos_analysis_lineage import classify_stage17_decision
    s = _study(tmp_path)
    _freeze(s, internal="freeze-x", modeling="mec-x")
    _stage17(s, {"bound_lineage": {
        "train_freeze_sha256": "freeze-x",
        "model_ids": ["m-123"],
        "modeling_execution_closure_sha256": "mec-x",
        "authorization_sha256": "a"}})
    assert classify_stage17_decision(s)["state"] == "FRESH"


def test_train_only_stage17_goes_stale_when_train_freeze_rewritten(tmp_path):
    from research_workflow.oos_analysis_lineage import classify_stage17_decision
    s = _study(tmp_path)
    _freeze(s, internal="freeze-x", modeling="mec-x")
    _stage17(s, {"bound_lineage": {
        "train_freeze_sha256": "freeze-x",
        "model_ids": ["m-123"],
        "modeling_execution_closure_sha256": "mec-x",
        "authorization_sha256": "a"}})
    assert classify_stage17_decision(s)["state"] == "FRESH"
    _freeze(s, internal="freeze-y", modeling="mec-x")  # re-freeze TRAIN
    v = classify_stage17_decision(s)
    assert v["state"] == "STALE" and any("TRAIN freeze changed" in r for r in v["reasons"])
