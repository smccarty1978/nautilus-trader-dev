"""Unit tests for the supervisor's pure pieces: packet/result staleness binding, provider capability detection,
typed state derivation on a synthetic study directory, decision-policy resolution."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

from research_workflow.supervisor import derive as D  # noqa: E402
from research_workflow.supervisor import packets as P  # noqa: E402
from research_workflow.supervisor import providers as PR  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"; r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(r), check=True)
    for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
        subprocess.run(["git", "config", k, v], cwd=str(r), check=True)
    (r / "studies" / "s1").mkdir(parents=True)
    (r / "studies" / "s1" / "study.yaml").write_text("study: {id: s1}\n", encoding="utf-8")
    (r / "studies" / "s1" / "research_decision.yaml").write_text("study_id: s1\nterminal_decisions: {}\nautonomy_decisions: {deterministic_defect: auto_fix}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(r), check=True); subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(r), check=True)
    return r


def _packet(tmp_path: Path, repo: Path, *, read_only_type: str = "CAUSAL_AUDIT"):
    study = repo / "studies" / "s1"
    return P.build_packet(task_id="001_t", session_type=read_only_type, study_id="s1", study_dir=study, study_worktree=repo, repo_root=repo, provider="scripted",
                          identity={"agent": "scripted", "session_id": "sess-1"}, result_path=tmp_path / "res" / "001_t.result.json", results_dir=tmp_path / "res",
                          task="audit", read_files=["WORKFLOW.md"], stop_conditions=["done"], extra={}, auditor="lookahead-auditor:001_t")


def test_packet_roundtrip_and_hash_binding(tmp_path):
    repo = _repo(tmp_path)
    body = _packet(tmp_path, repo)
    p = P.render_packet(body, tmp_path / "p.md")
    assert p.stat().st_size < 6000
    back = P.read_packet(p)
    assert back["packet_sha256"] == body["packet_sha256"] and back["study_contract_sha256"] == P.study_contract_sha256(repo / "studies" / "s1")
    text = p.read_text(encoding="utf-8").replace('"task": "audit"', '"task": "tampered"')
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="PACKET_HASH_MISMATCH"):
        P.read_packet(p)


def test_result_card_binding_fields_are_validated(tmp_path):
    repo = _repo(tmp_path)
    body = _packet(tmp_path, repo)
    out = P.write_result_card(body, status="DONE", session_id="sess-1", report=str(tmp_path / "r.md"))
    card = json.loads(out.read_text(encoding="utf-8"))
    ok, reason, field = P.validate_result(card, body, current_contract_sha256=body["study_contract_sha256"], current_plan_sha256=None, current_branch="main")
    assert ok, reason
    for f in P.BINDING_FIELDS:
        bad = dict(card); bad[f] = "x"
        ok, reason, field = P.validate_result(bad, body)
        assert not ok and field == f and reason.startswith("STALE_WORKER_RESULT"), (f, reason)
    bad = dict(card); bad["session_id"] = "other"
    assert P.validate_result(bad, body)[2] == "session_id"
    # a read-only worker whose study contract changed underneath it is stale even with a perfect card
    ok, reason, field = P.validate_result(card, body, current_contract_sha256="changed")
    assert not ok and field == "study_contract_sha256"
    ok, reason, field = P.validate_result(card, body, current_branch="study/other")
    assert not ok and field == "expected_branch"
    bad = dict(card); bad["protected_data_accessed"] = True
    assert P.validate_result(bad, body)[2] == "protected_data_accessed"


def test_provider_probe_uses_only_installed_flags():
    rec = PR.probe_provider("scripted")
    assert rec["AVAILABLE"] and rec["HEADLESS_SUPPORTED"]
    att = PR.probe_provider("antigravity")
    assert att["ATTENDED_SUPPORTED"] and not att["HEADLESS_SUPPORTED"]
    fake = {"provider": "claude", "AVAILABLE": True, "HEADLESS_SUPPORTED": False, "WRITE_SUPPORTED": False, "READ_ONLY_SUPPORTED": False, "binary": "claude", "flags": {"-p": False}}
    with pytest.raises(PR.ProviderError, match="PROVIDER_CAPABILITY_UNAVAILABLE"):
        PR.build_command("claude", packet_path=Path("p.md"), worktree=Path("."), read_only=False, results_dir=Path("."), session_id="s", probe=fake)
    fake2 = {**fake, "HEADLESS_SUPPORTED": True, "WRITE_SUPPORTED": True, "READ_ONLY_SUPPORTED": True,
             "flags": {"-p": True, "--output-format": True, "--dangerously-skip-permissions": True, "--allowedTools": True, "--max-turns": False, "--add-dir": False}}
    cmd = PR.build_command("claude", packet_path=Path("p.md"), worktree=Path("."), read_only=False, results_dir=Path("."), session_id="s", probe=fake2)
    assert cmd[:2] == ["claude", "-p"] and "--dangerously-skip-permissions" in cmd and "--max-turns" not in cmd and "--add-dir" not in cmd
    ro = PR.build_command("claude", packet_path=Path("p.md"), worktree=Path("."), read_only=True, results_dir=Path("."), session_id="s", probe=fake2)
    assert "--allowedTools" in ro and "--dangerously-skip-permissions" not in ro
    real = PR.probe_provider("claude")
    if real["AVAILABLE"]:
        assert real["probe_output_sha256"] and real["CLI_VERSION"]
        for flag, present in real["flags"].items():
            assert isinstance(present, bool)


def test_decision_resolves_semantic_gaps():
    gaps = [{"kind": "SEMANTIC_DECISION_REQUIRED", "where": "chronology.tuning_folds", "message": "declare", "detail": {}}]
    assert not D.decision_resolves({"terminal_decisions": {}}, gaps)
    assert D.decision_resolves({"terminal_decisions": {"tuning_folds": "monthly"}}, gaps)
    assert D.decision_resolves({"autonomy_decisions": {"fold_policy": "x"}}, [{"kind": "SEMANTIC_DECISION_REQUIRED", "where": "model", "detail": {"decision_key": "fold_policy"}}])


def test_derive_walks_the_artifact_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("NT_RESEARCH_SUPERVISOR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NT_RESEARCH_CONFIG", str(tmp_path / "cfg.yaml"))
    (tmp_path / "cfg.yaml").write_text(f"catalog_roots: []\nleases_dir: {(tmp_path / 'leases').as_posix()}\n", encoding="utf-8")
    repo = _repo(tmp_path)
    study = repo / "studies" / "s1"
    ident = {"user": "u", "host": "h", "owner": "u@h", "agent": "scripted", "session_id": "sup"}
    st = {"study_id": "s1", "study_worktree": str(repo), "execute_authorized": True, "consumed_handoffs": [], "user_decision": None}
    assert D.derive(st, supervisor_identity=ident)["code"] == "NO_SPEC"
    (study / "CAPABILITY_GAP_HANDOFF.json").write_text(json.dumps({"gaps": [{"kind": "MISSING_CAPABILITY", "where": "triggers.add"}], "proposed_chore_topic": "t",
                                                                   "suggested_platform_files": ["research_workflow/host/triggers.py"]}), encoding="utf-8")
    d = D.derive(st, supervisor_identity=ident)
    assert d["code"] == "CAPABILITY_GAP" and d["gap_kinds"] == ["MISSING_CAPABILITY"] and d["evidence"]["topic"] == "t"
    st["consumed_handoffs"] = [d["handoff_sha256"]]
    assert D.derive(st, supervisor_identity=ident)["code"] == "NO_SPEC"
    (study / "compiled_plan.json").write_text("{}", encoding="utf-8")
    d = D.derive(st, supervisor_identity=ident)
    assert d["code"] == "COMPILED" and d["through"] == "seal"
    work = study / "_work" / "controller"; work.mkdir(parents=True)
    from research_workflow.lifecycle_v2 import spec_sha256
    fp = {"study_spec": spec_sha256(study), "compiled_plan": P.sha256_file(study / "compiled_plan.json")}
    (work / "status.json").write_text(json.dumps({"STATUS": "OK", "state": "NEEDS_CAUSAL_AUDIT", "stage": "causal_audit", "artifact": "pkt", "fingerprints": fp}), encoding="utf-8")
    (study / "audit").mkdir(); (study / "audit" / "frozen_execution_manifest.json").write_text(json.dumps({"frozen_execution_composite_sha256": "abc"}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "NEEDS_CAUSAL_AUDIT"
    (study / "audit" / "status.json").write_text(json.dumps({"verdict": "CLEAR", "audited_execution_composite_sha256": "abc"}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "CONTROLLER_STEP"
    (study / "audit" / "status.json").write_text(json.dumps({"verdict": "BLOCKED", "audited_execution_composite_sha256": "abc"}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "AUDIT_BLOCKER"
    (work / "status.json").write_text(json.dumps({"STATUS": "BLOCKED", "state": "NEEDS_PREFLIGHT", "stage": "preflight", "blocker_code": "RUNTIME_FAILURE", "fingerprints": fp}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "DETERMINISTIC_BLOCKER"
    (work / "status.json").write_text(json.dumps({"STATUS": "BLOCKED", "state": "READY_TO_FIT", "stage": "fit", "blocker_code": "RUNTIME_FAILURE", "fingerprints": fp}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "EXECUTION_BLOCKER"
    (work / "status.json").write_text(json.dumps({"STATUS": "OK", "state": "READY_TO_SMOKE", "stage": "seal", "fingerprints": fp}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "READY_TO_EXECUTE"
    st["execute_authorized"] = False
    assert D.derive(st, supervisor_identity=ident)["code"] == "EXECUTION_NOT_AUTHORIZED"
    (work / "status.json").write_text(json.dumps({"STATUS": "OK", "state": "READY_TO_CLOSE", "stage": "analyze", "fingerprints": fp}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "READY_FOR_ANALYSIS"
    (study / "artifacts").mkdir(); (study / "artifacts" / "analysis_decision.json").write_text(json.dumps({"outcome": "o", "terminal_decision": "t"}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "ANALYSIS_DECIDED"
    (study / "study.yaml").write_text("study: {id: s1, tier: 2}\n", encoding="utf-8")   # spec changed under the card -> the card is stale
    assert D.derive(st, supervisor_identity=ident)["code"] == "COMPILED"
    (work / "run.lock").write_text(json.dumps({"pid": os.getpid(), "through": "analyze"}), encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "RUNNING"
    st["user_decision"] = {"code": "AUTHORIZATION_AMBIGUITY", "answered": False}
    assert D.derive(st, supervisor_identity=ident)["code"] == "USER_DECISION_REQUIRED"
    (study / "artifacts" / "study_closure.json").write_text("{}", encoding="utf-8")
    assert D.derive(st, supervisor_identity=ident)["code"] == "STUDY_CLOSED"
