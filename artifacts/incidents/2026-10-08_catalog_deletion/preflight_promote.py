"""Immediately-before-promotion reconfirmation: staged bytes == staging report; live targets empty dirs."""
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

STAGING = Path(r"C:\Users\Scott McCarty\Projects\nt_recovery_staging\sc23_copy")
LIVE = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog")
rep = json.loads((STAGING / "staging_copy_report.json").read_text(encoding="utf-8"))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


out = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "datasets": {}}
ok = True
for ds, info in rep["datasets"].items():
    staged = sorted(p.relative_to(STAGING / ds).as_posix() for p in (STAGING / ds).rglob("*") if p.is_file())
    listed = sorted(f["rel"] for f in info["files"])
    bad = [f["rel"] for f in info["files"] if sha(STAGING / ds / f["rel"]) != f["source_sha256"]]
    t = LIVE / ds
    entries = [str(p) for p in t.rglob("*")] if t.exists() else None
    r = {"staged_files": len(staged), "file_set_matches_report": staged == listed, "hash_mismatches": bad,
         "live_target_exists": t.exists(), "live_target_is_dir": t.is_dir(), "live_target_entries": entries}
    r["ok"] = staged == listed and not bad and t.is_dir() and entries == []
    ok &= r["ok"]
    out["datasets"][ds] = r
out["verdict"] = "READY_TO_PROMOTE" if ok else "REFUSE"
Path(sys.argv[1]).write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))
sys.exit(0 if ok else 1)
