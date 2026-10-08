"""Copy catalogs out of a VSS shadow copy into an isolated staging dir (no links, no overwrite).

Source is read through the \\\\?\\GLOBALROOT device path (read-only snapshot). Every file is hashed while it is
streamed, the staged copy is re-read and re-hashed, and mtimes are preserved. Refuses to write into an existing
destination and refuses any destination under the live data/ tree.
"""
import hashlib, json, os, sys
from pathlib import Path

SHADOW = int(sys.argv[1])
DATASETS = sys.argv[2].split(",")
STAGING = Path(sys.argv[3])
LIVE_DATA = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data").resolve()
SRC_ROOT = rf"\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy{SHADOW}\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog"
CHUNK = 8 << 20

assert not str(STAGING.resolve()).lower().startswith(str(LIVE_DATA).lower()), "staging under live data/ refused"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


report = {"shadow": SHADOW, "source_root": SRC_ROOT, "staging": str(STAGING), "datasets": {}}
for ds in DATASETS:
    src, dst = os.path.join(SRC_ROOT, ds), STAGING / ds
    if dst.exists():
        sys.exit(f"REFUSED: {dst} exists")
    files = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        for d in dirnames:
            if os.path.islink(os.path.join(dirpath, d)):
                sys.exit(f"REFUSED: link in source {dirpath}/{d}")
        for fn in sorted(filenames):
            s = os.path.join(dirpath, fn)
            rel = os.path.relpath(s, src)
            t = dst / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            with open(s, "rb") as fi, open(t, "xb") as fo:
                for b in iter(lambda: fi.read(CHUNK), b""):
                    h.update(b)
                    fo.write(b)
                fo.flush()
                os.fsync(fo.fileno())
            st = os.stat(s)
            os.utime(t, ns=(st.st_atime_ns, st.st_mtime_ns))
            src_sha, dst_sha = h.hexdigest(), sha(t)
            files.append({"rel": Path(rel).as_posix(), "size": st.st_size, "staged_size": t.stat().st_size,
                          "mtime_ns": st.st_mtime_ns, "source_sha256": src_sha, "staged_sha256": dst_sha,
                          "match": src_sha == dst_sha and st.st_size == t.stat().st_size})
            print(ds, rel, st.st_size, files[-1]["match"], flush=True)
    report["datasets"][ds] = {"file_count": len(files), "total_bytes": sum(f["size"] for f in files),
                              "all_match": all(f["match"] for f in files), "files": files}
out = STAGING / "staging_copy_report.json"
out.write_text(json.dumps(report, indent=1), encoding="utf-8")
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "files"} for k, v in report["datasets"].items()}))
