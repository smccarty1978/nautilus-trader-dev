"""Governed model fitting and TRAIN artifact freezing."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

from research.analysis.modeling import SplitPolicy, fit_arms, freeze_threshold, write_model_manifest
from research_workflow.experiment import write_train_freeze
from research_workflow.forward_outcomes.guard import (
    assert_causal_feature_surface,
    guard_training_frame,
)


def fit_models(
    study_path: str | Path,
    X: pd.DataFrame,
    y: pd.Series,
    *,
    meta: pd.DataFrame,
    spec,
    dataset_identity_sha256: Optional[str] = None,
    estimator: str = "gradient_boosting",
    hyperparameters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fit declared arms on one TRAIN partition and persist model provenance."""
    if "_partition" not in meta or set(meta["_partition"].dropna()) != {"train"}:
        raise ValueError("fit_models requires a single TRAIN partition")
    # A forward outcome resolves after the entry it describes, so it is a label. The
    # accident this guards is mundane: an outcome table joined onto candidates for
    # analysis, then a feature matrix built from the joined frame's columns. X is the
    # authoritative feature surface here, so it is the surface that gets checked.
    guard_training_frame(X, list(X.columns), context="fit_models feature matrix")
    models = fit_arms(
        X, y, spec, estimator=estimator, hyperparameters=hyperparameters,
        dataset_identity_sha256=dataset_identity_sha256,
        meta=meta,
    )
    out = Path(study_path).resolve() / "artifacts" / "experiment_models.json"
    manifest = write_model_manifest(models, out)
    return {"models": models, "manifest": manifest, "path": str(out)}


def freeze_train_artifacts(
    study_path: str | Path,
    *,
    feature_sets: Mapping[str, list[str]],
    models_manifest: Mapping[str, Any],
    preprocessing_hash: str,
    score_arrays: Mapping[str, Any],
    meta: pd.DataFrame,
    thresholds: Optional[Mapping[str, Any]] = None,
    deciles: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Freeze all TRAIN-derived objects before any OOS frame is accepted."""
    if "_partition" not in meta or set(meta["_partition"].dropna()) != {"train"}:
        raise ValueError("freeze_train_artifacts requires TRAIN-only metadata")
    # The frozen feature sets are what OOS scoring replays. Guarding them here as well
    # as in fit_models is deliberate: a set can be assembled and frozen without ever
    # passing through a fitter, and a leak frozen into the contract outlives the run.
    for arm, columns in feature_sets.items():
        assert_causal_feature_surface(
            columns, context=f"TRAIN freeze feature set for arm {arm!r}"
        )
    threshold_payload = dict(thresholds or {})
    if not threshold_payload:
        # Thresholds are caller-supplied only after they have been derived from
        # TRAIN scores; the workflow records them rather than inventing policy.
        for arm, scores in score_arrays.items():
            # Callers may provide the corresponding labels in ``y_true`` when
            # supplying explicit threshold records.  The default records freeze
            # score boundaries only; PPV is intentionally left to analysis.
            values = list(scores)
            threshold_payload[arm] = {
                "p90": {"method": "quantile", "parameter": 0.90, "threshold": float(pd.Series(values).quantile(0.90)), "derivation_population": "train"},
                "p95": {"method": "quantile", "parameter": 0.95, "threshold": float(pd.Series(values).quantile(0.95)), "derivation_population": "train"},
                "p97_5": {"method": "quantile", "parameter": 0.975, "threshold": float(pd.Series(values).quantile(0.975)), "derivation_population": "train"},
            }
    payload = {
        "partition": "train",
        "feature_sets": {k: list(v) for k, v in feature_sets.items()},
        "model_hashes": {
            arm: rec.get("fit_identity_sha256")
            for arm, rec in (models_manifest.get("arms") or {}).items()
        },
        "preprocessing_hash": preprocessing_hash,
        "thresholds": threshold_payload,
        "deciles": dict(deciles or {}),
    }
    return write_train_freeze(study_path, payload)
