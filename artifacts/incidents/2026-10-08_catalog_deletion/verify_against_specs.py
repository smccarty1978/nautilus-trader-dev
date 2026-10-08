"""Read-only verification of catalog directories against committed DatasetSpecs, using platform code on main."""
import hashlib, json, sys
from pathlib import Path
import yaml

REPO = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(REPO))
from research_workflow.roots import compute_catalog_digest  # noqa: E402
from research_workflow import dataset_v2  # noqa: E402

targets = json.loads(Path(sys.argv[1]).read_text())  # {label: [dataset_id, catalog_dir]}
out_path = Path(sys.argv[2])


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


res = {"repo_head": (REPO / ".git" / "HEAD").read_text().strip(), "checks": {}}
for label, (ds, cat) in targets.items():
    cat = Path(cat)
    spec = yaml.safe_load((REPO / "research" / "datasets" / f"{ds}.yaml").read_text(encoding="utf-8"))
    r = {"dataset_id": ds, "catalog_dir": str(cat)}
    d = compute_catalog_digest(cat)
    r["logical_digest"] = {"computed": d["logical_digest"], "spec": spec.get("logical_digest"),
                           "match": d["logical_digest"] == spec.get("logical_digest"),
                           "file_count": d["file_count"], "total_bytes": d["total_bytes"]}
    dm = cat / "dataset_manifest.json"
    if dm.exists():
        m = json.loads(dm.read_text(encoding="utf-8"))
        r["dataset_manifest"] = {"logical_digest": m.get("logical_digest"),
                                 "match": m.get("logical_digest") == d["logical_digest"] and
                                 [[f["path"], f["size"], f["sha256"]] for f in m.get("files", [])] ==
                                 [[f["path"], f["size"], f["sha256"]] for f in d["files"]]}
    if spec.get("reference_digest"):
        try:
            tabs = dataset_v2.load_reference_tables(cat, spec.get("reference_tables", []), reference_digest=spec["reference_digest"])
            r["reference_digest"] = {"spec": spec["reference_digest"], "match": True,
                                     "tables": {k: len(v) for k, v in tabs.items()}}
        except Exception as e:  # report, never repair
            r["reference_digest"] = {"spec": spec["reference_digest"], "match": False, "error": str(e)[:500]}
    bm = cat / "build_manifest.json"
    if bm.exists():
        b = json.loads(bm.read_text(encoding="utf-8"))
        prov = spec.get("provenance", {})
        r["builder_sha256"] = {"spec": prov.get("builder_sha256"), "manifest": (b.get("builder") or {}).get("sha256"),
                               "match": prov.get("builder_sha256") == (b.get("builder") or {}).get("sha256")}
        r["build_manifest_reference_digest_match"] = b.get("reference_digest") == spec.get("reference_digest")
        spec_src = {str(s["year"]): s["sha256"] for s in prov.get("sources", [])}
        man_src = b.get("sources")
        raw = {}
        for y, s in spec_src.items():
            rp = REPO / "data" / "raw" / f"NQ_v0_1s_{y}.parquet"
            raw[y] = {"spec": s, "raw_file": rp.name, "raw_sha256": sha(rp) if rp.exists() else None}
            raw[y]["match"] = raw[y]["raw_sha256"] == s
        r["raw_sources"] = raw
        r["build_manifest_sources_raw"] = man_src
    res["checks"][label] = r
    print(label, json.dumps({k: (v.get("match") if isinstance(v, dict) and "match" in v else None) for k, v in r.items()}), flush=True)
out_path.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
