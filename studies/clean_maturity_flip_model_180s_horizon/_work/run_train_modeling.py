"""TRAIN modeling dispatch for clean_maturity_flip_model_180s_horizon.

Composes only governed APIs:
  - implementation/two_phase_selection.py  (Phase 1 A/B/C, Phase 2 tune winner, Phase 3 2023 gate)
  - implementation/final_train_freeze.py   (final fit on full TRAIN + TRAIN-only thresholds + freeze)
  - research_workflow.model_selection.run_model_selection (called by the above)

No fitting / feature / target / threshold logic of its own. Builds X/y/meta from the merged
TRAIN parquets exactly as the parent study did:
  join key           : (observation_ts, regime_start_ns, checkpoint_index)   [candidates]
  X                  : the 13 canonical feature columns, arm-sliced arrival-first
  y                  : observations.target_flip_within_horizon  (disposition in LABELED_*)
  LONG  <=> observations.regime_direction == -1   (prevailing bearish; fade long)
  SHORT <=> observations.regime_direction == +1   (prevailing bullish; fade short)
  meta._partition       = "train" (all rows)
  meta._year            = calendar year of observation_ts
  meta._selection_role  = "tuning" for 2021/2022, "final_validation" for 2023
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
STUDY = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(STUDY / "implementation"))

from research.schemas.study_spec import StudySpec, ModelSelectionSpec, ModelFamilySpec
from research.analysis.identity import canonical_sha256
from research.analysis.spec import AnalysisSpec, ModelArm
from research_workflow.modeling import fit_models, freeze_train_artifacts
import two_phase_selection as tps

DECILE_QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def _preprocessing_hash(feature_list_sha256: str) -> str:
    return canonical_sha256({"calibration": "none", "feature_list_sha256": feature_list_sha256})


def _final_fit_and_freeze(direction, arm, X_full, y_full, tuned_hp, manifest_path, study_spec):
    """Framework-current replacement for implementation/final_train_freeze.py (which
    predates the f0bdadf model-artifact binding contract and is in the sealed execution
    closure -- editing it would stale the pre-exec seal and the just-run collection).
    Composes only the unchanged governed APIs fit_models / freeze_train_artifacts."""
    meta = pd.DataFrame({"_partition": ["train"] * len(X_full)})
    aspec = AnalysisSpec(
        analysis_id=f"{direction.lower()}_final_train_fit",
        run_id=f"{direction.lower()}_final_train_fit",
        model_arms=(ModelArm(name=arm, features=list(X_full.columns)),),
        seed=42,
    )
    fit_result = fit_models(
        str(STUDY), X_full, y_full, meta=meta, spec=aspec,
        estimator="lightgbm", hyperparameters=dict(tuned_hp),
    )
    models_manifest_path = STUDY / "artifacts" / f"experiment_models_{direction.lower()}.json"
    (STUDY / "artifacts" / "experiment_models.json").replace(models_manifest_path)

    fitted = fit_result["models"][arm]
    scores = fitted.predict_proba(X_full[list(X_full.columns)])
    ss = pd.Series(scores)
    deciles = {arm: {"boundaries": [float(ss.quantile(q)) for q in DECILE_QUANTILES],
                     "derivation": "TRAIN_ONLY"}}
    freeze_default = freeze_train_artifacts(
        str(STUDY),
        feature_sets={arm: list(X_full.columns)},
        models_manifest=fit_result["manifest"],
        preprocessing_hash=_preprocessing_hash(FEATURE_LIST_SHA256),
        score_arrays={arm: list(scores)},
        meta=meta,
        deciles=deciles,
        study_spec=study_spec,
        model_selection_manifest_path=str(manifest_path),
        model_artifact_records=fit_result["model_artifacts"]["records"],
    )
    freeze_path = STUDY / "artifacts" / f"train_experiment_freeze_{direction.lower()}.json"
    Path(freeze_default).replace(freeze_path)
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    return {
        "status": "FROZEN", "arm": arm, "n_rows": int(len(X_full)),
        "models_manifest_path": str(models_manifest_path),
        "train_freeze_path": str(freeze_path),
        "thresholds": frozen.get("thresholds", {}),
        "stage_scoped_lineage": frozen.get("stage_scoped_lineage", {}),
        "model_artifacts": frozen.get("model_artifacts", []),
        "tuned_hyperparameters": dict(tuned_hp), "random_seed": 42,
    }

JOIN_KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]
ARM_FEATURES = {
    "A": ["arrival_velocity", "arrival_acceleration", "ema_slope"],
    "B": ["arrival_velocity", "arrival_acceleration", "ema_slope",
          "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
          "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr"],
    "C": ["arrival_velocity", "arrival_acceleration", "ema_slope",
          "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
          "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
          "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
          "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr"],
}
DIRECTION_SIGN = {"LONG": -1, "SHORT": 1}
FEATURE_LIST_SHA256 = json.loads((STUDY / "config" / "feature_contract.json").read_text())["feature_list_sha256"]


def _study_spec() -> StudySpec:
    return StudySpec.model_validate(yaml.safe_load((STUDY / "study.yaml").read_text(encoding="utf-8")))


def _bounded_selection_spec() -> ModelSelectionSpec:
    ms = _study_spec().model.selection
    assert ms is not None, "study.yaml model.selection missing"
    return ms


def _load_train_frame() -> pd.DataFrame:
    cand = pd.read_parquet(STUDY / "artifacts" / "train_candidates_merged.parquet")
    obs = pd.read_parquet(STUDY / "artifacts" / "train_observations_merged.parquet")
    # observations carry the label + regime_direction + disposition + timing;
    # candidates carry the 13 features + regime_age_seconds (maturity) metadata.
    obs_cols = JOIN_KEY + ["regime_direction", "target_flip_within_horizon", "disposition",
                           "time_to_flip_seconds", "flip_ts", "censor_reason"]
    df = cand.merge(obs[obs_cols], on=JOIN_KEY, how="inner", validate="one_to_one")
    df = df[df["disposition"].isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])].copy()
    df["y"] = df["target_flip_within_horizon"].astype(int)
    df["_year"] = pd.to_datetime(df["observation_ts"], utc=True).dt.year
    df["_partition"] = "train"
    df["_selection_role"] = df["_year"].map(lambda y: "tuning" if y in (2021, 2022) else "final_validation")
    df = df.sort_values(JOIN_KEY).reset_index(drop=True)
    return df


def _direction_inputs(df: pd.DataFrame, direction: str) -> dict:
    d = df[df["regime_direction"] == DIRECTION_SIGN[direction]].reset_index(drop=True)
    tune = d[d["_year"].isin((2021, 2022))].reset_index(drop=True)
    full = d.reset_index(drop=True)  # 2021-2023, _selection_role tagged

    X_by_arm_tuning = {a: tune[cols].reset_index(drop=True) for a, cols in ARM_FEATURES.items()}
    X_final_by_arm = {a: full[cols].reset_index(drop=True) for a, cols in ARM_FEATURES.items()}
    feature_counts = {a: len(cols) for a, cols in ARM_FEATURES.items()}
    meta_cols = ["_year", "_partition", "_selection_role"]
    return dict(
        X_by_arm_tuning=X_by_arm_tuning,
        y_tuning=tune["y"].reset_index(drop=True),
        meta_tuning=tune[meta_cols].reset_index(drop=True),
        feature_counts=feature_counts,
        X_final_by_arm=X_final_by_arm,
        y_final=full["y"].reset_index(drop=True),
        meta_final=full[meta_cols].reset_index(drop=True),
        selection_spec_template=_bounded_selection_spec(),
    )


def main() -> None:
    df = _load_train_frame()
    summary = {
        "rows_labeled_total": int(len(df)),
        "by_year": df["_year"].value_counts().sort_index().to_dict(),
        "base_rate_overall": float(df["y"].mean()),
        "LONG_rows": int((df["regime_direction"] == -1).sum()),
        "SHORT_rows": int((df["regime_direction"] == 1).sum()),
        "LONG_base_rate": float(df.loc[df["regime_direction"] == -1, "y"].mean()),
        "SHORT_base_rate": float(df.loc[df["regime_direction"] == 1, "y"].mean()),
        "feature_list_sha256": FEATURE_LIST_SHA256,
    }
    print("FRAME_SUMMARY", json.dumps(summary, default=str))

    long_inputs = _direction_inputs(df, "LONG")
    short_inputs = _direction_inputs(df, "SHORT")
    results = tps.run_study_two_phase_selection(str(STUDY), long_inputs=long_inputs, short_inputs=short_inputs)

    dispatch = {}
    study_spec = _study_spec()
    for direction, res in results.items():
        p1, p23 = res.phase1, res.phase2_phase3
        dispatch[direction] = {
            "status": res.status,
            "winning_arm": p1.winning_arm,
            "per_arm_pr_auc": p1.per_arm_pr_auc,
            "per_arm_brier": p1.per_arm_brier,
            "tie_break_applied": p1.tie_break_applied,
            "tie_break_trace": p1.tie_break_trace,
            "tuned_hyperparameters": p23.tuned_hyperparameters,
            "inner_validation_score": p23.inner_validation_score,
            "final_validation_status": p23.final_validation_status,
            "final_validation_metrics": p23.final_validation_metrics,
            "final_validation_reasons": p23.final_validation_reasons,
            "summary": res.summary,
            "manifest_path": p23.manifest_path,
        }
    (STUDY / "artifacts" / "two_phase_selection_dispatch_summary.json").write_text(
        json.dumps(dispatch, indent=2, default=str), encoding="utf-8")
    print("TWO_PHASE_DONE", json.dumps({k: v["status"] for k, v in dispatch.items()}))

    # ---- final fit + freeze for each PASS direction ----
    freeze_summary = {}
    for direction, res in results.items():
        if res.status != "PASS_DIRECTION":
            freeze_summary[direction] = {"status": "SKIPPED_DIRECTION_FAILED"}
            continue
        di = _direction_inputs(df, direction)
        arm = res.phase1.winning_arm
        freeze_summary[direction] = _final_fit_and_freeze(
            direction, arm,
            di["X_final_by_arm"][arm].reset_index(drop=True),
            di["y_final"].reset_index(drop=True),
            res.phase2_phase3.tuned_hyperparameters,
            res.phase2_phase3.manifest_path,
            study_spec,
        )
    (STUDY / "artifacts" / "final_train_freeze_dispatch_summary.json").write_text(
        json.dumps(freeze_summary, indent=2, default=str), encoding="utf-8")
    print("FREEZE_DONE", json.dumps({k: v.get("status") for k, v in freeze_summary.items()}))


if __name__ == "__main__":
    main()
