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
    preprocessing_identity: Optional[Dict[str, Any]] = None,
    direction_routing: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Fit declared arms on one TRAIN partition and persist model provenance."""
    from research_workflow.experiment import _assert_study_open
    _assert_study_open(Path(study_path).resolve())
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
    from research_workflow.modeling_closure import resolve_modeling_closure
    from research_workflow.model_artifacts import persist_models
    study = Path(study_path).resolve()
    collection = {}
    frozen = study / "audit" / "frozen_execution_manifest.json"
    if frozen.is_file(): collection["COLLECTION_PRODUCER_CLOSURE"] = json.loads(frozen.read_text()).get("frozen_execution_composite_sha256")
    target = ((json.loads((study / "compiled_study.json").read_text()).get("contracts") or {}).get("target_contract") or {}) if (study / "compiled_study.json").is_file() else {}
    from research_workflow.target_runtime import resolve_target_runtime_closure
    driver_relpaths = list(((json.loads((study / "compiled_study.json").read_text()).get("spec", {}).get("execution", {}) or {}).get("modeling_driver_relpaths", [])) if (study / "compiled_study.json").is_file() else [])
    closures = {**collection, "TARGET_RUNTIME_CLOSURE": resolve_target_runtime_closure(study)["target_runtime_closure_sha256"], **resolve_modeling_closure(study, driver_relpaths=driver_relpaths)}
    compiled_payload = json.loads((study / "compiled_study.json").read_text()) if (study / "compiled_study.json").is_file() else {}
    contracts = compiled_payload.get("contracts") or {}
    try:
        from research_workflow.experiment import load_authorization
        years = list(load_authorization(study).train_years)
    except Exception:
        years = []
    persisted = persist_models(study, models, manifest,
        feature_contract_identity=__import__("research.analysis.identity", fromlist=["canonical_sha256"]).canonical_sha256(contracts.get("feature_contract") or {}),
        target_identity=closures["TARGET_RUNTIME_CLOSURE"], preprocessing_identity=preprocessing_identity or {"kind":"identity","identity":"identity"},
        train_frame_identity=dataset_identity_sha256, training_years=years, closures=closures, direction_routing=direction_routing)
    return {"models": models, "manifest": manifest, "path": str(out), "model_artifacts": persisted}


def _resolve_selection_bindings(
    model_selection_manifest_path: "str | Path | Mapping[str, str | Path]",
    feature_sets: Mapping[str, list[str]],
) -> Dict[str, tuple[Dict[str, Any], Optional[Dict[str, Any]], Path]]:
    """Bind every frozen arm to a selection-manifest winner.

    ``model_selection_manifest_path`` is either a single manifest (str/Path) shared
    by all arms, or a per-arm mapping ``{arm: path}`` -- the latter lets a
    direction-qualified aggregate freeze (arms ``LONG_C`` / ``SHORT_C``) bind each
    direction to its own two-phase selection manifest without collapsing them.

    Winner resolution for arm ``a`` in its manifest: exact key ``a`` if present,
    else -- when the manifest declares exactly one winner -- that sole winner
    (a per-direction manifest has one). Anything else resolves to ``None`` and the
    caller fails closed. Renaming an arm never skips the check.
    """
    if isinstance(model_selection_manifest_path, Mapping):
        per_arm = {arm: Path(p) for arm, p in model_selection_manifest_path.items()}
    else:
        shared = Path(model_selection_manifest_path)
        per_arm = {arm: shared for arm in feature_sets}
    out: Dict[str, tuple[Dict[str, Any], Optional[Dict[str, Any]], Path]] = {}
    cache: Dict[Path, Dict[str, Any]] = {}
    for arm in feature_sets:
        path = per_arm.get(arm)
        if path is None:
            raise ModelSelectionBindingRequired(
                f"MODEL_SELECTION_BINDING_REQUIRED: no selection manifest supplied for arm {arm!r}"
            )
        manifest = cache.get(path)
        if manifest is None:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            cache[path] = manifest
        winners = manifest.get("winner") or {}
        winner = winners.get(arm)
        if winner is None and len(winners) == 1:
            winner = next(iter(winners.values()))
        out[arm] = (manifest, winner, path)
    return out


def _selection_manifest_sha_field(
    selection_bindings: Optional[Dict[str, tuple[Dict[str, Any], Any, Path]]],
) -> Any:
    if not selection_bindings:
        return None
    shas = {arm: manifest.get("manifest_sha256") for arm, (manifest, _, _) in selection_bindings.items()}
    uniq = set(shas.values())
    if len(uniq) == 1:
        return next(iter(uniq))
    return shas


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
    model_selection_manifest_path: Optional[str | Path | Mapping[str, str | Path]] = None,
    dataset_identity_sha256: Optional[str] = None,
    model_artifact_records: Optional[list[Mapping[str, Any]]] = None,
    extra_payload: Optional[Mapping[str, Any]] = None,
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
    from research_workflow.experiment import _assert_study_open
    _assert_study_open(Path(study_path).resolve())
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
    selection_bindings: Optional[Dict[str, tuple[Dict[str, Any], Dict[str, Any], Path]]] = None
    selection = getattr(getattr(study_spec, "model", None), "selection", None)
    if selection is not None and selection.search_method != "none":
        if model_selection_manifest_path is None:
            raise ModelSelectionBindingRequired(
                "MODEL_SELECTION_BINDING_REQUIRED: study.model.selection declares "
                f"search_method={selection.search_method!r}; freeze_train_artifacts "
                "requires model_selection_manifest_path"
            )
        selection_bindings = _resolve_selection_bindings(model_selection_manifest_path, feature_sets)
        for arm, (manifest, winner, manifest_path) in selection_bindings.items():
            # Fail closed: an arm frozen under a declared search MUST trace to a winner.
            # Renaming an arm (e.g. C -> LONG_C) does not exempt it -- a direction-qualified
            # arm binds against the sole winner of its direction-specific manifest.
            if winner is None:
                raise ModelSelectionBindingMismatch(
                    f"MODEL_SELECTION_BINDING_MISMATCH: arm {arm!r} freezes under a declared "
                    f"hyperparameter search but no winner in {manifest_path} traces to it"
                )
            frozen_rec = (models_manifest.get("arms") or {}).get(arm) or {}
            if frozen_rec.get("hyperparameters") != winner.get("hyperparameters"):
                raise ModelSelectionBindingMismatch(
                    f"MODEL_SELECTION_BINDING_MISMATCH: arm {arm!r} freezes hyperparameters "
                    f"{frozen_rec.get('hyperparameters')!r}, which does not match the selection "
                    f"manifest's winner {winner.get('hyperparameters')!r}"
                )
            if frozen_rec.get("seed") != manifest.get("random_seed"):
                raise ModelSelectionBindingMismatch(
                    f"MODEL_SELECTION_BINDING_MISMATCH: arm {arm!r} freezes seed "
                    f"{frozen_rec.get('seed')!r}, which does not match the selection "
                    f"manifest's random_seed {manifest.get('random_seed')!r}"
                )
            if (manifest.get("final_validation_policy") == "gated"
                    and manifest.get("final_validation_status") != "PASS"):
                raise ModelSelectionFinalValidationFailed(
                    "MODEL_SELECTION_FINAL_VALIDATION_FAILED: the selection manifest's gated "
                    f"final-validation status is {manifest.get('final_validation_status')!r}, "
                    f"not PASS -- reasons: {manifest.get('final_validation_reasons')!r}. "
                    "The freeze refuses; it does not re-derive, re-search, or adjust hyperparameters."
                )
        # Backward-compatible single-manifest handle for the payload sha field below.
        if len(selection_bindings) == 1:
            selection_manifest = next(iter(selection_bindings.values()))[0]

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
        "model_selection_manifest_sha256": _selection_manifest_sha_field(selection_bindings),
    }
    for _k, _v in dict(extra_payload or {}).items():
        if _k in payload:
            raise ValueError(f"extra_payload may not override reserved freeze key {_k!r}")
        payload[_k] = _v
    study = Path(study_path).resolve()
    explicit_new = False
    if (study / "compiled_study.json").is_file():
        explicit_new = bool(((json.loads((study / "compiled_study.json").read_text()).get("contracts") or {}).get("target_contract") or {}).get("primitive"))
    if explicit_new:
        records = list(model_artifact_records or [])
        arms = set((models_manifest.get("arms") or {}))
        if {r.get("model_role") for r in records} != arms:
            raise ValueError("GOVERNED_MODEL_ARTIFACT_BINDING_REQUIRED: freeze requires exactly one persisted artifact record per model arm")
        payload["model_artifacts"] = [{k:r.get(k) for k in ("model_id","model_role","artifact_path","artifact_sha256","golden_fixture_path","golden_fixture_sha256","native_booster_path","native_booster_sha256")} for r in records]
    from research_workflow.modeling_closure import resolve_modeling_closure
    from research_workflow.target_runtime import resolve_target_runtime_closure
    driver_relpaths = list(((json.loads((study / "compiled_study.json").read_text()).get("spec", {}).get("execution", {}) or {}).get("modeling_driver_relpaths", [])) if (study / "compiled_study.json").is_file() else [])
    payload["stage_scoped_lineage"] = {
        "COLLECTION_PRODUCER_CLOSURE": (json.loads((study / "audit" / "frozen_execution_manifest.json").read_text()).get("frozen_execution_composite_sha256") if (study / "audit" / "frozen_execution_manifest.json").is_file() else None),
        "TARGET_RUNTIME_CLOSURE": resolve_target_runtime_closure(study)["target_runtime_closure_sha256"],
        "MODELING_EXECUTION_CLOSURE": resolve_modeling_closure(study, driver_relpaths=driver_relpaths)["modeling_execution_composite_sha256"],
    }
    return write_train_freeze(study_path, payload)
