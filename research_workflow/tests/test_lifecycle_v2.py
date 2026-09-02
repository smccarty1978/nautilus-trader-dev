"""The governed controller drives a fresh v2 study through every stage on the golden synthetic
data: compile -> prepare -> readiness -> preflight -> tests -> audits (packets, ingestion) ->
seal -> smoke -> collection -> reconcile -> merge -> fit -> freeze -> oos -> analyze -> close.
No study Python, no legacy collector, no real catalog."""
from __future__ import annotations

import json
import shutil
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


def _study_dir(tmp_path: Path) -> Path:
    study = tmp_path / "studies" / "golden_v2_flow"
    study.mkdir(parents=True)
    spec = (GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8")
    spec = spec.replace("id: golden_barrier", "id: golden_v2_flow").replace("chronology: {train: [2030], dev: [], prohibited: []}",
                                                                           "chronology: {train: [2029, 2030], dev: [2031], prohibited: [], authorized_dates: ['2030-01-01']}")
    spec = spec.replace("model: none", "model:\n  family: lightgbm\n  params: {n_estimators: 20, max_depth: 2, num_leaves: 4, learning_rate: 0.1, verbosity: -1}\n"
                                       "  validation: {protocol: model_selection.random, tuning_years: [2029, 2030], final_train_validation_years: []}")
    (study / "study.yaml").write_text(spec, encoding="utf-8")
    return study


def _write_audit(study: Path, kind: str, auditor: str) -> Path:
    frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text())["frozen_execution_composite_sha256"]
    name = "pass_01.md" if kind == "causal" else "contract_pass_01.md"
    block = {"verdict": "CLEAR", "audit_type": kind, "study": study.name, "auditor": auditor, "audited_execution_composite_sha256": frozen, "critical": 0, "warning": 0, "note": 1}
    p = study / "audit" / name
    p.write_text(f"# {kind} audit pass 01\n\nReviewed the packet.\n\n<!-- AUDIT_SUMMARY_V2_START -->\n{json.dumps(block)}\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    return p


def test_controller_runs_a_fresh_v2_study_end_to_end(tmp_path, synthetic_bars, monkeypatch):
    bars, expected = synthetic_bars
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow.lifecycle_v2 import V2Options, ingest_audit_report
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    study = _study_dir(tmp_path)
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    opts = V2Options(execute=True, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True,
                     closure={"outcome": "SYNTHETIC_FLOW_COMPLETE", "terminal_decision": "PLATFORM_V2_FLOW_PROVEN"})
    monkeypatch.setattr(V2StudyController, "_worktree", lambda self: {"path": str(ROOT), "branch": "test", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []})

    ctl = lambda: V2StudyController(study, options=opts, repo_root=ROOT)
    card = ctl().run(through="tests")
    assert card["STATUS"] == "OK" and card["actions_executed"] == ["compile", "prepare", "readiness", "preflight", "tests"], card
    assert (study / "compiled_plan.json").is_file() and (study / "audit" / "frozen_execution_manifest.json").is_file()
    assert json.loads((study / "audit" / "readiness.json").read_text())["overall_status"] == "PASS"
    assert json.loads((study / "audit" / "preflight.json").read_text())["status"] == "CLEAR"

    card = ctl().run(through="seal")
    assert card["state"] == "NEEDS_CAUSAL_AUDIT" and card["artifact"] and Path(card["artifact"]).name == "audit_packet_causal.json"
    packet = json.loads(Path(card["artifact"]).read_text())
    assert len(json.dumps(packet)) < 20_000 and packet["identity"]["execution_composite_sha256"]
    ingest_audit_report(study, "causal", _write_audit(study, "causal", "auditor_a"))
    card = ctl().run(through="seal")
    assert card["state"] == "NEEDS_CONTRACT_AUDIT"
    with pytest.raises(Exception):
        ingest_audit_report(study, "contract", _write_audit(study, "contract", "auditor_a"))   # distinct identities are enforced
    ingest_audit_report(study, "contract", _write_audit(study, "contract", "auditor_b"))
    card = ctl().run(through="seal")
    assert card["STATUS"] == "OK" and card["state"] == "READY_TO_SMOKE", card

    card = ctl().run(through="merge")
    assert card["STATUS"] == "OK" and card["state"] == "READY_TO_FIT", card
    smoke = json.loads((study / "artifacts" / "smoke_acceptance.json").read_text())
    assert smoke["status"] == "ACCEPTED" and smoke["candidates_count_total"] > 0
    parts = [json.loads((study / "_work" / "controller" / "partitions" / "train" / y / "manifest.json").read_text()) for y in ("2029", "2030")]
    assert sum(p["rows"]["candidates"] for p in parts) == expected["counts"]["barrier_candidates"] and all(p["rows"]["candidates"] > 0 for p in parts)
    receipts = study / "_work" / "controller" / "receipts"
    assert {p.stem for p in receipts.glob("*.json")} >= {"smoke", "collection", "reconcile", "merge"}

    card = ctl().run(through="freeze")
    assert card["STATUS"] == "OK" and card["state"] == "READY_TO_OOS", card
    models = json.loads((study / "artifacts" / "experiment_models.json").read_text())
    assert models["model_id"] and models["rows"]["binary"] > 0
    assert (study / "artifacts" / "train_experiment_freeze.json").is_file()

    card = ctl().run(through="analyze")
    assert card["STATUS"] == "OK" and card["state"] == "READY_TO_CLOSE", card
    analysis = json.loads((study / "artifacts" / "experiment_analysis_v2.json").read_text())
    assert analysis["oos_years"] == [2031]

    card = ctl().run(through="close")
    assert card["STATUS"] == "OK" and card["state"] == "STUDY_CLOSED", card
    from research_workflow.study_closure import load_study_closure
    assert load_study_closure(study)["outcome"] == "SYNTHETIC_FLOW_COMPLETE"
    # deterministic resume: nothing reruns once closed / receipts are fresh
    card = ctl().run(through="close")
    assert card["STATUS"] == "OK" and card["state"] == "STUDY_CLOSED" and not card["actions_executed"]
    assert not list(study.glob("**/*.py")), "a v2 study carries no study Python"


def test_controller_reports_typed_capability_gap(tmp_path, monkeypatch):
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow.lifecycle_v2 import V2Options
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    study = tmp_path / "studies" / "gap_study"; study.mkdir(parents=True)
    shutil.copy(GOLDEN / "study_add.yaml", study / "study.yaml")
    monkeypatch.setattr(V2StudyController, "_worktree", lambda self: {"path": str(ROOT), "branch": "t", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []})
    card = V2StudyController(study, options=V2Options(datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS), repo_root=ROOT).run(through="compile")
    assert card["STATUS"] == "BLOCKED" and card["blocker_code"] == "CAPABILITY_BLOCKER"
    assert any(g["kind"] == "MISSING_CAPABILITY" and g["where"] == "triggers.add" for g in card["capability_gaps"])


def test_second_controller_on_a_live_study_is_refused(tmp_path, monkeypatch):
    """One controller per study: a live run lock blocks a second run; a dead pid's lock is replaced."""
    import json as _json_mod
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow.lifecycle_v2 import V2Options
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    study = tmp_path / "studies" / "lock_study"; study.mkdir(parents=True)
    shutil.copy(GOLDEN / "study_barrier.yaml", study / "study.yaml")
    monkeypatch.setattr(V2StudyController, "_worktree", lambda self: {"path": str(ROOT), "branch": "t", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []})
    lock = study / "_work" / "controller" / "run.lock"; lock.parent.mkdir(parents=True)
    decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lock.write_text(_json_mod.dumps({"pid": decoy.pid, "started_at_utc": "now", "through": "analyze"}))
        card = V2StudyController(study, options=V2Options(datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS), repo_root=ROOT).run(through="compile")
        assert card["STATUS"] == "BLOCKED" and card["blocker_code"] == "STUDY_RUN_ALREADY_LIVE"
    finally:
        decoy.kill(); decoy.wait()
    lock.write_text(_json_mod.dumps({"pid": decoy.pid, "started_at_utc": "then", "through": "analyze"}))   # dead pid -> stale lock
    card = V2StudyController(study, options=V2Options(datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS), repo_root=ROOT).run(through="compile")
    assert card["STATUS"] == "OK" and not lock.exists()
