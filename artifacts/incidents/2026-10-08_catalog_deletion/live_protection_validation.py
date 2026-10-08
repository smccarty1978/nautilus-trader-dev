"""Post-activation validation on LIVE data (read-only + harmless write-open probes). Writes live_protection_validation.json."""
import json, re, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_CHORE = Path(__file__).resolve().parents[3]
MAIN = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(REPO_CHORE))
import pandas as pd, yaml  # noqa: E402
from scripts import protect_live_data as P  # noqa: E402
from research_workflow import roots, dataset_v2  # noqa: E402
from utils.runner.data import CausalDataLoader  # noqa: E402

BK = Path(sys.argv[1])
R = {"validated_at_utc": datetime.now(timezone.utc).isoformat(), "backup_dir": str(BK), "checks": {}}


def check(name, ok, **d):
    R["checks"][name] = {"pass": bool(ok), **d}
    print(("PASS " if ok else "FAIL ") + name, "" if ok else d, flush=True)


aces = lambda s: set(re.findall(r"\([^)]*\)", s.split("D:", 1)[1])) if "D:" in s else set()  # noqa: E731
man = json.loads((BK / "backup_manifest.json").read_text(encoding="utf-8"))
missing, compared = {}, 0
with tempfile.TemporaryDirectory() as td:
    for i, e in enumerate(man["entries"]):
        f = Path(td) / f"{i}.acl"
        subprocess.run(["icacls", e["path"], "/save", str(f)] + (["/T"] if e["kind"] == "catalog" else []),
                       capture_output=True, check=True)
        now = {n: s for n, s in P._read_save(f)}
        for name, sddl in e["descriptors"]:
            compared += 1
            gone = aces(sddl) - aces(now.get(name, ""))
            if gone:
                missing[name] = sorted(gone)
check("unrelated_aces_preserved_live", not missing, compared=compared, missing=dict(list(missing.items())[:5]))

dig = {}
for spec_p in sorted((MAIN / "research" / "datasets").glob("*.yaml")):
    s = yaml.safe_load(spec_p.read_text(encoding="utf-8")) or {}
    d = MAIN / "data" / "catalog" / str(s.get("dataset_id"))
    if s.get("logical_digest") and (d / "data").is_dir():
        dig[s["dataset_id"]] = roots.compute_catalog_digest(d)["logical_digest"] == s["logical_digest"]
check("all_spec_backed_catalogs_read_and_match", all(dig.values()) and len(dig) >= 7, catalogs=dig)

for ds in ("NQ_1S_V2_GLOBEX", "NQ_v0_2020_2026"):
    res = roots.resolve_dataset(ds, MAIN, verify_digest=True)  # the real ~/.nt_research/config.yaml
    check(f"resolve_dataset_live_{ds}", res.resolution == "configured_root" and res.logical_digest is not None,
          path=str(res.catalog_path))
G = MAIN / "data" / "catalog" / "NQ_1S_V2_GLOBEX"
spec = yaml.safe_load((MAIN / "research" / "datasets" / "NQ_1S_V2_GLOBEX.yaml").read_text(encoding="utf-8"))
t = dataset_v2.load_reference_tables(G, spec["reference_tables"], reference_digest=spec["reference_digest"])
check("reference_tables_live", len(t) == 6)
bars = CausalDataLoader(G).load_bars("NQ.XCME-1-SECOND-LAST-EXTERNAL", pd.Timestamp("2020-03-02T14:30Z"),
                                     pd.Timestamp("2020-03-02T15:30Z"))
check("nautilus_bar_read_live", len(bars) > 1000, n=len(bars))


def write_open_denied(p):
    try:
        open(p, "r+b").close()  # opens for write, writes nothing
        return False
    except PermissionError:
        return True


probe = {str(p): write_open_denied(p) for p in [next((G / "data" / "bar").rglob("*.parquet")),
                                                MAIN / "data" / "raw" / "NQ_v0_1s_2022.parquet",
                                                next((MAIN / "data" / "catalog" / "legacy").rglob("*.*"))]}
check("write_open_denied_live", all(probe.values()), probe=probe)
check("verify_reports_protected", P.main(["verify"]) == 0)
R["verdict"] = "PROTECTION_ACTIVE_VERIFIED" if all(c["pass"] for c in R["checks"].values()) else "PROTECTION_FAIL"
Path(sys.argv[2]).write_text(json.dumps(R, indent=1), encoding="utf-8")
print(R["verdict"])
