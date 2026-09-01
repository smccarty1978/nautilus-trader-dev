"""Declared Phase D TRAIN-only barrier-race modeling composition.

This is deliberately a small study-local *composition*, not a second modeling
framework.  It joins the frozen Phase-C tables, enforces the approved temporal
folds, and delegates fitting/provenance persistence to the shared modeling
utilities.  It is execution-closure-bound through
``execution.modeling_driver_relpaths``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from research.analysis.identity import canonical_sha256
from research.analysis.metrics import brier, pr_auc, roc_auc
from research.analysis.modeling import SplitPolicy, write_model_manifest
from research_workflow.modeling import fit_temporal_fold
from research_workflow.model_artifacts import persist_models
from research_workflow.modeling_closure import resolve_modeling_closure
from research_workflow.modeling_drivers import assert_declared_modeling_drivers

TRAIN_YEARS = (2021, 2022, 2023)
OOS_YEARS = frozenset((2024, 2025, 2026))
FEATURE_COUNT = 13
AUTHORITATIVE_TARGET_SHA256 = "21d598a823fd6430459380b3c9f6a75f2b90b61048d78cd7ff840b3f54218b0e"
AUTHORITATIVE_TARGET_LOGICAL_SHA256 = "552690f09c48d7a1208574e0aefa73aa10c0d0b717a34c9ff86474468e893b95"
ARMS = ("SL0_5", "SL1_0", "SL1_5")
DIRECTIONS = ("LONG", "SHORT")
FOLDS = (
    {"name": "fold_2022", "fit_years": (2021,), "validation_year": 2022},
    {"name": "fold_2023", "fit_years": (2021, 2022), "validation_year": 2023},
)
DEFAULT_CONFIGURATIONS = tuple(
    {
        "max_depth": depth, "num_leaves": leaves, "learning_rate": rate,
        "min_data_in_leaf": leaf, "n_estimators": 200, "n_jobs": 1,
        "deterministic": True, "verbosity": -1,
    }
    for depth, leaves, rate, leaf in product((3, 5, 7), (7, 15, 31), (0.03, 0.05), (100, 500))
)


class PhaseDProtocolError(RuntimeError):
    """The frozen Phase-D source does not satisfy the declared composition."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric(result: Any) -> dict[str, Any]:
    return result.to_dict() if hasattr(result, "to_dict") else result


def _log_loss(y: pd.Series, scores: np.ndarray) -> dict[str, Any]:
    from sklearn.metrics import log_loss
    return {"metric": "log_loss", "value": float(log_loss(y.astype(int), scores, labels=[0, 1])),
            "status": "ok", "n": int(len(y)), "n_missing": 0}


def _year(values: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(values):
        return values.dt.year.astype(int)
    numeric = pd.to_numeric(values, errors="raise")
    # Current runtime identities are ns; permit seconds only for bounded fixtures.
    unit = "ns" if float(numeric.abs().max()) > 10_000_000_000 else "s"
    return pd.to_datetime(numeric, unit=unit, utc=True).dt.year.astype(int)


def _direction(values: pd.Series) -> pd.Series:
    mapping = {1: "LONG", -1: "SHORT", "1": "LONG", "-1": "SHORT",
               "LONG": "LONG", "SHORT": "SHORT", "long": "LONG", "short": "SHORT"}
    result = values.map(mapping)
    if result.isna().any():
        raise PhaseDProtocolError(f"PHASE_D_UNKNOWN_DIRECTION:{sorted(map(str, values[result.isna()].unique()))}")
    return result


def _identity_columns(frame: pd.DataFrame) -> list[str]:
    keys = ["observation_ts", "regime_start_ns", "checkpoint_index"]
    missing = [key for key in keys if key not in frame]
    if missing:
        raise PhaseDProtocolError(f"PHASE_D_CANDIDATE_IDENTITY_MISSING:{missing}")
    return keys


def _load_frame(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise PhaseDProtocolError(f"PHASE_D_INPUT_MISSING:{path}")
    return pd.read_parquet(path)


def _assert_target_authority(study: Path) -> Path:
    """Authenticate the one reconciled Phase-C target before any frame is loaded."""
    target = study / "_work" / "train_merged_collection" / "phase_c2_reconciled_targets.parquet"
    record = study / "artifacts" / "train_target_authority_reconciliation.json"
    if not target.is_file() or not record.is_file():
        raise PhaseDProtocolError("PHASE_D_TARGET_AUTHORITY_EVIDENCE_MISSING")
    body = json.loads(record.read_text(encoding="utf-8"))
    text = json.dumps(body, sort_keys=True)
    if (AUTHORITATIVE_TARGET_SHA256 not in text or AUTHORITATIVE_TARGET_LOGICAL_SHA256 not in text
            or _sha(target) != AUTHORITATIVE_TARGET_SHA256):
        raise PhaseDProtocolError("PHASE_D_TARGET_AUTHORITY_MISMATCH")
    return target


def load_phase_c_inputs(
    candidates_path: str | Path, observations_path: str | Path, targets_path: str | Path,
    *, feature_columns: Iterable[str],
) -> pd.DataFrame:
    """Load only Phase-C TRAIN inputs and preserve their authoritative row order."""
    candidates, observations, targets = map(_load_frame, (candidates_path, observations_path, targets_path))
    keys = _identity_columns(candidates)
    _identity_columns(observations)
    if len(candidates) != len(observations) or len(candidates) != len(targets):
        raise PhaseDProtocolError("PHASE_D_PHASE_C_ROW_COUNT_MISMATCH")
    if not candidates[keys].equals(observations[keys]):
        raise PhaseDProtocolError("PHASE_D_CANDIDATE_OBSERVATION_IDENTITY_OR_ORDER_MISMATCH")
    cols = list(feature_columns)
    if len(cols) != FEATURE_COUNT or len(set(cols)) != FEATURE_COUNT:
        raise PhaseDProtocolError("PHASE_D_FEATURE_CONTRACT_NOT_EXACTLY_13")
    missing = [c for c in cols if c not in observations]
    if missing:
        raise PhaseDProtocolError(f"PHASE_D_FEATURE_COLUMNS_MISSING:{missing}")
    direction_col = next((c for c in ("regime_direction", "direction", "prevailing_regime") if c in candidates), None)
    if direction_col is None:
        raise PhaseDProtocolError("PHASE_D_DIRECTION_COLUMN_MISSING")
    out = pd.concat([candidates.reset_index(drop=True), observations[cols].reset_index(drop=True),
                     targets.reset_index(drop=True)], axis=1)
    if out.columns.duplicated().any():
        raise PhaseDProtocolError("PHASE_D_DUPLICATE_JOIN_COLUMN")
    out["_year"] = _year(out["observation_ts"])
    observed = set(out["_year"].unique())
    if observed & OOS_YEARS or not observed <= set(TRAIN_YEARS):
        raise PhaseDProtocolError(f"PHASE_D_NONTRAIN_YEAR_READ:{sorted(observed)}")
    out["_direction"] = _direction(out[direction_col])
    return out


def _cell_target_columns(stop_arm: str) -> tuple[str, str]:
    mapping = {"SL0_5": "sl0_5", "SL1_0": "sl1_0", "SL1_5": "sl1_5"}
    if stop_arm not in mapping:
        raise PhaseDProtocolError(f"PHASE_D_UNKNOWN_STOP_ARM:{stop_arm}")
    suffix = mapping[stop_arm]
    return f"target_tp1_{suffix}_label", f"target_tp1_{suffix}_disposition"


def _resolved_cell(frame: pd.DataFrame, direction: str, stop_arm: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    label, disposition = _cell_target_columns(stop_arm)
    if label not in frame or disposition not in frame:
        raise PhaseDProtocolError(f"PHASE_D_TARGET_COLUMNS_MISSING:{stop_arm}")
    direction_frame = frame[frame["_direction"] == direction].copy()
    # Runtime records the adverse-stop terminal as ``NEGATIVE``; Phase-D's
    # ``NEGATIVE_SL`` name is its semantic role, not a second label spelling.
    binary = direction_frame[direction_frame[disposition].isin(("POSITIVE", "NEGATIVE", "NEGATIVE_SL"))].copy()
    if binary.empty or not set(binary[label].dropna().unique()) <= {0.0, 1.0, 0, 1}:
        raise PhaseDProtocolError(f"PHASE_D_BINARY_TARGET_INVALID:{direction}:{stop_arm}")
    return direction_frame, binary


def _assert_group_integrity(frame: pd.DataFrame, fit_years: Iterable[int], validation_year: int) -> None:
    fit = set(frame.loc[frame["_year"].isin(fit_years), "regime_start_ns"])
    validation = set(frame.loc[frame["_year"] == validation_year, "regime_start_ns"])
    overlap = fit & validation
    if overlap:
        raise PhaseDProtocolError(f"PHASE_D_REGIME_GROUP_CROSSES_FOLD:{validation_year}:{len(overlap)}")


def _calibration(y: pd.Series, score: np.ndarray) -> dict[str, Any]:
    if y.nunique() < 2:
        return {"status": "NOT_COMPUTABLE", "reason": "single_class"}
    try:
        from sklearn.linear_model import LogisticRegression
        clipped = np.clip(score, 1e-6, 1 - 1e-6)
        logit = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
        fit = LogisticRegression(C=1e6, solver="lbfgs").fit(logit, y.astype(int))
        return {"status": "PASS", "slope": float(fit.coef_[0][0]), "intercept": float(fit.intercept_[0])}
    except Exception as exc:  # diagnostics must report, not hide, unsupported calibration.
        return {"status": "NOT_COMPUTABLE", "reason": type(exc).__name__}


def _deciles(frame: pd.DataFrame, score_col: str, label_col: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    work = frame[[score_col, label_col]].dropna().sort_values(score_col, kind="mergesort").copy()
    work["_decile"] = np.minimum(9, (np.arange(len(work)) * 10 // len(work))) + 1
    baseline = float(work[label_col].mean())
    return [{"decile": int(d), "n": int(len(g)), "positive_rate": float(g[label_col].mean()),
             "lift_vs_baseline": (float(g[label_col].mean()) / baseline if baseline else None),
             "mean_score": float(g[score_col].mean())}
            for d, g in work.groupby("_decile", sort=True)]


def _regime_diagnostics(frame: pd.DataFrame, score_col: str, label_col: str) -> dict[str, Any]:
    ordered = frame.sort_values(["regime_start_ns", "observation_ts", "checkpoint_index"], kind="mergesort")
    first = ordered.groupby("regime_start_ns", sort=False).first()[[score_col, label_col]].reset_index(drop=True)
    max_rows = ordered.loc[ordered.groupby("regime_start_ns")[score_col].idxmax(), [score_col, label_col]].reset_index(drop=True)
    mean = ordered.groupby("regime_start_ns", sort=False).agg({score_col: "mean", label_col: "max"}).reset_index(drop=True)
    output: dict[str, Any] = {}
    for name, table in (("first", first), ("max", max_rows), ("mean", mean)):
        output[name] = {"n_regimes": int(len(table)), "roc_auc": _metric(roc_auc(table[label_col], table[score_col])),
                        "score_bucket_lift": _deciles(table, score_col, label_col)}
    return output


def _first_fire(frame: pd.DataFrame, score_col: str, label_col: str) -> dict[str, Any]:
    threshold = float(frame[score_col].quantile(0.90))
    ordered = frame.sort_values(["regime_start_ns", "observation_ts", "checkpoint_index"], kind="mergesort")
    fires = ordered[ordered[score_col] >= threshold].groupby("regime_start_ns", sort=False).first()
    baseline = float(ordered[label_col].mean()) if len(ordered) else None
    rate = float(fires[label_col].mean()) if len(fires) else None
    return {"threshold": threshold, "threshold_population": "validation_scores_only", "triggered_regimes": int(len(fires)),
            "positive_rate": rate, "baseline_positive_rate": baseline,
            "lift": (rate / baseline if baseline else None)}


def _timeout_by_decile(frame: pd.DataFrame, score_col: str, disposition_col: str) -> list[dict[str, Any]]:
    work = frame[[score_col, disposition_col]].dropna(subset=[score_col]).sort_values(score_col, kind="mergesort").copy()
    if work.empty:
        return []
    work["_decile"] = np.minimum(9, (np.arange(len(work)) * 10 // len(work))) + 1
    return [{"decile": int(d), "n": int(len(g)), "timeout_rate": float((g[disposition_col] == "TIMEOUT").mean())}
            for d, g in work.groupby("_decile", sort=True)]


def _importance(model: Any) -> dict[str, list[dict[str, Any]]]:
    names = list(model.provenance.ordered_features)
    est = model.estimator
    gain = getattr(getattr(est, "booster_", None), "feature_importance", None)
    if gain is None:
        return {"gain": [], "split": []}
    return {"gain": [{"feature": n, "importance": float(v)} for n, v in zip(names, gain(importance_type="gain"))],
            "split": [{"feature": n, "importance": float(v)} for n, v in zip(names, gain(importance_type="split"))]}


def _fit_one(study: Path, X: pd.DataFrame, y: pd.Series, *, arm: str, config: Mapping[str, Any], dataset_id: str,
             fold: Mapping[str, Any]) -> Any:
    return fit_temporal_fold(study, X, y.astype(int), arm=arm, estimator="lightgbm", seed=42,
        hyperparameters=dict(config), dataset_identity_sha256=dataset_id,
        split_policy=SplitPolicy(kind="explicit_index", description=f"Phase D {fold['name']} expanding temporal regime-grouped"),
        meta=pd.DataFrame({"_partition": ["train"] * len(X)}))


def run_phase_d(
    study_path: str | Path, *, candidates_path: str | Path, observations_path: str | Path,
    targets_path: str | Path | None = None, output_dir: str | Path | None = None,
    configurations: Iterable[Mapping[str, Any]] = DEFAULT_CONFIGURATIONS,
) -> dict[str, Any]:
    """Run the authorized TRAIN-only protocol; callers must have passed lifecycle gates."""
    study = Path(study_path).resolve()
    compiled = json.loads((study / "compiled_study.json").read_text(encoding="utf-8"))
    spec = compiled.get("spec") or {}
    execution = spec.get("execution") or {}
    declared = list(execution.get("modeling_driver_relpaths") or [])
    assert_declared_modeling_drivers(study, declared)
    if "implementation/phase_d_modeling.py" not in declared:
        raise PhaseDProtocolError("PHASE_D_DRIVER_NOT_DECLARED")
    chronology = spec.get("chronology") or {}
    if tuple(chronology.get("train") or []) != TRAIN_YEARS or 2024 not in (chronology.get("dev") or []):
        raise PhaseDProtocolError("PHASE_D_CHRONOLOGY_CONTRACT_MISMATCH")
    authoritative_target = _assert_target_authority(study)
    if targets_path is not None and Path(targets_path).resolve() != authoritative_target.resolve():
        raise PhaseDProtocolError("PHASE_D_ARBITRARY_TARGET_PATH_PROHIBITED")
    feature_path = study / "config" / "feature_contract.json"
    features = json.loads(feature_path.read_text(encoding="utf-8"))["feature_list"]
    frame = load_phase_c_inputs(candidates_path, observations_path, authoritative_target, feature_columns=features)
    source_hashes = {name: _sha(Path(value)) for name, value in {"candidates": candidates_path, "observations": observations_path, "targets": authoritative_target}.items()}
    dataset_id = canonical_sha256({"phase": "D", "source_sha256": source_hashes, "feature_contract_sha256": canonical_sha256(features)})
    out = Path(output_dir) if output_dir else study / "artifacts" / "phase_d"
    out.mkdir(parents=True, exist_ok=True)
    configs = [dict(c) for c in configurations]
    if not configs:
        raise PhaseDProtocolError("PHASE_D_EMPTY_CONFIGURATION_SET")
    closure = resolve_modeling_closure(study, driver_relpaths=declared)
    results: dict[str, Any] = {"schema_version": 1, "phase": "PHASE_D_MODELING", "train_years": list(TRAIN_YEARS),
        "oos_accessed": False, "feature_columns": features, "source_sha256": source_hashes,
        "configuration_count": len(configs), "folds": list(FOLDS), "cells": {}}
    persisted: list[dict[str, Any]] = []
    for direction in DIRECTIONS:
        for stop_arm in ARMS:
            cell_name = f"{direction}_{stop_arm}"
            all_direction, binary = _resolved_cell(frame, direction, stop_arm)
            label, disposition = _cell_target_columns(stop_arm)
            attempts: list[dict[str, Any]] = []
            for index, config in enumerate(configs):
                fold_metrics = []
                for fold in FOLDS:
                    _assert_group_integrity(binary, fold["fit_years"], fold["validation_year"])
                    fit = binary[binary["_year"].isin(fold["fit_years"])]
                    validation = binary[binary["_year"] == fold["validation_year"]]
                    if fit.empty or validation.empty:
                        raise PhaseDProtocolError(f"PHASE_D_EMPTY_TEMPORAL_FOLD:{cell_name}:{fold['name']}")
                    model = _fit_one(study, fit[features], fit[label], arm=f"{cell_name}_C{index:02d}_{fold['name']}", config=config, dataset_id=dataset_id, fold=fold)
                    scores = model.predict_proba(validation[features])
                    fold_metrics.append({"fold": fold["name"], "roc_auc": _metric(roc_auc(validation[label], scores)),
                        "pr_auc": _metric(pr_auc(validation[label], scores)), "log_loss": _log_loss(validation[label], scores), "brier": _metric(brier(validation[label], scores))})
                    manifest = write_model_manifest({model.provenance.arm: model}, out / f"{model.provenance.arm}.json")
                    saved = persist_models(study, {model.provenance.arm: model}, manifest,
                        feature_contract_identity=canonical_sha256(features), target_identity=source_hashes["targets"],
                        preprocessing_identity={"kind": "identity", "identity": "identity"}, train_frame_identity=dataset_id,
                        training_years=list(fold["fit_years"]), closures=closure)
                    persisted.extend(saved["records"])
                roc_values = [x["roc_auc"]["value"] for x in fold_metrics]
                pr_values = [x["pr_auc"]["value"] for x in fold_metrics]
                attempts.append({"configuration_index": index, "hyperparameters": config, "fold_metrics": fold_metrics,
                    "mean_roc_auc": float(np.mean(roc_values)), "min_roc_auc": float(np.min(roc_values)),
                    "mean_pr_auc": float(np.mean(pr_values)), "roc_auc_std": float(np.std(roc_values))})
            # Fixed predeclared stable ordering: higher worst-fold AUC, then mean AUC/PR, then lower dispersion, then configuration order.
            attempts.sort(key=lambda a: (-a["min_roc_auc"], -a["mean_roc_auc"], -a["mean_pr_auc"], a["roc_auc_std"], a["configuration_index"]))
            winner = attempts[0]
            fold_reports: dict[str, Any] = {}
            final_models: dict[str, Any] = {}
            for fold in FOLDS:
                fit = binary[binary["_year"].isin(fold["fit_years"])]
                valid_all = all_direction[all_direction["_year"] == fold["validation_year"]].copy()
                valid_binary = valid_all[valid_all[disposition].isin(("POSITIVE", "NEGATIVE", "NEGATIVE_SL"))].copy()
                model = _fit_one(study, fit[features], fit[label], arm=f"{cell_name}_SELECTED_{fold['name']}", config=winner["hyperparameters"], dataset_id=dataset_id, fold=fold)
                valid_all["_score"] = model.predict_proba(valid_all[features])
                valid_binary = valid_all[valid_all[disposition].isin(("POSITIVE", "NEGATIVE", "NEGATIVE_SL"))].copy()
                score = valid_binary["_score"].to_numpy()
                fold_reports[fold["name"]] = {"n": int(len(valid_binary)), "unique_regimes": int(valid_binary["regime_start_ns"].nunique()),
                    "candidates_per_regime": float(len(valid_binary) / valid_binary["regime_start_ns"].nunique()),
                    "prevalence": float(valid_binary[label].mean()), "roc_auc": _metric(roc_auc(valid_binary[label], score)),
                    "pr_auc": _metric(pr_auc(valid_binary[label], score)), "log_loss": _log_loss(valid_binary[label], score), "brier": _metric(brier(valid_binary[label], score)),
                    "calibration": _calibration(valid_binary[label], score), "deciles": _deciles(valid_binary, "_score", label),
                    "regime_level": _regime_diagnostics(valid_binary, "_score", label), "first_fire": _first_fire(valid_binary, "_score", label),
                    "timeout_by_decile": _timeout_by_decile(valid_all, "_score", disposition), "feature_importance": _importance(model)}
                final_models[model.provenance.arm] = model
                manifest = write_model_manifest({model.provenance.arm: model}, out / f"{model.provenance.arm}.json")
                saved = persist_models(study, {model.provenance.arm: model}, manifest,
                    feature_contract_identity=canonical_sha256(features), target_identity=source_hashes["targets"],
                    preprocessing_identity={"kind": "identity", "identity": "identity"}, train_frame_identity=dataset_id,
                    training_years=list(fold["fit_years"]), closures=closure)
                persisted.extend(saved["records"])
            results["cells"][cell_name] = {"attempts": attempts, "selected": winner, "validation": fold_reports}
    results["model_artifact_count"] = len(persisted)
    results["model_artifacts"] = [{k: r.get(k) for k in ("model_id", "model_role", "artifact_path", "artifact_sha256", "native_booster_path", "native_booster_sha256")} for r in persisted]
    results["result_sha256"] = canonical_sha256({k: v for k, v in results.items() if k != "result_sha256"})
    destination = out / "phase_d_modeling_report.json"
    destination.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    receipt_path = out / "phase_d_model_artifacts.json"
    receipt_path.write_text(json.dumps(results["model_artifacts"], indent=2, sort_keys=True), encoding="utf-8")
    return {"status": "PASS", "artifact": str(destination), "sha256": _sha(destination), "model_artifact_count": len(persisted), "oos_accessed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run declared Phase D TRAIN-only modeling")
    parser.add_argument("--study", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--targets", help="must equal the canonical reconciled target path; otherwise refused")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    receipt = run_phase_d(args.study, candidates_path=args.candidates, observations_path=args.observations,
                          targets_path=args.targets, output_dir=args.output_dir)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
