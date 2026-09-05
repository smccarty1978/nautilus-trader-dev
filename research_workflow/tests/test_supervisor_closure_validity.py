"""DEV-09 (2026-09-05, Supervisor V1 validation): the supervisor treated a study_closure.json the platform REJECTED
(undeclared terminal_decision) as the study's terminal state. A closure counts only when research_workflow.study_closure
accepts it; an invalid one is recovered (removed + close re-run) when the decision is admissible, else it is a
RESEARCH_CONTRACT_CONFLICT card; the analysis packet names the declared vocabulary."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_workflow.supervisor import derive as D  # noqa: E402

IDENT = {"user": "u", "host": "h", "owner": "u@h", "agent": "scripted", "session_id": "sup"}


def _study(tmp_path, monkeypatch, declared: str = "  SUPERVISOR_V1_VALIDATED: 'accepted'\n  SUPERVISOR_V1_NOT_VALIDATED: 'rejected'\n"):
    monkeypatch.setenv("NT_RESEARCH_SUPERVISOR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NT_RESEARCH_CONFIG", str(tmp_path / "cfg.yaml"))
    (tmp_path / "cfg.yaml").write_text(f"catalog_roots: []\nleases_dir: {(tmp_path / 'leases').as_posix()}\n", encoding="utf-8")
    repo = tmp_path / "r"; study = repo / "studies" / "s1"; (study / "artifacts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    (study / "study.yaml").write_text("study: {id: s1}\n", encoding="utf-8")
    (study / "research_decision.yaml").write_text("study_id: s1\nterminal_decisions:\n" + declared, encoding="utf-8")
    (study / "compiled_plan.json").write_text("{}", encoding="utf-8")
    st = {"study_id": "s1", "study_worktree": str(repo), "execute_authorized": True, "consumed_handoffs": [], "user_decision": None}
    return repo, study, st


def test_invalid_closure_is_not_terminal(tmp_path, monkeypatch):
    repo, study, st = _study(tmp_path, monkeypatch)
    (study / "artifacts" / "study_closure.json").write_text(json.dumps({"schema_version": 1, "study_id": "s1", "status": "CLOSED", "outcome": "X",
                                                                        "terminal_decision": "UNDECLARED", "platform": "v2", "plan_sha256": "p", "closed_at_utc": "t",
                                                                        "bound_evidence": {}}), encoding="utf-8")
    (study / "artifacts" / "analysis_decision.json").write_text(json.dumps({"outcome": "X", "terminal_decision": "UNDECLARED"}), encoding="utf-8")
    d = D.derive(st, supervisor_identity=IDENT)
    assert d["code"] == "CLOSURE_INVALID" and "TERMINAL_DECISION_UNDECLARED" in (d["evidence"]["error"] or "") and d["evidence"]["decision_check"]["ok"] is False
    assert d["evidence"]["decision_check"]["declared"] == ["SUPERVISOR_V1_NOT_VALIDATED", "SUPERVISOR_V1_VALIDATED"]
    # the decision becomes admissible (contract fixed on the study branch): recovery is now allowed
    (study / "artifacts" / "analysis_decision.json").write_text(json.dumps({"outcome": "X", "terminal_decision": "SUPERVISOR_V1_VALIDATED"}), encoding="utf-8")
    d = D.derive(st, supervisor_identity=IDENT)
    assert d["code"] == "CLOSURE_INVALID" and d["evidence"]["decision_check"]["ok"] is True


def test_analysis_decided_carries_the_vocabulary_check(tmp_path, monkeypatch):
    repo, study, st = _study(tmp_path, monkeypatch)
    work = study / "_work" / "controller"; work.mkdir(parents=True)
    from research_workflow.lifecycle_v2 import spec_sha256
    from research_workflow.supervisor import packets as P
    fp = {"study_spec": spec_sha256(study), "compiled_plan": P.sha256_file(study / "compiled_plan.json")}
    (work / "status.json").write_text(json.dumps({"STATUS": "OK", "state": "READY_TO_CLOSE", "stage": "analyze", "fingerprints": fp}), encoding="utf-8")
    monkeypatch.setattr(D, "_current_platform_composite", lambda study, wt: None)
    (study / "artifacts" / "analysis_decision.json").write_text(json.dumps({"outcome": "X", "terminal_decision": "NOPE"}), encoding="utf-8")
    d = D.derive(st, supervisor_identity=IDENT)
    assert d["code"] == "ANALYSIS_DECIDED" and d["evidence"]["decision_check"]["ok"] is False
    (study / "artifacts" / "analysis_decision.json").write_text(json.dumps({"outcome": "X", "terminal_decision": "SUPERVISOR_V1_VALIDATED_accepted"}), encoding="utf-8")
    d = D.derive(st, supervisor_identity=IDENT)
    assert d["evidence"]["decision_check"]["ok"] is True          # KEY_VALUE form is accepted by the platform validator


def test_core_routes_undeclared_decision_to_a_contract_conflict_card_and_recovers_a_declared_one(tmp_path, monkeypatch):
    from research_workflow.supervisor import state as S
    from research_workflow.supervisor.core import Supervisor
    repo, study, st = _study(tmp_path, monkeypatch)
    full = S.new_state(study_id="s1", question_path=None, question_sha256=None, platform_commit=None, provider="scripted", study_branch="study/s1",
                       study_worktree=str(repo), repo_root=str(repo), execute_authorized=True, options={"controller_command": [sys.executable, "-c", "print('close')"]})
    S.save_state(full)
    closure = study / "artifacts" / "study_closure.json"
    closure.write_text(json.dumps({"schema_version": 1, "study_id": "s1", "status": "CLOSED", "outcome": "X", "terminal_decision": "UNDECLARED", "platform": "v2",
                                   "plan_sha256": "p", "closed_at_utc": "t", "bound_evidence": {}}), encoding="utf-8")
    (study / "artifacts" / "analysis_decision.json").write_text(json.dumps({"outcome": "X", "terminal_decision": "UNDECLARED"}), encoding="utf-8")
    sup = Supervisor("s1")
    card = sup.tick()
    assert card["action"] == "USER_DECISION_REQUIRED" and sup.state["user_decision"]["code"] == "RESEARCH_CONTRACT_CONFLICT" and closure.exists()
    # the contract is fixed on the study branch; the operator answers; the supervisor removes the rejected closure and re-runs close ONCE
    (study / "artifacts" / "analysis_decision.json").write_text(json.dumps({"outcome": "X", "terminal_decision": "SUPERVISOR_V1_VALIDATED"}), encoding="utf-8")
    sup.decide({"acknowledged": True})
    sup = Supervisor("s1"); card = sup.tick()
    assert card["action"] == "JOB_LAUNCHED" and card["through"] == "close" and not closure.exists()
    assert any(e["kind"] == "INVALID_CLOSURE_REMOVED" for e in S.read_events("s1"))
    assert sup.state["attempts"]["CLOSURE_RECOVERY"] == 1


def test_analysis_packet_names_the_declared_vocabulary(tmp_path, monkeypatch):
    from research_workflow.supervisor import state as S
    from research_workflow.supervisor.core import Supervisor
    repo, study, st = _study(tmp_path, monkeypatch)
    full = S.new_state(study_id="s1", question_path=None, question_sha256=None, platform_commit=None, provider="scripted", study_branch="study/s1",
                       study_worktree=str(repo), repo_root=str(repo), execute_authorized=True,
                       options={"scripted_worker": [sys.executable, "-c", "import time; time.sleep(3)"]})
    S.save_state(full)
    sup = Supervisor("s1")
    card = sup._launch_analysis({"code": "READY_FOR_ANALYSIS", "evidence": {}})
    assert card["action"] == "WORKER_LAUNCHED"
    packet = Path(sup.state["active_worker"]["packet_path"]).read_text(encoding="utf-8")
    assert "SUPERVISOR_V1_VALIDATED" in packet and "RESEARCH_CONTRACT_CONFLICT" in packet
    from research_workflow.supervisor.procs import kill_tree
    kill_tree(int(sup.state["active_worker"]["pid"]))
