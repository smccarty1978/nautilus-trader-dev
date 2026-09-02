"""Platform-v2 item 04: the single controller owns every lifecycle stage."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_workflow.controller_contracts import ControllerState
from research_workflow.governed_controller import RECEIPT_STAGES, STAGE_ORDER, ControllerActions, GovernedStudyController

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _controller(tmp_path: Path, *, closure_outcome: str | None = None):
    study = tmp_path / "s"; study.mkdir(); calls = []; composite = "a" * 64
    def mk(name, extra=None):
        def leaf(s: Path):
            calls.append(name)
            if extra: extra(s)
            out = s / "_work" / "controller" / f"{name}.out"; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(name)
            return {"status": "PASS", "output_artifacts": [out], **({"partitions": [{"id": "2021", "status": "PASS"}]} if name in {"collection", "oos"} else {})}
        return leaf
    def compile(s): _write(s / "compiled_study.json", {"spec": {}}); calls.append("compile")
    def prepare(s): _write(s / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": composite}); calls.append("prepare")
    def readiness(s): _write(s / "audit/readiness.json", {"overall_status": "PASS"}); calls.append("readiness")
    def tests(s): _write(s / "_work/controller/test_summary.json", {"status": "PASS", "execution_composite_sha256": composite, "counts": {"passed": 1}}); calls.append("tests")
    def preflight(s): _write(s / "audit/preflight.json", {"status": "CLEAR", "execution_composite_sha256": composite}); calls.append("preflight")
    def seal(s): _write(s / "artifacts/preexec_audit_seal.json", {"ok": True}); calls.append("seal")
    def close(s):
        calls.append("close")
        _write(s / "artifacts/study_closure.json", {"schema_version": 1, "study_id": s.name, "status": "CLOSED", "outcome": closure_outcome or "DIAGNOSTIC_NEGATIVE", "terminal_decision": "P5_NO_MEANINGFUL_SIGNAL"})
        return {"status": "PASS", "output_artifacts": [s / "artifacts/study_closure.json"]}
    actions = ControllerActions(compile=compile, prepare=prepare, readiness=readiness, tests=tests, preflight=preflight, seal=seal,
                                smoke=mk("smoke"), collection=mk("collection"), reconcile=mk("reconcile"), merge=mk("merge"), fit=mk("fit"),
                                freeze=mk("freeze"), oos=mk("oos"), analyze=mk("analyze"), close=close)
    actions.synthetic_test = True
    c = GovernedStudyController(study, actions=actions)
    c._worktree = lambda: {"path": str(tmp_path), "branch": "test", "head": "x", "dirty_paths": [], "unsafe_dirty_paths": []}
    c._fingerprints = lambda: {"execution_composite": composite if (study / "audit/frozen_execution_manifest.json").exists() else None, "current_execution_composite": composite,
                               "approved_request": None, "study_spec": None, "compiled_study": None}
    c._valid_resume_handoff = lambda fp: None
    return study, c, calls, composite


def _clear_audits(study: Path, composite: str):
    _write(study / "audit/status.json", {"status": "CLEAR", "audited_execution_composite_sha256": composite})
    _write(study / "audit/contract_status.json", {"status": "CLEAR", "audited_execution_composite_sha256": composite})


def test_stage_order_covers_the_whole_lifecycle():
    assert STAGE_ORDER == ("compile", "prepare", "readiness", "preflight", "tests", "causal_audit", "contract_audit", "seal",
                           "smoke", "collection", "reconcile", "merge", "fit", "freeze", "oos", "analyze", "close")
    assert set(RECEIPT_STAGES) == {"smoke", "collection", "reconcile", "merge", "fit", "freeze", "oos", "analyze", "close"}


def test_all_late_stages_run_in_order_with_receipts_and_resume(tmp_path: Path):
    study, c, calls, composite = _controller(tmp_path)
    c.run(through="seal"); _clear_audits(study, composite); c.run(through="seal")
    calls.clear()
    card = c.run(through="analyze")
    assert card["state"] == ControllerState.READY_TO_CLOSE.value
    assert calls == ["smoke", "collection", "reconcile", "merge", "fit", "freeze", "oos", "analyze"]
    for stage in ("smoke", "collection", "reconcile", "merge", "fit", "freeze", "oos", "analyze"):
        receipt = json.loads((study / "_work/controller/receipts" / f"{stage}.json").read_text())
        assert receipt["status"] == "PASS" and receipt["execution_composite_sha256"] == composite
    calls.clear(); c.run(through="analyze")
    assert calls == []  # every stage fresh -> nothing re-executed


def test_stage_by_stage_states(tmp_path: Path):
    study, c, calls, composite = _controller(tmp_path)
    c.run(through="seal"); _clear_audits(study, composite); c.run(through="seal")
    expect = {"smoke": ControllerState.READY_TO_COLLECT, "collection": ControllerState.READY_TO_RECONCILE, "reconcile": ControllerState.READY_TO_MERGE,
              "merge": ControllerState.READY_TO_FIT, "fit": ControllerState.READY_TO_FREEZE, "freeze": ControllerState.READY_TO_OOS,
              "oos": ControllerState.READY_TO_ANALYZE, "analyze": ControllerState.READY_TO_CLOSE, "close": ControllerState.STUDY_CLOSED}
    for stage, state in expect.items():
        assert c.run(through=stage)["state"] == state.value, stage


def test_close_is_terminal_and_never_rerun(tmp_path: Path):
    study, c, calls, composite = _controller(tmp_path)
    c.run(through="seal"); _clear_audits(study, composite); c.run(through="seal")
    assert c.run(through="close")["state"] == ControllerState.STUDY_CLOSED.value
    calls.clear()
    assert c.run(through="close")["state"] == ControllerState.STUDY_CLOSED.value and calls == []


def test_corrupt_receipt_reruns_only_that_stage(tmp_path: Path):
    study, c, calls, composite = _controller(tmp_path)
    c.run(through="seal"); _clear_audits(study, composite); c.run(through="freeze")
    (study / "_work/controller/fit.out").write_text("tampered")
    calls.clear(); c.run(through="freeze")
    assert calls == ["fit", "freeze"]  # fit receipt invalid -> fit and downstream rerun; merge untouched


def test_missing_leaf_is_a_capability_blocker(tmp_path: Path):
    study, c, calls, composite = _controller(tmp_path)
    c.run(through="seal"); _clear_audits(study, composite); c.run(through="seal")
    c.actions.fit = None
    card = c.run(through="fit")
    assert card["STATUS"] == "BLOCKED" and card["blocker_code"] == "CAPABILITY_BLOCKER" and card["stage"] == "fit"


@pytest.mark.parametrize("script", ["run_research_workflow.py", "run_partitioned_train_collection.py", "reconcile_study_capabilities.py"])
def test_duplicate_orchestrators_are_deprecated_shims(script: str):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 2
    card = json.loads(r.stdout.strip().splitlines()[-1])
    assert card["STATUS"] == "DEPRECATED" and "research.py study run" in card["use"]


def test_production_close_requires_operator_decision(tmp_path: Path):
    from research_workflow.controller_actions import production_actions
    study = tmp_path / "studies" / "demo"; study.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="CLOSURE_DECISION_REQUIRED"):
        production_actions(execute_authorized=True).close(study)


def test_label_column_is_declared_or_explicit_never_guessed(tmp_path: Path):
    from research_workflow.controller_actions import _label_column
    study = tmp_path / "s"; study.mkdir()
    _write(study / "compiled_study.json", {"contracts": {"target_contract": {"primitive": "flip_within_horizon", "target_type": "flip"}}})
    assert _label_column(study, None) == "target_flip_within_horizon"
    _write(study / "compiled_study.json", {"contracts": {"target_contract": {"primitive": "ordered_barrier"}}})
    with pytest.raises(RuntimeError, match="LABEL_COLUMN_REQUIRED"):
        _label_column(study, None)
    assert _label_column(study, "target_tp1_sl1_0_label") == "target_tp1_sl1_0_label"
    _write(study / "compiled_study.json", {"contracts": {"target_contract": {"primitive": "composite", "label_column": "composite_label"}}})
    assert _label_column(study, None) == "composite_label"


def test_train_matrix_uses_declared_features_and_train_rows_only(tmp_path: Path):
    from research_workflow.controller_actions import _train_matrix
    study = tmp_path / "s"; mdir = study / "_work" / "controller" / "merged"; mdir.mkdir(parents=True)
    feats = ["f_a", "f_b"]
    _write(study / "compiled_study.json", {"contracts": {"feature_contract": {"feature_list": feats}, "target_contract": {"primitive": "flip_within_horizon", "target_type": "flip"}},
                                            "spec": {"chronology": {"train": [2021], "dev": [2024], "prohibited": [2025]}, "model": {"arms": ["A"]}}})
    n = 20
    ts = pd.Timestamp("2021-03-01", tz="UTC").value + np.arange(n) * 5_000_000_000
    cand = pd.DataFrame({"observation_ts": ts, "regime_start_ns": ts[0], "checkpoint_index": np.arange(n), "f_a": np.arange(n, dtype=float), "f_b": 1.0, "extra": 9.0})
    obs = pd.DataFrame({"observation_ts": ts, "regime_start_ns": ts[0], "checkpoint_index": np.arange(n), "target_flip_within_horizon": [None, 1, 0] * 6 + [1, 0]})
    cand.to_parquet(mdir / "candidates.parquet", index=False); obs.to_parquet(mdir / "observations.parquet", index=False)
    import hashlib
    _write(mdir / "identity.json", {"candidates_sha256": hashlib.sha256((mdir / "candidates.parquet").read_bytes()).hexdigest(),
                                    "observations_sha256": hashlib.sha256((mdir / "observations.parquet").read_bytes()).hexdigest(), "dataset_identity_sha256": "x"})
    _write(study / "_work/controller/receipts/merge.json", {"status": "PASS"})
    X, y, meta, arms, info = _train_matrix(study, label_column=None, arms=None)
    assert list(X.columns) == feats and "extra" not in X.columns
    assert info["n_censored_dropped"] == 6 and len(X) == 14 and set(y.unique()) <= {0, 1}
    assert set(meta["_partition"]) == {"train"} and arms == {"A": feats}
