"""A6 (CRIT-5/6): run-lock race, same-id model-store race, and writer-lease ownership/TTL.
All state lives under tempfile dirs; the real leases dir and model store are never touched."""
from __future__ import annotations
import json, os, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

res = []


def rec(case, outcome, verdict):
    res.append({"case": case, "outcome": str(outcome)[:400], "verdict": verdict})


HERE = Path(__file__).resolve().parent

# ---------------- 1. 8-process race on locks.acquire_exclusive ----------------
LOCK_CHILD = HERE / "_child_lock.py"
LOCK_CHILD.write_text('''
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
''', encoding="utf-8")

for trial in (1, 2):
    TD = Path(tempfile.mkdtemp())
    lock = TD / "run.lock"
    barrier = time.time() + 2.0
    procs = [subprocess.Popen([sys.executable, str(LOCK_CHILD), str(lock), str(barrier), str(ROOT)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(8)]
    outs = [p.communicate() for p in procs]
    winners = []
    for o, e in outs:
        for line in o.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("acquired"):
                winners.append(d["pid"])
    rec("C5 8-process race on locks.acquire_exclusive (trial %d)" % trial,
        "winners=%d %s ; lock payload pid=%s" % (len(winners), winners,
                                                 (json.loads(lock.read_text())["pid"] if lock.is_file() else None)),
        "BLOCKED" if len(winners) == 1 else "BYPASSED")

# ---------------- 2. 6-process store_model race on one id ----------------
STORE_CHILD = HERE / "_child_store.py"
STORE_CHILD.write_text('''
import hashlib, json, sys, time
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, sys.argv[3])
from research_workflow.model_store import ModelLineage, store_model
from research.analysis.modeling import _build_estimator
MR = Path(sys.argv[1]); barrier = float(sys.argv[2])
rng = np.random.default_rng(5)
FE = ["f_a", "f_b"]
fr = pd.DataFrame({c: rng.normal(size=300) for c in FE})
y = (fr["f_a"] > 0).astype(int)
est = _build_estimator("lightgbm", 42, {"n_estimators": 15, "max_depth": 2, "num_leaves": 4, "learning_rate": 0.1, "verbosity": -1})
est.fit(fr[FE], y)
lin = ModelLineage(study_id="race", cell_id="c", direction="both", target_arm="a", fold_id="final", config_id="C00",
                   seed=42, ordered_inputs=list(FE),
                   feature_contract_sha256=hashlib.sha256(json.dumps(list(FE)).encode()).hexdigest(),
                   preprocessing_contract_sha256="identity", target_contract_sha256="t"*64,
                   target_frame_identity="p"*64, training_population_identity="p"*64,
                   train_years=[2029], validation_years=[], hyperparameters={}, family="lightgbm", model_role="primary")
mid = hashlib.sha256(json.dumps(lin.__dict__, sort_keys=True, default=str).encode()).hexdigest()
while time.time() < barrier:
    pass
try:
    m = store_model(model_id=mid, estimator=est, lineage=lin, tier="registry", selection_status="selected",
                    metrics={}, golden_train_frame=fr[FE], model_root=MR, golden_rows=300)
    print(json.dumps({"ok": True, "model_id": mid, "byte": m["canonical"]["byte_sha256"]}))
except Exception as exc:
    print(json.dumps({"ok": False, "err": type(exc).__name__ + ": " + str(exc)[:150]}))
''', encoding="utf-8")

TD = Path(tempfile.mkdtemp())
MR = TD / "mr"
barrier = time.time() + 12.0
procs = [subprocess.Popen([sys.executable, str(STORE_CHILD), str(MR), str(barrier), str(ROOT)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(6)]
outs = [p.communicate() for p in procs]
parsed = []
for o, e in outs:
    for line in o.splitlines():
        try:
            parsed.append(json.loads(line))
        except ValueError:
            pass
    if not o.strip():
        parsed.append({"ok": False, "err": "NO OUTPUT: " + e.strip()[-200:]})
model_dirs = sorted(p.name for p in (MR / "models").iterdir()) if (MR / "models").is_dir() else []
model_dirs = [d for d in model_dirs if not d.startswith(".")]
staging = sorted(p.name for p in (MR / "models" / ".staging").iterdir()) if (MR / "models" / ".staging").is_dir() else []
bytes_seen = {p.get("byte") for p in parsed if p.get("ok")}
rec("W-modelstore 6-process concurrent store_model on ONE id",
    "results=%s ; model dirs=%s ; leftover staging=%s ; distinct canonical bytes=%s"
    % (json.dumps(parsed)[:300], model_dirs, staging, bytes_seen),
    "BLOCKED" if len(model_dirs) == 1 and len(bytes_seen) <= 1 and all(p.get("ok") for p in parsed) and not staging
    else "BYPASSED")

# ---------------- 3. writer lease ----------------
from research_workflow import workspace as W  # noqa
from research_workflow.roots import RootConfig  # noqa
import dataclasses

LD = Path(tempfile.mkdtemp())
WT = LD / "worktree"
WT.mkdir()
CFG = RootConfig(path=None, catalog_roots=(), model_root=LD / "mr", leases_dir=LD / "leases",
                 worktree_root=LD / "wtr", lease_ttl_seconds=3600)
print("test leases_dir:", W.leases_dir(CFG))
assert str(W.leases_dir(CFG)).startswith(str(LD)), "refusing to touch the real leases dir"

(LD / "leases").mkdir(parents=True, exist_ok=True)
now = datetime.now(timezone.utc)
DEAD_PID = 999_999
lease_path = LD / "leases" / "adv_study.json"


def write_lease(**over):
    body = {"schema_version": 2, "study_id": "adv_study", "branch": "b", "worktree": str(WT.resolve()),
            "owner": "owner_a", "created_at_utc": now.isoformat(),
            "holder": {"pid": DEAD_PID, "kind": "cli", "renewed_at_utc": now.isoformat()},
            "ttl_seconds": 3600, "released_at_utc": None}
    body.update(over)
    lease_path.write_text(json.dumps(body, indent=1), encoding="utf-8")
    return body


write_lease()
leases = W.read_leases(CFG)
rec("C6 lease survives creator-pid death within TTL", "state=%s" % leases[0]["state"],
    "BLOCKED" if leases[0]["state"] == "live" else "BYPASSED")

write_lease(holder={"pid": DEAD_PID, "kind": "cli",
                    "renewed_at_utc": (now - timedelta(seconds=7200)).isoformat()},
            created_at_utc=(now - timedelta(seconds=7200)).isoformat())
rec("C6 lease goes stale past TTL with a dead pid", "state=%s" % W.read_leases(CFG)[0]["state"],
    "BLOCKED" if W.read_leases(CFG)[0]["state"] == "stale" else "BYPASSED")

write_lease()
try:
    W.renew_lease(WT, owner="owner_b", pid=os.getpid(), kind="controller", config=CFG)
    rec("C6 a DIFFERENT owner renews the lease", "renewed - no error", "BYPASSED")
except Exception as exc:
    rec("C6 a DIFFERENT owner renews the lease", type(exc).__name__ + ": " + str(exc)[:200], "BLOCKED")

try:
    out = W.renew_lease(WT, owner="owner_a", pid=os.getpid(), kind="controller", config=CFG)
    rec("C6 the owner renews (control)", "state=%s holder=%s" % (out["state"], out["holder"]), "OK")
except Exception as exc:
    rec("C6 the owner renews (control)", type(exc).__name__ + ": " + str(exc)[:200], "UNEXPECTED_REJECT")

write_lease()
try:
    W.release_lease("adv_study", owner="owner_b", config=CFG)
    rec("C6 a DIFFERENT owner releases the lease", "released - no error", "BYPASSED")
except Exception as exc:
    rec("C6 a DIFFERENT owner releases the lease", type(exc).__name__ + ": " + str(exc)[:200], "BLOCKED")

# a second writer cannot create a lease over a live one for the same worktree
write_lease()
try:
    W._write_lease("other_study", "b2", WT, config=CFG, owner="owner_b")
    rec("C6 a second writer takes a lease on a worktree with a LIVE lease", "created - no error", "BYPASSED")
except Exception as exc:
    rec("C6 a second writer takes a lease on a worktree with a LIVE lease",
        type(exc).__name__ + ": " + str(exc)[:200], "BLOCKED")

# reclaim must never touch a live lease -- exercise ws_list --reclaim if present
write_lease(holder={"pid": os.getpid(), "kind": "cli", "renewed_at_utc": now.isoformat()})
live_before = W.read_leases(CFG)[0]["state"]
reclaimed = None
try:
    reclaimed = W.ws_list(repo_root=ROOT, config=CFG, reclaim=True)
except Exception as exc:
    reclaimed = type(exc).__name__ + ": " + str(exc)[:200]
after = W.read_leases(CFG)
rec("C6 reclaim never touches a LIVE lease",
    "before=%s after=%s reclaim_result=%s" % (live_before, [r["state"] for r in after], json.dumps(reclaimed, default=str)[:200]),
    "BLOCKED" if after and after[0]["state"] == "live" else "BYPASSED")

# dead lease when the worktree is gone
write_lease(worktree=str((LD / "gone").resolve()))
rec("C6 lease is DEAD when its worktree no longer exists", "state=%s" % W.read_leases(CFG)[0]["state"],
    "BLOCKED" if W.read_leases(CFG)[0]["state"] == "dead" else "BYPASSED")

# schema v1 record still readable
lease_path.write_text(json.dumps({"study_id": "adv_study", "branch": "b", "worktree": str(WT.resolve()),
                                  "owner": "owner_a", "pid": os.getpid(),
                                  "created_at_utc": now.isoformat()}, indent=1), encoding="utf-8")
rec("C6 schema-v1 lease record still readable", "state=%s holder=%s" % (
    W.read_leases(CFG)[0]["state"], W.read_leases(CFG)[0]["holder"]),
    "OK" if W.read_leases(CFG)[0]["state"] == "live" else "BYPASSED")

print(json.dumps(res, indent=1))
Path(__file__).with_name("a6_results.json").write_text(json.dumps({"results": res}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT")], indent=1))
