import json
import subprocess
import sys
from pathlib import Path

from research_workflow.controller_contracts import ControllerState
from research_workflow.governed_controller import ControllerActions, GovernedStudyController, _materialize_preflight_tests, compact_card


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
