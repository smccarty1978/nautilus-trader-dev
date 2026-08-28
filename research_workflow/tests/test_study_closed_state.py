"""Terminal STUDY_CLOSED workflow state (research_workflow/study_closure.py).

A valid artifacts/study_closure.json with status == "CLOSED" short-circuits advance()
before any TRAIN/OOS authorization or execution branch, without mutating prior artifacts.
"""
import json
from pathlib import Path

import pytest
import yaml

from research_workflow.workflow_engine import WorkflowActions, WorkflowEngine


def _request(study: Path) -> dict:
    return {"study_spec": {
        "study": {"id": study.name, "type": "flip_prediction", "description": "x"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state", "session": "RTH"},
        "target": {"type": "flip", "event": "regime_flip", "direction": "bullish", "horizon_seconds": 60},
        "chronology": {"train": [2021], "dev": [2022], "prohibited": [2025, 2026]},
        "features": {"source": "canonical_verified_definition_universe", "instances": []},
        "model": {}, "execution": {"runtime": "nautilustrader"}}}


def _actions() -> WorkflowActions:
    def put(name, payload):
        def f(s):
            p = s / name; p.parent.mkdir(exist_ok=True, parents=True); p.write_text(json.dumps(payload)); return payload
        return f

    def prepared(s):
        (s / "compiled_study.json").write_text(json.dumps({"spec": {}}))
        (s / "audit").mkdir(exist_ok=True)
        try:
            from scripts.resolve_execution_manifest import resolve_execution_manifest
            composite = resolve_execution_manifest(s)[0]
        except Exception:
            composite = "fixture"
        (s / "audit/frozen_execution_manifest.json").write_text(
            json.dumps({"frozen_execution_composite_sha256": composite}))
        return {}

    def audit(name):
        def f(s):
            p = s / name; p.parent.mkdir(exist_ok=True, parents=True)
            payload = {"verdict": "CLEAR", "audited_execution_composite_sha256":
                       json.loads((s / "audit/frozen_execution_manifest.json").read_text())["frozen_execution_composite_sha256"]}
            p.write_text(json.dumps(payload)); return payload
        return f

    return WorkflowActions(
        reconcile=lambda s: {}, prepare=prepared,
        readiness=put("audit/readiness.json", {"overall_status": "PASS"}),
        preflight=put("audit/preflight.json", {"verdict": "CLEAR"}),
        causal=audit("audit/status.json"), contract=audit("audit/contract_status.json"),
        seal=put("artifacts/preexec_audit_seal.json", {"seal_status": "LOCKED"}))


def _study_at_train_gate(tmp_path: Path, *, name: str = "s") -> Path:
    study = tmp_path / name
    study.mkdir()
    (study / "research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    result = WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"
    return study


def _closure(study: Path, **overrides) -> dict:
    body = {
        "schema_version": 1, "study_id": study.name, "status": "CLOSED",
        "outcome": "DIAGNOSTIC_NEGATIVE", "terminal_decision": "no_signal",
    }
    body.update(overrides)
    return body


def _write_closure(study: Path, body: dict) -> None:
    (study / "artifacts").mkdir(exist_ok=True, parents=True)
    (study / "artifacts" / "study_closure.json").write_text(json.dumps(body, indent=2))


# 1 -----------------------------------------------------------------------------
def test_closed_short_circuits_train_authorization(tmp_path):
    study = _study_at_train_gate(tmp_path)
    _write_closure(study, _closure(study))
    result = WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "STUDY_CLOSED"
    assert result["next_deterministic_action"] is None
    assert result["authorization_state"] == "STUDY_CLOSED"


# 2 -----------------------------------------------------------------------------
def test_closed_short_circuits_oos_branches(tmp_path):
    study = _study_at_train_gate(tmp_path)
    # make the study otherwise land on an OOS branch
    (study / "artifacts" / "train_experiment_freeze.json").write_text(
        json.dumps({"partition": "train", "authorization_sha256": "x"}))
    (study / "artifacts" / "experiment_authorization.json").write_text(
        json.dumps({"schema_version": 1, "study_id": study.name}))
    _write_closure(study, _closure(study))
    result = WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "STUDY_CLOSED"
    assert result["next_deterministic_action"] is None


# 3 -----------------------------------------------------------------------------
def test_closure_outcome_and_terminal_decision_surfaced_exactly(tmp_path):
    study = _study_at_train_gate(tmp_path)
    _write_closure(study, _closure(study, outcome="DIAGNOSTIC_POSITIVE",
                                  terminal_decision="ship_it"))
    result = WorkflowEngine(study, actions=_actions()).advance()
    sc = result["study_closure"]
    assert sc["study_id"] == study.name
    assert sc["status"] == "CLOSED"
    assert sc["outcome"] == "DIAGNOSTIC_POSITIVE"
    assert sc["terminal_decision"] == "ship_it"
    assert sc["closure_artifact_path"] == "artifacts/study_closure.json"
    assert isinstance(sc["closure_artifact_sha256"], str) and len(sc["closure_artifact_sha256"]) == 64


# 4 -----------------------------------------------------------------------------
def test_mismatched_study_id_does_not_close(tmp_path):
    study = _study_at_train_gate(tmp_path)
    _write_closure(study, _closure(study, study_id="a_different_study"))
    result = WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "STUDY_CLOSURE_INVALID"
    assert "STUDY_ID_MISMATCH" in result["blockers"][0]["detail"]


# 5 -----------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "{ not json",
    json.dumps({"schema_version": 1, "study_id": "s", "status": "CLOSED"}),          # missing outcome/decision
    json.dumps({"schema_version": 9, "study_id": "s", "status": "CLOSED",
                "outcome": "x", "terminal_decision": "y"}),                          # unsupported schema
    json.dumps({"schema_version": 1, "study_id": "s", "status": "DRAFT",
                "outcome": "x", "terminal_decision": "y"}),                          # not CLOSED
    json.dumps({"schema_version": 1, "study_id": "s", "status": "CLOSED",
                "outcome": "  ", "terminal_decision": "y"}),                         # blank outcome
])
def test_malformed_closure_fails_visibly(tmp_path, bad):
    study = _study_at_train_gate(tmp_path)
    (study / "artifacts" / "study_closure.json").write_text(bad)
    result = WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "STUDY_CLOSURE_INVALID"
    assert result["blockers"] and result["blockers"][0]["detail"]


# 6 -----------------------------------------------------------------------------
def test_absence_of_closure_preserves_existing_behavior(tmp_path):
    study = _study_at_train_gate(tmp_path)
    assert not (study / "artifacts" / "study_closure.json").exists()
    result = WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"


# 7 -----------------------------------------------------------------------------
def test_historical_authorization_does_not_override_closed(tmp_path):
    study = _study_at_train_gate(tmp_path)
    from research_workflow.experiment import authorize_experiment
    authorize_experiment(study)  # valid TRAIN authorization artifact
    assert (study / "artifacts" / "experiment_authorization.json").is_file()
    _write_closure(study, _closure(study))
    result = WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "STUDY_CLOSED"
    assert result["authorization_state"] == "STUDY_CLOSED"


# 8 -----------------------------------------------------------------------------
def test_closure_detection_does_not_rewrite_prior_seals_or_artifacts(tmp_path):
    study = _study_at_train_gate(tmp_path)
    from research_workflow.experiment import authorize_experiment
    authorize_experiment(study)
    _write_closure(study, _closure(study))

    watched = {
        p: (p.read_bytes(), p.stat().st_mtime)
        for p in [study / "artifacts" / "preexec_audit_seal.json",
                  study / "audit" / "frozen_execution_manifest.json",
                  study / "audit" / "status.json",
                  study / "audit" / "contract_status.json",
                  study / "artifacts" / "experiment_authorization.json",
                  study / "artifacts" / "study_closure.json"]
    }
    WorkflowEngine(study, actions=_actions()).advance()
    for p, (content, mtime) in watched.items():
        assert p.read_bytes() == content, f"{p.name} content changed"
        assert p.stat().st_mtime == mtime, f"{p.name} mtime changed"


# 9 -----------------------------------------------------------------------------
def test_ordinary_non_closed_study_unaffected(tmp_path):
    study = tmp_path / "ordinary"
    study.mkdir()
    (study / "research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    result = WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"
    assert "study_closure" not in result


# terminal-decision validation against declared terminal_decisions --------------
def test_terminal_decision_must_be_declared_when_study_declares_them(tmp_path):
    study = tmp_path / "d"
    study.mkdir()
    req = _request(study)
    req["terminal_decisions"] = {"P5": "NO_MEANINGFUL_SIGNAL", "ABORT": "GOVERNANCE_FAILURE"}
    (study / "research_decision.yaml").write_text(yaml.safe_dump(req))
    WorkflowEngine(study, actions=_actions()).advance()

    _write_closure(study, _closure(study, terminal_decision="P5_NO_MEANINGFUL_SIGNAL"))
    assert WorkflowEngine(study, actions=_actions()).advance()["terminal_state"] == "STUDY_CLOSED"

    _write_closure(study, _closure(study, terminal_decision="P99_MADE_UP"))
    r = WorkflowEngine(study, actions=_actions()).advance()
    assert r["terminal_state"] == "STUDY_CLOSURE_INVALID"
    assert "UNDECLARED" in r["blockers"][0]["detail"]
