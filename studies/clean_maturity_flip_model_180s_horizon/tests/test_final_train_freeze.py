"""Bounded-fixture proof of the final-fit/freeze step.

Synthetic data only. Proves, before any real 2021-2023 TRAIN data is passed through it:
  - LONG and SHORT never clobber each other's experiment_models.json / train_experiment_
    freeze.json (both governed functions write to one hardcoded path per call).
  - Thresholds (P90/P95/P97.5) and deciles are derived TRAIN-only from the fitted model's
    own score distribution, not invented or caller-declared.
  - The freeze genuinely binds to the supplied model_selection_manifest_path -- a
    hyperparameter/seed mismatch against the declared winner is refused, not silently
    accepted.
  - A non-"train"-only meta partition is refused before any fit is attempted.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

STUDY_DIR = Path(__file__).resolve().parents[1]


def _repo_root() -> Path:
    for candidate in [STUDY_DIR, *STUDY_DIR.parents]:
        if (candidate / "features" / "registry.py").exists() and (candidate / "research").is_dir():
            return candidate
    import features
    return Path(features.__file__).resolve().parents[1]


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
IMPLEMENTATION_DIR = STUDY_DIR / "implementation"
if str(IMPLEMENTATION_DIR) not in sys.path:
    sys.path.insert(0, str(IMPLEMENTATION_DIR))

from research.schemas.study_spec import StudySpec  # noqa: E402
from research_workflow.modeling import ModelSelectionBindingMismatch  # noqa: E402
from final_train_freeze import (  # noqa: E402
    FinalFreezeError,
    run_final_train_fit_and_freeze,
)

BASE_SPEC = dict(
    study={"id": "final_freeze_smoke", "type": "flip_prediction", "description": "smoke"},
    instrument={"symbol": "NQ"},
    population={"prevailing_regime": "both"},
    target={"direction": "both", "horizon_seconds": 180},
)


def _synthetic_train_frame(seed: int, n: int = 300):
    rng = np.random.default_rng(seed)
    latent = rng.normal(size=n)
    X = pd.DataFrame({
        "f0": latent + rng.normal(scale=0.3, size=n),
        "f1": rng.normal(size=n),
        "f2": rng.normal(size=n),
    })
    y = pd.Series((latent > 0).astype(int))
    meta = pd.DataFrame({"_partition": ["train"] * n})
    return X, y, meta


def _write_study_yaml(tmp: str, spec_dict: dict) -> None:
    """`freeze_train_artifacts` -> `write_train_freeze` re-derives authorization from a
    REAL study.yaml on disk at study_path -- it does not trust the in-memory StudySpec
    object alone (defense-in-depth, discovered by this test before any real data was
    involved). A synthetic fixture must therefore also write one."""
    (Path(tmp) / "study.yaml").write_text(yaml.safe_dump(spec_dict), encoding="utf-8")


def _no_selection_spec(tmp: str) -> StudySpec:
    d = dict(BASE_SPEC, chronology={"train": [2021, 2022, 2023], "dev": [2024]})
    _write_study_yaml(tmp, d)
    return StudySpec.model_validate(d)


def _gated_selection_spec(tmp: str, winner_hp: dict) -> StudySpec:
    d = dict(
        BASE_SPEC,
        chronology={"train": [2021, 2022, 2023], "dev": [2024]},
        model={"selection": {
            "allowed_families": [{
                "family": "lightgbm",
                "fixed_hyperparameters": {"verbosity": -1},
                "tunable_hyperparameters": [
                    {"name": "num_leaves", "kind": "choice", "values": [4, 8]},
                ],
            }],
            "search_method": "random", "max_trials": 2, "random_seed": 42,
            "tuning_years": [2021, 2022], "final_train_validation_years": [2023],
            "primary_selection_metric": "pr_auc", "final_validation_policy": "gated",
            "final_validation_requirements": {
                "primary_metric_bound": {"metric": "pr_auc", "minimum": 0.0}
            },
        }},
    )
    _write_study_yaml(tmp, d)
    return StudySpec.model_validate(d)


def _write_selection_manifest(tmp: str, hyperparameters: dict, seed: int, status: str = "PASS") -> Path:
    manifest = {
        "schema_version": 1,
        "random_seed": seed,
        "final_validation_policy": "gated",
        "final_validation_status": status,
        "winner": {"C": {"family": "lightgbm", "hyperparameters": hyperparameters,
                          "inner_validation_score": 0.3}},
    }
    p = Path(tmp) / "selection_manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return p


def test_final_freeze_no_clobber_across_directions():
    tmp = tempfile.mkdtemp()
    spec = _no_selection_spec(tmp)
    for direction, seed in (("LONG", 1), ("SHORT", 2)):
        X, y, meta = _synthetic_train_frame(seed)
        run_final_train_fit_and_freeze(
            tmp, direction, arm="C", X_train_full=X, y_train_full=y, meta_train_full=meta,
            tuned_hyperparameters={"n_estimators": 10, "num_leaves": 4, "verbosity": -1},
            random_seed=seed, feature_list_sha256="deadbeef",
            model_selection_manifest_path=_write_selection_manifest(
                tmp, {"n_estimators": 10, "num_leaves": 4, "verbosity": -1}, seed),
            study_spec=spec,
        )
    artifacts = Path(tmp) / "artifacts"
    assert (artifacts / "experiment_models_long.json").exists()
    assert (artifacts / "experiment_models_short.json").exists()
    assert (artifacts / "train_experiment_freeze_long.json").exists()
    assert (artifacts / "train_experiment_freeze_short.json").exists()
    assert not (artifacts / "experiment_models.json").exists()
    assert not (artifacts / "train_experiment_freeze.json").exists()


def test_final_freeze_thresholds_and_deciles_are_train_only():
    tmp = tempfile.mkdtemp()
    X, y, meta = _synthetic_train_frame(3)
    result = run_final_train_fit_and_freeze(
        tmp, "LONG", arm="C", X_train_full=X, y_train_full=y, meta_train_full=meta,
        tuned_hyperparameters={"n_estimators": 10, "num_leaves": 4, "verbosity": -1},
        random_seed=3, feature_list_sha256="deadbeef",
        model_selection_manifest_path=_write_selection_manifest(
            tmp, {"n_estimators": 10, "num_leaves": 4, "verbosity": -1}, 3),
        study_spec=_no_selection_spec(tmp),
    )
    th = result.thresholds["C"]
    for key in ("p90", "p95", "p97_5"):
        assert th[key]["derivation_population"] == "train"
    frozen = json.loads(Path(result.train_freeze_path).read_text(encoding="utf-8"))
    assert len(frozen["deciles"]["C"]["boundaries"]) == 9
    assert frozen["deciles"]["C"]["derivation"] == "TRAIN_ONLY"


def test_final_freeze_binds_to_selection_manifest_and_rejects_mismatch():
    tmp = tempfile.mkdtemp()
    X, y, meta = _synthetic_train_frame(4)
    good_hp = {"n_estimators": 10, "num_leaves": 4, "verbosity": -1}
    manifest_path = _write_selection_manifest(tmp, good_hp, seed=4)

    # Matching hyperparameters/seed -- freeze succeeds.
    run_final_train_fit_and_freeze(
        tmp, "LONG", arm="C", X_train_full=X, y_train_full=y, meta_train_full=meta,
        tuned_hyperparameters=good_hp, random_seed=4, feature_list_sha256="deadbeef",
        model_selection_manifest_path=manifest_path, study_spec=_gated_selection_spec(tmp, good_hp),
    )

    # Mismatched hyperparameters against the SAME declared winner -- must be refused.
    tmp2 = tempfile.mkdtemp()
    bad_hp = {"n_estimators": 999, "num_leaves": 4, "verbosity": -1}
    with pytest.raises(ModelSelectionBindingMismatch):
        run_final_train_fit_and_freeze(
            tmp2, "LONG", arm="C", X_train_full=X, y_train_full=y, meta_train_full=meta,
            tuned_hyperparameters=bad_hp, random_seed=4, feature_list_sha256="deadbeef",
            model_selection_manifest_path=manifest_path, study_spec=_gated_selection_spec(tmp2, good_hp),
        )


def test_final_freeze_rejects_non_train_partition():
    tmp = tempfile.mkdtemp()
    X, y, meta = _synthetic_train_frame(5)
    meta = meta.copy()
    meta.loc[0, "_partition"] = "dev"
    with pytest.raises(FinalFreezeError):
        run_final_train_fit_and_freeze(
            tmp, "LONG", arm="C", X_train_full=X, y_train_full=y, meta_train_full=meta,
            tuned_hyperparameters={"n_estimators": 10, "num_leaves": 4, "verbosity": -1},
            random_seed=5, feature_list_sha256="deadbeef",
            model_selection_manifest_path=_write_selection_manifest(
                tmp, {"n_estimators": 10, "num_leaves": 4, "verbosity": -1}, 5),
            study_spec=_no_selection_spec(tmp),
        )
