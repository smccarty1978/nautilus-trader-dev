"""Red-team packet C1: the controller run lock (and the shared ``locks.acquire_exclusive``
primitive it is built on) must be genuinely atomic under concurrent acquisition -- a
check-then-write race lets two callers both observe "no lock" and both write, which is what
the pre-fix ``_acquire_run_lock`` did (``_read`` then ``_json``, two syscalls with a window
between them)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from research_workflow.governed_controller_v2 import _pid_alive
from research_workflow.locks import acquire_exclusive, release

ROOT = Path(__file__).resolve().parents[2]

_WORKER_SCRIPT = textwrap.dedent("""
    import json, os, sys, time
    sys.path.insert(0, {root!r})
    from research_workflow.locks import acquire_exclusive
    start_file, lock_path, result_path = sys.argv[1], sys.argv[2], sys.argv[3]
    while not os.path.exists(start_file):
        time.sleep(0.005)
    r = acquire_exclusive(lock_path, {{"pid": os.getpid()}}, is_stale=lambda e, m: False, max_attempts=3)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({{"pid": os.getpid(), "acquired": r.acquired}}, f)
""")


def _run_round(tmp_path: Path, lock: Path, n: int, round_no: int) -> int:
    """Launch n subprocesses that race to acquire ``lock``; return the winner count."""
    if lock.exists():
        lock.unlink()
    script = tmp_path / "worker.py"
    script.write_text(_WORKER_SCRIPT.format(root=str(ROOT)), encoding="utf-8")
    start_file = tmp_path / f"start_{round_no}"
    result_dir = tmp_path / f"round_{round_no}"
    result_dir.mkdir()
    procs = []
    for i in range(n):
        result_path = result_dir / f"{i}.json"
        procs.append(subprocess.Popen([sys.executable, str(script), str(start_file), str(lock), str(result_path)]))
    start_file.write_text("go", encoding="utf-8")   # release every waiting subprocess at once
    for p in procs:
        assert p.wait(timeout=30) == 0
    winners = 0
    for i in range(n):
        rec = json.loads((result_dir / f"{i}.json").read_text(encoding="utf-8"))
        if rec["acquired"]:
            winners += 1
    return winners


def test_run_lock_exactly_one_winner(tmp_path):
    lock = tmp_path / "run.lock"
    # round 1: N=8 processes race for a fresh lock -> exactly one winner
    assert _run_round(tmp_path, lock, 8, 0) == 1
    # the winner releases; a second independent round again has exactly one winner
    release(lock, owns=lambda existing: True)
    assert _run_round(tmp_path, lock, 8, 1) == 1


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_stale_lock_dead_pid_is_reclaimed(tmp_path):
    lock = tmp_path / "run.lock"
    dead = _dead_pid()
    lock.write_text(json.dumps({"pid": dead}), encoding="utf-8")

    def is_stale(existing, mtime):
        pid = int((existing or {}).get("pid") or 0)
        return not (pid and _pid_alive(pid))

    r = acquire_exclusive(lock, {"pid": os.getpid()}, is_stale=is_stale, max_attempts=3)
    assert r.acquired and r.stale_reclaimed
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_live_lock_is_not_stolen(tmp_path):
    lock = tmp_path / "run.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")   # our own pid is alive
    r = acquire_exclusive(lock, {"pid": 999999999}, is_stale=lambda existing, mtime: False)
    assert not r.acquired
    assert r.payload is not None and r.payload["pid"] == os.getpid()
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()   # untouched
