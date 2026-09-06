"""DEV-07 (2026-09-05, continuation of the first real validation): `supervise stop` killed the detached 70-minute
controller job because the job is a CHILD of the loop process and stop used a process-tree kill. `stop` must end
exactly the loop process; the job / worker it spawned keep running and are consumed on `resume`."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOOP_CODE = "\n".join([
    "import sys, time",
    "from research_workflow.supervisor.procs import spawn_detached",
    "pid = spawn_detached([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=sys.argv[1], log_path=__import__('pathlib').Path(sys.argv[1]) / 'job.log')",
    "print(pid, flush=True)",
    "time.sleep(60)",
])


def test_stop_kills_only_the_loop_process_never_its_detached_job(tmp_path, monkeypatch):
    from research_workflow.supervisor import state as S
    from research_workflow.supervisor.core import Supervisor
    from research_workflow.supervisor.procs import kill_pid, pid_alive
    monkeypatch.setenv("NT_RESEARCH_SUPERVISOR_HOME", str(tmp_path / "home"))
    st = S.new_state(study_id="s", question_path=None, question_sha256=None, platform_commit=None, provider="scripted", study_branch="study/s",
                     study_worktree=str(tmp_path), repo_root=str(tmp_path), execute_authorized=False)
    S.save_state(st)
    loop = subprocess.Popen([sys.executable, "-c", LOOP_CODE, str(tmp_path)], cwd=str(ROOT), stdout=subprocess.PIPE, text=True)
    job_pid = int(loop.stdout.readline().strip())
    sup = Supervisor("s")
    (sup.dir / "pid").write_text(str(loop.pid), encoding="utf-8")
    sup.state["active_job"] = {"kind": "controller", "pid": job_pid, "through": "analyze"}
    try:
        assert pid_alive(loop.pid) and pid_alive(job_pid)
        out = sup.stop()
        time.sleep(1.0)
        assert out["loop_killed"] is True and not pid_alive(loop.pid)
        assert pid_alive(job_pid) and out["job_alive"] is True, "the detached job must survive `supervise stop`"
    finally:
        kill_pid(job_pid)
        try:
            loop.kill()
        except Exception:
            pass


def test_kill_pid_does_not_touch_children(tmp_path):
    from research_workflow.supervisor.procs import kill_pid, kill_tree, pid_alive
    parent = subprocess.Popen([sys.executable, "-c", LOOP_CODE, str(tmp_path)], cwd=str(ROOT), stdout=subprocess.PIPE, text=True)
    child = int(parent.stdout.readline().strip())
    try:
        assert kill_pid(parent.pid) and not pid_alive(parent.pid) and pid_alive(child)
    finally:
        kill_tree(child)
