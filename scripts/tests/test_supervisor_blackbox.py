"""Research Supervisor V1 black-box proof (packet section 8 + hardening addendum section 11).

Everything runs on a throwaway canonical repo, a machine-local config under tmp, the golden SYNTHETIC study
(no catalog, no data replay) and the ``scripted`` provider (no model tokens). The controller jobs are the real
:class:`V2StudyController` launched DETACHED by the supervisor; the workers are real fresh processes that write
their result cards through ``research study result``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_workflow.tests import supervisor_support as SUP  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


# ---------------------------------------------------------------------------- fixtures / helpers
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    box = SUP.make_repo(tmp_path)
    for k, v in box["env"].items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("NT_SUP_TEST_PLAN", raising=False)
    q = tmp_path / "question.md"
    q.write_text("Does a synthetic level regime predict a +1 ATR move before -1 ATR within 60s?\n", encoding="utf-8")
    box["question"] = q
    return box


def _options(**over):
    base = {"scripted_worker": SUP.scripted_worker_command(), "controller_command": SUP.controller_command(), "merge_gate_cap_check": None,
            "max_workers": 2, "max_heavy_jobs": 2, "worker_timeout_s": 300, "job_timeout_s": 900}
    base.update(over)
    return base


def _wait_pid(pid: int, timeout_s: float) -> None:
    from research_workflow.supervisor.procs import pid_alive
    t0 = time.time()
    while pid_alive(pid):
        if time.time() - t0 > timeout_s:
            raise AssertionError(f"pid {pid} still alive after {timeout_s}s")
        time.sleep(0.2)


def drive(study_id: str, *, max_ticks: int = 200, timeout_s: float = 900.0, restart_each_tick: bool = False, stop_when=None, stop_before_wait=None):
    """Tick until terminal / user decision; between ticks wait for the active process (a test must never poll an AI, but
    it may wait on a pid). Records the invariant 'no AI alive while a deterministic job runs'. ``stop_before_wait`` is
    evaluated right after the tick, BEFORE waiting on the launched process (to interpose while a job/worker is live)."""
    from research_workflow.supervisor.core import Supervisor
    stats = {"ai_alive_during_job": 0, "ticks": 0, "actions": []}
    sup = Supervisor(study_id)
    t0 = time.time()
    for _ in range(max_ticks):
        if restart_each_tick:
            sup = Supervisor(study_id)   # a fresh process would do exactly this: reload state, re-derive
        card = sup.tick(); stats["ticks"] += 1; stats["actions"].append(card["action"])
        st = sup.state
        if stop_before_wait and stop_before_wait(sup):
            break
        if st.get("active_job"):
            if st.get("active_worker"):
                stats["ai_alive_during_job"] += 1
            _wait_pid(int(st["active_job"]["pid"]), timeout_s)
        elif st.get("active_worker") and st["active_worker"].get("pid"):
            _wait_pid(int(st["active_worker"]["pid"]), timeout_s)
        if st.get("terminal") or st.get("user_intervention_required") or st.get("stopped"):
            break
        if stop_when and stop_when(sup):
            break
        assert time.time() - t0 < timeout_s, "drive timed out"
    return sup, stats


def _start(box, *, plan: dict, execute_authorized: bool = True, study_id: str = "sup_blackbox", **opts):
    from research_workflow.supervisor.core import Supervisor
    os.environ["NT_SUP_TEST_PLAN"] = json.dumps(plan)
    sup = Supervisor.start(question=box["question"], repo_root=box["repo"], study_id=study_id, provider="scripted", execute_authorized=execute_authorized,
                           options=_options(**opts))
    return sup


# ---------------------------------------------------------------------------- the black box
def test_one_prompt_to_study_closed(sandbox):
    """question -> design (gap) -> chore claim + capability worker -> merge gate (auto_if_green) -> fresh design -> controller to
    NEEDS_CAUSAL_AUDIT -> causal worker -> contract worker -> detached smoke..analyze with NO worker alive -> analysis worker -> close."""
    sup = _start(sandbox, plan={"gap_first": True, "auto_merge": True})
    sid = sup.study_id
    sup, stats = drive(sid)
    st = sup.state
    assert st.get("terminal") and st["derived_state"] == "STUDY_CLOSED", (st.get("derived_state"), st.get("user_decision"), stats["actions"])
    study = Path(st["study_worktree"]) / "studies" / sid
    assert (study / "artifacts" / "study_closure.json").is_file()
    # worker chain: exactly these roles, each a fresh process with its own session id
    hist = st["worker_history"]
    types = [h["session_type"] for h in hist]
    assert types == ["STUDY_DESIGN_COMPILE", "CAPABILITY_IMPLEMENTATION", "STUDY_DESIGN_COMPILE", "CAUSAL_AUDIT", "CONTRACT_AUDIT", "ANALYSIS_DECISION"], types
    assert [h["status"] for h in hist] == ["BLOCKED", "DONE", "DONE", "DONE", "DONE", "DONE"]
    assert len({h["session_id"] for h in hist}) == len(hist) == st["counters"]["workers_launched"] == 6
    assert st["counters"]["max_packet_bytes"] < 12_000, st["counters"]["max_packet_bytes"]
    assert st["counters"]["user_interventions"] == 0 and st.get("user_decision") is None
    assert stats["ai_alive_during_job"] == 0
    # deterministic jobs: seal x3 (compile..causal packet, contract packet, seal), analyze, close
    throughs = [e["through"] for e in _events(sid) if e["kind"] == "JOB_LAUNCHED"]
    assert throughs == ["seal", "seal", "seal", "analyze", "close"], throughs
    # capability flow landed on main with --no-ff, the claim is released, main was merged into the study
    repo = sandbox["repo"]
    assert (repo / SUP.CAPABILITY_MARKER).is_file()
    log = subprocess.run(["git", "log", "--oneline", "--first-parent", "-3"], cwd=str(repo), capture_output=True, text=True).stdout
    assert "merge(chore/" in log
    from research_workflow.workspace import read_chores
    assert all(c["state"] != "live" for c in read_chores())
    assert (Path(st["study_worktree"]) / SUP.CAPABILITY_MARKER).is_file()
    # read-only auditors wrote OUTSIDE the study; the supervisor copied + ingested (packet 11.C)
    assert (study / "audit" / "pass_01.md").is_file() and (study / "audit" / "contract_pass_01.md").is_file()
    causal = json.loads((study / "audit" / "status.json").read_text()); contract = json.loads((study / "audit" / "contract_status.json").read_text())
    assert causal["verdict"] == "CLEAR" and contract["verdict"] == "CLEAR" and causal["auditor"] != contract["auditor"]
    assert causal["audit_report_path"].replace("\\", "/") == "audit/pass_01.md"   # committed WITH the study, not machine-local
    results_dir = sup.dir / "results"
    assert len(list(results_dir.glob("*.report.md"))) == 2 and not list(study.rglob("*.result.json"))
    # scientific meaning lives in the study, not only in supervisor state
    assert json.loads((study / "artifacts" / "analysis_decision.json").read_text())["outcome"] == "SYNTHETIC_FLOW_COMPLETE"
    from research_workflow.study_closure import load_study_closure
    assert load_study_closure(study)["outcome"] == "SYNTHETIC_FLOW_COMPLETE"
    assert (study / "_work" / "handoff" / "SESSION_HANDOFF.json").is_file()
    # status card reflects the terminal state; a further tick is a no-op
    from research_workflow.supervisor.core import Supervisor
    assert Supervisor(sid).status()["derived_state"] == "STUDY_CLOSED"
    assert Supervisor(sid).tick()["action"] == "TERMINAL"


def test_semantic_decision_not_covered_stops_then_decide_resumes(sandbox):
    sup = _start(sandbox, plan={"semantic_first": True}, study_id="sup_semantic")
    sid = sup.study_id
    sup, stats = drive(sid)
    st = sup.state
    assert st["user_intervention_required"] and st["user_decision"]["code"] == "SCIENTIFIC_SEMANTIC_DECISION_REQUIRED"
    assert st["counters"]["user_interventions"] == 1 and Path(st["user_decision"]["card_path"]).is_file()
    assert sup.tick()["action"] == "USER_DECISION_REQUIRED" and st["active_worker"] is None   # progression stopped, nothing launched
    from research_workflow.supervisor.core import Supervisor
    out = Supervisor(sid).decide({"terminal_decisions": {"direction_convention": "regime.dir"}})
    assert out["applied"]["study_file"].endswith("USER_DECISION_01.json")
    study = Path(st["study_worktree"]) / "studies" / sid
    assert (study / "_work" / "handoff" / "USER_DECISION_01.json").is_file()   # the answer lives in the study
    sup, _ = drive(sid, stop_when=lambda s: (Path(s.state["study_worktree"]) / "studies" / sid / "compiled_plan.json").is_file())
    assert (study / "compiled_plan.json").is_file()
    assert sup.state["counters"]["user_interventions"] == 1


def test_adopt_existing_study_resumes_at_contract_audit_without_rerun(sandbox):
    """Packet 11.D: progress to NEEDS_CONTRACT_AUDIT, delete supervisor state, adopt -> next action is CONTRACT_AUDIT, no earlier stage re-runs."""
    sup = _start(sandbox, plan={}, study_id="sup_adopt")
    sid = sup.study_id
    # drive until the contract auditor has been launched (its card completes, but is never consumed: the state dir is deleted)
    sup, _ = drive(sid, stop_when=lambda s: (s.state.get("active_worker") or {}).get("session_type") == "CONTRACT_AUDIT")
    assert sup.state["derived_state"] == "NEEDS_CONTRACT_AUDIT" and sup.state["counters"]["jobs_launched"] == 2
    study = Path(sup.state["study_worktree"]) / "studies" / sid
    assert (study / "audit" / "status.json").is_file() and not (study / "audit" / "contract_status.json").exists()
    stamp_before = {p.name: p.stat().st_mtime for p in (study / "audit").glob("*.json")}
    from research_workflow.workspace import release_lease
    release_lease(sid, owner=sup.identity["owner"], identity=sup.identity)   # the old supervisor session ends and releases its writer lease
    shutil.rmtree(sup.dir)
    from research_workflow.supervisor.core import Supervisor
    adopted = Supervisor.adopt(study_dir=study, repo_root=sandbox["repo"], provider="scripted", execute_authorized=True, options=_options())
    assert adopted.state["adopted"] and adopted.state["derived_state"] == "NEEDS_CONTRACT_AUDIT" and adopted.state["next_action"] == "launch CONTRACT_AUDIT"
    card = adopted.tick()
    assert card["action"] == "WORKER_LAUNCHED" and card["session_type"] == "CONTRACT_AUDIT" and adopted.state["counters"]["jobs_launched"] == 0
    _wait_pid(int(adopted.state["active_worker"]["pid"]), 120)
    assert {p.name: p.stat().st_mtime for p in (study / "audit").glob("*.json") if p.name in stamp_before} == stamp_before


def test_adopt_with_foreign_live_lease_waits(sandbox):
    sup = _start(sandbox, plan={}, study_id="sup_lease")
    sid = sup.study_id
    from research_workflow.workspace import read_leases
    lease = next(l for l in read_leases() if l["study_id"] == sid)
    p = Path(lease["lease_path"]) if lease.get("lease_path") else Path(os.environ["NT_RESEARCH_SUPERVISOR_HOME"]) / "leases" / f"{sid}.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["owner_agent"] = "codex"; raw["owner_session_id"] = "foreign-session"; raw["holder"] = {"pid": os.getpid(), "kind": "cli", "renewed_at_utc": raw["created_at_utc"]}
    p.write_text(json.dumps(raw), encoding="utf-8")   # simulate another live writer (this test's own pid keeps it live)
    shutil.rmtree(sup.dir)
    from research_workflow.supervisor.core import Supervisor
    adopted = Supervisor.adopt(study_dir=Path(sup.state["study_worktree"]) / "studies" / sid, repo_root=sandbox["repo"], provider="scripted", options=_options())
    assert adopted.state["derived_state"] == "WAIT_STUDY_LEASE"
    assert adopted.tick()["action"] == "WAIT_STUDY_LEASE" and adopted.state["active_worker"] is None
    assert json.loads(p.read_text(encoding="utf-8"))["owner_session_id"] == "foreign-session"   # never force-released


def test_crash_and_resume_derives_from_artifacts(sandbox):
    """Kill the supervisor while a worker runs and while the controller runs; restart -> state derived, no completed stage re-run,
    a card completed offline is consumed, a stale worker pid is reaped."""
    sup = _start(sandbox, plan={"worker_sleep_s": 2.0}, study_id="sup_crash")
    sid = sup.study_id
    card = sup.tick()
    assert card["action"] == "WORKER_LAUNCHED"
    pid = int(sup.state["active_worker"]["pid"])
    del sup                                                    # "crash" while the worker runs
    _wait_pid(pid, 120)                                        # the worker completes its card while the supervisor is offline
    from research_workflow.supervisor.core import Supervisor
    s2 = Supervisor(sid)
    s2.tick()                                                  # consumes the offline-completed card, then derives COMPILED
    assert s2.state["worker_history"][-1]["status"] == "DONE" and s2.state["active_worker"] is None
    if not s2.state.get("active_job"):
        s2.tick()
    assert s2.state["active_job"] and s2.state["active_job"]["through"] == "seal"
    jpid = int(s2.state["active_job"]["pid"])
    del s2                                                     # "crash" while the controller runs
    s3 = Supervisor(sid)
    c = s3.tick()
    assert c["action"] == "WAITING_JOB" and s3.state["active_worker"] is None
    _wait_pid(jpid, 600)
    s3 = Supervisor(sid)
    s3.tick()                                                  # reaps the job, derives NEEDS_CAUSAL_AUDIT, launches the auditor
    assert s3.state["active_job"] is None and s3.state["last_completed_deterministic_artifact"]["state"] == "NEEDS_CAUSAL_AUDIT"
    assert s3.state["counters"]["jobs_launched"] == 1          # compile..causal packet ran exactly once
    # stale worker pid (dead, no card) is reaped as FAILED and counted
    aw = s3.state["active_worker"]; assert aw and aw["session_type"] == "CAUSAL_AUDIT"
    _wait_pid(int(aw["pid"]), 120)
    Path(aw["result_path"]).unlink()                           # pretend it died before writing its card
    aw["pid"] = 999_999_999
    from research_workflow.supervisor import state as S
    S.save_state(s3.state)
    s4 = Supervisor(sid); s4.tick()                              # reaps the stale pid as FAILED, then relaunches ONE bounded retry
    assert s4.state["worker_history"][-1]["status"] == "FAILED" and s4.state["worker_history"][-1]["reason"] == "RESULT_CARD_MISSING"
    assert s4.state["attempts"][aw["attempt_key"]] == 2 and not s4.state["user_intervention_required"]
    assert s4.state["active_worker"]["session_type"] == "CAUSAL_AUDIT" and s4.state["active_worker"]["session_id"] != aw["session_id"]
    _wait_pid(int(s4.state["active_worker"]["pid"]), 120)


def test_capability_merged_offline_is_detected_from_git(sandbox):
    """Without platform_merge: auto_if_green the gate stops for approval (default). While it waits, a human merges the chore
    branch by hand; on resume the supervisor detects the merge from git and never merges twice."""
    sup = _start(sandbox, plan={"gap_first": True}, study_id="sup_offline")
    sid = sup.study_id
    sup, _ = drive(sid)
    assert sup.state["user_decision"]["code"] == "DESTRUCTIVE_ACTION_REQUIRES_APPROVAL"
    cap = sup.state["active_capability"]; assert cap["status"] == "implemented" and cap["merge_gate"]["green"] and cap["merge_gate"]["policy"] != "auto_if_green"
    subprocess.run(["git", "merge", "--no-ff", cap["chore_branch"], "-m", "merged by a human while the supervisor was offline"], cwd=str(sandbox["repo"]), check=True, capture_output=True)
    from research_workflow.supervisor.core import Supervisor
    Supervisor(sid).decide({"approve": True})
    s2 = Supervisor(sid); card = s2.tick()
    assert card["action"] == "CAPABILITY_COMPLETE", card
    ev = [e for e in _events(sid) if e["kind"] == "CAPABILITY_MERGED"]
    assert len(ev) == 1 and ev[-1].get("detected_from_git") is True
    log = subprocess.run(["git", "log", "--format=%s", "--first-parent"], cwd=str(sandbox["repo"]), capture_output=True, text=True).stdout.splitlines()
    assert sum("merged by a human" in l for l in log) == 1 and not any(l.startswith("merge(chore/") for l in log)


def test_stale_worker_result_is_refused(sandbox):
    sup = _start(sandbox, plan={"worker_sleep_s": 0}, study_id="sup_stale")
    sid = sup.study_id
    sup.tick(); aw = sup.state["active_worker"]; _wait_pid(int(aw["pid"]), 120)
    card = json.loads(Path(aw["result_path"]).read_text(encoding="utf-8"))
    card["source_commit"] = "0" * 40                            # tamper one binding field
    Path(aw["result_path"]).write_text(json.dumps(card), encoding="utf-8")
    from research_workflow.supervisor.core import Supervisor
    s2 = Supervisor(sid); s2.tick()
    last = s2.state["worker_history"][-1]
    assert last["status"] == "FAILED" and last["reason"].startswith("STALE_WORKER_RESULT") and last["field"] == "source_commit"
    assert s2.state["attempts"][aw["attempt_key"]] == 1


def test_execution_not_authorized_asks_once_and_decide_resumes(sandbox):
    sup = _start(sandbox, plan={}, execute_authorized=False, study_id="sup_auth")
    sid = sup.study_id
    sup, _ = drive(sid)
    assert sup.state["user_decision"]["code"] == "AUTHORIZATION_AMBIGUITY" and sup.state["counters"]["user_interventions"] == 1
    from research_workflow.supervisor.core import Supervisor
    Supervisor(sid).decide({"execute_authorized": True})
    s2 = Supervisor(sid); card = s2.tick()
    assert card["action"] == "JOB_LAUNCHED" and card["through"] == "analyze" and card["heavy"] is True
    _wait_pid(int(s2.state["active_job"]["pid"]), 600)


# ---------------------------------------------------------------------------- resources (11.A, 11.E)
def test_main_merge_lock_serializes_concurrent_merges(sandbox):
    repo = sandbox["repo"]
    for b in ("chore/a", "chore/b"):
        subprocess.run(["git", "checkout", "-q", "-b", b], cwd=str(repo), check=True)
        (repo / f"{b.split('/')[1]}.txt").write_text(b, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True); subprocess.run(["git", "commit", "-q", "-m", b], cwd=str(repo), check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=str(repo), check=True)
    cmd = [sys.executable, str(ROOT / "research_workflow" / "tests" / "supervisor_support.py"), "merge_under_lock", "--repo", str(repo), "--hold-s", "1.0", "--branch"]
    procs = [subprocess.Popen([*cmd, b], cwd=str(ROOT), stdout=subprocess.PIPE, text=True) for b in ("chore/a", "chore/b")]
    outs = [json.loads(p.communicate(timeout=120)[0].strip().splitlines()[-1]) for p in procs]
    assert all("merged" in o for o in outs), outs
    log = subprocess.run(["git", "log", "--format=%s", "--first-parent"], cwd=str(repo), capture_output=True, text=True).stdout.splitlines()
    assert log[:2] == ["merge chore/b", "merge chore/a"] or log[:2] == ["merge chore/a", "merge chore/b"]
    assert not (repo / ".git" / "MERGE_HEAD").exists() and (repo / "a.txt").is_file() and (repo / "b.txt").is_file()
    from research_workflow.supervisor.state import locks_root
    assert not (locks_root() / "main_merge.lock").exists()


def test_resource_slots_are_machine_wide_and_dead_pid_slots_are_reclaimed(sandbox):
    from research_workflow.supervisor import resources as R
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (R.slots_dir("workers")).mkdir(parents=True, exist_ok=True)
        (R.slots_dir("workers") / "0.slot").write_text(json.dumps({"pid": holder.pid, "kind": "workers", "study_id": "other", "task_id": "t"}), encoding="utf-8")
        sup = _start(sandbox, plan={}, study_id="sup_slots", max_workers=1)
        card = sup.tick()
        assert card["action"] == "WAIT_RESOURCE" and sup.state["active_worker"] is None and sup.state["counters"]["workers_launched"] == 0
    finally:
        holder.kill(); holder.wait()
    card = sup.tick()                                          # the holder pid is dead -> its slot is reclaimed
    assert card["action"] == "WORKER_LAUNCHED"
    _wait_pid(int(sup.state["active_worker"]["pid"]), 120)
    sup.tick()
    assert R.slot_status()["workers"] == []                    # released on consumption


def _events(sid: str):
    from research_workflow.supervisor.state import read_events
    return read_events(sid)


def _job_launches(sid: str, through: str) -> int:
    return sum(1 for e in _events(sid) if e["kind"] == "JOB_LAUNCHED" and e.get("through") == through)


# ---------------------------------------------------------------------------- the defects the first real validation found (2026-09-05)
def _detach_real_loop(sid: str):
    """The REAL detached loop (`scripts/research_supervisor.py supervise loop --study <id>`, DEV-01 argv) from this repository,
    ticking the sandbox study through the machine-local home the fixture exported."""
    from research_workflow.supervisor.cli import _detach_loop
    out = _detach_loop(ROOT, sid, grace_s=3.0)
    assert out["loop_alive"] is True and "blocker_code" not in out, out
    assert out["command"][2:4] == ["supervise", "loop"], out["command"]
    return int(out["loop_pid"])


def _wait_until(pred, timeout_s: float, what: str) -> None:
    t0 = time.time()
    while not pred():
        if time.time() - t0 > timeout_s:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.25)


def test_detached_loop_argv_ticks_and_stop_kills_only_the_loop(sandbox):
    """DEV-01 / DEV-01b / DEV-07 black-box: the argv `supervise start` detaches parses and the loop TICKS (a dead loop with
    STATUS OK was the first defect); `supervise stop` ends the loop process only -- the worker it spawned survives and its
    card is consumed on resume without a relaunch."""
    from research_workflow.supervisor.core import Supervisor
    from research_workflow.supervisor.procs import pid_alive
    sup = _start(sandbox, plan={"worker_sleep_s": 6.0}, study_id="sup_loop")
    sid = sup.study_id
    loop_pid = _detach_real_loop(sid)
    try:
        _wait_until(lambda: (Supervisor(sid).state.get("active_worker") or {}).get("pid"), 60, "the detached loop to launch the design worker")
        st = Supervisor(sid).state
        assert st["counters"]["ticks"] >= 1 and st["counters"]["workers_launched"] == 1
        worker_pid = int(st["active_worker"]["pid"])
        assert pid_alive(worker_pid), "the scripted worker (sleeping 6s) must still be running"
        out = Supervisor(sid).stop()
        assert out["loop_killed"] is True and out["worker_pid"] == worker_pid and out["worker_alive"] is True
        _wait_until(lambda: not pid_alive(loop_pid), 10, "the loop process to die")
        assert pid_alive(worker_pid), "`supervise stop` must not kill the worker the loop spawned (DEV-07)"
        _wait_pid(worker_pid, 120)                                # the worker completes its card while no supervisor is alive
        s2 = Supervisor(sid); card = s2.resume()                  # resume = reconcile: the completed card is consumed, nothing relaunched
        hist = s2.state["worker_history"]
        assert hist[-1]["task_id"] == st["active_worker"]["task_id"] and hist[-1]["status"] == "DONE"
        assert s2.state["counters"]["workers_launched"] == 1 and card["action"] == "JOB_LAUNCHED" and card["through"] == "seal"
        _wait_pid(int(s2.state["active_job"]["pid"]), 600)
    finally:
        from research_workflow.supervisor.procs import kill_pid
        kill_pid(loop_pid)


def test_stop_during_analyze_job_survives_and_resume_reconciles_without_rerun(sandbox):
    """DEV-07 + resume reconciliation black-box on the REAL detached loop and the REAL controller: the loop launches the
    heavy analyze job; `supervise stop` kills the loop only; the job runs to completion with no supervisor alive; a fresh
    loop reconciles the completed card and never launches analyze again; the study closes."""
    from research_workflow.supervisor.core import Supervisor
    from research_workflow.supervisor.procs import pid_alive
    sup = _start(sandbox, plan={}, study_id="sup_stopjob")
    sid = sup.study_id
    # drive in-process to the sealed, authorized state; stop right after the analyze job is launched (do not wait on it)
    sup, stats = drive(sid, stop_before_wait=lambda s: (s.state.get("active_job") or {}).get("through") == "analyze")
    job = sup.state["active_job"]; assert job and job["through"] == "analyze" and job["heavy"] is True
    job_pid = int(job["pid"]); assert pid_alive(job_pid)
    ticks_before = int(sup.state["counters"]["ticks"])
    loop_pid = _detach_real_loop(sid)                            # a real loop now babysits the job (WAITING_JOB ticks)
    try:
        _wait_until(lambda: int(Supervisor(sid).state["counters"]["ticks"]) > ticks_before, 60, "the detached loop to tick")
        out = Supervisor(sid).stop()
        assert out["loop_killed"] is True and out["job_pid"] == job_pid and out["job_alive"] is True
        _wait_until(lambda: not pid_alive(loop_pid), 10, "the loop to die")
        assert pid_alive(job_pid), "the detached analyze job must survive `supervise stop` (DEV-07)"
        assert Supervisor(sid).state["stopped"] is True and Supervisor(sid).tick()["action"] == "STOPPED"   # a stopped supervisor launches nothing
        _wait_pid(job_pid, 900)                                   # the controller finishes with NO supervisor and NO AI alive
        launches_before = _job_launches(sid, "analyze")
        s2 = Supervisor(sid); card = s2.resume()                  # what the CLI's `supervise resume` loop does on its first tick
        fin = [e for e in _events(sid) if e["kind"] == "JOB_FINISHED" and e.get("through") == "analyze"]
        assert fin and fin[-1]["fresh_card"] is True and fin[-1]["state"] == "READY_TO_CLOSE", fin
        assert _job_launches(sid, "analyze") == launches_before == 1, "resume must reconcile the completed job, never relaunch it"
        assert card["action"] == "WORKER_LAUNCHED" and card["session_type"] == "ANALYSIS_DECISION"
    finally:
        from research_workflow.supervisor.procs import kill_pid
        kill_pid(loop_pid)
    sup, stats2 = drive(sid)
    assert sup.state["terminal"] and sup.state["derived_state"] == "STUDY_CLOSED"
    assert _job_launches(sid, "analyze") == 1 and _job_launches(sid, "close") == 1
    assert stats["ai_alive_during_job"] == 0 and stats2["ai_alive_during_job"] == 0


def test_rejected_closure_is_never_terminal_and_close_validates_before_persisting(sandbox):
    """DEV-08 / DEV-09 black-box on the real controller: an analysis decision outside the declared vocabulary never reaches
    close (RESEARCH_CONTRACT_CONFLICT); the controller's close REFUSES to persist an undeclared closure; a stray invalid
    closure on disk is never terminal and is recovered once the decision is admissible."""
    from research_workflow.supervisor.core import Supervisor
    from research_workflow.study_closure import load_study_closure
    sup = _start(sandbox, plan={"declare_vocab": True, "undeclared_decision": True}, study_id="sup_closure")
    sid = sup.study_id
    sup, _ = drive(sid)
    st = sup.state
    study = Path(st["study_worktree"]) / "studies" / sid
    assert "PLATFORM_V2_FLOW_PROVEN" in (study / "research_decision.yaml").read_text(encoding="utf-8")
    assert st["user_intervention_required"] and st["user_decision"]["code"] == "RESEARCH_CONTRACT_CONFLICT", (st["derived_state"], st.get("user_decision"))
    assert _job_launches(sid, "close") == 0 and not (study / "artifacts" / "study_closure.json").exists() and not st.get("terminal")
    # the controller itself validates BEFORE persisting: an undeclared decision leaves no closure behind (DEV-08)
    cmd = [str(t).replace("{study}", str(study)).replace("{through}", "close") for t in SUP.controller_command()]
    r = subprocess.run([*cmd, "--execute-authorized", "--closure-outcome", "X", "--closure-decision", "NOT_IN_THE_DECLARED_VOCABULARY"],
                       cwd=str(st["study_worktree"]), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    last = json.loads(r.stdout.strip().splitlines()[-1])
    assert last["STATUS"] == "BLOCKED" and not (study / "artifacts" / "study_closure.json").exists(), (last, r.stderr[-800:])
    # a stray INVALID closure (what a pre-DEV-08 close left behind) is never terminal
    (study / "artifacts" / "study_closure.json").write_text(json.dumps({"schema_version": 1, "study_id": sid, "status": "CLOSED", "outcome": "X",
                                                                        "terminal_decision": "NOT_IN_THE_DECLARED_VOCABULARY", "platform": "v2", "plan_sha256": "p",
                                                                        "closed_at_utc": "t", "bound_evidence": {}}), encoding="utf-8")
    Supervisor(sid).decide({"acknowledged": True})
    s2 = Supervisor(sid); card = s2.tick()
    assert s2.state["derived_state"] == "CLOSURE_INVALID" and card["action"] == "USER_DECISION_REQUIRED" and s2.state["user_decision"]["code"] == "RESEARCH_CONTRACT_CONFLICT"
    assert not s2.state.get("terminal") and (study / "artifacts" / "study_closure.json").exists()
    # the decision is corrected on the study branch (declared label); the supervisor removes the rejected closure and re-runs close ONCE
    dec_path = study / "artifacts" / "analysis_decision.json"
    dec = json.loads(dec_path.read_text(encoding="utf-8")); dec["terminal_decision"] = "PLATFORM_V2_FLOW_PROVEN"
    dec_path.write_text(json.dumps(dec, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(st["study_worktree"]), check=True); subprocess.run(["git", "commit", "-q", "-m", "fix decision"], cwd=str(st["study_worktree"]), check=True)
    Supervisor(sid).decide({"acknowledged": True})
    sup, _ = drive(sid)
    assert sup.state["terminal"] and sup.state["derived_state"] == "STUDY_CLOSED"
    assert any(e["kind"] == "INVALID_CLOSURE_REMOVED" for e in _events(sid)) and _job_launches(sid, "close") == 1
    assert load_study_closure(study)["terminal_decision"] == "PLATFORM_V2_FLOW_PROVEN"


@pytest.mark.parametrize("mode", ["spec", "platform"])
def test_stale_controller_card_forces_reseal_never_an_audit(sandbox, monkeypatch, mode):
    """DEV-06 black-box: a controller card whose fingerprints no longer match the study spec (`spec`) or whose recorded
    execution composite differs from what the platform compiles now (`platform`) is stale -- the supervisor re-runs the
    controller to seal and never launches an auditor against it."""
    from research_workflow.supervisor import derive as D
    from research_workflow.supervisor.core import Supervisor
    from research_workflow.supervisor.procs import kill_tree
    sup = _start(sandbox, plan={"worker_sleep_s": 30.0}, study_id=f"sup_stale_{mode}")
    sid = sup.study_id
    sup, _ = drive(sid, stop_before_wait=lambda s: (s.state.get("active_worker") or {}).get("session_type") == "CAUSAL_AUDIT")
    aw = sup.state["active_worker"]; assert aw and aw["session_type"] == "CAUSAL_AUDIT"
    study = Path(sup.state["study_worktree"]) / "studies" / sid
    card_before = json.loads((study / "_work" / "controller" / "status.json").read_text(encoding="utf-8"))
    assert card_before["state"] == "NEEDS_CAUSAL_AUDIT"
    kill_tree(int(aw["pid"]))                                     # the auditor dies before its card (a crash); the card now goes stale underneath it
    Path(aw["result_path"]).unlink(missing_ok=True)
    if mode == "spec":
        spec = study / "study.yaml"                                 # a REAL spec change (a comment alone does not move the normalized spec hash)
        text = spec.read_text(encoding="utf-8"); assert "n_estimators: 20" in text
        spec.write_text(text.replace("n_estimators: 20", "n_estimators: 21"), encoding="utf-8")
        subprocess.run(["git", "commit", "-q", "-am", "edit spec after seal"], cwd=str(sup.state["study_worktree"]), check=True)
    else:
        monkeypatch.setattr(D, "_current_platform_composite", lambda study, wt: "platform-moved-" + str(card_before["fingerprints"].get("current_execution_composite"))[:8])
    s2 = Supervisor(sid); card = s2.tick()
    assert s2.state["worker_history"][-1]["status"] == "FAILED" and s2.state["worker_history"][-1]["reason"] == "RESULT_CARD_MISSING"
    assert s2.state["derived_state"] == "COMPILED" and card["action"] == "JOB_LAUNCHED" and card["through"] == "seal", (s2.state["derived_state"], card)
    assert s2.state["derived_from"] and s2.state["active_worker"] is None
    ev = [e for e in _events(sid) if e["kind"] == "DERIVED"][-1]
    assert ev["code"] == "COMPILED"
    audits = [e for e in _events(sid) if e["kind"] == "WORKER_LAUNCHED" and e["session_type"] == "CAUSAL_AUDIT"]
    assert len(audits) == 1, "no auditor may be launched against a stale card"
    _wait_pid(int(s2.state["active_job"]["pid"]), 600)
    if mode == "platform":
        monkeypatch.setattr(D, "_current_platform_composite", lambda study, wt: None)   # the platform is consistent again after the reseal
    s3 = Supervisor(sid); card = s3.tick()
    fresh = json.loads((study / "_work" / "controller" / "status.json").read_text(encoding="utf-8"))
    assert fresh["state"] == "NEEDS_CAUSAL_AUDIT" and card["action"] == "WORKER_LAUNCHED" and card["session_type"] == "CAUSAL_AUDIT"
    if mode == "spec":
        assert fresh["fingerprints"]["study_spec"] != card_before["fingerprints"]["study_spec"]
    kill_tree(int(s3.state["active_worker"]["pid"]))
