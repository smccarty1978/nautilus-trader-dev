"""THE FOUR STAGES, step 4 (EXPLORE): declared analysis over a REGISTERED frame by id.

Packet gates proven here:
  1. a frame registered by one study resolves in another, by id, with parity (the rows a second
     study -- a different id, a different worktree, no study directory at all -- reads are the
     rows the registering study merged);
  6. an EXPLORE run passes no seal, no audit, no closure, and leaves the frame byte-identical;
  -- measured: time from a registered frame to a table (reported in explore.json `elapsed`).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
import yaml

from research_workflow.tests.test_frame_store import _collect_spec, _options, _run_collect_through_merge, _study, synthetic_bars  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _explore_yaml(path: Path, *, frame_id: str | None = None, steps=None, artifacts=None) -> Path:
    body = {"explore": {"id": "golden_census", "question": "how many arm_a wins per direction?"},
            "analysis": {"steps": steps if steps is not None else [
                {"id": "wins", "op": "analysis.classify.precedence", "rows": "frame",
                 "params": {"output_column": "kind", "rules": [{"label": "win", "when": [["arm_a_label", "eq", 1]]}, {"label": "other", "when": []}]}}],
                         "artifacts": artifacts if artifacts is not None else [
                             {"name": "wins.json", "source": "wins", "kind": "json"}, {"name": "wins.parquet", "source": "wins", "kind": "frame"}]}}
    if frame_id:
        body["frame"] = frame_id
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def registered(tmp_path_factory, synthetic_bars):
    """One collect study run through merge and registered; its merged bytes captured; the study then DELETED."""
    from research_workflow.frame_store import register_frame
    bars, expected = synthetic_bars
    tmp = tmp_path_factory.mktemp("explore")
    frame_root = tmp / "frames"
    opts = _options(bars, expected)
    study = _study(tmp, "collect_src", _collect_spec("collect_src"))
    # pytest's monkeypatch is function-scoped; this fixture is module-scoped, so patch the worktree by hand
    from research_workflow.governed_controller_v2 import V2StudyController
    original = V2StudyController._worktree
    V2StudyController._worktree = lambda self: {"path": str(ROOT), "branch": "test", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []}
    try:
        class _MP:
            def setattr(self, *a, **k):
                pass
        _run_collect_through_merge(study, opts, _MP())
        merged = study / "_work" / "controller" / "merged"
        merged_sha = {n: _sha(merged / n) for n in ("candidates.parquet", "observations.parquet")}
        import pandas as pd
        merged_rows = pd.read_parquet(merged / "candidates.parquet")
        card = register_frame(study, frame_root=frame_root, repo_root=ROOT, options=opts)
    finally:
        V2StudyController._worktree = original
    assert card["result"] == "registered"
    receipt = json.loads((study / "artifacts" / "frame_registration.json").read_text())
    assert receipt["state"] == "FRAME_REGISTERED" and receipt["frame_id"] == card["frame_id"] and receipt["STATUS"] == "OK"
    shutil.rmtree(study)                       # the frame outlives the study
    return {"frame_id": card["frame_id"], "frame_root": frame_root, "merged_sha": merged_sha, "merged_rows": merged_rows, "tmp": tmp}


def test_gate1_frame_resolves_by_id_from_another_study_with_parity(registered, tmp_path, monkeypatch):
    """A second 'study' (another worktree, another cwd, no study directory) resolves the frame by id and reads
    exactly the rows the registering study merged."""
    from research_workflow.explore import run_explore
    from research_workflow.frame_store import load_frame, load_frame_record, verify_frame
    other = tmp_path / "other_worktree" / "studies" / "reader_study"; other.mkdir(parents=True)
    monkeypatch.chdir(other)
    fid = registered["frame_id"]
    rec = load_frame_record(fid, registered["frame_root"])
    assert rec["candidates_sha256"] == registered["merged_sha"]["candidates.parquet"]
    assert rec["observations_sha256"] == registered["merged_sha"]["observations.parquet"]
    frame = load_frame(fid, registered["frame_root"])
    assert len(frame) == len(registered["merged_rows"]) == rec["rows"] > 0
    key = ["observation_ts", "regime_start_ns", "checkpoint_index"]
    a = registered["merged_rows"].sort_values(key).reset_index(drop=True)[key]
    b = frame.sort_values(key).reset_index(drop=True)[key]
    assert a.equals(b), "the rows read by id are not the rows the registering study merged"
    # and via the runner: by id, from here, with the frame id resolved through NT_RESEARCH_FRAME_ROOT like an operator would
    monkeypatch.setenv("NT_RESEARCH_FRAME_ROOT", str(registered["frame_root"]))
    spec = _explore_yaml(other / "explore.yaml", frame_id=fid)
    card = run_explore(fid, spec, out_dir=other / "tables")
    assert card["STATUS"] == "OK" and card["rows"] == rec["rows"]
    wins = json.loads((other / "tables" / "wins.json").read_text())
    assert wins and (other / "tables" / "wins.parquet").is_file()
    assert verify_frame(fid, registered["frame_root"])["verified"]


def test_gate6_explore_passes_no_governance_and_leaves_the_frame_byte_identical(registered, tmp_path):
    from research_workflow.explore import EXPLORE_RECORD, run_explore
    from research_workflow.frame_store import frame_dir
    fid, root = registered["frame_id"], registered["frame_root"]
    fdir = frame_dir(fid, root)
    before = {p.relative_to(fdir).as_posix(): _sha(p) for p in fdir.rglob("*") if p.is_file()}
    spec = _explore_yaml(tmp_path / "explore.yaml")
    out = tmp_path / "out"
    card = run_explore(fid, spec, out_dir=out, frame_root=root)
    assert card["STATUS"] == "OK" and card["frame_unmodified"] is True
    after = {p.relative_to(fdir).as_posix(): _sha(p) for p in fdir.rglob("*") if p.is_file()}
    assert before == after, "the frame directory changed during EXPLORE"
    record = json.loads((out / EXPLORE_RECORD).read_text())
    # no seal, no audit, no closure, no deliverable gate: none of these exist in an explore run
    assert record["governance"] == {**record["governance"], "claim": None, "seal": None, "contract_audit": None, "closure": None, "deliverable_gate": None}
    written = sorted(p.name for p in out.iterdir())
    assert written == sorted(["explore.json", "wins.json", "wins.parquet"])
    # (the frame's own provenance/ carries the COLLECT study's frame seal -- registered with it, untouched here: before == after)
    for name in ("preexec_audit_seal.json", "study_closure.json", "frozen_execution_manifest.json", "contract_status.json", "status.json"):
        assert not list(out.rglob(name))
    # freely re-runnable: the same spec over the same frame writes the same tables again
    first = {p.name: _sha(p) for p in out.iterdir() if p.name != EXPLORE_RECORD}
    card2 = run_explore(fid, spec, out_dir=out, frame_root=root)
    assert card2["STATUS"] == "OK"
    assert {p.name: _sha(p) for p in out.iterdir() if p.name != EXPLORE_RECORD} == first
    assert before == {p.relative_to(fdir).as_posix(): _sha(p) for p in fdir.rglob("*") if p.is_file()}
    # measured: registered frame -> table
    el = record["elapsed"]
    assert el["total_s"] < 60 and set(el) == {"verify_s", "load_s", "pipeline_s", "total_s"}
    print(f"\nEXPLORE elapsed: {el} rows={record['rows']}")


def test_explore_compile_proves_the_pipeline_before_running(registered, tmp_path):
    from research_workflow.explore import ExploreError, compile_explore, load_explore_spec, run_explore
    fid, root = registered["frame_id"], registered["frame_root"]
    # unknown op, unbound input, undeclared artifact source, train_frame, empty artifacts
    bad = _explore_yaml(tmp_path / "bad.yaml", steps=[
        {"id": "a", "op": "analysis.no.such_op", "rows": "frame"},
        {"id": "b", "op": "analysis.control.cell_matched", "rows": "train_frame", "inputs": {"anchors": "zzz"}, "params": {}},
    ], artifacts=[{"name": "x.json", "source": "nope", "kind": "json"}])
    compiled, gaps = compile_explore(load_explore_spec(bad))
    assert compiled is None
    d = gaps.to_dict()
    kinds = {(g["where"], g["kind"]) for g in d["gaps"]}
    assert ("analysis.steps[0].op", "MISSING_CAPABILITY") in kinds
    assert ("analysis.steps[1].rows", "UNSUPPORTED_COMPOSITION") in kinds and ("analysis.steps[1].inputs.anchors", "UNSUPPORTED_COMPOSITION") in kinds
    assert ("analysis.artifacts[0].source", "UNSUPPORTED_COMPOSITION") in kinds
    assert any("train_frame" in g["message"] and "EXPLORE" in g["message"] for g in d["gaps"])
    # the study-only keys do not exist here
    for extra in ({"analysis": {"source": "oos", "steps": [], "artifacts": []}}, {"analysis": {"model_scores": True, "steps": [], "artifacts": []}}):
        compiled, gaps = compile_explore(extra)
        assert compiled is None and gaps.to_dict()["kinds"] == ["INVALID_PARAMETERIZATION"]
    # a run over a gapped spec writes nothing and reports the gaps
    card = run_explore(fid, bad, out_dir=tmp_path / "never", frame_root=root)
    assert card["STATUS"] == "CAPABILITY_GAP" and not (tmp_path / "never").exists()
    # a spec written against another frame refuses to run over this one
    wrong = _explore_yaml(tmp_path / "wrong.yaml", frame_id="0" * 64)
    with pytest.raises(ExploreError, match="EXPLORE_FRAME_MISMATCH"):
        run_explore(fid, wrong, out_dir=tmp_path / "never2", frame_root=root)
    with pytest.raises(ExploreError, match="EXPLORE_FRAME_UNAVAILABLE"):
        run_explore("f" * 64, _explore_yaml(tmp_path / "ok.yaml"), out_dir=tmp_path / "never3", frame_root=root)


def test_explore_cli_runs_by_frame_id(registered, tmp_path):
    import subprocess
    import sys
    fid, root = registered["frame_id"], registered["frame_root"]
    spec = _explore_yaml(tmp_path / "explore.yaml", frame_id=fid)
    env = {**os.environ, "NT_RESEARCH_FRAME_ROOT": str(root)}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "research.py"), "explore", "compile", "--spec", str(spec)], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1])["ops"] == ["analysis.classify.precedence"]
    out = tmp_path / "cli_out"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "research.py"), "explore", "run", "--frame", fid, "--spec", str(spec), "--out", str(out)],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    card = json.loads(r.stdout.strip().splitlines()[-1])
    assert card["STATUS"] == "OK" and card["frame_unmodified"] is True and (out / "wins.json").is_file()
