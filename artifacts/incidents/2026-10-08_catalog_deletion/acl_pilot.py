"""ACL protection pilot on DISPOSABLE copies of real data (never live paths). Writes acl_pilot.json.

Pilot tree: <pilot>/catalog/NQ_1S_V2_GLOBEX (copy of the verified staged catalog), <pilot>/raw/ (copies of two raw
files). Exercises: platform reads under protection, denied mutations, the incident sequence, new-dataset creation,
preservation of unrelated ACEs, rollback (restore from backup and remove), owner recovery.
"""
import hashlib, json, os, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import pandas as pd  # noqa: E402
import pyarrow as pa, pyarrow.parquet as pq  # noqa: E402
from scripts import protect_live_data as P  # noqa: E402
from research_workflow import roots, dataset_v2  # noqa: E402
from utils.runner.data import CausalDataLoader  # noqa: E402

PILOT = Path(sys.argv[1])
STAGED = Path(r"C:\Users\Scott McCarty\Projects\nt_recovery_staging\sc23_copy\NQ_1S_V2_GLOBEX")
RAW_SRC = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw")
LIVE = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data")
assert LIVE.resolve() not in PILOT.resolve().parents and PILOT.resolve() != LIVE.resolve(), "pilot must not be live"
CAT, RAW, DS = PILOT / "catalog", PILOT / "raw", PILOT / "catalog" / "NQ_1S_V2_GLOBEX"
SPEC = {"logical": "9e7aecb7a2910b4402a6cb4f34cc2f6deb5df19d0e889b2c696cf4f844292c64",
        "reference": "e577a36165abd690f70221041c4e2b6c7302b876b81d63e7a1f4076b46514514"}
ARGS = ["--catalog-root", str(CAT), "--raw-dir", str(RAW), "--state", str(PILOT / "state.json")]
R = {"started_utc": datetime.now(timezone.utc).isoformat(), "pilot": str(PILOT), "checks": {}}


def check(name, ok, **detail):
    R["checks"][name] = {"pass": bool(ok), **detail}
    print(("PASS " if ok else "FAIL ") + name, detail if not ok else "", flush=True)


def denied(fn):
    try:
        fn()
        return False
    except PermissionError:
        return True


def tree_sddl(tag):
    f = PILOT / f"sddl_{tag}.acl"
    subprocess.run(["icacls", str(CAT), "/save", str(f), "/T"], capture_output=True, check=True)
    g = PILOT / f"sddl_{tag}_raw.acl"
    subprocess.run(["icacls", str(RAW), "/save", str(g), "/T"], capture_output=True, check=True)
    return {("cat", n): s for n, s in P._read_save(f)} | {("raw", n): s for n, s in P._read_save(g)}


def aces(s):
    """ACE strings of the DACL, without the DACL control-flag prefix (P/AI)."""
    import re
    return set(re.findall(r"\([^)]*\)", s.split("D:", 1)[1])) if "D:" in s else set()


# ---- setup -------------------------------------------------------------------------------------------------
if PILOT.exists():
    sys.exit(f"pilot dir {PILOT} exists; refusing to reuse")
shutil.copytree(STAGED, DS)
RAW.mkdir(parents=True)
for n in ("NQ_v0_1s_2016.parquet", "NQ_v0_1s_2017.parquet"):
    shutil.copy2(RAW_SRC / n, RAW / n)
subprocess.run(["icacls", str(DS), "/grant", "*S-1-5-32-546:(OI)(CI)(R)"], capture_output=True, check=True)  # unrelated ACE
before = tree_sddl("before")
check("setup_digest_matches_spec", roots.compute_catalog_digest(DS)["logical_digest"] == SPEC["logical"])

# ---- apply -------------------------------------------------------------------------------------------------
check("apply", P.main(["apply", *ARGS, "--backup-dir", str(PILOT / "bk1")]) == 0)
check("verify", P.main(["verify", *ARGS]) == 0)
bm = json.loads((PILOT / "bk1" / "backup_manifest.json").read_text())
check("backup_records_original_descriptors", len(bm["entries"]) > 0 and all(e["descriptors"] for e in bm["entries"]),
      entries=len(bm["entries"]))
during = tree_sddl("during")
missing = {f"{k[0]}:{k[1]}": sorted(aces(v) - aces(during[k])) for k, v in before.items() if aces(v) - aces(during[k])}
check("unrelated_aces_preserved", not missing, missing=missing)

# ---- legitimate reads ---------------------------------------------------------------------------------------
check("read_logical_digest_under_protection", roots.compute_catalog_digest(DS)["logical_digest"] == SPEC["logical"])
tabs = dataset_v2.load_reference_tables(DS, ["gaps", "holidays", "maintenance", "out_of_calendar", "rolls", "sessions"],
                                        reference_digest=SPEC["reference"])
check("read_reference_tables_with_digest", len(tabs) == 6, rows={k: len(v) for k, v in tabs.items() if k != "gaps"})
cfg_path = PILOT / "pilot_config.yaml"
cfg_path.write_text(f"catalog_roots:\n  - '{CAT.as_posix()}'\n", encoding="utf-8")
res = roots.resolve_dataset("NQ_1S_V2_GLOBEX", REPO, config=roots.load_config(cfg_path), verify_digest=True)
check("resolve_dataset_via_catalog_roots_with_digest", Path(res.catalog_path).resolve() == DS.resolve()
      and res.logical_digest == SPEC["logical"] and res.resolution == "configured_root", resolved=str(res)[:300])
bars = CausalDataLoader(DS).load_bars("NQ.XCME-1-SECOND-LAST-EXTERNAL", pd.Timestamp("2020-03-02T14:30Z"),
                                      pd.Timestamp("2020-03-02T15:30Z"))
check("nautilus_catalog_bar_read", len(bars) > 1000, n_bars=len(bars))
check("raw_parquet_read", pq.ParquetFile(RAW / "NQ_v0_1s_2016.parquet").metadata.num_rows > 0)

# ---- denied mutations ---------------------------------------------------------------------------------------
part = next((DS / "data" / "bar").rglob("*.parquet"))
check("deny_delete_file", denied(part.unlink))
check("deny_overwrite_file", denied(lambda: part.open("r+b").close()))
check("deny_create_file_in_catalog", denied(lambda: (part.parent / "x.parquet").write_bytes(b"x")))
check("deny_rename_catalog", denied(lambda: os.rename(DS, CAT / "renamed")))
check("deny_rmtree_catalog", denied(lambda: shutil.rmtree(DS)))
check("deny_delete_raw", denied((RAW / "NQ_v0_1s_2016.parquet").unlink))
check("deny_overwrite_raw", denied(lambda: (RAW / "NQ_v0_1s_2016.parquet").open("r+b").close()))
check("catalog_intact_after_denials", roots.compute_catalog_digest(DS)["logical_digest"] == SPEC["logical"])

# ---- the incident sequence ----------------------------------------------------------------------------------
repo = PILOT / "gitrepo"
repo.mkdir()
g = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)  # noqa: E731
g("init", "-q"); (repo / "f").write_text("x"); g("add", "f")
g("-c", "user.email=p@p", "-c", "user.name=p", "commit", "-qm", "i")
wt = PILOT / "gitrepo-tmp_worktree"
g("worktree", "add", "--detach", str(wt))
(wt / "data" / "catalog").mkdir(parents=True)
link = wt / "data" / "catalog" / "NQ_1S_V2_GLOBEX"
jr = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(DS)], capture_output=True, text=True)
rm = g("worktree", "remove", "--force", str(wt))
check("incident_sequence_loses_nothing", jr.returncode == 0 and
      roots.compute_catalog_digest(DS)["logical_digest"] == SPEC["logical"],
      junction_rc=jr.returncode, git_rc=rm.returncode, git_stderr=rm.stderr.strip()[:300])
if link.exists():
    os.rmdir(link)  # the link itself, non-recursively

# ---- new datasets can still be created ----------------------------------------------------------------------
new = CAT / "NEW_PILOT_DS"
(new / "data" / "bar").mkdir(parents=True)
pq.write_table(pa.table({"x": [1, 2, 3]}), new / "data" / "bar" / "p.parquet")
roots.write_dataset_manifest(new, "NEW_PILOT_DS")
tmpb = CAT / "_tmp_build"
(tmpb / "data").mkdir(parents=True)
(tmpb / "data" / "a.parquet").write_bytes(b"x")
os.rename(tmpb, CAT / "NEW_PILOT_DS2")
(CAT / "NEW_PILOT_DS2" / "data" / "a.parquet").unlink()
shutil.rmtree(CAT / "NEW_PILOT_DS2")
(RAW / "NQ_v0_1s_2099.parquet").write_bytes(b"new raw year")
check("new_dataset_build_rename_cleanup_and_new_raw_allowed",
      (new / "dataset_manifest.json").exists() and not (CAT / "NEW_PILOT_DS2").exists() and (RAW / "NQ_v0_1s_2099.parquet").exists())
check("protect_new_dataset_afterwards", P.main(["apply", *ARGS, "--backup-dir", str(PILOT / "bk2")]) == 0
      and P.main(["verify", *ARGS]) == 0 and denied((new / "data" / "bar" / "p.parquet").unlink))

# ---- rollback: restore (LIFO) returns every original descriptor ---------------------------------------------
check("restore_bk2", P.main(["restore", "--backup-dir", str(PILOT / "bk2")]) == 0)
check("restore_bk1", P.main(["restore", "--backup-dir", str(PILOT / "bk1")]) == 0)
after = tree_sddl("after_restore")
diff = {f"{k[0]}:{k[1]}": [before[k], after.get(k)] for k in before
        if P.normalize_sddl(before[k]) != P.normalize_sddl(after.get(k, ""))}
ai_only = sum(1 for k in before if before[k] != after.get(k) and P.normalize_sddl(before[k]) == P.normalize_sddl(after[k]))
check("restore_reinstates_original_descriptors", not diff, differing=dict(list(diff.items())[:5]),
      ai_flag_only_differences=ai_only, compared=len(before))
check("unprotected_after_restore", P.main(["verify", *ARGS]) == 1)

# ---- owner (administrative) recovery path via remove -----------------------------------------------------------
check("reapply", P.main(["apply", *ARGS, "--backup-dir", str(PILOT / "bk3")]) == 0)
check("owner_remove", P.main(["remove", *ARGS]) == 0)
after2 = tree_sddl("after_remove")
diff2 = [k for k in before if P.normalize_sddl(before[k]) != P.normalize_sddl(after2.get(k, ""))]
check("remove_reinstates_original_descriptors", not diff2, differing=[f"{a}:{b}" for a, b in diff2[:5]])
part2 = next((DS / "data" / "bar").rglob("*.parquet"))
part2.unlink()
check("owner_can_modify_after_lifting", not part2.exists())

R["finished_utc"] = datetime.now(timezone.utc).isoformat()
R["verdict"] = "PILOT_PASS" if all(c["pass"] for c in R["checks"].values()) else "PILOT_FAIL"
Path(sys.argv[2]).write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
print(R["verdict"])
