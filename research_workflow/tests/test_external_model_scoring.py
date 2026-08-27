from __future__ import annotations

import hashlib

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
    spec = DerivedCausalInputSpec.model_validate({
        "name": "parent_score", "parent_study_id": "parent",
        "parent_train_freeze_artifact": "freeze.json",
        "parent_train_freeze_artifact_sha256": "freeze-sha",
        "parent_frozen_execution_composite_sha256": "composite-sha",
        "model_hashes": {"LONG_C": "long-hash", "SHORT_C": "short-hash"},
        "preprocessing_hash": "prep-identity",
        "model_artifact_path": bundle_path.name,
        "model_artifact_sha256": file_sha(bundle_path),
        "preprocessing_artifact_path": prep_path.name,
        "preprocessing_artifact_sha256": file_sha(prep_path),
        "ordered_feature_surfaces": {"LONG_C": ["a", "b"], "SHORT_C": ["b", "a"]},
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
