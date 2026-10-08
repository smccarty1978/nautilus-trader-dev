"""Replay the exact incident tool calls (from the transcripts) through the INSTALLED user-level hook command."""
import json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

HOOK = Path.home() / ".claude" / "hooks" / "nt_data_guard.py"
replay = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = []
for o in replay:
    ev = {"tool_name": o["tool"], "tool_input": {"command": o["command"]}, "session_id": "replay"}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), capture_output=True, text=True)
    out.append({"agent": o["agent"], "transcript_line": o["line"], "original_ts": o["ts"], "tool": o["tool"],
                "command": o["command"], "hook_exit": r.returncode, "blocked": r.returncode == 2,
                "reason": r.stderr.strip()[:200]})
    print(o["agent"][-6:], o["line"], "BLOCKED" if r.returncode == 2 else "ALLOWED", r.stderr.strip()[:90], flush=True)
res = {"replayed_at_utc": datetime.now(timezone.utc).isoformat(), "hook": str(HOOK), "n": len(out),
       "blocked": sum(x["blocked"] for x in out), "verdict": "ALL_BLOCKED" if all(x["blocked"] for x in out) else "GAP",
       "calls": out}
Path(sys.argv[2]).write_text(json.dumps(res, indent=1), encoding="utf-8")
print(res["verdict"], f'{res["blocked"]}/{res["n"]}')
