"""Predeclared arms, direction cells, monthly folds and alongside-reference scoring.

Before this, a study could declare `arms: [A, B, C]` and Platform V2 would compile it, run
it, and silently fit ONE model on the union feature surface with direction="both" and one
hyperparameter set. Nothing errored. That is a wrong-experiment risk, not a missing
convenience: the artifacts look like the declared protocol and are not it.

The tests here pin four things:

  * a BARE arm list is now REFUSED at compile with SEMANTIC_DECISION_REQUIRED, so the silent
    path cannot be taken by accident (test_bare_arm_list_is_refused);
  * declared arms x cells actually train separate models, on their own columns, with their
    own hyperparameters (test_arms_x_cells_train_independently);
  * monthly folds are derived AT COMPILE TIME with every fit window strictly preceding its
    validation window (test_month_folds_*), so "no future month in a fold's training set" is
    a checkable property of the plan rather than a promise in prose;
  * paired arm deltas are computed only over IDENTICAL validation rows, and a row-count
    mismatch is reported as unpaired rather than differenced (test_paired_deltas_*).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_workflow.grammar.spec import StudySpecV2
from research_workflow.lifecycle_v2 import KEY, LifecycleV2Error, V2Lifecycle, V2Options

NS = 1_000_000_000
FEATURES = ["f_base_a", "f_base_b", "f_extra_c", "f_extra_d"]


# --------------------------------------------------------------------------- #
# compile-surface tests (no execution)
# --------------------------------------------------------------------------- #
def _compile(tmp_path: Path, model_block: str, study_id: str = "arm_probe"):
    """Compile the proven 13-feature 180s surface with a substituted model block."""
    import yaml

    from research_workflow.grammar.compiler import compile_study
    base = Path(__file__).resolve().parents[2] / "studies" / "v2_shape_a_flip_180s" / "study.yaml"
    spec = base.read_text(encoding="utf-8")
    spec = spec.replace("id: v2_shape_a_flip_180s", f"id: {study_id}")
    spec = spec.replace("dataset: NQ_1S_V2,", "dataset: NQ_1S_V2_GLOBEX,")
    head, _, _ = spec.partition("\nmodel:")
    return compile_study(yaml.safe_load(head + "\n" + model_block))


def _gaps(result):
    report = result.gaps
    if report is None:
        return []
    return [(g.kind.value if hasattr(g.kind, "value") else str(g.kind), str(g.where), str(g.message))
            for g in report.gaps]


def test_bare_arm_list_is_refused(tmp_path):
    """The exact declaration that used to compile and silently train one model."""
    res = _compile(tmp_path, "model:\n  family: lightgbm\n  arms: [BASELINE, PLUS_VOLUME]\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: model_selection.random, tuning_years: [2021]}\n")
    gaps = _gaps(res)
    hit = [g for g in gaps if g[1] == "model.arms"]
    assert hit, f"a bare arm list must be refused; gaps were {gaps}"
    assert "SEMANTIC_DECISION_REQUIRED" in hit[0][0]
    assert "informational" in hit[0][2] and "ONE model" in hit[0][2]


def test_declared_arms_compile_and_carry_their_own_features(tmp_path):
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  arms:\n"
                             "    - {id: A, baseline: true, features: [arrival_velocity, ema_slope]}\n"
                             "    - {id: B, features: [arrival_velocity, ema_slope, rolling_300s_giveback_atr]}\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: model_selection.random, tuning_years: [2021]}\n")
    assert not _gaps(res), _gaps(res)
    arms = res.plan.model["arms"]
    assert [a["id"] for a in arms] == ["A", "B"]
    assert arms[0]["baseline"] is True and arms[1]["baseline"] is False
    assert arms[1]["features"] == ["arrival_velocity", "ema_slope", "rolling_300s_giveback_atr"]


def test_arm_naming_a_feature_outside_the_surface_is_refused(tmp_path):
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  arms:\n"
                             "    - {id: A, baseline: true, features: [arrival_velocity]}\n"
                             "    - {id: B, features: [not_a_declared_feature]}\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: model_selection.random, tuning_years: [2021]}\n")
    assert any("model.arms[1].features" in g[1] for g in _gaps(res)), _gaps(res)


def test_cell_filtering_on_an_unemitted_column_is_refused(tmp_path):
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  cells:\n    - {id: LONG, subset: {no_such_column: 1}}\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: model_selection.random, tuning_years: [2021]}\n")
    assert any("model.cells[0].subset" in g[1] for g in _gaps(res)), _gaps(res)


def test_month_folds_are_derived_at_compile_time(tmp_path):
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: walk_forward_months, fold_months_year: 2021,\n"
                             "               train_months: 3, validate_months: 1, step_months: 1}\n")
    assert not _gaps(res), _gaps(res)
    folds = res.plan.model["validation"]["month_folds"]
    assert len(folds) == 9, [f["fold"] for f in folds]
    assert folds[0] == {"fold": "2021-04", "fit_months": ["2021-01", "2021-02", "2021-03"],
                        "validation_months": ["2021-04"]}
    assert folds[-1]["validation_months"] == ["2021-12"]


def test_every_month_fold_fits_strictly_before_it_validates(tmp_path):
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: walk_forward_months, fold_months_year: 2021,\n"
                             "               train_months: 3, validate_months: 1, step_months: 1}\n")
    for f in res.plan.model["validation"]["month_folds"]:
        assert max(f["fit_months"]) < min(f["validation_months"]), f


def test_reference_models_compile_alongside_trained_arms(tmp_path):
    """A frozen reference is scored on the SAME rows the arms train on. mode stays train."""
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: model_selection.random, tuning_years: [2021]}\n"
                             "  reference_models:\n"
                             f"    - {{id: {'a' * 64}, name: PARENT_LONG, label: target_flip_within_horizon}}\n")
    assert not _gaps(res), _gaps(res)
    refs = res.plan.model["reference_models"]
    assert len(refs) == 1 and refs[0]["name"] == "PARENT_LONG"
    assert res.plan.model["mode"] == "train", "a reference must not flip the study into score mode"


def test_reference_model_with_a_foreign_label_is_refused(tmp_path):
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: model_selection.random, tuning_years: [2021]}\n"
                             "  reference_models:\n"
                             f"    - {{id: {'a' * 64}, label: not_an_outcome_of_this_study}}\n")
    assert any("model.reference_models[0].label" in g[1] for g in _gaps(res)), _gaps(res)


def test_reference_model_id_must_be_a_store_sha256(tmp_path):
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: model_selection.random, tuning_years: [2021]}\n"
                             "  reference_models:\n"
                             "    - {id: not-a-sha, label: target_flip_within_horizon}\n")
    assert any("model.reference_models[0].id" in g[1] for g in _gaps(res)), _gaps(res)


def test_month_folds_may_not_walk_a_dev_year(tmp_path):
    res = _compile(tmp_path, "model:\n  family: lightgbm\n"
                             "  params: {n_estimators: 20, verbosity: -1, random_state: 42}\n"
                             "  validation: {protocol: walk_forward_months, fold_months_year: 2022,\n"
                             "               train_months: 3, validate_months: 1}\n")
    assert any("fold_months_year" in g[1] for g in _gaps(res)), _gaps(res)


# --------------------------------------------------------------------------- #
# fit-stage tests on a fabricated merged frame (real estimators, no collection)
# --------------------------------------------------------------------------- #
def _fabricate(study: Path, *, model: dict, n: int = 1600, year: int = 2021) -> None:
    rng = np.random.default_rng(5)
    ts = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", periods=n, tz="UTC")
    direction = rng.choice([1, -1], size=n)
    x = rng.normal(size=(n, len(FEATURES)))
    # Signal lives in f_extra_c only, and only for the LONG cell -- so an arm that excludes it
    # and a cell that excludes those rows are genuinely different experiments.
    logit = 0.2 * x[:, 0] + np.where(direction == 1, 1.6 * x[:, 2], 0.0)
    y = (rng.uniform(size=n) < 1 / (1 + np.exp(-logit))).astype(int)
    cand = pd.DataFrame({"observation_ts": ts.astype("int64"),
                         "regime_start_ns": (ts.astype("int64") // (3600 * NS)) * 3600 * NS,
                         "checkpoint_index": np.arange(n) % 7,
                         "regime_direction": direction})
    for i, f in enumerate(FEATURES):
        cand[f] = x[:, i]
    obs = cand[list(KEY)].copy()
    obs["target_flip_within_horizon"] = y
    obs["disposition"] = "LABELED"
    merged = study / "_work" / "controller" / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    cand.to_parquet(merged / "candidates.parquet", index=False)
    obs.to_parquet(merged / "observations.parquet", index=False)
    (merged / "identity.json").write_text(json.dumps({"candidates_identity": "fab"}), encoding="utf-8")
    (study / "audit").mkdir(parents=True, exist_ok=True)
    (study / "audit" / "frozen_execution_manifest.json").write_text(
        json.dumps({"frozen_execution_composite_sha256": "c" * 64}), encoding="utf-8")
    plan = {"plan_sha256": "p" * 64, "study": {"id": study.name},
            "columns": {"features": FEATURES, "derived": [], "metadata": ["regime_direction"]},
            "outcome": {"label_column": "target_flip_within_horizon", "kernel": "flip", "contract": "label"},
            "chronology": {"train": [year], "dev": [], "prohibited": []}, "model": model}
    (study / "compiled_plan.json").write_text(json.dumps(plan), encoding="utf-8")


def _fit(tmp_path: Path, model: dict, name: str = "fit_probe") -> dict:
    study = tmp_path / "studies" / name
    study.mkdir(parents=True, exist_ok=True)
    _fabricate(study, model=model)
    lc = V2Lifecycle(study, options=V2Options(execute=True, model_root=tmp_path / "store"))
    lc.fit()
    return json.loads((study / "artifacts" / "experiment_models.json").read_text(encoding="utf-8"))


_PARAMS = {"n_estimators": 30, "max_depth": 2, "num_leaves": 4, "verbosity": -1, "random_state": 42}
_VAL = {"protocol": "validation.walk_forward_months", "tuning_years": [2021], "final_train_validation_years": [],
        "fold_months_year": 2021, "train_months": 3, "validate_months": 1, "step_months": 1,
        "month_folds": [{"fold": f"2021-{m:02d}",
                         "fit_months": [f"2021-{k:02d}" for k in range(m - 3, m)],
                         "validation_months": [f"2021-{m:02d}"]} for m in range(4, 13)]}


def test_arms_x_cells_train_independently(tmp_path):
    body = _fit(tmp_path, {
        "mode": "train", "family": "model.lightgbm", "params": _PARAMS, "validation": _VAL,
        "arms": [{"id": "A", "features": ["f_base_a", "f_base_b"], "params": {}, "baseline": True},
                 {"id": "B", "features": ["f_base_a", "f_base_b", "f_extra_c"], "params": {}, "baseline": False}],
        "cells": [{"id": "LONG", "subset": {"regime_direction": 1}, "params": {"n_estimators": 40}},
                  {"id": "SHORT", "subset": {"regime_direction": -1}, "params": {"n_estimators": 20}}],
        "reference_models": [], "models": [], "search_space": {}})
    got = {(m["arm"], m["cell"]) for m in body["models"]}
    assert got == {("A", "LONG"), ("A", "SHORT"), ("B", "LONG"), ("B", "SHORT")}
    assert len({m["model_id"] for m in body["models"]}) == 4, "each (arm, cell) needs its own identity"
    by = {(m["arm"], m["cell"]): m for m in body["models"]}
    assert by[("A", "LONG")]["features"] == ["f_base_a", "f_base_b"]
    assert by[("B", "LONG")]["features"] == ["f_base_a", "f_base_b", "f_extra_c"]
    # per-CELL hyperparameters are what makes a direction-specific configuration declarable
    assert by[("A", "LONG")]["hyperparameters"]["n_estimators"] == 40
    assert by[("A", "SHORT")]["hyperparameters"]["n_estimators"] == 20
    assert by[("A", "LONG")]["direction"] == "1" and by[("A", "SHORT")]["direction"] == "-1"


def test_cells_partition_the_population(tmp_path):
    body = _fit(tmp_path, {
        "mode": "train", "family": "model.lightgbm", "params": _PARAMS, "validation": _VAL,
        "arms": [{"id": "A", "features": FEATURES, "params": {}, "baseline": True}],
        "cells": [{"id": "LONG", "subset": {"regime_direction": 1}, "params": {}},
                  {"id": "SHORT", "subset": {"regime_direction": -1}, "params": {}}],
        "reference_models": [], "models": [], "search_space": {}})
    rows = {m["cell"]: m["final_fit_rows"] for m in body["models"]}
    assert rows["LONG"] + rows["SHORT"] == body["rows"]["binary"]
    assert min(rows.values()) > 0


def test_monthly_folds_execute_and_report_effective_sample_size(tmp_path):
    body = _fit(tmp_path, {
        "mode": "train", "family": "model.lightgbm", "params": _PARAMS, "validation": _VAL,
        "arms": [{"id": "A", "features": FEATURES, "params": {}, "baseline": True}],
        "cells": [], "reference_models": [], "models": [], "search_space": {}})
    assert body["fold_protocol"] == "walk_forward_months"
    folds = body["models"][0]["metrics"]["folds"]
    assert [f["fold"] for f in folds] == [f"2021-{m:02d}" for m in range(4, 13)]
    ok = [f for f in folds if f["status"] == "OK"]
    assert ok, "no fold executed"
    for f in ok:
        # regime counts, not just row counts: 5s checkpoints inside one regime are not
        # independent samples and the artifact must not let a reader assume they are.
        assert f["train_unique_regimes"] is not None
        assert f["metrics"]["unique_regimes"] is not None
        assert f["metrics"]["base_rate"] is not None


def test_train_derived_thresholds_come_from_the_fit_window(tmp_path):
    """P90/P95 are quantiles of the FIT window's scores, applied unchanged to validation.
    Deriving them from validation rows would leak the very rows being judged."""
    body = _fit(tmp_path, {
        "mode": "train", "family": "model.lightgbm", "params": _PARAMS, "validation": _VAL,
        "arms": [{"id": "A", "features": FEATURES, "params": {}, "baseline": True}],
        "cells": [], "reference_models": [], "models": [], "search_space": {}})
    folds = [f for f in body["models"][0]["metrics"]["folds"] if f["status"] == "OK"]
    for f in folds:
        d = f["train_derived_thresholds"]
        assert set(d) == {"p90", "p95"}
        assert d["p95"]["threshold"] >= d["p90"]["threshold"]
        # a p90 cut retains roughly a tenth of validation, never all of it
        assert 0.0 <= d["p90"]["retained_fraction"] < 0.9
        assert d["p95"]["retained_fraction"] <= d["p90"]["retained_fraction"]


def test_single_arm_keeps_the_historical_artifact_shape(tmp_path):
    """A study declaring neither arms nor cells must still produce the schema-2 keys the
    freeze and analyze stages read, so this change is inert for existing studies."""
    body = _fit(tmp_path, {"mode": "train", "family": "model.lightgbm", "params": _PARAMS,
                           "validation": {"protocol": "validation.model_selection.random", "tuning_years": [2021],
                                          "final_train_validation_years": []},
                           "arms": [], "cells": [], "reference_models": [], "models": [], "search_space": {}})
    assert body["model_id"] and body["features"] == FEATURES
    assert body["metrics"]["folds"] == [] or isinstance(body["metrics"]["folds"], list)
    assert len(body["models"]) == 1 and body["models"][0]["arm"] == "primary"


# --------------------------------------------------------------------------- #
# paired deltas
# --------------------------------------------------------------------------- #
def _entry(arm, cell, baseline, folds):
    return {"arm": arm, "cell": cell, "baseline_arm": baseline, "metrics": {"folds": folds}}


def _fold(name, n, roc, lift=1.0, brier=0.2):
    return {"fold": name, "status": "OK",
            "metrics": {"n": n, "roc_auc": roc, "pr_auc_over_base_rate": lift, "brier": brier}}


def test_paired_deltas_are_computed_per_fold_against_the_baseline_arm():
    trained = [_entry("A", "LONG", True, [_fold("m1", 100, 0.50), _fold("m2", 100, 0.60)]),
               _entry("B", "LONG", False, [_fold("m1", 100, 0.55), _fold("m2", 100, 0.58)])]
    out = V2Lifecycle._paired_arm_deltas(trained)
    s = out["LONG"]["arms"]["B"]["summary"]["roc_auc"]
    assert out["LONG"]["baseline_arm"] == "A"
    assert s["n_folds"] == 2
    assert s["folds_positive"] == 1 and s["folds_negative"] == 1
    assert s["best"] == pytest.approx(0.05) and s["worst"] == pytest.approx(-0.02)


def test_a_row_count_mismatch_is_reported_unpaired_not_differenced():
    """A delta over different rows is not a comparison."""
    trained = [_entry("A", "LONG", True, [_fold("m1", 100, 0.50)]),
               _entry("B", "LONG", False, [_fold("m1", 87, 0.90)])]
    out = V2Lifecycle._paired_arm_deltas(trained)
    rows = out["LONG"]["arms"]["B"]["per_fold"]
    assert rows[0]["status"] == "UNPAIRED_ROW_COUNT_MISMATCH"
    assert out["LONG"]["arms"]["B"]["summary"]["roc_auc"] is None


def test_no_baseline_arm_yields_no_paired_comparison():
    trained = [_entry("A", "LONG", False, [_fold("m1", 100, 0.5)]),
               _entry("B", "LONG", False, [_fold("m1", 100, 0.6)])]
    assert V2Lifecycle._paired_arm_deltas(trained) == {}


def test_deltas_are_kept_separate_per_cell():
    trained = [_entry("A", "LONG", True, [_fold("m1", 10, 0.50)]),
               _entry("B", "LONG", False, [_fold("m1", 10, 0.60)]),
               _entry("A", "SHORT", True, [_fold("m1", 10, 0.50)]),
               _entry("B", "SHORT", False, [_fold("m1", 10, 0.40)])]
    out = V2Lifecycle._paired_arm_deltas(trained)
    assert out["LONG"]["arms"]["B"]["summary"]["roc_auc"]["folds_positive"] == 1
    assert out["SHORT"]["arms"]["B"]["summary"]["roc_auc"]["folds_negative"] == 1
