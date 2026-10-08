"""Post-promotion: live files vs staging report (bytes, sha256, mtime), canonical spec checks on LIVE, verdict."""
import hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

EV = Path(sys.argv[1])
STAGING = Path(r"C:\Users\Scott McCarty\Projects\nt_recovery_staging\sc23_copy")
LIVE = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog")
HERE = Path(__file__).parent
rep = json.loads((STAGING / "staging_copy_report.json").read_text(encoding="utf-8"))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


inv, ok = {}, True
for ds, info in rep["datasets"].items():
    live_set = sorted(p.relative_to(LIVE / ds).as_posix() for p in (LIVE / ds).rglob("*") if p.is_file())
    files = []
    for f in info["files"]:
        p = LIVE / ds / f["rel"]
        st = p.stat()
        h = sha(p)
        files.append({"rel": f["rel"], "size": st.st_size, "sha256": h, "mtime_ns": st.st_mtime_ns,
                      "matches_staging": h == f["source_sha256"] and st.st_size == f["size"],
                      "mtime_preserved": st.st_mtime_ns == f["mtime_ns"]})
    extra = sorted(set(live_set) - {f["rel"] for f in info["files"]})
    d_ok = all(x["matches_staging"] for x in files) and not extra and len(live_set) == len(info["files"])
    ok &= d_ok
    inv[ds] = {"file_count": len(live_set), "total_bytes": sum(x["size"] for x in files), "unexpected_files": extra,
               "all_match_staging": d_ok, "files": files}

targets = HERE / "targets_live.json"
targets.write_text(json.dumps({f"live_{ds}": [ds, str(LIVE / ds)] for ds in rep["datasets"]}))
spec_out = EV / "live_spec_verification.json"
subprocess.run([sys.executable, str(HERE / "verify_against_specs.py"), str(targets), str(spec_out)], check=True)
spec = json.loads(spec_out.read_text(encoding="utf-8"))["checks"]
canon = {}
for k, v in spec.items():
    c = {"logical_digest_match": v["logical_digest"]["match"], "logical_digest": v["logical_digest"]["computed"],
         "dataset_manifest_match": v.get("dataset_manifest", {}).get("match")}
    if "reference_digest" in v:
        c["reference_digest_match"] = v["reference_digest"]["match"]
        c["builder_sha256_match"] = v["builder_sha256"]["match"]
        c["raw_sources_match"] = all(x["match"] for x in v["raw_sources"].values())
    canon[k] = c
    ok &= all(x is not False for x in c.values() if isinstance(x, bool) or x is None)
verdict = {"verdict": "RECOVERED_VERIFIED" if ok else "RECOVERY_FAILED",
           "verified_at_utc": datetime.now(timezone.utc).isoformat(),
           "source": "VSS HarddiskVolumeShadowCopy23 (~2026-10-08T07:12Z) -> staging sc23_copy -> live",
           "scope": [str(LIVE / ds) for ds in rep["datasets"]],
           "canonical_checks_on_live": canon,
           "inventory": inv}
(EV / "recovery_verdict.json").write_text(json.dumps(verdict, indent=1), encoding="utf-8")
print(json.dumps({"verdict": verdict["verdict"], "canonical": canon,
                  "inventory": {k: {kk: vv for kk, vv in v.items() if kk != "files"} for k, v in inv.items()}}, indent=1))
sys.exit(0 if ok else 1)
