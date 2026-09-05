"""Machine-wide resources shared by every supervisor process (packet sections 11.A and 11.E).

* ``<home>/locks/main_merge.lock`` -- every read-then-mutate of canonical ``main`` (capability merge,
  closed-study merge, merging main into a study worktree) holds it for the bounded operation only.
* ``<home>/locks/slots/{workers,heavy}/<n>.slot`` -- ``max_workers`` / ``max_heavy_jobs`` enforced
  across processes by O_EXCL slot files; a slot whose holder pid is dead is reclaimable.

Both reuse :func:`research_workflow.locks.acquire_exclusive` (atomic create; never byte-range locks).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from research_workflow.locks import acquire_exclusive, read_payload, release
from research_workflow.supervisor.procs import pid_alive
from research_workflow.supervisor.state import locks_root, now_utc

MAIN_MERGE_LOCK_MAX_AGE_S = 1800.0
DEFAULT_MAX_WORKERS = 2
DEFAULT_MAX_HEAVY_JOBS = 2


def _dead_holder(existing: Optional[dict], mtime: float, *, max_age_s: Optional[float]) -> bool:
    if not existing:
        return (time.time() - mtime) > 60
    pid = int(existing.get("pid") or 0)
    if pid and pid != os.getpid() and pid_alive(pid):
        return bool(max_age_s) and (time.time() - mtime) > float(max_age_s)
    return True


class MainMergeLock:
    """``with MainMergeLock(study_id, op) as ok:`` -- ``ok`` is False when another holder is live (WAIT_MERGE_LOCK)."""

    def __init__(self, study_id: str, operation: str) -> None:
        self.path = locks_root() / "main_merge.lock"
        self.payload = {"pid": os.getpid(), "study_id": study_id, "operation": operation, "started_at_utc": now_utc()}
        self.acquired = False
        self.holder: Optional[dict] = None

    def __enter__(self) -> bool:
        r = acquire_exclusive(self.path, self.payload, is_stale=lambda e, m: _dead_holder(e, m, max_age_s=MAIN_MERGE_LOCK_MAX_AGE_S), max_attempts=3)
        self.acquired = r.acquired
        self.holder = None if r.acquired else r.payload
        return self.acquired

    def __exit__(self, *exc: Any) -> None:
        if self.acquired:
            release(self.path, owns=lambda e: bool(e) and int(e.get("pid") or 0) == os.getpid())
            self.acquired = False


def slots_dir(kind: str) -> Path:
    return locks_root() / "slots" / kind


def acquire_slot(kind: str, *, max_slots: int, study_id: str, task_id: str) -> Optional[Path]:
    """Take one of ``max_slots`` slot files for ``kind`` ("workers" | "heavy"); None when all are held by live pids."""
    for n in range(max(1, int(max_slots))):
        p = slots_dir(kind) / f"{n}.slot"
        r = acquire_exclusive(p, {"pid": os.getpid(), "kind": kind, "study_id": study_id, "task_id": task_id, "started_at_utc": now_utc()},
                              is_stale=lambda e, m: _dead_holder(e, m, max_age_s=None), max_attempts=2)
        if r.acquired:
            return p
    return None


def release_slot(path: Optional[Path]) -> bool:
    if not path:
        return False
    return release(Path(path), owns=lambda e: bool(e) and int(e.get("pid") or 0) == os.getpid())


def slot_status() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for kind in ("workers", "heavy"):
        d = slots_dir(kind)
        rows = []
        if d.is_dir():
            for p in sorted(d.glob("*.slot")):
                e = read_payload(p) or {}
                rows.append({"slot": p.name, "pid": e.get("pid"), "alive": pid_alive(int(e.get("pid") or 0)), "study_id": e.get("study_id"), "task_id": e.get("task_id")})
        out[kind] = rows
    return out


__all__ = ["MainMergeLock", "acquire_slot", "release_slot", "slot_status", "slots_dir",
           "DEFAULT_MAX_WORKERS", "DEFAULT_MAX_HEAVY_JOBS", "MAIN_MERGE_LOCK_MAX_AGE_S"]
