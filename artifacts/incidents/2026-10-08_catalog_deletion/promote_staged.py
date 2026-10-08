"""Promote verified staged catalogs into their (empty) live directories. Run only with owner authorization.

Refuses unless every live target directory is empty or absent; copies with exclusive create (never overwrites);
re-hashes every promoted file against the staging report (which itself was verified against the VSS source and the
committed DatasetSpecs). Prints a JSON result; exit 1 on any mismatch.
"""
import hashlib, json, os, sys
from pathlib import Path

STAGING = Path(sys.argv[1])          # ...\nt_recovery_staging\sc23_copy
LIVE_ROOT = Path(sys.argv[2])        # ...\Nautilus Trader\data\catalog
report = json.loads((STAGING / "staging_copy_report.json").read_text(encoding="utf-8"))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


for ds in report["datasets"]:
    t = LIVE_ROOT / ds
    if t.exists() and any(t.iterdir()):
        sys.exit(f"REFUSED: live target {t} is not empty")
result = {}
for ds, info in report["datasets"].items():
    if not info["all_match"]:
        sys.exit(f"REFUSED: staging report for {ds} is not all_match")
    bad = []
    for f in info["files"]:
        src, dst = STAGING / ds / f["rel"], LIVE_ROOT / ds / f["rel"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as fi, open(dst, "xb") as fo:
            for b in iter(lambda: fi.read(8 << 20), b""):
                fo.write(b)
            fo.flush()
            os.fsync(fo.fileno())
        os.utime(dst, ns=(f["mtime_ns"], f["mtime_ns"]))
        if sha(dst) != f["source_sha256"] or dst.stat().st_size != f["size"]:
            bad.append(f["rel"])
    result[ds] = {"files": len(info["files"]), "mismatches": bad}
print(json.dumps(result))
sys.exit(1 if any(v["mismatches"] for v in result.values()) else 0)
