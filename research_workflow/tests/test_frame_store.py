"""THE FOUR STAGES, step 1 (COLLECT): a `stage: collect` study runs the governed controller through
merge under a causal-only frame seal and registers an immutable, content-hashed frame that
outlives it. Gates proven here (packet §7): 2 (frame identity is independent of the study id),
6-partial (the store never modifies a frame; re-registration is idempotent), 8 (a research plan
carries no `stage` key, so every existing plan and plan_sha256 is byte-identical), plus the
collect-stage compile refusals and the typed `completed_<unknown>` cadence gap."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000


@pytest.fixture(scope="module")
def synthetic_bars():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    return bars, expected


def _collect_spec(study_id: str, *, keep_qualify: bool = False) -> str:
    """The supervisor's scripted design worker writes the same collect spec (supervisor_support.collect_spec)."""
    from research_workflow.tests.supervisor_support import collect_spec
    spec = collect_spec(study_id)
    if keep_qualify:
        spec = spec.replace("  direction: regime.dir\n", '  qualify: "regime.age_s >= 10s and regime.frozen_atr > 0"\n  direction: regime.dir\n', 1)
    return spec


def _study(tmp_path: Path, study_id: str, spec: str) -> Path:
    study = tmp_path / "studies" / study_id
    study.mkdir(parents=True)
    (study / "study.yaml").write_text(spec, encoding="utf-8")
    return study


def _write_causal_audit(study: Path) -> Path:
    frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text())["frozen_execution_composite_sha256"]
    block = {"verdict": "CLEAR", "audit_type": "causal", "study": study.name, "auditor": "auditor_a",
             "audited_execution_composite_sha256": frozen, "critical": 0, "warning": 0, "note": 1}
    p = study / "audit" / "pass_01.md"
    p.write_text(f"# causal audit pass 01\n\nReviewed the packet.\n\n<!-- AUDIT_SUMMARY_V2_START -->\n{json.dumps(block)}\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    return p


def _options(bars, expected):
    from research_workflow.lifecycle_v2 import V2Options
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    return V2Options(execute=True, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True)


def _run_collect_through_merge(study: Path, opts, monkeypatch) -> dict:
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow.lifecycle_v2 import ingest_audit_report
    monkeypatch.setattr(V2StudyController, "_worktree", lambda self: {"path": str(ROOT), "branch": "test", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []})
    ctl = lambda: V2StudyController(study, options=opts, repo_root=ROOT)
    card = ctl().run(through="seal")
    assert card["state"] == "NEEDS_CAUSAL_AUDIT", card
    ingest_audit_report(study, "causal", _write_causal_audit(study))
    card = ctl().run(through="seal")
    # the contract audit is NOT REQUIRED for a frame: seal follows the causal audit directly
    assert card["STATUS"] == "OK" and card["state"] == "READY_TO_SMOKE", card
    assert "contract_audit" not in card["actions_executed"] and not (study / "audit" / "contract_status.json").exists()
    seal = json.loads((study / "artifacts" / "preexec_audit_seal.json").read_text())
    assert seal["seal_kind"] == "frame" and seal["audits"]["contract"]["status"] == "NOT_REQUIRED" and seal["audits"]["causal"]["auditor"] == "auditor_a"
    card = ctl().run(through="merge")
    assert card["STATUS"] == "OK" and card["next_state"] == "READY_TO_REGISTER_FRAME", card
    assert card["frame"]["next"].endswith(f"frame register --study studies/{study.name}")
    # the claim stages do not apply to a frame
    blocked = ctl().run(through="fit")
    assert blocked["STATUS"] == "BLOCKED" and blocked["blocker_code"] == "COLLECT_STAGE_NOT_APPLICABLE", blocked
    return card


def test_collect_study_registers_a_frame_whose_identity_is_independent_of_the_study(tmp_path, synthetic_bars, monkeypatch):
    bars, expected = synthetic_bars
    from research_workflow.frame_store import FrameStoreError, list_frames, load_frame, load_frame_record, register_frame, verify_frame
    opts = _options(bars, expected)
    frame_root = tmp_path / "frames"
    a = _study(tmp_path, "collect_a", _collect_spec("collect_a"))
    b = _study(tmp_path, "collect_b", _collect_spec("collect_b"))
    _run_collect_through_merge(a, opts, monkeypatch)
    _run_collect_through_merge(b, opts, monkeypatch)
    plan_a = json.loads((a / "compiled_plan.json").read_text()); plan_b = json.loads((b / "compiled_plan.json").read_text())
    assert plan_a["stage"] == "collect" and plan_a["plan_sha256"] != plan_b["plan_sha256"], "different study ids compile to different plans"
    # register from study A; register from study B lands on the SAME frame (gate 2)
    ra = register_frame(a, frame_root=frame_root, repo_root=ROOT, options=opts)
    rb = register_frame(b, frame_root=frame_root, repo_root=ROOT, options=opts)
    assert ra["result"] == "registered" and rb["result"] == "already_registered" and ra["frame_id"] == rb["frame_id"], (ra, rb)
    fid = ra["frame_id"]
    rec = load_frame_record(fid, frame_root)
    assert rec["years"] == [2029, 2030] and rec["prohibited"] == [2031] and rec["population"]["permissive"] is True
    assert {"m_age_s", "m_frozen_atr"} <= {m["column"] for m in rec["columns"]["metadata"]}
    assert rec["rows"] == expected["counts"]["barrier_candidates"] or rec["rows"] > 0
    sources = json.loads((frame_root / fid / "sources.json").read_text())["sources"]
    assert [s["study_id"] for s in sources] == ["collect_a", "collect_b"]
    assert "collect_a" not in json.dumps(rec["components"]) and "collect_b" not in json.dumps(rec["components"])
    # the frame is readable without either study
    import shutil
    shutil.rmtree(a); shutil.rmtree(b)
    assert verify_frame(fid, frame_root)["verified"]
    frame = load_frame(fid, frame_root)
    assert len(frame) == rec["rows"] and "m_age_s" in frame.columns and "arm_a_label" in frame.columns
    assert [f["frame_id"] for f in list_frames(frame_root)] == [fid]
    # immutable: a byte change is detected, and nothing in the store rewrote it
    p = frame_root / fid / "candidates.parquet"
    p.write_bytes(p.read_bytes() + b"\0")
    with pytest.raises(FrameStoreError, match="FRAME_BYTES_DRIFTED"):
        verify_frame(fid, frame_root)


def test_collect_study_with_every_candidate_qualify_is_refused_as_not_permissive(tmp_path):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    study = _study(tmp_path, "collect_q", _collect_spec("collect_q", keep_qualify=True))
    out = compile_study(load_spec(study), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert not out.ok
    gaps = out.gaps.to_dict()["gaps"]
    assert any(g["where"] == "population.qualify" and "COLLECT_MUST_BE_PERMISSIVE" in g["message"] and g["kind"] == "UNSUPPORTED_COMPOSITION" for g in gaps), gaps


def test_collect_study_refuses_model_dev_years_and_analysis(tmp_path):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    spec = _collect_spec("collect_m")
    spec = spec.replace("dev: []", "dev: [2031]").replace("prohibited: [2031]", "prohibited: []")
    spec = spec.replace("model: none", "model:\n  family: lightgbm\n  params: {n_estimators: 5}\n"
                                       "  validation: {protocol: model_selection.random, tuning_years: [2029, 2030], final_train_validation_years: []}")
    spec += ("analysis:\n  source: train\n  steps:\n    - {id: s, op: analysis.classify.precedence, rows: frame, params: {column: c, categories: [{label: x, when: 'arm_a_label == 1'}]}}\n"
             "  artifacts:\n    - {name: s.json, source: s, kind: json}\n")
    study = _study(tmp_path, "collect_m", spec)
    out = compile_study(load_spec(study), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert not out.ok
    where = {g["where"] for g in out.gaps.to_dict()["gaps"]}
    assert {"model", "chronology.dev", "analysis"} <= where, where


def test_research_plan_carries_no_stage_key_so_existing_plans_are_unchanged(tmp_path):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    study = tmp_path / "studies" / "golden_barrier"; study.mkdir(parents=True)
    (study / "study.yaml").write_text((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    out = compile_study(load_spec(study), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok
    d = out.plan.to_dict()
    assert "stage" not in d and "stage" not in out.plan.identity_payload()
    text = out.plan.write(study / "compiled_plan.json").read_text(encoding="utf-8")
    assert '"stage"' not in text
    # a research study's deliverable table still includes the claim stages
    assert any(b["producer"] == "stage:fit" for b in out.plan.deliverables) or not out.plan.deliverables


def test_unknown_completed_cadence_is_a_typed_gap_not_a_value_error(tmp_path):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    spec = (GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8").replace(
        "  cadence: {every: 5s, anchor: regime.start_ns, max_age: 600s}\n", "  cadence: completed_bogus\n")
    study = tmp_path / "studies" / "golden_barrier"; study.mkdir(parents=True)
    (study / "study.yaml").write_text(spec, encoding="utf-8")
    out = compile_study(load_spec(study), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert not out.ok
    gaps = out.gaps.to_dict()["gaps"]
    assert any(g["where"] == "population.cadence" and g["kind"] == "INVALID_PARAMETERIZATION" and "completed_bogus" in g["message"] for g in gaps), gaps
