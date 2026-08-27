"""Final governed TRAIN fit + threshold derivation + TRAIN freeze, per direction.

Runs strictly AFTER a direction has passed its Phase 2/3 (`two_phase_selection.py`) 2023
reject-only gate. Fits the winning arm's tuned hyperparameters on the FULL TRAIN partition
(2021-2023, single_partition -- no held-out split, matching the parent study's own
convention), derives TRAIN-only thresholds, and freezes -- using only existing governed APIs:
`research_workflow.modeling.fit_models` / `freeze_train_artifacts`,
`research.analysis.spec.AnalysisSpec`/`ModelArm`. No custom fitting, feature, target, or
threshold-selection logic.

Two of the governed functions this composes (`fit_models`, `freeze_train_artifacts` ->
`write_train_freeze`) write to a single hardcoded path regardless of caller
(`artifacts/experiment_models.json`, `artifacts/train_experiment_freeze.json`) -- exactly the
class of defect `two_phase_selection.py`'s Phase 1 hit (independent contract review, pass 09).
Both calls here are wrapped with an immediate rename to a direction-specific path, mirroring
that already-verified fix, so LONG and SHORT can never clobber each other.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pandas as pd

from research.analysis.identity import canonical_sha256
from research.analysis.spec import AnalysisSpec, ModelArm
from research_workflow.modeling import fit_models, freeze_train_artifacts

DECILE_QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


class FinalFreezeError(RuntimeError):
    """A required invariant of the final-fit/freeze step was violated."""


def _rename_off_default(study_path: str | Path, default_rel: str, out_rel: str) -> Path:
    study_dir = Path(study_path).resolve()
    default_path = study_dir / default_rel
    out_path = study_dir / out_rel
    if default_path.resolve() != out_path.resolve():
        if not default_path.exists():
            raise FinalFreezeError(f"expected governed output at {default_path}, not found")
        default_path.replace(out_path)
    return out_path


def preprocessing_hash_for(feature_list_sha256: str) -> str:
    """No scaling/imputation/encoding step exists in this pipeline (raw LightGBM on the
    declared feature surface, same as the parent study's "calibration": "none" convention)
    -- the preprocessing identity is just a deterministic binding to the feature contract,
    via the same `canonical_sha256` helper `research_workflow/model_selection.py` already
    uses, not an invented hash algorithm."""
    return canonical_sha256({"calibration": "none", "feature_list_sha256": feature_list_sha256})


@dataclass
class FinalFreezeResult:
    direction: str
    arm: str
    models_manifest_path: str
    train_freeze_path: str
    thresholds: Dict[str, Any]
    n_rows: int


def run_final_train_fit_and_freeze(
    study_path: str | Path,
    direction: str,
    *,
    arm: str,
    X_train_full: pd.DataFrame,
    y_train_full: pd.Series,
    meta_train_full: pd.DataFrame,
    tuned_hyperparameters: Mapping[str, Any],
    random_seed: int,
    feature_list_sha256: str,
    model_selection_manifest_path: str | Path,
    study_spec: Any,
) -> FinalFreezeResult:
    """Fits `arm` on the full TRAIN partition (2021-2023) at `tuned_hyperparameters`,
    derives TRAIN-only thresholds/deciles from its own score distribution, and freezes --
    binding to `model_selection_manifest_path` so `freeze_train_artifacts`'s own
    `ModelSelectionBindingMismatch`/`ModelSelectionFinalValidationFailed` guards apply.

    `meta_train_full` MUST carry `_partition == "train"` for every row and nothing else
    (single_partition fit, no held-out split -- matches the parent study's own
    `split_policy.kind == "single_partition"` convention exactly).
    """
    if meta_train_full["_partition"].nunique() != 1 or meta_train_full["_partition"].iloc[0] != "train":
        raise FinalFreezeError(
            f"{direction}: meta_train_full must be entirely '_partition'=='train', "
            f"got {sorted(meta_train_full['_partition'].unique())}"
        )
    if len(X_train_full) != len(y_train_full) or len(X_train_full) != len(meta_train_full):
        raise FinalFreezeError(f"{direction}: X/y/meta row-count mismatch")

    analysis_spec = AnalysisSpec(
        analysis_id=f"{direction.lower()}_final_train_fit",
        run_id=f"{direction.lower()}_final_train_fit",
        model_arms=(ModelArm(name=arm, features=list(X_train_full.columns)),),
        seed=random_seed,
    )
    fit_result = fit_models(
        study_path, X_train_full, y_train_full, meta=meta_train_full, spec=analysis_spec,
        estimator="lightgbm", hyperparameters=dict(tuned_hyperparameters),
    )
    models_manifest_path = _rename_off_default(
        study_path, "artifacts/experiment_models.json",
        f"artifacts/experiment_models_{direction.lower()}.json",
    )

    fitted = fit_result["models"][arm]
    scores = fitted.predict_proba(X_train_full[list(X_train_full.columns)])
    score_series = pd.Series(scores)

    deciles = {
        arm: {
            "boundaries": [float(score_series.quantile(q)) for q in DECILE_QUANTILES],
            "derivation": "TRAIN_ONLY",
        }
    }

    freeze_path_default = freeze_train_artifacts(
        study_path,
        feature_sets={arm: list(X_train_full.columns)},
        models_manifest=fit_result["manifest"],
        preprocessing_hash=preprocessing_hash_for(feature_list_sha256),
        score_arrays={arm: scores.tolist()},
        meta=meta_train_full,
        deciles=deciles,
        study_spec=study_spec,
        model_selection_manifest_path=str(model_selection_manifest_path),
    )
    train_freeze_path = _rename_off_default(
        study_path, freeze_path_default.relative_to(Path(study_path).resolve()).as_posix(),
        f"artifacts/train_experiment_freeze_{direction.lower()}.json",
    )

    frozen_payload = json.loads(train_freeze_path.read_text(encoding="utf-8"))
    return FinalFreezeResult(
        direction=direction,
        arm=arm,
        models_manifest_path=str(models_manifest_path),
        train_freeze_path=str(train_freeze_path),
        thresholds=frozen_payload.get("thresholds", {}),
        n_rows=len(X_train_full),
    )


__all__ = [
    "FinalFreezeError",
    "FinalFreezeResult",
    "preprocessing_hash_for",
    "run_final_train_fit_and_freeze",
    "DECILE_QUANTILES",
]
