from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import pytest
from sklearn.linear_model import LogisticRegression

from research.schemas.study_spec import DerivedCausalInputSpec
from research_workflow.external_model_scoring import (
    ExternalModelScoringError,
    FrozenExternalModelScorer,
)


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path):
    model = LogisticRegression().fit([[0.0, 0.0], [1.0, 1.0]], [0, 1])
    bundle_path = tmp_path / "models.joblib"
    prep_path = tmp_path / "preprocessing.json"
    joblib.dump({
        "LONG_C": {"estimator": model, "fit_identity_sha256": "long-hash"},
        "SHORT_C": {"estimator": model, "fit_identity_sha256": "short-hash"},
    }, bundle_path)
    prep_path.write_text('{"identity":"prep"}', encoding="utf-8")
    freeze_path = tmp_path / "freeze.json"
    freeze = {
        "study_id": "parent",
        "provenance": "TRAIN_ONLY",
        "model_hashes": {"LONG_C": "long-hash", "SHORT_C": "short-hash"},
        "feature_sets": {"C": ["a", "b"]},
        "preprocessing_hash": "prep-identity",
    }
    freeze_path.write_text(json.dumps(freeze, sort_keys=True), encoding="utf-8")
    spec = DerivedCausalInputSpec.model_validate({
        "name": "parent_score", "parent_study_id": "parent",
        "parent_train_freeze_artifact": "freeze.json",
        "parent_train_freeze_artifact_sha256": file_sha(freeze_path),
        "parent_frozen_execution_composite_sha256": "composite-sha",
        "model_hashes": {"LONG_C": "long-hash", "SHORT_C": "short-hash"},
        "preprocessing_hash": "prep-identity",
        "model_artifact_path": bundle_path.name,
        "model_artifact_sha256": file_sha(bundle_path),
        "preprocessing_artifact_path": prep_path.name,
        "preprocessing_artifact_sha256": file_sha(prep_path),
        "ordered_feature_surfaces": {"LONG_C": ["a", "b"], "SHORT_C": ["a", "b"]},
        "direction_arm_mapping": {"LONG": "LONG_C", "SHORT": "SHORT_C"},
    })
    return spec


def test_frozen_external_scorer_binds_and_preserves_order_and_direction(tmp_path):
    scorer = FrozenExternalModelScorer.bind(fixture(tmp_path), parent_dir=tmp_path)
    observation = scorer.score(
        {"a": 1.0, "b": 0.0}, checkpoint_ts=10, direction="SHORT",
        availability_ts={"a": 8, "b": 9},
    )
    assert observation.arm == "SHORT_C"
    assert observation.latest_input_availability_ts == 9
    assert 0.0 <= observation.score <= 1.0


def test_external_scorer_refuses_future_or_missing_inputs(tmp_path):
    scorer = FrozenExternalModelScorer.bind(fixture(tmp_path), parent_dir=tmp_path)
    with pytest.raises(ExternalModelScoringError, match="NOT_AVAILABLE"):
        scorer.score(
            {"a": 1.0, "b": 0.0}, checkpoint_ts=10, direction="LONG",
            availability_ts={"a": 8, "b": 11},
        )
    with pytest.raises(ExternalModelScoringError, match="incomplete"):
        scorer.score(
            {"a": 1.0}, checkpoint_ts=10, direction="LONG",
            availability_ts={"a": 8},
        )


def test_external_scorer_refuses_artifact_or_model_identity_mismatch(tmp_path):
    spec = fixture(tmp_path)
    bad = spec.model_copy(update={"model_artifact_sha256": "bad"})
    with pytest.raises(ExternalModelScoringError, match="sha256 mismatch"):
        FrozenExternalModelScorer.bind(bad, parent_dir=tmp_path)
    bad_hash = spec.model_copy(update={"model_hashes": {"LONG_C": "bad", "SHORT_C": "short-hash"}})
    with pytest.raises(ExternalModelScoringError, match="fit identity"):
        FrozenExternalModelScorer.bind(bad_hash, parent_dir=tmp_path)


def test_external_scorer_matches_repaired_model_c_for_deterministic_parent_row():
    """The governed scorer must reproduce the frozen parent estimator exactly."""
    repo = Path(__file__).resolve().parents[2]
    parent = repo / "studies" / "clean_maturity_flip_model_rolling_productivity"
    artifacts = parent / "artifacts"
    freeze_path = artifacts / "train_experiment_freeze_repaired.json"
    model_path = artifacts / "train_fitted_models.joblib"
    prep_path = artifacts / "preprocessing_manifest.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    surface = list(freeze["feature_sets"]["C"])
    spec = DerivedCausalInputSpec.model_validate({
        "name": "model_c_score_at_candidate",
        "parent_study_id": freeze["study_id"],
        "parent_train_freeze_artifact": "artifacts/train_experiment_freeze_repaired.json",
        "parent_train_freeze_artifact_sha256": file_sha(freeze_path),
        "parent_frozen_execution_composite_sha256": "7b0994145ce702fedbf3b589a98fa869b09ef57253a17722b8de25931cbb96c8",
        "model_hashes": {"LONG_C": freeze["model_hashes"]["LONG_C"], "SHORT_C": freeze["model_hashes"]["SHORT_C"]},
        "preprocessing_hash": freeze["preprocessing_hash"],
        "model_artifact_path": "artifacts/train_fitted_models.joblib",
        "model_artifact_sha256": file_sha(model_path),
        "preprocessing_artifact_path": "artifacts/preprocessing_manifest.json",
        "preprocessing_artifact_sha256": file_sha(prep_path),
        "ordered_feature_surfaces": {"LONG_C": surface, "SHORT_C": surface},
        "direction_arm_mapping": {"LONG": "LONG_C", "SHORT": "SHORT_C"},
    })
    scorer = FrozenExternalModelScorer.bind(spec, parent_dir=parent)
    values = {name: (index + 1) / 100.0 for index, name in enumerate(surface)}
    availability = {name: 90 for name in surface}
    observed = scorer.score(values, checkpoint_ts=100, direction="LONG", availability_ts=availability)
    bundle = joblib.load(model_path)
    estimator = bundle["LONG_C"]["estimator"]
    expected = float(estimator.predict_proba([[values[name] for name in surface]])[0][1])
    assert observed.score == pytest.approx(expected, abs=1e-15)
