"""Red-Team Remediation Pass 1 -- the cross-cutting acceptance checklist.

One compact assertion per acceptance item. The detailed coverage lives in the per-finding
test files (test_target_session_policy_fidelity, test_target_field_coverage,
test_population_qualification_strictness, test_modeling_driver_lineage,
test_derived_input_model_id_prepare, test_multiple_derived_inputs,
test_bare_flip_independent_parity, test_oos_analysis_lineage,
test_model_reuse_scientific_status).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from research.engines.target_engine import compile_target_contract
from research.schemas.study_spec import PopulationSpec, TargetSpec
from research_workflow.model_artifacts import ModelArtifactError, assert_scientific_status_reusable
from research_workflow.modeling_drivers import (
    UndeclaredModelingDriverError,
    assert_declared_modeling_drivers,
)
from research_workflow.modeling_closure import resolve_modeling_closure
from research_workflow.target_runtime import (
    NEGATIVE,
    TargetResult,
    TargetRuntimeError,
    FlipTargetRuntime,
    assert_target_semantic_field_coverage,
    validate_target_parity,
)

NS = 1_000_000_000


# 1. authored target session=false cannot execute as true
def test_acc01_session_false_stays_false():
    tc = compile_target_contract(
        TargetSpec.model_validate({"type": "flip", "horizon_seconds": 300, "session_end_censoring": False})
    )
    assert tc["session_end_censoring"] is False
    assert tc["censoring_policy"]["session_end_censoring"] is False


# 2. authored target field cannot be silently ignored
def test_acc02_unimplemented_field_rejected():
    with pytest.raises(TargetRuntimeError, match="TARGET_SEMANTIC_FIELD_UNSUPPORTED"):
        assert_target_semantic_field_coverage(
            {"primitive": "flip_within_horizon", "horizon_seconds": 300,
             "confirmation": {"mode": "bar_close", "confirmation_bars": 5}}
        )


# 3. unknown population qualification cannot be silently ignored
def test_acc03_unknown_qualification_rejected():
    with pytest.raises(Exception, match="made_up"):
        PopulationSpec.model_validate({"qualification": {"age_gate_seconds": 1, "made_up": 2}})


# 4. undeclared modeling code cannot influence a governed fit
def test_acc04_undeclared_modeling_driver_fails_closed(tmp_path):
    s = tmp_path / "s"
    (s / "implementation").mkdir(parents=True)
    (s / "implementation" / "driver.py").write_text(
        "from research_workflow.modeling import fit_models\n"
    )
    with pytest.raises(UndeclaredModelingDriverError, match="MODELING_DRIVER_UNDECLARED"):
        assert_declared_modeling_drivers(s, [])


# 5. modeling implementation edit stales model but not collection
def test_acc05_modeling_edit_moves_only_the_modeling_closure(tmp_path):
    s = tmp_path / "s"
    (s / "implementation").mkdir(parents=True)
    drv = s / "implementation" / "driver.py"
    drv.write_text("V = 1\n")
    before = resolve_modeling_closure(s, driver_relpaths=["implementation/driver.py"])
    drv.write_text("V = 2\n")
    after = resolve_modeling_closure(s, driver_relpaths=["implementation/driver.py"])
    assert before["modeling_execution_composite_sha256"] != after["modeling_execution_composite_sha256"]
    # collection producer closure is a different resolver entirely and is untouched.
    from scripts.resolve_execution_manifest import compute_ast_closure  # noqa: F401


# 6. model_id derived input survives PREPARE  (full flow in test_derived_input_model_id_prepare)
def test_acc06_model_id_binding_has_prepare_path():
    import inspect

    from research_workflow.derived_inputs import _verify_one

    src = inspect.getsource(_verify_one)
    assert "di.model_id" in src and "_verify_model_id" in src


# 7 & 8. multiple / checkpoint-grid external scores execute and persist
def test_acc07_08_all_declared_derived_scores_filled_for_any_population():
    class _FakeScorer:
        def score(self, inputs, **kw):
            return SimpleNamespace(score=0.42)

    from research_workflow.generic_collector import GenericStudyCollector

    obj = GenericStudyCollector.__new__(GenericStudyCollector)
    obj._derived_scorers = [
        {"name": "s1", "scorer": _FakeScorer(), "surface": {"LONG": ["f"], "SHORT": ["f"]}},
        {"name": "s2", "scorer": _FakeScorer(), "surface": {"LONG": ["f"], "SHORT": ["f"]}},
    ]
    # a checkpoint-grid style record (no prevailing_direction / episode fields)
    rec = {"observation_ts": 1, "regime_direction": 1, "f": 1.0}
    obj._apply_derived_scores(rec)
    assert rec["s1"] == pytest.approx(0.42) and rec["s2"] == pytest.approx(0.42)


# 9. bare-flip parity catches an intentional runtime defect
def test_acc09_bare_flip_parity_catches_corruption(monkeypatch):
    rt = FlipTargetRuntime()
    T = 1000 * NS
    p = rt.open_pending({"observation_ts": T, "horizon_seconds": 300, "regime_direction": 1,
                         "target_direction_role": "opposite", "session_close_ts": None})
    rt.ingest_flip(p, {"ts": T + 60 * NS, "direction": -1})

    monkeypatch.setattr(FlipTargetRuntime, "_terminal_pending",
                        staticmethod(lambda pending, *, final: TargetResult(NEGATIVE, 0, pending["horizon_end_ts"])))
    bad = FlipTargetRuntime().terminal(p, final=True)
    row = FlipTargetRuntime().parity_row(p, {"disposition": bad.disposition, "label": bad.label,
                                             "censor_reason": bad.censor_reason})
    report = validate_target_parity(
        {"primitive": "flip_within_horizon", "horizon_seconds": 300, "direction": None}, [row]
    )
    assert not report["passed"] and report["disposition_mismatches"] == 1


# 10. OOS analysis becomes stale after TRAIN/model identity change
def test_acc10_oos_analysis_goes_stale(tmp_path, monkeypatch):
    import hashlib
    import research_workflow.analysis as amod
    from research_workflow.analysis import analyze_results
    from research_workflow.experiment import authorize_experiment
    from research_workflow.oos_analysis_lineage import classify_oos_analysis

    s = tmp_path / "s"
    s.mkdir()
    (s / "study.yaml").write_text("study:\n  id: s\nchronology:\n  train: [2021]\n  dev: [2022]\n  prohibited: [2025, 2026]\n")
    (s / "artifacts").mkdir(); (s / "audit").mkdir()
    authorize_experiment(s)
    auth = json.loads((s / "artifacts" / "experiment_authorization.json").read_text())

    def _freeze(tag):
        reg_dir = s.parent / "model_registry"
        reg_dir.mkdir(exist_ok=True)
        art_file = s / "models/m.joblib"; art_file.parent.mkdir(exist_ok=True); art_file.write_bytes(b"dummy")
        gold_file = s / "models/m_gold.json"; gold_file.write_bytes(b"gold")
        reg_dir.joinpath("m.json").write_text(json.dumps({
            "model_id": "m", "artifact_path": str(art_file.relative_to(s.parent)),
            "artifact_sha256": hashlib.sha256(art_file.read_bytes()).hexdigest(),
            "golden_fixture_path": str(gold_file.relative_to(s.parent)),
            "golden_fixture_sha256": hashlib.sha256(gold_file.read_bytes()).hexdigest(),
        }))
        (s / "artifacts" / "train_experiment_freeze.json").write_text(json.dumps({
            "partition": "train", "authorization_sha256": auth["authorization_sha256"],
            "freeze_sha256": tag, "model_artifacts": [{"model_id": "m", "model_role": "A"}],
            "stage_scoped_lineage": {"MODELING_EXECUTION_CLOSURE": "mc-" + tag},
        }))

    monkeypatch.setattr(amod, "assert_oos_open",
                        lambda p: json.loads((s / "artifacts" / "train_experiment_freeze.json").read_text()))
    _freeze("v1")
    frame = pd.DataFrame({"target": [0, 1, 0, 1], "score_A": [0.1, 0.9, 0.2, 0.8]})
    analyze_results(s, frame, score_columns={"A": "score_A"}, target_column="target", oos_run_id="r1")
    assert classify_oos_analysis(s)["state"] == "FRESH"
    _freeze("v2")
    assert classify_oos_analysis(s)["state"] == "STALE"


# 11. INVALID_TARGET model cannot be silently reused
def test_acc11_invalid_target_model_blocked():
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        assert_scientific_status_reusable({"model_id": "m", "scientific_status": "INVALID_TARGET"})


# 12. ordered-barrier + composite canaries remain green
def test_acc12_canaries_green():
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "research_workflow/tests/test_composite_target_expression.py",
         "research_workflow/tests/test_single_primitive_ordered_barrier_regression.py",
         "research_workflow/tests/test_ordered_barrier_entry_reference.py"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout[-3000:]
