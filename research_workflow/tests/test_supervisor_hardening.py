"""Supervisor V1 hardening-01 (from the first real validation, study supv1_shape_a_flip_180s, 2026-09-05):
DEV-01b a dead detached loop is reported, never a dead loop_pid with STATUS OK; DEV-04 the read-only allowlist covers
the PowerShell tool; DEV-05 the controller script executes from the STUDY worktree; DEV-06 a persisted controller card
is stale once the platform composite it recorded differs from what the platform compiles now."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_workflow.supervisor import cli as supervisor_cli  # noqa: E402
from research_workflow.supervisor import derive as D  # noqa: E402
from research_workflow.supervisor import packets as P  # noqa: E402
from research_workflow.supervisor import providers as PR  # noqa: E402


def test_detach_loop_reports_a_loop_that_dies_at_startup(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor_cli.S, "study_state_dir", lambda sid: tmp_path / sid)
    (tmp_path / "s" / "logs").mkdir(parents=True)
    dead = supervisor_cli._detach_loop(ROOT, "s", command=[sys.executable, "-c", "import sys; print('boom'); sys.exit(2)"], grace_s=3.0)
    assert dead["loop_alive"] is False and dead["blocker_code"] == "LOOP_DIED" and "boom" in dead["log_tail"]
    alive = supervisor_cli._detach_loop(ROOT, "s", command=[sys.executable, "-c", "import time; time.sleep(5)"], grace_s=1.0)
    try:
        assert alive["loop_alive"] is True and "blocker_code" not in alive
    finally:
        from research_workflow.supervisor.procs import kill_tree
        kill_tree(int(alive["loop_pid"]))


def test_start_card_fails_closed_when_the_loop_died(monkeypatch, tmp_path, capsys):
    """The CLI card for start/resume/adopt is FAIL when _detach_loop reports LOOP_DIED (the validation saw STATUS OK + dead pid)."""
    import argparse
    monkeypatch.setattr(supervisor_cli, "_detach_loop", lambda repo_root, sid: {"loop_pid": 1, "loop_alive": False, "blocker_code": "LOOP_DIED", "log": "x"})

    class FakeSup:
        study_id = "s"; state = {"stopped": False}
        def __init__(self, study_id): pass
        def tick(self): return {}
    monkeypatch.setattr("research_workflow.supervisor.core.Supervisor", FakeSup)
    monkeypatch.setattr(supervisor_cli.S, "save_state", lambda st: None)
    monkeypatch.setattr(supervisor_cli.S, "append_event", lambda *a, **k: None)
    ns = argparse.Namespace(cmd="resume", study_id="s", no_detach=False)
    rc = supervisor_cli.cmd_supervise(ns, ROOT)
    card = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 2 and card["STATUS"] == "FAIL" and card["blocker_code"] == "LOOP_DIED"


def test_read_only_allowlist_covers_bash_and_powershell():
    probe = {"provider": "claude", "AVAILABLE": True, "HEADLESS_SUPPORTED": True, "WRITE_SUPPORTED": True, "READ_ONLY_SUPPORTED": True, "binary": "claude",
             "flags": {"-p": True, "--output-format": True, "--allowedTools": True, "--disallowedTools": True, "--add-dir": True}}
    cmd = PR.build_command("claude", packet_path=Path("p.md"), worktree=Path("."), read_only=True, results_dir=Path("."), session_id="s", probe=probe)
    allowed = cmd[cmd.index("--allowedTools") + 1:]
    assert "PowerShell(python scripts/research.py:*)" in allowed and "Bash(python scripts/research.py:*)" in allowed
    assert "--dangerously-skip-permissions" not in cmd


def test_controller_command_runs_the_study_worktree_platform(tmp_path, monkeypatch):
    from research_workflow.supervisor import state as S
    from research_workflow.supervisor.core import Supervisor
    monkeypatch.setenv("NT_RESEARCH_SUPERVISOR_HOME", str(tmp_path / "home"))
    st = S.new_state(study_id="s", question_path=None, question_sha256=None, platform_commit=None, provider="scripted", study_branch="study/s",
                     study_worktree=str(tmp_path / "wt"), repo_root=str(tmp_path / "canonical"), execute_authorized=True)
    S.save_state(st)
    sup = Supervisor("s")
    cmd = sup._controller_command("seal", None)
    assert Path(cmd[1]) == tmp_path / "wt" / "scripts" / "run_governed_study.py" and "--execute-authorized" in cmd
    assert str(tmp_path / "canonical") not in " ".join(cmd)


def test_controller_card_is_stale_when_the_platform_composite_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("NT_RESEARCH_SUPERVISOR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NT_RESEARCH_CONFIG", str(tmp_path / "cfg.yaml"))
    (tmp_path / "cfg.yaml").write_text(f"catalog_roots: []\nleases_dir: {(tmp_path / 'leases').as_posix()}\n", encoding="utf-8")
    repo = tmp_path / "r"; study = repo / "studies" / "s1"; work = study / "_work" / "controller"; work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    (study / "study.yaml").write_text("study: {id: s1}\n", encoding="utf-8")
    (study / "compiled_plan.json").write_text("{}", encoding="utf-8")
    from research_workflow.lifecycle_v2 import spec_sha256
    fp = {"study_spec": spec_sha256(study), "compiled_plan": P.sha256_file(study / "compiled_plan.json"), "current_execution_composite": "old", "execution_composite": "old"}
    (work / "status.json").write_text(json.dumps({"STATUS": "BLOCKED", "state": "NEEDS_CONTRACT_AUDIT", "stage": "contract_audit", "blocker_code": "CONTRACT_BLOCKER", "fingerprints": fp}), encoding="utf-8")
    ident = {"user": "u", "host": "h", "owner": "u@h", "agent": "scripted", "session_id": "sup"}
    st = {"study_id": "s1", "study_worktree": str(repo), "execute_authorized": True, "consumed_handoffs": [], "user_decision": None}
    monkeypatch.setattr(D, "_current_platform_composite", lambda study, wt: "old")
    assert D.derive(st, supervisor_identity=ident)["code"] == "AUDIT_BLOCKER"          # same platform: the blocker stands
    monkeypatch.setattr(D, "_current_platform_composite", lambda study, wt: "new")
    d = D.derive(st, supervisor_identity=ident)
    assert d["code"] == "COMPILED" and d["evidence"]["platform_changed"] == {"recorded": "old", "current": "new"}   # platform merged: recompile first
    monkeypatch.setattr(D, "_current_platform_composite", lambda study, wt: None)
    assert D.derive(st, supervisor_identity=ident)["code"] == "AUDIT_BLOCKER"          # cannot compile here (synthetic): no opinion
