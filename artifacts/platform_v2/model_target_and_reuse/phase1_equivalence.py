"""PHASE 1 feasibility: could the replay-closure delta have changed ANY byte of the persisted partitions?

Static evidence: classify every replay-closure file whose CONTENT differs between the commit the atlas
partitions were produced under and current main (line endings normalised: git blobs are LF, this worktree is CRLF).

Empirical evidence: re-replay the recorded smoke DAY under CURRENT code with the requesting study's plan and
compare the persisted parquet sha256 against the atlas's recorded smoke manifest (produced under the OLD closure).
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from research_workflow.grammar.compiler import compile_study, load_spec              # noqa: E402
from research_workflow.lifecycle_v2 import V2Lifecycle                               # noqa: E402
from research_workflow.replay_closure import collection_closure, replay_plan_sha256  # noqa: E402

STUDY_SRC = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-nq_mtf_structural_predictive_ranking\studies\nq_mtf_structural_predictive_ranking\study.yaml")
ATLAS = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-nq_mtf_regime_structural_geometry_atlas\studies\nq_mtf_regime_structural_geometry_atlas")
ATLAS_COMMIT = "137a7e91"
CRLF = b"\r\n"
LF = b"\n"


def norm(b):
    return None if b is None else b.replace(CRLF, LF)


def git_show(commit, rel):
    r = subprocess.run(["git", "show", f"{commit}:{rel}"], capture_output=True, cwd=str(ROOT))
    return r.stdout if r.returncode == 0 else None


def run_text(args):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT)).stdout or ""


def main():
    out_path = Path(sys.argv[1])
    work = Path(tempfile.mkdtemp())
    d = work / "studies" / "nq_mtf_structural_predictive_ranking"
    d.mkdir(parents=True)
    (d / "study.yaml").write_text(STUDY_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    res = compile_study(load_spec(d), repo_root=ROOT)
    assert res.ok, res.card()
    plan = res.plan.to_dict()
    atlas_plan = json.loads((ATLAS / "compiled_plan.json").read_text(encoding="utf-8"))
    cur, old = collection_closure(plan), collection_closure(atlas_plan)

    report = {
        "A_recorded_atlas_replay_plan_sha256": replay_plan_sha256(atlas_plan),
        "B_current_replay_plan_sha256": replay_plan_sha256(plan),
        "replay_plan_identical": replay_plan_sha256(plan) == replay_plan_sha256(atlas_plan),
        "C_recorded_replay_closure": old["composite_sha256"],
        "D_current_replay_closure": cur["composite_sha256"],
        "closure_file_count": {"recorded": len(old["files"]), "current": len(cur["files"])},
        "closure_membership_identical": sorted(old["files"]) == sorted(cur["files"]),
    }

    changed = []
    for rel in sorted(set(cur["files"]) | set(old["files"])):
        a = norm(git_show(ATLAS_COMMIT, rel))
        b = norm((ROOT / rel).read_bytes()) if (ROOT / rel).is_file() else None
        if a != b:
            changed.append({"file": rel,
                            "sha_at_atlas_commit": hashlib.sha256(a).hexdigest() if a is not None else None,
                            "sha_current": hashlib.sha256(b).hexdigest() if b is not None else None})
    report["E_changed_replay_closure_files"] = changed

    classifications = []
    for entry in changed:
        rel = entry["file"]
        old_txt = (norm(git_show(ATLAS_COMMIT, rel)) or b"").decode("utf-8", "replace")
        new_txt = (norm((ROOT / rel).read_bytes()) or b"").decode("utf-8", "replace")
        needle = "grammar.spec" if rel.endswith("spec.py") else Path(rel).stem
        importers = [ln for ln in run_text(["git", "grep", "-n", needle]).splitlines()
                     if "import" in ln and any(ln.startswith(f + ":") for f in cur["files"])]
        diff = run_text(["git", "diff", "--unified=0", "--ignore-cr-at-eol", ATLAS_COMMIT, "--", rel])
        added = [l[1:].rstrip() for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        removed = [l[1:].rstrip() for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
        helper_same = None
        if "def duration_seconds" in old_txt and "def duration_seconds" in new_txt:
            helper_same = old_txt.split("def duration_seconds")[1][:800] == new_txt.split("def duration_seconds")[1][:800]
        classifications.append({
            "file": rel, "replay_path_importers": importers,
            "symbols_imported_on_replay_path": sorted({ln.split("import")[-1].strip() for ln in importers}),
            "lines_added": len(added), "lines_removed": len(removed), "added": added, "removed": removed,
            "replay_time_helper_unchanged": helper_same,
        })
    report["F_classification"] = classifications

    smokes = sorted((ATLAS / "runs").glob("*_smoke/collection/manifest.json"))
    rec = json.loads(smokes[-1].read_text(encoding="utf-8"))
    date = rec["date"]
    import pandas as pd
    s = int(pd.Timestamp(f"{date} 00:00:00", tz="UTC").value)
    e = int(pd.Timestamp(f"{date} 23:59:59.999999999", tz="UTC").value)
    from research_workflow.host_runner import run_plan_on_catalog
    run = run_plan_on_catalog(plan, start_date=date, end_date=date, repo_root=ROOT, primary_interval=(s, e),
                              warmup_days=plan["chronology"]["warmup"]["days_before_partition"])
    outdir = work / "replay"
    outdir.mkdir()
    man = V2Lifecycle._persist(run, outdir, {"kind": "smoke", "date": date, "plan_sha256": plan["plan_sha256"]})
    report["EMPIRICAL_smoke_equivalence"] = {
        "date": date, "recorded_source": str(smokes[-1]),
        "recorded_under_plan": rec["plan_sha256"], "recorded_under_closure": old["composite_sha256"],
        "replayed_under_plan": plan["plan_sha256"], "replayed_under_closure": cur["composite_sha256"],
        "recorded_rows": rec["rows"], "replayed_rows": man["rows"],
        "recorded_bars": rec["stats"]["bars"], "replayed_bars": man["stats"]["bars"],
        "candidates_sha256": {"recorded": rec["candidates_sha256"], "replayed": man["candidates_sha256"],
                              "identical": rec["candidates_sha256"] == man["candidates_sha256"]},
        "observations_sha256": {"recorded": rec["observations_sha256"], "replayed": man["observations_sha256"],
                                "identical": rec["observations_sha256"] == man["observations_sha256"]},
    }
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "F_classification"}, indent=1, default=str)[:2600])


if __name__ == "__main__":
    main()
