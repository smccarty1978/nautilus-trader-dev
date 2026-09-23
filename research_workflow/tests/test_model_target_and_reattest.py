"""`model.target` (a label derived at modeling time), the vacuous-fit hard failure, and closure re-attestation.

Three defects this file pins:

  * a study could not train on a target derived from its OWN collected outcome columns. The fit label came from
    `outcome.label_column`, which is inside the partition-reuse key, so the only way to change it was to
    re-collect. The audited atlas frame's label is single-class (65,290 positive / 0 negative), so the frozen
    experiment could not be fitted at all.
  * a vacuous fit must be a hard failure. `CELL_FINAL_FIT_DEGENERATE` already covered "this cell has no fittable
    rows"; what was missing was a failure that names the TARGET and its class counts before any cell is reached,
    and a backstop for an empty/incomplete model set. Both are pinned here.
  * a partition collected under one replay closure was refused after ANY edit to a closure file, even one that
    provably cannot change a persisted row. Re-attestation permits reuse only with evidence, and excuses exactly
    two key components -- never the plan, dataset, interval or artifact bytes.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from research_workflow.grammar.compiler import compile_study
from research_workflow.lifecycle_v2 import KEY, LifecycleV2Error, V2Lifecycle, V2Options
from research_workflow.replay_closure import ATTESTATION_SCHEMA_VERSION, attestation_permits

NS = 1_000_000_000
REPO = Path(__file__).resolve().parents[2]
FEATURES = ["f_base_a", "f_base_b"]
META = ["dir_5m", "age_s_5m", "prior_mfe_atr_1h"]
_PARAMS = {"n_estimators": 20, "max_depth": 2, "num_leaves": 4, "verbosity": -1, "random_state": 42}
_VAL = {"protocol": "validation.model_selection.random", "tuning_years": [2023], "final_train_validation_years": [2024]}


# --------------------------------------------------------------------------------------------- #
# compile surface
# --------------------------------------------------------------------------------------------- #
def _compile(model_block: dict, study_id: str = "mt_probe"):
    base = REPO / "studies" / "v2_shape_a_flip_180s" / "study.yaml"
    text = base.read_text(encoding="utf-8").replace("id: v2_shape_a_flip_180s", f"id: {study_id}")
    text = text.replace("dataset: NQ_1S_V2,", "dataset: NQ_1S_V2_GLOBEX,")
    head, _, _ = text.partition("\nmodel:")
    body = yaml.safe_load(head)
    body["model"] = model_block
    return compile_study(body)


def _model(**over) -> dict:
    out = {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS)}
    out.update(over)
    return out


def _card(result) -> str:
    return json.dumps(result.card())


def test_target_expression_compiles_and_is_hashed():
    out = _compile(_model(target={"id": "winner", "expr": "terminal_gross_pnl_atr > 0"}))
    assert out.ok, out.card()
    t = out.plan.to_dict()["model"]["target"]
    assert t["id"] == "winner" and t["expr"] == "terminal_gross_pnl_atr > 0"
    assert len(t["expression_sha256"]) == 64 and t["columns"] == ["terminal_gross_pnl_atr"]


def test_target_may_read_outcome_columns_but_features_may_not():
    """A label resolves after its entry; a feature may not. The same column, two different answers."""
    ok = _compile(_model(target={"id": "w", "expr": "terminal_gross_pnl_atr > 0"}))
    assert ok.ok, ok.card()
    bad = _compile(_model(target={"id": "w", "expr": "terminal_gross_pnl_atr > 0"},
                          feature_columns=["terminal_gross_pnl_atr"]))
    assert not bad.ok and "outcome column of this study's outcome contract" in _card(bad)


def test_target_referencing_an_unknown_column_is_refused():
    out = _compile(_model(target={"id": "w", "expr": "no_such_outcome > 0"}))
    assert not out.ok and "does not emit" in _card(out)


def test_target_syntax_error_is_a_compile_gap():
    out = _compile(_model(target={"id": "w", "expr": "terminal_gross_pnl_atr >"}))
    assert not out.ok and "EXPRESSION_SYNTAX" in _card(out)


def test_target_shape_is_validated():
    for bad in ({"id": "w"}, {"expr": "x > 0"}, {"id": "w", "expr": "x > 0", "extra": 1}):
        out = _compile(_model(target=bad))
        assert not out.ok, bad


def test_score_mode_refuses_a_target():
    out = _compile({"mode": "score", "models": [{"id": "a" * 64, "label": "target_flip_within_horizon"}],
                    "target": {"id": "w", "expr": "terminal_gross_pnl_atr > 0"}})
    assert not out.ok and "train-mode declaration" in _card(out)


def test_plan_without_a_target_is_unchanged():
    plain = _compile(_model())
    assert plain.ok and "target" not in plain.plan.to_dict()["model"]


# --------------------------------------------------------------------------------------------- #
# fit stage on a fabricated two-year frame (real estimator, no collection)
# --------------------------------------------------------------------------------------------- #
def _fabricate(study: Path, *, model: dict, per_year: int = 700, positive_rate=(0.45, 0.45)) -> None:
    rng = np.random.default_rng(3)
    rows = []
    for year, rate in zip((2023, 2024), positive_rate):
        ts = pd.date_range(f"{year}-01-03", f"{year}-12-20 20:00", periods=per_year, tz="UTC")
        x = rng.normal(size=(per_year, len(FEATURES) + len(META)))
        g = rng.normal(size=per_year) + (0.9 * x[:, len(FEATURES)])
        if rate == 0.0:
            g = np.abs(g) + 0.01                      # every row a winner: single-class target
        d = pd.DataFrame({"observation_ts": ts.astype("int64"),
                          "regime_start_ns": (ts.astype("int64") // (3600 * NS)) * 3600 * NS,
                          "checkpoint_index": np.arange(per_year) % 4, "_g": g})
        for i, c in enumerate(FEATURES + META):
            d[c] = x[:, i]
        rows.append(d)
    cand = pd.concat(rows, ignore_index=True)
    obs = cand[list(KEY)].copy()
    obs["terminal_gross_pnl_atr"] = cand.pop("_g")
    obs["target_flip_within_horizon"] = 1.0                      # the degenerate single-class raw label
    obs["disposition"] = "LABELED_POSITIVE"
    merged = study / "_work" / "controller" / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    cand.to_parquet(merged / "candidates.parquet", index=False)
    obs.to_parquet(merged / "observations.parquet", index=False)
    (merged / "identity.json").write_text(json.dumps({"candidates_identity": "fab"}), encoding="utf-8")
    (study / "audit").mkdir(parents=True, exist_ok=True)
    (study / "audit" / "frozen_execution_manifest.json").write_text(
        json.dumps({"frozen_execution_composite_sha256": "c" * 64}), encoding="utf-8")
    plan = {"plan_sha256": "p" * 64, "study": {"id": study.name},
            "columns": {"features": FEATURES, "derived": [], "metadata": [{"column": c, "ref": f"t.{c}"} for c in META],
                        "identity": list(KEY), "observation": ["target_flip_within_horizon", "disposition", "terminal_gross_pnl_atr"]},
            "outcome": {"label_column": "target_flip_within_horizon", "kernel": "flip", "contract": "label"},
            "chronology": {"train": [2023, 2024], "dev": [], "prohibited": [2025, 2026]}, "model": model}
    (study / "compiled_plan.json").write_text(json.dumps(plan), encoding="utf-8")


def _fit(tmp_path: Path, model: dict, name: str, **kw):
    study = tmp_path / "studies" / name
    study.mkdir(parents=True, exist_ok=True)
    _fabricate(study, model=model, **kw)
    V2Lifecycle(study, options=V2Options(execute=True, model_root=tmp_path / "store")).fit()
    return json.loads((study / "artifacts" / "experiment_models.json").read_text(encoding="utf-8"))


def _target_model(**over):
    out = {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS), "validation": dict(_VAL),
           "feature_columns": FEATURES + META, "target": {"id": "winner", "expr": "terminal_gross_pnl_atr > 0",
                                                          "expression_sha256": "e" * 64, "columns": ["terminal_gross_pnl_atr"]}}
    out.update(over)
    return out


def test_derived_target_trains_and_records_its_population(tmp_path):
    body = _fit(tmp_path, _target_model(), "fit_target")
    t = body["target"]
    assert t["id"] == "winner" and t["expr"] == "terminal_gross_pnl_atr > 0"
    assert t["positive_n"] > 0 and t["negative_n"] > 0
    assert t["eligible_n"] == t["positive_n"] + t["negative_n"]
    assert body["models"][0]["features"] == FEATURES + META
    assert body["label_column"].endswith("winner")


def test_fit_uses_only_the_tuning_years(tmp_path):
    body = _fit(tmp_path, _target_model(), "fit_years")
    assert body["tuning_years"] == [2023] and body["final_train_validation_years"] == [2024]
    assert body["models"][0]["final_fit_rows"] == 700, "the final estimator sees the 2023 rows only"


def test_single_class_target_hard_fails(tmp_path):
    """The exact shape of the audited frame's raw label: every row positive."""
    with pytest.raises(LifecycleV2Error, match="MODEL_TARGET_SINGLE_CLASS"):
        _fit(tmp_path, _target_model(), "fit_single", positive_rate=(0.0, 0.0))


def test_the_raw_degenerate_label_still_hard_fails_without_a_target(tmp_path):
    """No target declared: the legacy path meets the audited frame's single-class label and must NOT report PASS.

    `CELL_FINAL_FIT_DEGENERATE` predates this chore and already covers it; the point of the test is that the
    all-positive label can never produce a PASS with zero models, by either route."""
    model = {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS), "validation": dict(_VAL),
             "feature_columns": FEATURES + META}
    with pytest.raises(LifecycleV2Error, match="CELL_FINAL_FIT_DEGENERATE|MODEL_FIT_PRODUCED_NO_MODELS"):
        _fit(tmp_path, model, "fit_vacuous")


def test_non_binary_target_is_refused(tmp_path):
    with pytest.raises(LifecycleV2Error, match="MODEL_TARGET_NOT_BINARY"):
        _fit(tmp_path, _target_model(target={"id": "g", "expr": "terminal_gross_pnl_atr * 2",
                                             "expression_sha256": "e" * 64, "columns": ["terminal_gross_pnl_atr"]}), "fit_cont")


def test_unresolvable_target_is_refused(tmp_path):
    with pytest.raises(LifecycleV2Error, match="MODEL_TARGET_UNRESOLVED"):
        _fit(tmp_path, _target_model(target={"id": "x", "expr": "not_a_column > 0",
                                             "expression_sha256": "e" * 64, "columns": ["not_a_column"]}), "fit_unres")


def test_incomplete_arm_set_hard_fails(tmp_path):
    """An arm whose cell yields no rows must fail the run, not silently produce fewer models."""
    model = _target_model(arms=[{"id": "a", "baseline": True, "features": FEATURES},
                                {"id": "b", "features": META}],
                          cells=[{"id": "all", "subset": {}}, {"id": "impossible", "subset": {"checkpoint_index": 99}}])
    with pytest.raises(LifecycleV2Error, match="CELL_FINAL_FIT_DEGENERATE|MODEL_FIT_INCOMPLETE|MODEL_FIT_PRODUCED_NO_MODELS"):
        _fit(tmp_path, model, "fit_incomplete")


# --------------------------------------------------------------------------------------------- #
# re-attestation: what it excuses, and what it must never excuse
# --------------------------------------------------------------------------------------------- #
REC = {"replay_plan_sha256": "plan", "replay_closure_composite_sha256": "OLD", "authorization_sha256": "AUTH_A",
       "dataset": {"dataset_id": "NQ"}, "partition": {"period": "train", "year": 2023}}


def _expected(**over):
    out = dict(REC)
    out.update(over)
    return out


def _attestation(**over):
    entry = {"partition_id": "train-2023",
             "recorded": {"replay_closure_composite_sha256": "OLD"},
             "current": {"replay_closure_composite_sha256": "NEW"},
             "closure_delta": {"membership_identical": True},
             "equivalence_proof": {"kind": "bounded_replay_byte_equality", "identical": True,
                                   "reference": {"replay_closure_composite_sha256": "OLD", "candidates_sha256": "c", "observations_sha256": "o"},
                                   "current": {"replay_closure_composite_sha256": "NEW", "candidates_sha256": "c", "observations_sha256": "o"}},
             "authorization_equivalence": {"year_roles_identical": True, "differing_fields": ["study_id", "study_path"],
                                           "recorded": {"authorization_sha256": "AUTH_A"}, "current": {"authorization_sha256": "AUTH_B"}}}
    entry.update(over)
    return {"schema_version": ATTESTATION_SCHEMA_VERSION, "entries": [entry]}


def test_attestation_permits_a_pure_closure_change():
    ok, reason = attestation_permits("train-2023", REC, _expected(replay_closure_composite_sha256="NEW"), _attestation())
    assert ok and reason == "REUSABLE_BY_CLOSURE_ATTESTATION"


def test_attestation_permits_a_cross_study_authorization_with_identical_year_roles():
    ok, reason = attestation_permits("train-2023", REC, _expected(authorization_sha256="AUTH_B"), _attestation())
    assert ok and reason == "REUSABLE_BY_AUTHORIZATION_ATTESTATION"


@pytest.mark.parametrize("over,expect", [
    ({"replay_plan_sha256": "other"}, "ATTESTATION_SCOPE"),
    ({"dataset": {"dataset_id": "ES"}}, "ATTESTATION_SCOPE"),
    ({"partition": {"period": "train", "year": 2024}}, "ATTESTATION_SCOPE"),
])
def test_attestation_never_excuses_plan_dataset_or_interval(over, expect):
    ok, reason = attestation_permits("train-2023", REC, _expected(**over), _attestation())
    assert not ok and reason.startswith(expect)


def test_attestation_requires_byte_equality():
    bad = _attestation(equivalence_proof={"kind": "bounded_replay_byte_equality", "identical": False})
    ok, reason = attestation_permits("train-2023", REC, _expected(replay_closure_composite_sha256="NEW"), bad)
    assert not ok and reason == "ATTESTATION_NO_BYTE_EQUALITY_PROOF"


def test_attestation_requires_identical_closure_membership():
    bad = _attestation(closure_delta={"membership_identical": False})
    ok, reason = attestation_permits("train-2023", REC, _expected(replay_closure_composite_sha256="NEW"), bad)
    assert not ok and reason == "ATTESTATION_CLOSURE_MEMBERSHIP_CHANGED"


def test_attestation_requires_matching_composites():
    bad = _attestation(current={"replay_closure_composite_sha256": "SOMETHING_ELSE"})
    ok, reason = attestation_permits("train-2023", REC, _expected(replay_closure_composite_sha256="NEW"), bad)
    assert not ok and reason == "ATTESTATION_COMPOSITE_MISMATCH"


def test_attestation_refuses_widened_authorization_years():
    bad = _attestation(authorization_equivalence={"year_roles_identical": False, "differing_fields": ["train_years"],
                                                  "recorded": {"authorization_sha256": "AUTH_A"},
                                                  "current": {"authorization_sha256": "AUTH_B"}})
    ok, reason = attestation_permits("train-2023", REC, _expected(authorization_sha256="AUTH_B"), bad)
    assert not ok and reason == "ATTESTATION_AUTHORIZATION_NOT_EQUIVALENT"


def test_no_attestation_means_no_reuse():
    ok, reason = attestation_permits("train-2023", REC, _expected(replay_closure_composite_sha256="NEW"), None)
    assert not ok and reason == "NO_CLOSURE_ATTESTATION"
    ok, reason = attestation_permits("train-2099", REC, _expected(replay_closure_composite_sha256="NEW"), _attestation())
    assert not ok and reason.startswith("ATTESTATION_MISSING_PARTITION")
