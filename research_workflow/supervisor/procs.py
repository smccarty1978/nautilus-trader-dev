"""Process helpers: detached spawn (the user's terminal returns immediately), pid liveness, process-tree kill.

Windows: ``CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`` with stdout/stderr to a log file; POSIX:
``start_new_session``. The same helper launches the supervisor loop, AI workers and controller jobs.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional


def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        import psutil  # type: ignore
        if not psutil.pid_exists(pid):
            return False
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except Exception:
            return True
    except ImportError:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and code.value == 259
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def spawn_detached(command: List[str], *, cwd: Path, log_path: Path, env: Optional[Mapping[str, Optional[str]]] = None) -> int:
    """Start ``command`` fully detached from this terminal; return its pid. stdout+stderr -> ``log_path``."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    full_env: Dict[str, str] = {**os.environ}
    for k, v in (env or {}).items():          # None removes an inherited variable (a fresh worker must not inherit the parent harness's session)
        if v is None:
            full_env.pop(k, None)
        else:
            full_env[k] = str(v)
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    kwargs: Dict[str, object] = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    else:
        kwargs["start_new_session"] = True
    with log_path.open("ab") as log:
        proc = subprocess.Popen(command, cwd=str(cwd), env=full_env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                close_fds=True, **kwargs)  # type: ignore[arg-type]
    return int(proc.pid)


def kill_pid(pid: int) -> bool:
    """Kill exactly ONE process (DEV-07): `supervise stop` ends the loop and must leave the detached controller job and
    any worker -- which the loop spawned and which are therefore its children -- running to completion."""
    if not pid_alive(pid):
        return False
    try:
        import psutil  # type: ignore
        p = psutil.Process(pid)
        p.kill()
        p.wait(timeout=5)
        return True
    except Exception:
        pass
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)   # no /T: never the tree
        else:
            os.kill(pid, 9)
        return True
    except Exception:
        return False


def kill_tree(pid: int) -> bool:
    """Kill ``pid`` and its descendants (WORKER_TIMEOUT / stop). Returns whether anything was signalled."""
    if not pid_alive(pid):
        return False
    try:
        import psutil  # type: ignore
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        psutil.wait_procs(procs, timeout=5)
        return True
    except Exception:
        pass
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            os.kill(pid, 9)
        return True
    except Exception:
        return False


__all__ = ["pid_alive", "spawn_detached", "kill_tree", "kill_pid"]
