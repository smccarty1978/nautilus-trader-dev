"""Atomic OS-level exclusive-create lock primitive, shared by the controller run lock
(:mod:`research_workflow.governed_controller_v2`), the writer lease
(:mod:`research_workflow.workspace`) and the model-store per-model lock
(:mod:`research_workflow.model_store`).

``os.open(path, O_CREAT | O_EXCL | O_WRONLY)`` is atomic on both POSIX and Windows/NTFS: the
OS guarantees exactly one caller among any number of concurrent callers observes success: this
is a check-and-write in a single syscall, not a check-then-write race. Do not use
``fcntl``/``msvcrt`` byte-range locking here -- this module only creates/removes whole files.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

IsStale = Callable[[Optional[dict], float], bool]


class LockError(RuntimeError):
    pass


@dataclass
class LockResult:
    acquired: bool
    path: Path
    payload: Optional[dict] = None       # ours if acquired, else the current holder's (or None if unparseable)
    stale_reclaimed: bool = False


def _write_new(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        data = (json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_payload(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def acquire_exclusive(path: Path, payload: Mapping[str, Any], *, is_stale: IsStale, max_attempts: int = 3) -> LockResult:
    """Atomically create ``path`` with ``payload`` as its only content.

    ``is_stale(existing_payload, mtime_epoch_s) -> bool`` decides whether an existing lock file
    may be removed and the create retried. Bounded to ``max_attempts`` O_EXCL attempts: the
    loser of a concurrent stale-reclaim race gets exactly one more try (re-reads and re-decides)
    before giving up -- this never spins.
    """
    path = Path(path)
    last_existing: Optional[dict] = None
    for attempt in range(max(1, max_attempts)):
        try:
            _write_new(path, payload)
            return LockResult(True, path, dict(payload), stale_reclaimed=attempt > 0)
        except FileExistsError:
            existing = read_payload(path)
            last_existing = existing
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue  # vanished between the failed create and stat(); retry
            if is_stale(existing, mtime):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            return LockResult(False, path, existing, stale_reclaimed=False)
    return LockResult(False, path, last_existing, stale_reclaimed=False)


def acquire_wait(path: Path, payload: Mapping[str, Any], *, is_stale: IsStale, timeout_s: float = 30.0,
                  poll_interval_s: float = 0.05) -> LockResult:
    """Like :func:`acquire_exclusive` but retries for up to ``timeout_s`` (bounded wait) instead
    of giving up after ``max_attempts``. Used where a caller should wait out a short-lived holder
    (e.g. a manifest-mutation lock) rather than fail immediately."""
    deadline = time.monotonic() + timeout_s
    while True:
        result = acquire_exclusive(path, payload, is_stale=is_stale, max_attempts=1)
        if result.acquired or time.monotonic() >= deadline:
            return result
        time.sleep(poll_interval_s)


def release(path: Path, *, owns: Callable[[Optional[dict]], bool]) -> bool:
    """Remove ``path`` only if ``owns(existing_payload)`` is true. Returns whether it removed it."""
    path = Path(path)
    existing = read_payload(path)
    if owns(existing):
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


__all__ = ["LockError", "LockResult", "acquire_exclusive", "acquire_wait", "release", "read_payload"]
