
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from research_workflow.locks import acquire_exclusive
lock = Path(sys.argv[1]); barrier = float(sys.argv[2])
while time.time() < barrier:
    pass
def is_stale(existing, mtime):
    if not existing:
        return (time.time() - mtime) > 60
    pid = int(existing.get("pid") or 0)
    if not pid or pid == os.getpid():
        return True
    try:
        os.kill(pid, 0); return False
    except (OSError, PermissionError):
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h: return True
            c = ctypes.c_ulong(); ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(c))
            ctypes.windll.kernel32.CloseHandle(h)
            return not (ok and c.value == 259)
        except Exception:
            return False
r = acquire_exclusive(lock, {"pid": os.getpid()}, is_stale=is_stale, max_attempts=3)
print(json.dumps({"pid": os.getpid(), "acquired": bool(r.acquired)}))
