import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from research.schemas.study_spec import StudySpec
from research_workflow.controller_contracts import ControllerState
from research_workflow.governed_controller import ControllerActions, GovernedStudyController, _materialize_preflight_tests, compact_card
from research_workflow.workflow_engine import _sha


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _controller(tmp_path):
    study = tmp_path / "s"; study.mkdir(); calls = []
    composite = "a" * 64
    def compile(s): _write(s / "compiled_study.json", {"spec": {}}); calls.append("compile")
    def prepare(s): _write(s / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": composite}); calls.append("prepare")
    def readiness(s): _write(s / "audit/readiness.json", {"overall_status": "PASS"}); calls.append("readiness")
    def tests(s): _write(s / "_work/controller/test_summary.json", {"status": "PASS", "execution_composite_sha256": composite, "counts": {"passed": 1}}); calls.append("tests")
    def preflight(s): _write(s / "audit/preflight.json", {"status": "CLEAR", "execution_composite_sha256": composite}); calls.append("preflight")
    def seal(s): _write(s / "artifacts/preexec_audit_seal.json", {"ok": True}); calls.append("seal")
    actions = ControllerActions(compile=compile, prepare=prepare, readiness=readiness, tests=tests, preflight=preflight, seal=seal)
    actions.synthetic_test = True
    c = GovernedStudyController(study, actions=actions)
    c._worktree = lambda: {"path": str(tmp_path), "branch": "test", "head": "x", "dirty_paths": [], "unsafe_dirty_paths": []}
    c._fingerprints = lambda: {"execution_composite": composite if (study / "audit/frozen_execution_manifest.json").exists() else None, "current_execution_composite": composite,
                               "approved_request": None, "study_spec": None, "compiled_study": None}
    return study, c, calls, composite


def test_inspect_does_not_mutate(tmp_path):
    study, c, calls, _ = _controller(tmp_path)
    result = c.run(through="prepare", inspect=True)
    assert result["state"] == ControllerState.NEEDS_COMPILE.value and not calls and not (study / "_work").exists()


def test_audit_handoff_resume_and_seal_are_idempotent(tmp_path):
    study, c, calls, composite = _controller(tmp_path)
    result = c.run(through="seal")
    assert result["state"] == ControllerState.NEEDS_CAUSAL_AUDIT.value
    assert calls == ["compile", "prepare", "readiness", "preflight", "tests"]
    assert (study / "_work/controller/audit_packet_causal.json").is_file()
    _write(study / "audit/status.json", {"status": "CLEAR", "audited_execution_composite_sha256": composite})
    result = c.run(through="seal")
    assert result["state"] == ControllerState.NEEDS_CONTRACT_AUDIT.value
    _write(study / "audit/contract_status.json", {"status": "CLEAR", "audited_execution_composite_sha256": composite})
    result = c.run(through="seal")
    assert result["state"] == ControllerState.READY_TO_COLLECT.value and calls[-1] == "seal"
    before = list(calls); c.run(through="seal"); assert calls == before


def test_stale_prepare_reexecutes_only_downstream_chain(tmp_path):
    study, c, calls, composite = _controller(tmp_path)
    _write(study / "compiled_study.json", {}); _write(study / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": "old"})
    result = c.run(through="prepare")
    assert result["state"] == ControllerState.NEEDS_PREPARE.value and calls == ["prepare"]


def test_worktree_contamination_and_compact_output(tmp_path):
    study, c, _, _ = _controller(tmp_path)
    c._worktree = lambda: {"path": "x", "branch": "x", "head": "x", "dirty_paths": ["bad.py"], "unsafe_dirty_paths": ["bad.py"]}
    result = c.run(inspect=True)
    assert result["STATUS"] == "BLOCKED" and result["failure_packet"] is None
    line = compact_card(result)
    assert "STATUS=BLOCKED" in line and "fingerprints" not in line
    assert result["dry_run"] and not (study / "_work").exists()


def test_blocked_audit_is_not_overwritten(tmp_path):
    study, c, _, composite = _controller(tmp_path)
    for path, data in ((study / "compiled_study.json", {}), (study / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": composite}),
                       (study / "audit/readiness.json", {"overall_status": "PASS"}), (study / "_work/controller/test_summary.json", {"status": "PASS", "execution_composite_sha256": composite}),
                       (study / "audit/preflight.json", {"status": "CLEAR", "execution_composite_sha256": composite}),
                       (study / "audit/status.json", {"status": "BLOCKED", "audited_execution_composite_sha256": composite})):
        _write(path, data)
    result = c.run(through="causal_audit")
    assert result["blocker_code"] == "CAUSALITY_BLOCKER" and _read_json(study / "audit/status.json")["status"] == "BLOCKED"


def test_source_drift_invalidates_prepare_and_all_downstream(tmp_path):
    study, c, _, composite = _controller(tmp_path)
    for path, data in ((study / "compiled_study.json", {}), (study / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": composite}),
                       (study / "audit/readiness.json", {"overall_status": "PASS", "execution_composite_sha256": composite}), (study / "_work/controller/test_summary.json", {"status": "PASS", "execution_composite_sha256": composite}),
                       (study / "audit/preflight.json", {"status": "CLEAR", "execution_composite_sha256": composite}), (study / "audit/status.json", {"status": "CLEAR", "audited_execution_composite_sha256": composite}),
                       (study / "audit/contract_status.json", {"status": "CLEAR", "audited_execution_composite_sha256": composite}), (study / "artifacts/preexec_audit_seal.json", {})):
        _write(path, data)
    old = {"study_spec": "old", "execution_composite": composite, "current_execution_composite": composite}
    _write(study / "_work/controller/status.json", {"fingerprints": old})
    c._fingerprints = lambda: {"study_spec": "new", "execution_composite": composite, "current_execution_composite": composite}
    assert not c._fresh_stage("prepare", c._fingerprints())
    assert not c._fresh_stage("readiness", c._fingerprints())
    assert not c._fresh_stage("preflight", c._fingerprints())
    assert not c._fresh_stage("causal_audit", c._fingerprints())
    assert not c._fresh_stage("seal", c._fingerprints())


def test_collection_requires_explicit_partition_receipt_and_resumes(tmp_path):
    study, c, calls, composite = _controller(tmp_path)
    _write(study / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": composite})
    output = study / "runs" / "intended" / "output.json"; _write(output, {"ok": True})
    c._write_receipt("collection", {"status": "PASS", "output_artifacts": [output], "partitions": [{"id": "train-2024", "status": "PASS"}]}, c._fingerprints())
    assert c._fresh_stage("collection", c._fingerprints())
    # A smoke/day manifest alone is deliberately never a collection completion signal.
    (study / "_work/controller/receipts/collection.json").unlink()
    _write(study / "runs" / "smoke" / "status.json", {"status": "SUCCESS"})
    assert not c._fresh_stage("collection", c._fingerprints())


def test_reconcile_and_analysis_receipts_are_hash_bound(tmp_path):
    study, c, _, _ = _controller(tmp_path); out = study / "artifacts" / "x.json"; _write(out, {})
    _write(study / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": "a" * 64})
    fp = c._fingerprints()
    c._write_receipt("reconcile", {"status": "PASS", "output_artifacts": [out]}, fp)
    c._write_receipt("analyze", {"status": "PASS", "output_artifacts": [out]}, fp)
    assert c._receipt_current("reconcile", fp) and c._receipt_current("analyze", fp)


def test_materializes_authoritative_preflight_test_outcome(tmp_path):
    study = tmp_path / "s"; study.mkdir(); composite = "b" * 64
    _write(study / "audit/preflight.json", {"audit_ready": True, "diagnostic_mode": False, "required_checks": ["CAUSAL_INVARIANTS"], "check_outcomes": {"CAUSAL_INVARIANTS": "PASSED"}, "execution_composite_sha256": composite})
    assert _materialize_preflight_tests(study)["execution_composite_sha256"] == composite
    _write(study / "audit/preflight.json", {"audit_ready": True, "diagnostic_mode": False, "required_checks": ["CAUSAL_INVARIANTS"], "check_outcomes": {"CAUSAL_INVARIANTS": "FAILED"}, "execution_composite_sha256": composite})
    import pytest
    with pytest.raises(RuntimeError, match="PREFLIGHT_TEST_EVIDENCE"):
        _materialize_preflight_tests(study)


def _read_json(path): return json.loads(path.read_text(encoding="utf-8"))


def _legacy_handoff(tmp_path, monkeypatch):
    """A minimal, fully-bound legacy TRAIN handoff; no collection input is opened."""
    study, controller, calls, composite = _controller(tmp_path)
    controller.repo_root = tmp_path.resolve()
    controller._manifest_is_tracked = lambda _: True
    authored = {
        "study": {"id": "s", "type": "flip_prediction", "description": "legacy"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state"},
        "target": {"type": "flip", "horizon_seconds": 300},
        "features": {"source": "canonical_verified_definition_universe"},
        "chronology": {"train": [2021], "dev": [2022], "prohibited": [2025, 2026]},
        "execution": {"runtime": "nautilustrader"},
    }
    spec_sha = StudySpec.model_validate(authored).compute_sha256()
    (study / "study.yaml").write_text(yaml.safe_dump(authored), encoding="utf-8")
    _write(study / "compiled_study.json", {"spec_sha256": spec_sha})
    _write(study / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": composite})
    _write(study / "artifacts/preexec_audit_seal.json", {"seal": "fixture"})
    target = study / "_work/train/targets.parquet"; target.parent.mkdir(parents=True)
    pq.write_table(pa.table({"label": [1.0]}), target)
    manifest = {
        "study_id": "s", "frozen_at_phase": "PHASE_C_COMPLETE", "next_phase": "PHASE_D_MODELING",
        "study_status": "READY_FOR_PHASE_D_MODELING", "phase_d_authorized": False, "recollection_required": False,
        "oos_accessed": False, "spec_sha256": spec_sha, "seal_composite_sha256": composite,
        "authoritative_train_target": {"path": "s/_work/train/targets.parquet", "sha256": _sha(target), "row_count": 1, "columns": ["label"]},
        "verified_artifacts": {
            "compiled": {"path": "s/compiled_study.json", "sha256": _sha(study / "compiled_study.json")},
            "seal": {"path": "s/artifacts/preexec_audit_seal.json", "sha256": _sha(study / "artifacts/preexec_audit_seal.json")},
        },
    }
    _write(study / "artifacts/resume_manifest.json", manifest)
    monkeypatch.setattr("research_workflow.study_spec_compiler.compile_approved_request",
                        lambda study, write=False: {"ok": False, "terminal": "SEMANTIC_DECISION_REQUIRED"})
    monkeypatch.setattr("research_workflow.seal.verify_preexec_audit_seal", lambda _: True)
    return study, controller, calls, composite, manifest


def test_legacy_handoff_a_valid_returns_phase_d_without_collection(tmp_path, monkeypatch):
    study, controller, calls, _, _ = _legacy_handoff(tmp_path, monkeypatch)
    controller.actions.collection = lambda _: calls.append("collection")
    card = controller.run(through="analyze", dry_run=True)
    assert card["state"] == ControllerState.PHASE_D_MODELING_READY_NOT_AUTHORIZED.value
    assert card["stage"] == "phase_handoff" and card["next_state"] == "PHASE_D_MODELING"
    assert card["blocker_code"] == "SEMANTIC_BLOCKER" and calls == []


def test_legacy_handoff_b_bad_artifact_falls_through(tmp_path, monkeypatch):
    study, controller, _, _, manifest = _legacy_handoff(tmp_path, monkeypatch)
    manifest["verified_artifacts"]["compiled"]["sha256"] = "0" * 64
    _write(study / "artifacts/resume_manifest.json", manifest)
    assert controller.run(through="compile", dry_run=True)["state"] == ControllerState.NEEDS_COMPILE.value


def test_legacy_handoff_c_seal_mismatch_falls_through(tmp_path, monkeypatch):
    _, controller, _, _, _ = _legacy_handoff(tmp_path, monkeypatch)
    def stale_seal(_):
        raise RuntimeError("stale seal")
    monkeypatch.setattr("research_workflow.seal.verify_preexec_audit_seal", stale_seal)
    assert controller.run(through="compile", dry_run=True)["state"] == ControllerState.NEEDS_COMPILE.value


def test_legacy_handoff_d_current_composite_mismatch_falls_through(tmp_path, monkeypatch):
    _, controller, _, composite, _ = _legacy_handoff(tmp_path, monkeypatch)
    controller._fingerprints = lambda: {"execution_composite": composite, "current_execution_composite": "b" * 64}
    assert controller.run(through="compile", dry_run=True)["state"] == ControllerState.NEEDS_COMPILE.value


def test_legacy_handoff_e_oos_access_rejected_without_opening_data(tmp_path, monkeypatch):
    study, controller, _, _, manifest = _legacy_handoff(tmp_path, monkeypatch)
    manifest["oos_accessed"] = True
    _write(study / "artifacts/resume_manifest.json", manifest)
    assert controller.run(through="compile", dry_run=True)["state"] == ControllerState.NEEDS_COMPILE.value


def test_legacy_handoff_f_modern_study_with_missing_lineage_still_compiles(tmp_path, monkeypatch):
    _, controller, _, _, _ = _legacy_handoff(tmp_path, monkeypatch)
    monkeypatch.setattr("research_workflow.study_spec_compiler.compile_approved_request",
                        lambda study, write=False: {"ok": True, "spec_sha256": "fixture"})
    assert controller.run(through="compile", dry_run=True)["state"] == ControllerState.NEEDS_COMPILE.value


def test_legacy_handoff_g_remains_non_executable_until_authorized(tmp_path, monkeypatch):
    _, controller, calls, _, _ = _legacy_handoff(tmp_path, monkeypatch)
    controller.actions.collection = lambda _: calls.append("collection")
    card = controller.run(through="collection", dry_run=False)
    assert card["state"] == ControllerState.PHASE_D_MODELING_READY_NOT_AUTHORIZED.value
    assert card["blocker_code"] == "SEMANTIC_BLOCKER"
    assert calls == []


def test_synthetic_git_worktree_resume_and_verbose_child(tmp_path):
    """Acceptance C/D/E: no model polling, full child log, and artifact-based resume."""
    root = tmp_path / "repo"; root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    study = root / "studies" / "s"; study.mkdir(parents=True)
    (root / ".gitignore").write_text("studies/s/_work/\n", encoding="utf-8")
    (study / "study.yaml").write_text("id: s\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True); subprocess.run(["git", "commit", "-m", "fixture"], cwd=root, check=True, capture_output=True)
    actions = ControllerActions(compile=lambda _: None); actions.synthetic_test = True
    c = GovernedStudyController(study, actions=actions, owned_paths=("studies/s",), repo_root=root, max_runtime=5, stale_progress_timeout=5)
    c._fingerprints = lambda: {"execution_composite": None, "current_execution_composite": None, "approved_request": None, "study_spec": None, "compiled_study": None}
    # A child can be verbose without adding any output to the controller's compact surface.
    result = c.run_subprocess("synthetic", [sys.executable, "-c", "print('verbose child evidence')"])
    assert result["status"] == "completed" and "verbose child evidence" in Path(result["log_file"]).read_text(encoding="utf-8")
    # Existing compile artifact means an interrupted invocation resumes at PREPARE.
    _write(study / "compiled_study.json", {})
    card = c.run(through="prepare", inspect=True)
    assert card["state"] == ControllerState.NEEDS_PREPARE.value
