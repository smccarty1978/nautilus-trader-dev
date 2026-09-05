"""Population parity is a PRE-FIT gate, not a post-hoc report check.

The requirement was never "detect drift eventually" -- it was that a drifted population must
not reach the model comparison. Running the check at `analyze` protects the final report but
still lets the wrong rows be merged, fit, frozen and scored against OOS first: wasted compute,
and model artifacts produced from a population nobody authorized.

The gate therefore sits between `reconcile` and `merge`:

    collection -> reconcile -> population_parity -> merge -> fit -> freeze -> oos -> analyze

It reuses `analysis.gate.population_parity`; there is deliberately no second parity engine.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_workflow.governed_controller import RECEIPT_STAGES, STAGE_ORDER
from research_workflow.lifecycle_v2 import LifecycleV2Error, V2Lifecycle, V2Options

NS = 10 ** 9
YEAR = 2024
EXEMPT = "2024-12-31"


def test_the_gate_runs_after_reconcile_and_before_merge_and_fit():
    order = list(STAGE_ORDER)
    assert order[order.index("reconcile") + 1] == "population_parity"
    assert order.index("population_parity") < order.index("merge") < order.index("fit")
    assert order.index("population_parity") < order.index("freeze")
    assert order.index("population_parity") < order.index("oos")
    assert "population_parity" in RECEIPT_STAGES      # freshness is a hash-bound receipt


def _rows(days, per_day=4, start_key=0):
    out = []
    for di, day in enumerate(days):
        base = int(pd.Timestamp(day, tz="America/Chicago").tz_convert("UTC").value)
        for i in range(per_day):
            out.append({"observation_ts": base + (i + 1) * 60 * NS,
                        "regime_start_ns": base + di * 10_000 * NS + start_key,
                        "checkpoint_index": i,
                        "regime_direction": 1 if i % 2 == 0 else -1,
                        "f0": float(i), "f1": float(di)})
    return pd.DataFrame(out)


def _study(tmp_path: Path, population: pd.DataFrame, reference: pd.DataFrame, *,
           excluded=None, gate=True) -> Path:
    study = tmp_path / "studies" / "parity_probe"
    (study / "audit").mkdir(parents=True, exist_ok=True)
    part = study / "_work" / "controller" / "partitions" / "train" / str(YEAR)
    part.mkdir(parents=True, exist_ok=True)
    population.to_parquet(part / "candidates.parquet", index=False)
    obs = population[["observation_ts", "regime_start_ns", "checkpoint_index"]].copy()
    # both classes present: a single-class label makes the fit degenerate for reasons
    # that have nothing to do with the gate under test
    obs["target_flip_within_horizon"] = (np.arange(len(obs)) % 2).astype(int)
    obs["disposition"] = "LABELED"
    obs.to_parquet(part / "observations.parquet", index=False)

    refdir = tmp_path / "studies" / "parent_study" / "artifacts"
    refdir.mkdir(parents=True, exist_ok=True)
    refpath = refdir / "ref.parquet"
    reference.to_parquet(refpath, index=False)
    sha = hashlib.sha256(refpath.read_bytes()).hexdigest()

    params = {"reference_path": "parent_study/artifacts/ref.parquet", "reference_sha256": sha,
              "key": ["regime_start_ns", "checkpoint_index"],
              "reference_key": ["regime_start_ns", "checkpoint_index"],
              "timestamp_column": "observation_ts", "reference_timestamp_column": "observation_ts",
              "exclusion_timezone": "America/Chicago"}
    if excluded is not None:
        params["excluded_session_dates"] = excluded
    analysis = {"source": "train",
                "steps": [{"id": "parity", "op": "analysis.gate.population_parity", "rows": "frame",
                           "inputs": {}, "params": params, "gate": gate}],
                "artifacts": []}
    plan = {"plan_sha256": "p" * 64, "study": {"id": "parity_probe"},
            "columns": {"features": ["f0", "f1"], "derived": [], "metadata": []},
            "outcome": {"label_column": "target_flip_within_horizon", "kernel": "flip", "contract": "label"},
            "chronology": {"train": [YEAR], "dev": [], "prohibited": []},
            "model": {"mode": "train", "family": "model.lightgbm",
                      "params": {"n_estimators": 5, "max_depth": 2, "num_leaves": 4, "verbosity": -1, "random_state": 42},
                      "validation": {"protocol": "validation.model_selection.random", "tuning_years": [YEAR],
                                     "final_train_validation_years": []},
                      "arms": [], "cells": [], "reference_models": [], "models": [], "search_space": {}},
            "analysis": analysis}
    (study / "compiled_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (study / "audit" / "frozen_execution_manifest.json").write_text(
        json.dumps({"frozen_execution_composite_sha256": "c" * 64}), encoding="utf-8")
    return study


def _lc(study: Path, tmp_path: Path) -> V2Lifecycle:
    return V2Lifecycle(study, options=V2Options(execute=True, model_root=tmp_path / "store",
                                                studies_root=tmp_path / "studies"))


DAYS = ["2024-01-02", "2024-01-03"]


def test_parity_pass_allows_merge_and_fit(tmp_path):
    rows = _rows(DAYS)
    study = _study(tmp_path, rows, rows)
    lc = _lc(study, tmp_path)
    assert lc.population_parity()["status"] == "PASS"
    body = json.loads((study / "_work" / "controller" / "population_parity.json").read_text(encoding="utf-8"))
    assert body["status"] == "PASS" and body["gates"][0]["payload"]["status"] == "PASS"
    lc.merge()
    lc.fit()
    assert (study / "artifacts" / "experiment_models.json").is_file()


def test_parity_fail_blocks_before_any_model_artifact_exists(tmp_path):
    reference = _rows(DAYS)
    drifted = reference.iloc[:-1]                      # one candidate silently missing
    study = _study(tmp_path, drifted, reference)
    lc = _lc(study, tmp_path)
    with pytest.raises(LifecycleV2Error, match="POPULATION_PARITY_GATE_FAILED"):
        lc.population_parity()
    body = json.loads((study / "_work" / "controller" / "population_parity.json").read_text(encoding="utf-8"))
    assert body["status"] == "BLOCKED"
    assert "ANALYSIS_POPULATION_PARITY_FAILED" in body["gates"][0]["error"]
    # the point of the ordering: nothing downstream has been produced
    assert not (study / "_work" / "controller" / "merged").exists()
    assert not (study / "artifacts" / "experiment_models.json").exists()
    assert not (study / "artifacts" / "train_experiment_freeze.json").exists()


def test_a_declared_whole_session_exception_is_honoured(tmp_path):
    reference = _rows(DAYS)
    population = pd.concat([reference, _rows([EXEMPT], per_day=3, start_key=7)], ignore_index=True)
    study = _study(tmp_path, population, reference,
                   excluded=[{"date": EXEMPT, "reason": "parent source catalog has no bars for this session"}])
    lc = _lc(study, tmp_path)
    assert lc.population_parity()["status"] == "PASS"
    body = json.loads((study / "_work" / "controller" / "population_parity.json").read_text(encoding="utf-8"))
    ex = body["gates"][0]["payload"]["excluded_session_dates"]
    assert ex == [{"date": EXEMPT, "reason": "parent source catalog has no bars for this session",
                   "removed_from_population": 3, "removed_from_reference": 0}]


def test_a_stale_exception_blocks_rather_than_passing_quietly(tmp_path):
    rows = _rows(DAYS)                                  # nothing on the exempt date at all
    study = _study(tmp_path, rows, rows,
                   excluded=[{"date": EXEMPT, "reason": "no longer describes reality"}])
    with pytest.raises(LifecycleV2Error, match="POPULATION_PARITY_GATE_FAILED"):
        _lc(study, tmp_path).population_parity()


def test_an_exception_cannot_mask_drift_on_a_non_exempt_date(tmp_path):
    """The property that keeps the escape hatch narrow."""
    reference = _rows(DAYS)
    population = pd.concat([reference.iloc[:-1],                       # drift on 2024-01-03
                            _rows([EXEMPT], per_day=3, start_key=7)],  # legitimate exemption
                           ignore_index=True)
    study = _study(tmp_path, population, reference,
                   excluded=[{"date": EXEMPT, "reason": "parent source catalog has no bars for this session"}])
    with pytest.raises(LifecycleV2Error, match="POPULATION_PARITY_GATE_FAILED"):
        _lc(study, tmp_path).population_parity()
    body = json.loads((study / "_work" / "controller" / "population_parity.json").read_text(encoding="utf-8"))
    assert "1 reference key(s) absent" in body["gates"][0]["error"]


def test_a_study_declaring_no_gate_passes_the_stage_as_a_no_op(tmp_path):
    rows = _rows(DAYS)
    study = _study(tmp_path, rows, rows, gate=False)
    assert _lc(study, tmp_path).population_parity()["status"] == "PASS"
    body = json.loads((study / "_work" / "controller" / "population_parity.json").read_text(encoding="utf-8"))
    assert body["status"] == "NO_GATE_DECLARED"
