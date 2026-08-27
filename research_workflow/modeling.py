"""Governed model fitting and TRAIN artifact freezing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

from research.analysis.modeling import SplitPolicy, fit_arms, freeze_threshold, write_model_manifest
from research_workflow.experiment import write_train_freeze
from research_workflow.forward_outcomes.guard import (
    assert_causal_feature_surface,
    guard_training_frame,
)


class ModelSelectionBindingRequired(RuntimeError):
    """study.model.selection declares a search, but no selection manifest was supplied."""


class ModelSelectionBindingMismatch(RuntimeError):
    """A frozen arm's hyperparameters/seed do not match the selection manifest's winner."""


class ModelSelectionFinalValidationFailed(RuntimeError):
    """The selection manifest's gated final-validation status is FAIL; the freeze refuses.

    No re-derivation, no re-search, no hyperparameter change is attempted here -- the
    only actions are refuse-to-freeze (this) or accept (final_validation_status == PASS,
    or policy == report_only)."""


def fit_models(
    study_path: str | Path,
    X: pd.DataFrame,
    y: pd.Series,
    *,
    meta: pd.DataFrame,
    spec,
    study_spec: Optional[Any] = None,
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
    if study_spec is not None and getattr(study_spec, "required_gates", None):
        from research_workflow.gates import assert_gates_satisfied

        assert_gates_satisfied(
            study_path,
            study_spec,
            stage="pre_fit",
            dataset_identity_sha256=dataset_identity_sha256,
        )
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
    study_spec: Optional[Any] = None,
    model_selection_manifest_path: Optional[str | Path] = None,
    dataset_identity_sha256: Optional[str] = None,
) -> Path:
    """Freeze all TRAIN-derived objects before any OOS frame is accepted.

    ``study_spec`` (a ``research.schemas.study_spec.StudySpec``, optional for backward
    compatibility with callers that predate model selection / required gates) drives two
    additional fail-closed checks when supplied:

    * if ``study_spec.model.selection`` declares a search (``search_method != "none"``),
      ``model_selection_manifest_path`` is required, and every frozen arm's
      hyperparameters/seed must trace exactly to that manifest's winner
      (``ModelSelectionBindingMismatch`` otherwise) -- the freeze refuses a model whose
      family/hyperparameters cannot be traced to the declared selection protocol. If the
      manifest's ``final_validation_policy`` is ``"gated"`` and its
      ``final_validation_status`` is not ``"PASS"``, the freeze refuses outright
      (``ModelSelectionFinalValidationFailed``) -- no re-derivation is attempted.
    * any ``study_spec.required_gates`` staged ``"train_freeze"`` must be satisfied
      (``research_workflow.gates.assert_gates_satisfied``).
    """
    if "_partition" not in meta or set(meta["_partition"].dropna()) != {"train"}:
        raise ValueError("freeze_train_artifacts requires TRAIN-only metadata")
    # The frozen feature sets are what OOS scoring replays. Guarding them here as well
    # as in fit_models is deliberate: a set can be assembled and frozen without ever
    # passing through a fitter, and a leak frozen into the contract outlives the run.
    for arm, columns in feature_sets.items():
        assert_causal_feature_surface(
            columns, context=f"TRAIN freeze feature set for arm {arm!r}"
        )

    selection_manifest: Optional[Dict[str, Any]] = None
    selection = getattr(getattr(study_spec, "model", None), "selection", None)
    if selection is not None and selection.search_method != "none":
        if model_selection_manifest_path is None:
            raise ModelSelectionBindingRequired(
                "MODEL_SELECTION_BINDING_REQUIRED: study.model.selection declares "
                f"search_method={selection.search_method!r}; freeze_train_artifacts "
                "requires model_selection_manifest_path"
            )
        selection_manifest = json.loads(Path(model_selection_manifest_path).read_text(encoding="utf-8"))
        for arm in feature_sets:
            winner = (selection_manifest.get("winner") or {}).get(arm)
            if winner is None:
                continue
            frozen_rec = (models_manifest.get("arms") or {}).get(arm) or {}
            if frozen_rec.get("hyperparameters") != winner.get("hyperparameters"):
                raise ModelSelectionBindingMismatch(
                    f"MODEL_SELECTION_BINDING_MISMATCH: arm {arm!r} freezes hyperparameters "
                    f"{frozen_rec.get('hyperparameters')!r}, which does not match the selection "
                    f"manifest's winner {winner.get('hyperparameters')!r}"
                )
            if frozen_rec.get("seed") != selection_manifest.get("random_seed"):
                raise ModelSelectionBindingMismatch(
                    f"MODEL_SELECTION_BINDING_MISMATCH: arm {arm!r} freezes seed "
                    f"{frozen_rec.get('seed')!r}, which does not match the selection "
                    f"manifest's random_seed {selection_manifest.get('random_seed')!r}"
                )
        if (selection_manifest.get("final_validation_policy") == "gated"
                and selection_manifest.get("final_validation_status") != "PASS"):
            raise ModelSelectionFinalValidationFailed(
                "MODEL_SELECTION_FINAL_VALIDATION_FAILED: the selection manifest's gated "
                f"final-validation status is {selection_manifest.get('final_validation_status')!r}, "
                f"not PASS -- reasons: {selection_manifest.get('final_validation_reasons')!r}. "
                "The freeze refuses; it does not re-derive, re-search, or adjust hyperparameters."
            )

    if study_spec is not None and getattr(study_spec, "required_gates", None):
        from research_workflow.gates import assert_gates_satisfied
        assert_gates_satisfied(
            study_path,
            study_spec,
            stage="train_freeze",
            dataset_identity_sha256=dataset_identity_sha256,
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
        "model_selection_manifest_sha256": (
            selection_manifest.get("manifest_sha256") if selection_manifest else None
        ),
    }
    return write_train_freeze(study_path, payload)
