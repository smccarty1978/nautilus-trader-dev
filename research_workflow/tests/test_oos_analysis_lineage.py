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
