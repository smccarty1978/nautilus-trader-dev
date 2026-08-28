"""Governed TRAIN merge + pre-fit gate + LightGBM selection/fit + TRAIN freeze.

deep_pullback_5s_reacceleration_model. Runs strictly AFTER the partitioned TRAIN
collection (2021, 2022, 2023) is complete and reconciled.

Composes ONLY existing governed APIs -- no bespoke collector / model trainer /
target engine / forward tracker / threshold-selection logic (research_decision.yaml
prohibits those explicitly):

  research_workflow.partitioning.merge_partition_outputs   -- deterministic merge
  research_workflow.gates.compute_population_scope_sha256   -- pre-fit gate scope
  research_workflow.model_selection.run_model_selection     -- 2021->2022 fold + gated 2023
  research_workflow.modeling.fit_models / freeze_train_artifacts
  research.analysis.spec.AnalysisSpec / ModelArm
  research.analysis.modeling.frame_content_identity / library_versions / fit_model

Mirrors studies/clean_maturity_flip_model_180s_horizon/implementation/final_train_freeze.py
(single governed-API composition, no science of its own).

Chronology (sealed compiled contract wins):
  tuning_years              = [2021, 2022]   inner walk-forward fold: fit 2021 -> validate 2022
  final_train_validation    = [2023]         gated: refit on 2021+2022, score 2023
  final fit scope           = all resolved 2021-2023 TRAIN rows (parent-study single_partition
                              convention -- no held-out split for the frozen model)

Binary population: disposition in {LABELED_POSITIVE, LABELED_NEGATIVE}; CENSORED excluded.
Feature surface: the 34 frozen canonical FeatureInstances (config/feature_contract.json order)
followed by the derived input model_c_score_at_candidate. Nulls are NOT dropped -- LightGBM's
native missing handling is the contracted behaviour (rolling_300s_* / model_c null_policy=allow).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd

from research.analysis.identity import canonical_sha256
from research.analysis.modeling import (
    frame_content_identity,
    library_versions,
    series_content_identity,
)
from research.analysis.spec import AnalysisSpec, ModelArm
from research_workflow.gates import compute_population_scope_sha256
from research_workflow.modeling import fit_models, freeze_train_artifacts
from research_workflow.model_selection import run_model_selection
from research_workflow.partitioning import build_year_partitions, merge_partition_outputs

SEALED_COMPOSITE = "1a2e54fad3b4c6e0ce4e51b083728573293af5d9977b48037c7d5073555cf5bc"
KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]
DECILE_QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
ARM = "BROAD"
SEED = 0


class TrainFreezeError(RuntimeError):
    """A required invariant of the merge/fit/freeze step was violated."""


# --------------------------------------------------------------------------- #
# 1. per-partition verification
# --------------------------------------------------------------------------- #
def _year_of(ts_ns: pd.Series) -> pd.Series:
    return pd.to_datetime(ts_ns, unit="ns", utc=True).dt.year


def verify_partition(run_dir: Path, expected_year: int, expected_columns: Sequence[str]) -> Dict[str, Any]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    cand = pd.read_parquet(run_dir / "collection" / "candidates.parquet")
    obs = pd.read_parquet(run_dir / "collection" / "observations.parquet")

    findings: List[str] = []
    composite = manifest.get("execution_manifest_sha256") or manifest.get("composite_seal_hash")
    if composite != SEALED_COMPOSITE:
        findings.append(f"execution composite {composite!r} != sealed {SEALED_COMPOSITE!r}")
    if manifest.get("study_id") != "deep_pullback_5s_reacceleration_model":
        findings.append(f"study_id {manifest.get('study_id')!r}")
    if len(cand) != len(obs):
        findings.append(f"candidate/observation count mismatch: {len(cand)} != {len(obs)}")
    if cand.duplicated(KEY).any():
        findings.append(f"{int(cand.duplicated(KEY).sum())} duplicate candidate keys")
    if list(cand.columns) != list(expected_columns):
        findings.append("candidate column contract drift")
    cand_years = set(_year_of(cand["candidate_ts"]).unique().tolist())
    if cand_years - {expected_year}:
        findings.append(f"candidate years {sorted(cand_years)} outside partition year {expected_year}")
    disp = obs["disposition"].value_counts().to_dict()

    return {
        "run_id": manifest.get("run_id"),
        "year": expected_year,
        "execution_composite": composite,
        "candidates": int(len(cand)),
        "observations": int(len(obs)),
        "candidate_key_duplicates": int(cand.duplicated(KEY).sum()),
        "disposition_counts": {k: int(v) for k, v in disp.items()},
        "column_contract_ok": list(cand.columns) == list(expected_columns),
        "year_identity_ok": not (cand_years - {expected_year}),
        "passed": not findings,
        "findings": findings,
    }


# --------------------------------------------------------------------------- #
# 2. deterministic merge
# --------------------------------------------------------------------------- #
def merge_train_partitions(
    study_dir: Path, run_dirs: Mapping[int, Path], expected_columns: Sequence[str]
) -> Dict[str, Any]:
    years = sorted(run_dirs)
    partitions = {p.partition_id: p for p in build_year_partitions(study_dir, "train")}
    cand_frames, obs_frames, part_specs = [], [], []
    for y in years:
        cand_frames.append(pd.read_parquet(run_dirs[y] / "collection" / "candidates.parquet"))
        obs_frames.append(pd.read_parquet(run_dirs[y] / "collection" / "observations.parquet"))
        part_specs.append(partitions[f"train-{y}"])

    merged_cand = merge_partition_outputs(cand_frames, part_specs, key_columns=KEY)
    merged_obs = merge_partition_outputs(obs_frames, part_specs, key_columns=KEY)

    merged_cand = merged_cand.assign(_source_year=_year_of(merged_cand["candidate_ts"]).astype(int))
    merged_obs = merged_obs.assign(_source_year=_year_of(merged_obs["observation_ts"]).astype(int))

    if merged_cand.duplicated(KEY).any() or merged_obs.duplicated(KEY).any():
        raise TrainFreezeError("duplicate candidate keys after merge")
    if merged_cand.duplicated(["episode_id"]).any():
        raise TrainFreezeError("duplicate episode identities after merge")
    missing_features = [c for c in expected_columns if c not in merged_cand.columns]
    if missing_features:
        raise TrainFreezeError(f"merged frame missing declared features: {missing_features}")

    part_hashes = {
        f"train-{y}": {
            "candidates_sha256": frame_content_identity(cf.reindex(sorted(cf.columns), axis=1)),
            "provenance_sha256": ps.provenance_sha256,
        }
        for y, cf, ps in zip(years, cand_frames, part_specs)
    }
    merged_frame_sha256 = frame_content_identity(merged_cand.reindex(sorted(merged_cand.columns), axis=1))

    return {
        "merged_candidates": merged_cand,
        "merged_observations": merged_obs,
        "merged_frame_sha256": merged_frame_sha256,
        "partition_hashes": part_hashes,
        "row_counts": {int(y): int((merged_cand["_source_year"] == y).sum()) for y in years},
        "total_candidates": int(len(merged_cand)),
    }


# --------------------------------------------------------------------------- #
# 3. modeling frame (X / y / meta)
# --------------------------------------------------------------------------- #
def build_modeling_frame(
    merged_cand: pd.DataFrame,
    merged_obs: pd.DataFrame,
    ordered_features: Sequence[str],
    derived_name: str,
) -> Dict[str, Any]:
    obs_cols = KEY + ["disposition", "target_flip_within_horizon", "censored"]
    joined = merged_cand.merge(merged_obs[obs_cols], on=KEY, how="inner", validate="one_to_one")
    if len(joined) != len(merged_cand):
        raise TrainFreezeError(
            f"candidate/observation join lost rows: {len(joined)} of {len(merged_cand)}"
        )

    resolved_mask = joined["disposition"].isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])
    censored_n = int((joined["disposition"] == "CENSORED").sum())
    resolved = joined.loc[resolved_mask].copy()

    # never coerce censored -> negative
    y = resolved["target_flip_within_horizon"].astype(float)
    if y.isna().any() or not set(y.unique()).issubset({0.0, 1.0}):
        raise TrainFreezeError("resolved binary label is not strictly {0,1}")

    model_columns = list(ordered_features) + [derived_name]
    X = resolved[model_columns].apply(pd.to_numeric, errors="coerce").astype("float64")

    year = resolved["_source_year"].astype(int)
    meta = pd.DataFrame({
        "_partition": "train",
        "_year": year.values,
        "_selection_role": np.where(year.isin([2021, 2022]).values, "tuning", "final_validation"),
    }, index=resolved.index)

    per_col_null = {c: float(X[c].isna().mean()) for c in model_columns}

    return {
        "X": X.reset_index(drop=True),
        "y": y.reset_index(drop=True),
        "meta": meta.reset_index(drop=True),
        "prevailing_direction": resolved["prevailing_direction"].reset_index(drop=True),
        "model_columns": model_columns,
        "resolved_rows": int(len(resolved)),
        "pos": int((y == 1.0).sum()),
        "neg": int((y == 0.0).sum()),
        "censored_excluded": censored_n,
        "per_column_null_rate": per_col_null,
        "model_c_available": float(X[derived_name].notna().mean()),
        "joined": joined,
    }


# --------------------------------------------------------------------------- #
# 4. pre-fit population / target gate
# --------------------------------------------------------------------------- #
def write_pre_fit_gate(
    study_dir: Path, spec, frame: Dict[str, Any], dataset_identity_sha256: str
) -> Dict[str, Any]:
    gate = next(g for g in spec.required_gates if g.id == "population_target_gate")
    scope_sha256 = compute_population_scope_sha256(spec, gate.scope_fields)

    y, direction, meta = frame["y"], frame["prevailing_direction"], frame["meta"]
    joined = frame["joined"]

    def _counts(mask) -> Dict[str, int]:
        sub_y = y[mask.values] if hasattr(mask, "values") else y[mask]
        return {
            "target_resolved": int(len(sub_y)),
            "success": int((sub_y == 1.0).sum()),
            "failure": int((sub_y == 0.0).sum()),
            "positive_rate": (float((sub_y == 1.0).mean()) if len(sub_y) else None),
        }

    by_year = {int(yr): _counts(meta["_year"] == yr) for yr in sorted(meta["_year"].unique())}
    by_direction = {
        ("LONG" if d == 1 else "SHORT"): _counts(direction == d)
        for d in sorted(direction.unique())
    }
    dup_disp = int(joined.duplicated(KEY).sum())
    censored_session = int((joined["disposition"] == "CENSORED").sum())

    pathological = []
    if frame["pos"] == 0 or frame["neg"] == 0:
        pathological.append("degenerate class balance")
    for yr, c in by_year.items():
        if c["target_resolved"] == 0:
            pathological.append(f"year {yr} has no resolved rows")
    status = "FAIL" if pathological else "PASS"

    payload = {
        "gate_id": "population_target_gate",
        "schema_version": 1,
        "status": status,
        "scope_sha256": scope_sha256,
        "dataset_identity_sha256": dataset_identity_sha256,
        "producer": "studies/deep_pullback_5s_reacceleration_model/implementation/train_merge_fit_freeze.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "lifecycle_point": "post_train_merge_pre_fit",
        "optimization_use": "prohibited",
        "totals": {
            "merged_candidates": int(len(joined)),
            "target_resolved": frame["resolved_rows"],
            "success": frame["pos"],
            "failure": frame["neg"],
            "censored_session": censored_session,
            "duplicate_or_overlap_dispositions": dup_disp,
            "base_rate": float(frame["pos"] / frame["resolved_rows"]),
        },
        "by_year": by_year,
        "by_direction": by_direction,
        "pathological_findings": pathological,
    }
    out = study_dir / "artifacts" / "population_target_gate.json"
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- #
# 5-6. governed selection + reporting metrics
# --------------------------------------------------------------------------- #
def _report_metrics(y_true: np.ndarray, y_score: np.ndarray) -> Dict[str, Any]:
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        log_loss,
        roc_auc_score,
    )

    y_true = np.asarray(y_true, dtype=float)
    y_score = np.asarray(y_score, dtype=float)
    out: Dict[str, Any] = {
        "n": int(len(y_true)),
        "positive_base_rate": float(y_true.mean()) if len(y_true) else None,
        "prediction_distribution": {
            "min": float(np.min(y_score)) if len(y_score) else None,
            "p10": float(np.quantile(y_score, 0.10)) if len(y_score) else None,
            "median": float(np.median(y_score)) if len(y_score) else None,
            "mean": float(np.mean(y_score)) if len(y_score) else None,
            "p90": float(np.quantile(y_score, 0.90)) if len(y_score) else None,
            "max": float(np.max(y_score)) if len(y_score) else None,
        },
    }
    if len(np.unique(y_true)) == 2:
        out["roc_auc"] = float(roc_auc_score(y_true, y_score))
        out["pr_auc"] = float(average_precision_score(y_true, y_score))
        out["log_loss"] = float(log_loss(y_true, y_score, labels=[0, 1]))
        out["brier"] = float(brier_score_loss(y_true, y_score))
    return out


def run_selection_and_report(study_dir: Path, spec, frame: Dict[str, Any]) -> Dict[str, Any]:
    X, y, meta = frame["X"], frame["y"], frame["meta"]
    selection_spec = spec.model.selection

    manifest = run_model_selection(study_dir, {ARM: X}, y, meta, selection_spec)

    # reporting metrics: replay the SAME governed splits, compute the required panel
    from research.analysis.modeling import SplitPolicy, fit_model

    fit21 = meta["_year"] == 2021
    val22 = meta["_year"] == 2022
    tuning = meta["_selection_role"] == "tuning"
    final23 = meta["_selection_role"] == "final_validation"

    m_fold = fit_model(
        X[fit21.values], y[fit21.values], arm=ARM, estimator="lightgbm", seed=SEED,
        split_policy=SplitPolicy(kind="explicit_index", description="report: inner fold fit 2021"),
        meta=meta[fit21.values],
    )
    inner = _report_metrics(y[val22.values].to_numpy(), m_fold.predict_proba(X[val22.values]))

    m_gate = fit_model(
        X[tuning.values], y[tuning.values], arm=ARM, estimator="lightgbm", seed=SEED,
        split_policy=SplitPolicy(kind="explicit_index", description="report: gated refit 2021+2022"),
        meta=meta[tuning.values],
    )
    gated_2023 = _report_metrics(y[final23.values].to_numpy(), m_gate.predict_proba(X[final23.values]))

    return {
        "manifest": manifest,
        "manifest_path": str(study_dir / "artifacts" / "model_selection_manifest.json"),
        "inner_validation_2022": inner,
        "gated_final_validation_2023": gated_2023,
        "selected_configuration": manifest["winner"][ARM],
        "final_validation_status": manifest["final_validation_status"],
    }


# --------------------------------------------------------------------------- #
# 7-8. final fit + freeze
# --------------------------------------------------------------------------- #
def _preprocessing_hash(model_feature_sha256: str) -> str:
    # No scaling / imputation / encoding / calibration (calibration_required = false);
    # raw LightGBM on the declared surface, native NaN handling. Identity binds to the
    # feature contract via the same helper model_selection.py uses -- not a new algorithm.
    return canonical_sha256({"calibration": "none", "feature_list_sha256": model_feature_sha256})


def final_fit_and_freeze(
    study_dir: Path,
    spec,
    frame: Dict[str, Any],
    selection: Dict[str, Any],
    *,
    dataset_identity_sha256: str,
    merge_info: Dict[str, Any],
    gate_payload: Dict[str, Any],
) -> Dict[str, Any]:
    X, y, meta = frame["X"], frame["y"], frame["meta"]
    model_columns = frame["model_columns"]
    model_feature_sha256 = canonical_sha256(model_columns)
    winner_hp = dict(selection["selected_configuration"].get("hyperparameters") or {})

    analysis_spec = AnalysisSpec(
        analysis_id="deep_pullback_final_train_fit",
        run_id="deep_pullback_final_train_fit",
        model_arms=(ModelArm(name=ARM, features=list(model_columns)),),
        seed=SEED,
    )
    fit_result = fit_models(
        study_dir, X, y, meta=meta, spec=analysis_spec, study_spec=spec,
        dataset_identity_sha256=dataset_identity_sha256,
        estimator="lightgbm", hyperparameters=winner_hp,
    )
    fitted = fit_result["models"][ARM]
    scores = fitted.predict_proba(X)
    score_series = pd.Series(scores)

    # persist the fitted estimator so the frozen model is replayable at OOS / by an
    # NT strategy (mirrors the parent study's artifacts/train_fitted_models.joblib).
    import hashlib as _hashlib

    import joblib

    model_artifact_path = study_dir / "artifacts" / "train_fitted_models.joblib"
    joblib.dump({ARM: fitted.estimator}, model_artifact_path)
    model_artifact_sha256 = _hashlib.sha256(model_artifact_path.read_bytes()).hexdigest()

    deciles = {ARM: {
        "boundaries": [float(score_series.quantile(q)) for q in DECILE_QUANTILES],
        "derivation": "TRAIN_ONLY",
    }}
    preprocessing_hash = _preprocessing_hash(model_feature_sha256)

    freeze_path = freeze_train_artifacts(
        study_dir,
        feature_sets={ARM: list(model_columns)},
        models_manifest=fit_result["manifest"],
        preprocessing_hash=preprocessing_hash,
        score_arrays={ARM: scores.tolist()},
        meta=meta,
        deciles=deciles,
        study_spec=spec,
        model_selection_manifest_path=selection["manifest_path"],
        dataset_identity_sha256=dataset_identity_sha256,
    )
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))

    # reproducibility: re-run the IDENTICAL governed fit_models call and compare the
    # frozen configuration's fit identity, model bytes, and prediction identity.
    from research.analysis.modeling import prediction_identity

    original_fit_identity = fit_result["manifest"]["arms"][ARM]["fit_identity_sha256"]
    repro_result = fit_models(
        study_dir, X, y, meta=meta, spec=analysis_spec, study_spec=spec,
        dataset_identity_sha256=dataset_identity_sha256,
        estimator="lightgbm", hyperparameters=winner_hp,
    )
    repro_fitted = repro_result["models"][ARM]
    repro_scores = repro_fitted.predict_proba(X)
    prediction_parity = prediction_identity(scores) == prediction_identity(repro_scores)
    fit_identity_parity = (
        repro_result["manifest"]["arms"][ARM]["fit_identity_sha256"] == original_fit_identity
    )
    artifact_bytes_parity = repro_fitted.provenance.model_sha256 == fitted.provenance.model_sha256

    from research_workflow.modeling_closure import resolve_modeling_closure

    modeling_closure = resolve_modeling_closure(
        study_dir, driver_relpaths=["implementation/train_merge_fit_freeze.py"],
    )
    (study_dir / "artifacts" / "modeling_execution_manifest.json").write_text(
        json.dumps(modeling_closure, indent=2, default=str) + "\n", encoding="utf-8")

    lineage = {
        "schema_version": 1,
        "study_id": "deep_pullback_5s_reacceleration_model",
        "collection_producer_composite_sha256": SEALED_COMPOSITE,
        "modeling_execution_composite_sha256": modeling_closure["modeling_execution_composite_sha256"],
        "modeling_execution_file_count": modeling_closure["file_count"],
        "sealed_execution_composite_sha256": SEALED_COMPOSITE,
        "train_experiment_freeze_sha256": frozen["freeze_sha256"],
        "authorization_sha256": frozen["authorization_sha256"],
        "train_source_partition_hashes": merge_info["partition_hashes"],
        "merged_train_frame_sha256": merge_info["merged_frame_sha256"],
        "merged_train_dataset_identity_sha256": dataset_identity_sha256,
        "binary_population_definition": {
            "included_dispositions": ["LABELED_POSITIVE", "LABELED_NEGATIVE"],
            "excluded_dispositions": ["CENSORED"],
            "label_column": "target_flip_within_horizon",
            "censored_rows_never_coerced_to_negative": True,
            "resolved_rows": frame["resolved_rows"],
            "positives": frame["pos"],
            "negatives": frame["neg"],
            "censored_excluded": frame["censored_excluded"],
        },
        "feature_order": model_columns,
        "feature_order_sha256": model_feature_sha256,
        "canonical_feature_count": len(model_columns) - 1,
        "derived_input": {
            "name": "model_c_score_at_candidate",
            "kind": "frozen_external_model_score",
            "parent_study_id": "clean_maturity_flip_model_rolling_productivity",
            "retrain_prohibited": True,
            "direction_arm_mapping": {"LONG": "LONG_C", "SHORT": "SHORT_C"},
            "availability_reference": "decision_ts",
        },
        "null_policy": {
            "handling": "lightgbm_native_missing",
            "complete_case_filtering": False,
            "per_column_null_rate": frame["per_column_null_rate"],
        },
        "preprocessing": {"calibration": "none", "scaling": "none", "imputation": "none",
                          "preprocessing_hash": preprocessing_hash},
        "model_family": "lightgbm",
        "arm": ARM,
        "hyperparameters": winner_hp,
        "deterministic_seed": SEED,
        "tuning_chronology": {
            "tuning_years": spec.model.selection.tuning_years,
            "inner_walk_forward_folds": [{"fit_years": [2021], "val_year": 2022}],
            "final_train_validation_years": spec.model.selection.final_train_validation_years,
        },
        "model_selection": {
            "search_method": spec.model.selection.search_method,
            "configurations_evaluated": manifest_configs(selection),
            "selected_configuration": selection["selected_configuration"],
            "primary_selection_metric": spec.model.selection.primary_selection_metric or "roc_auc(default)",
            "selected_using_2021_2022_only": True,
            "model_selection_manifest_sha256": selection["manifest"]["manifest_sha256"],
        },
        "gated_2023_validation_metrics": selection["gated_final_validation_2023"],
        "inner_2022_validation_metrics": selection["inner_validation_2022"],
        "final_fit_scope": "all_resolved_train_rows_2021_2023_single_partition",
        "final_fit_rows": int(len(X)),
        "fitted_model_artifact": {
            "manifest_path": "artifacts/experiment_models.json",
            "model_artifact_path": "artifacts/train_fitted_models.joblib",
            "model_artifact_sha256": model_artifact_sha256,
            "fit_identity_sha256": original_fit_identity,
            "model_sha256": fitted.provenance.model_sha256,
            "x_content_sha256": fitted.provenance.x_content_sha256,
            "y_content_sha256": fitted.provenance.y_content_sha256,
        },
        "thresholds": frozen["thresholds"],
        "deciles": frozen["deciles"],
        "reproducibility": {
            "fit_identity_parity": bool(fit_identity_parity),
            "prediction_parity": bool(prediction_parity),
            "artifact_bytes_parity": bool(artifact_bytes_parity),
        },
        "library_versions": library_versions(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    lineage_path = study_dir / "artifacts" / "train_freeze_lineage.json"
    lineage_path.write_text(json.dumps(lineage, indent=2, default=str) + "\n", encoding="utf-8")

    return {
        "freeze_path": str(freeze_path),
        "freeze_sha256": frozen["freeze_sha256"],
        "lineage_path": str(lineage_path),
        "models_manifest_path": str(study_dir / "artifacts" / "experiment_models.json"),
        "model_artifact_path": str(model_artifact_path),
        "model_artifact_sha256": model_artifact_sha256,
        "fit_identity_sha256": original_fit_identity,
        "model_sha256": fitted.provenance.model_sha256,
        "preprocessing_hash": preprocessing_hash,
        "final_fit_rows": int(len(X)),
        "reproducibility": lineage["reproducibility"],
        "hyperparameters": winner_hp,
    }


def manifest_configs(selection: Dict[str, Any]) -> int:
    attempts = selection["manifest"].get("attempts", {}).get(ARM, [])
    return len(attempts)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def run(study_dir: str | Path, run_dirs: Mapping[int, str | Path]) -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    from backtests.nt_runtime.compiled_study_loader import load_compiled_study

    spec = load_compiled_study(study_dir).spec
    fc = json.loads((study_dir / "config" / "feature_contract.json").read_text(encoding="utf-8"))
    ordered_features = list(fc["feature_list"])
    derived_name = fc["derived_causal_inputs"][0]["name"]

    rd = {int(y): Path(p).resolve() for y, p in run_dirs.items()}
    sample_cols = list(pd.read_parquet(rd[sorted(rd)[0]] / "collection" / "candidates.parquet").columns)

    verifications = {y: verify_partition(rd[y], y, sample_cols) for y in sorted(rd)}
    if any(not v["passed"] for v in verifications.values()):
        raise TrainFreezeError(f"partition verification failed: {verifications}")

    merge_info = merge_train_partitions(study_dir, rd, ordered_features)
    frame = build_modeling_frame(
        merge_info["merged_candidates"], merge_info["merged_observations"],
        ordered_features, derived_name,
    )
    dataset_identity_sha256 = merge_info["merged_frame_sha256"]

    gate_payload = write_pre_fit_gate(study_dir, spec, frame, dataset_identity_sha256)
    if gate_payload["status"] != "PASS":
        raise TrainFreezeError(f"pre-fit population/target gate FAILED: {gate_payload['pathological_findings']}")

    selection = run_selection_and_report(study_dir, spec, frame)
    freeze = final_fit_and_freeze(
        study_dir, spec, frame, selection,
        dataset_identity_sha256=dataset_identity_sha256,
        merge_info=merge_info, gate_payload=gate_payload,
    )

    return {
        "verifications": verifications,
        "merge": {k: v for k, v in merge_info.items() if k not in ("merged_candidates", "merged_observations")},
        "frame": {k: v for k, v in frame.items()
                  if k not in ("X", "y", "meta", "prevailing_direction", "joined")},
        "pre_fit_gate": gate_payload,
        "selection": {k: v for k, v in selection.items() if k != "manifest"},
        "selection_manifest_sha256": selection["manifest"]["manifest_sha256"],
        "freeze": freeze,
        "dataset_identity_sha256": dataset_identity_sha256,
    }


if __name__ == "__main__":
    import sys

    study = "studies/deep_pullback_5s_reacceleration_model"
    runs = {
        2021: "studies/deep_pullback_5s_reacceleration_model/runs/20260828_144743_deep_pullback_5s_reacceleration_model_full",
        2022: "studies/deep_pullback_5s_reacceleration_model/runs/20260828_150235_deep_pullback_5s_reacceleration_model_full",
        2023: "studies/deep_pullback_5s_reacceleration_model/runs/20260828_152004_deep_pullback_5s_reacceleration_model_full",
    }
    result = run(study, runs)
    json.dump(result, sys.stdout, indent=2, default=str)
    print()
