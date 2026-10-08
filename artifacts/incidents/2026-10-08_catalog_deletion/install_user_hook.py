"""Install the data guard as a USER-level PreToolUse hook, preserving every existing setting."""
import hashlib, json, shutil
from pathlib import Path

SRC = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-data_safety_guard\scripts\hooks\data_guard.py")
DST = Path.home() / ".claude" / "hooks" / "nt_data_guard.py"
SETTINGS = Path.home() / ".claude" / "settings.json"
DST.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, DST)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
assert sha(SRC) == sha(DST)
before = json.loads(SETTINGS.read_text(encoding="utf-8"))
cfg = json.loads(json.dumps(before))
cmd = f'python "{DST.as_posix()}"'
entry = {"matcher": "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit",
         "hooks": [{"type": "command", "command": cmd, "timeout": 20}]}
pre = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
if not any(h.get("command") == cmd for e in pre for h in e.get("hooks", [])):
    pre.append(entry)
SETTINGS.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
after = json.loads(SETTINGS.read_text(encoding="utf-8"))
preserved = all(after.get(k) == v for k, v in before.items() if k != "hooks")
print(json.dumps({"hook_copy": str(DST), "hook_sha256": sha(DST), "command": cmd, "unrelated_keys_preserved": preserved,
                  "keys_before": sorted(before), "keys_after": sorted(after)}, indent=1))
