"""``model.feature_columns``: the model input surface is not the observation collection surface.

Before this, the fit surface was ``columns.features + columns.derived`` and nothing else, so a study whose
observations live in ``features.metadata`` (every tracker-state column: MTF directions, regime age, current and
prior regime geometry) could not model them at all. The only way to make them model-eligible was to re-declare
them as features, which changes the compiled plan OUTSIDE the replay-key exclusion set and therefore re-replays
every already-collected year -- two audited years of identical bars to reclassify columns.

``model.feature_columns`` selects model inputs from the columns a study ALREADY EMITS. It changes no observation
value, no tracker, no outcome column and no partition identity: ``model`` is excluded from the reuse key
(``research_workflow.replay_closure.REPLAY_PLAN_EXCLUDED_KEYS``), so a partition collected without the
declaration stays valid with it. Eligibility is per column and fail-closed -- there is no "metadata is safe" rule.
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
from research_workflow.replay_closure import replay_plan_sha256

NS = 1_000_000_000
REPO = Path(__file__).resolve().parents[2]
FEATURES = ["f_base_a", "f_base_b"]
META = ["dir_5m", "dir_15m", "dir_1h", "age_s_5m", "mfe_atr_15m", "prior_mfe_atr_1h", "sd_prior_start_1h_b"]
_PARAMS = {"n_estimators": 25, "max_depth": 2, "num_leaves": 4, "verbosity": -1, "random_state": 42}


# --------------------------------------------------------------------------------------------- #
# compile surface (production compiler, the committed 180s study with a substituted model block)
# --------------------------------------------------------------------------------------------- #
def _spec(model_block: dict, study_id: str = "mfc_probe") -> dict:
    base = REPO / "studies" / "v2_shape_a_flip_180s" / "study.yaml"
    text = base.read_text(encoding="utf-8").replace("id: v2_shape_a_flip_180s", f"id: {study_id}")
    text = text.replace("dataset: NQ_1S_V2,", "dataset: NQ_1S_V2_GLOBEX,")
    head, _, _ = text.partition("\nmodel:")
    body = yaml.safe_load(head)
    body["model"] = model_block
    return body


def _compile(model_block: dict, study_id: str = "mfc_probe"):
    return compile_study(_spec(model_block, study_id))


def _model(**over) -> dict:
    out = {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS)}
    out.update(over)
    return out


def _messages(result) -> str:
    return json.dumps(result.card())


@pytest.fixture(scope="module")
def plain():
    """The committed study's own model block, untouched: the legacy path."""
    out = _compile(_model())
    assert out.ok, out.card()
    return out.plan.to_dict()


def test_declared_metadata_column_is_model_eligible(plain):
    meta = [m["column"] for m in plain["columns"]["metadata"]][:4]
    assert meta, "the fixture study must declare metadata columns"
    out = _compile(_model(feature_columns=meta))
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    assert plan["model"]["feature_columns"] == meta
    assert plan["columns"]["features"] == plain["columns"]["features"], "the OBSERVATION surface must not move"
    assert plan["columns"]["metadata"] == plain["columns"]["metadata"]


def test_declaration_order_is_the_feature_order(plain):
    meta = [m["column"] for m in plain["columns"]["metadata"]][:4]
    out = _compile(_model(feature_columns=list(reversed(meta))))
    assert out.ok, out.card()
    assert out.plan.to_dict()["model"]["feature_columns"] == list(reversed(meta))


def test_unknown_column_is_refused():
    out = _compile(_model(feature_columns=["no_such_column_anywhere"]))
    assert not out.ok and "no_such_column_anywhere" in _messages(out) and "not a column this study emits" in _messages(out)


@pytest.mark.parametrize("col", ["observation_ts", "regime_start_ns", "checkpoint_index"])
def test_identity_column_is_refused(col):
    out = _compile(_model(feature_columns=[col]))
    assert not out.ok and "identity/provenance column" in _messages(out)


def test_outcome_and_label_columns_are_refused(plain):
    label = plain["outcome"]["label_column"]
    for col in [label] + [c for c in plain["outcome"]["observation_columns"] if c.startswith(("terminal_", "fp_", "executable_entry_"))][:4] \
            + ["disposition", "censor_reason", "resolved_at_ts", "observed_seconds", "horizon_end_ts"]:
        out = _compile(_model(feature_columns=[col]))
        assert not out.ok, f"{col} must be refused"
        assert ("outcome column of this study's outcome contract" in _messages(out)
                or "forward-outcome guard" in _messages(out)), (col, _messages(out)[:300])


@pytest.mark.parametrize("col", ["max_mfe_atr", "final_return", "time_to_max_mfe", "mfe_300s_atr",
                                 "favorable_before_adverse_1p0atr", "post_confirmation_drawdown"])
def test_future_derived_names_are_refused_by_the_guard(col):
    out = _compile(_model(feature_columns=[col]))
    assert not out.ok and ("forward-outcome guard" in _messages(out) or "not a column this study emits" in _messages(out))


def test_duplicate_declaration_is_refused(plain):
    col = [m["column"] for m in plain["columns"]["metadata"]][0]
    out = _compile(_model(feature_columns=[col, col]))
    assert not out.ok and "duplicate" in _messages(out).lower()


def test_arms_may_subset_the_declared_model_surface(plain):
    meta = [m["column"] for m in plain["columns"]["metadata"]][:4]
    out = _compile(_model(feature_columns=meta,
                          arms=[{"id": "all", "baseline": True, "features": meta},
                                {"id": "half", "features": meta[:2]}]))
    assert out.ok, out.card()
    arms = {a["id"]: a for a in out.plan.to_dict()["model"]["arms"]}
    assert arms["half"]["features"] == meta[:2]
    bad = _compile(_model(feature_columns=meta[:2], arms=[{"id": "x", "baseline": True, "features": [meta[3]]}]))
    assert not bad.ok and "not in the study's declared surface" in _messages(bad)


def test_ordinary_feature_columns_still_work(plain):
    feats = plain["columns"]["features"][:3]
    out = _compile(_model(feature_columns=feats))
    assert out.ok, out.card()
    assert out.plan.to_dict()["model"]["feature_columns"] == feats


def test_legacy_plan_is_byte_identical_without_the_declaration(plain):
    again = _compile(_model())
    assert again.ok
    assert again.plan.to_dict()["plan_sha256"] == plain["plan_sha256"]
    assert "feature_columns" not in plain["model"], "a plan that never declared it keeps its pre-capability shape"


def test_score_mode_refuses_the_declaration():
    out = _compile({"mode": "score", "models": [{"id": "a" * 64, "label": "target_flip_within_horizon"}],
                    "feature_columns": ["dir_5m"]})
    assert not out.ok and "train-mode declaration" in _messages(out)


# --------------------------------------------------------------------------------------------- #
# THE REUSE INVARIANT: the model surface is not the collection surface
# --------------------------------------------------------------------------------------------- #
def test_declaring_feature_columns_does_not_change_the_partition_reuse_key(plain):
    meta = [m["column"] for m in plain["columns"]["metadata"]][:6]
    with_cols = _compile(_model(feature_columns=meta))
    assert with_cols.ok, with_cols.card()
    p_with = with_cols.plan.to_dict()
    # the reuse key (replay_plan_sha256 + closure + dataset + partition + authorization) must not move
    assert replay_plan_sha256(p_with) == replay_plan_sha256(plain), "an already-collected partition must stay valid"
    assert p_with["closure"]["stages"] == plain["closure"]["stages"], "the collection/replay closure must be identical"
    for section in ("streams", "trackers", "population", "triggers", "outcome", "columns", "warmup", "availability"):
        assert p_with[section] == plain[section], f"{section} must be untouched by a model-surface declaration"
    # ...while the MODEL contract does change
    assert p_with["plan_sha256"] != plain["plan_sha256"]
    assert p_with["model"]["feature_columns"] == meta


def test_reuse_key_is_insensitive_to_the_selected_surface(plain):
    meta = [m["column"] for m in plain["columns"]["metadata"]]
    a = _compile(_model(feature_columns=meta[:3])).plan.to_dict()
    b = _compile(_model(feature_columns=meta[:6])).plan.to_dict()
    assert replay_plan_sha256(a) == replay_plan_sha256(b) == replay_plan_sha256(plain)
    assert a["plan_sha256"] != b["plan_sha256"], "the model contract must reflect the selected surface"


# --------------------------------------------------------------------------------------------- #
# fit stage on a fabricated two-year merged frame (real estimator, no collection)
# --------------------------------------------------------------------------------------------- #
def _fabricate(study: Path, *, model: dict, per_year: int = 900) -> None:
    rng = np.random.default_rng(7)
    rows = []
    for year in (2023, 2024):
        ts = pd.date_range(f"{year}-01-03", f"{year}-12-20 20:00", periods=per_year, tz="UTC")
        x = rng.normal(size=(per_year, len(FEATURES) + len(META)))
        # signal in a METADATA column, so a model that cannot read metadata cannot find it
        logit = 1.4 * x[:, len(FEATURES)] + 0.3 * x[:, 0] + (0.0 if year == 2023 else 0.0)
        y = (rng.uniform(size=per_year) < 1 / (1 + np.exp(-logit))).astype(int)
        d = pd.DataFrame({"observation_ts": ts.astype("int64"),
                          "regime_start_ns": (ts.astype("int64") // (3600 * NS)) * 3600 * NS,
                          "checkpoint_index": np.arange(per_year) % 5,
                          "row_direction": rng.choice([1, -1], size=per_year), "_label": y})
        for i, c in enumerate(FEATURES + META):
            d[c] = x[:, i]
        rows.append(d)
    cand = pd.concat(rows, ignore_index=True)
    obs = cand[list(KEY)].copy()
    obs["target_flip_within_horizon"] = cand.pop("_label")
    obs["disposition"] = "LABELED"
    obs["terminal_gross_pnl_atr"] = rng.normal(size=len(obs))     # an outcome column riding along
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


def _fit(tmp_path: Path, model: dict, name: str) -> dict:
    study = tmp_path / "studies" / name
    study.mkdir(parents=True, exist_ok=True)
    _fabricate(study, model=model)
    V2Lifecycle(study, options=V2Options(execute=True, model_root=tmp_path / "store")).fit()
    return json.loads((study / "artifacts" / "experiment_models.json").read_text(encoding="utf-8"))


_VAL_2023_2024 = {"protocol": "validation.model_selection.random", "tuning_years": [2023],
                  "final_train_validation_years": [2024]}


def test_fit_uses_the_declared_metadata_surface(tmp_path):
    body = _fit(tmp_path, {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS),
                           "feature_columns": META, "validation": _VAL_2023_2024}, "fit_meta")
    assert body["models"][0]["features"] == META, "the fitted model's ordered inputs are the declared order"
    assert body["models"][0]["n_features"] == len(META)


def test_fit_falls_back_to_the_declared_feature_surface(tmp_path):
    body = _fit(tmp_path, {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS),
                           "validation": _VAL_2023_2024}, "fit_legacy")
    assert body["models"][0]["features"] == FEATURES, "a plan without the declaration keeps the old surface"


def test_fit_refuses_a_column_absent_from_the_collected_frame(tmp_path):
    with pytest.raises(LifecycleV2Error, match="MODEL_FEATURE_COLUMNS_UNBOUND"):
        _fit(tmp_path, {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS),
                        "feature_columns": META + ["never_collected"], "validation": _VAL_2023_2024}, "fit_unbound")


def test_fit_refuses_an_outcome_column_even_if_a_plan_smuggles_it_in(tmp_path):
    """Defence in depth: the compiler refuses it, and so does the fit-stage guard."""
    from research_workflow.forward_outcomes.guard import OutcomeLeakError
    with pytest.raises(OutcomeLeakError):
        _fit(tmp_path, {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS),
                        "feature_columns": META + ["max_mfe_atr"], "validation": _VAL_2023_2024}, "fit_leak")


def test_2023_fit_2024_score_chronology(tmp_path):
    """The final model sees 2023 rows ONLY; 2024 is scored once, and never participates in fitting."""
    body = _fit(tmp_path, {"mode": "train", "family": "lightgbm", "params": dict(_PARAMS),
                           "feature_columns": META, "validation": _VAL_2023_2024}, "fit_chrono")
    assert body["tuning_years"] == [2023] and body["final_train_validation_years"] == [2024]
    m = body["models"][0]
    assert m["final_fit_rows"] == 900, "the final fit is the 2023 rows only (900 fabricated per year)"
    final_val = m["metrics"]["final_validation"]
    assert final_val["n"] == 900, "2024 is evaluated as a whole, once"
    assert m["metrics"]["tuning"] is None, "no hyperparameter search: 2024 cannot enter selection"
    assert m["metrics"]["folds"] == [], "one tuning year yields zero folds; nothing was selected on 2024"


def test_compiler_refuses_2024_in_both_roles(plain):
    """A year may not tune and final-validate; and the OOS/dev period may not be used TRAIN-side."""
    bad = _compile(_model(validation={"protocol": "validation.model_selection.random",
                                      "tuning_years": [2021], "final_train_validation_years": [2021]}))
    assert not bad.ok and "double use" in _messages(bad)


# --------------------------------------------------------------------------------------------- #
# the requesting study's own frozen surface
# --------------------------------------------------------------------------------------------- #
def test_requesting_study_surface_shape_is_expressible(plain):
    """A model surface of the shape the predictive-ranking study froze: MTF directions, current geometry,
    prior-regime geometry -- all metadata columns, declared explicitly, with the reuse key untouched."""
    meta = [m["column"] for m in plain["columns"]["metadata"]]
    chosen = meta[: min(40, len(meta))]
    out = _compile(_model(feature_columns=chosen))
    assert out.ok, out.card()
    p = out.plan.to_dict()
    assert p["model"]["feature_columns"] == chosen
    assert replay_plan_sha256(p) == replay_plan_sha256(plain)
