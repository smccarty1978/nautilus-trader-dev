"""RT-03 -- a registry-only model_id derived input survives PREPARE.

``DerivedCausalInputSpec`` allows a ``model_id`` binding (no parent study), but PREPARE's
``verify_derived_causal_inputs`` unconditionally built a path from ``parent_study_id`` and
crashed. It now branches: ``model_id`` -> immutable model-registry verification via
``model_artifacts.resolve_model``.
"""
from __future__ import annotations

import json

import pytest
from sklearn.linear_model import LogisticRegression

from research.analysis.modeling import FittedModel, FitProvenance
from research.schemas.study_spec import DerivedCausalInputSpec, StudySpec
from research_workflow.derived_inputs import (
    DerivedInputBindingError,
    verify_derived_causal_inputs,
)
from research_workflow.model_artifacts import persist_models


def _register_model(repo_root, *, scientific_status="VALID_PRIMARY", reuse_status="PERMITTED"):
    study = repo_root / "studies" / "parent"
    study.mkdir(parents=True)
    est = LogisticRegression().fit([[0, 0], [1, 1]], [0, 1])
    prov = FitProvenance("A", "logistic_regression", ["x", "y"], 2, 2, 0, {}, {}, None, None, {}, "x")
    rec = persist_models(
        study, {"A": FittedModel(est, prov)},
        {"arms": {"A": {**prov.to_dict(), "fit_identity_sha256": prov.fit_identity_sha256}}},
    )["records"][0]
    reg = repo_root / "studies" / "model_registry" / f"{rec['model_id']}.json"
    body = json.loads(reg.read_text())
    body["scientific_status"] = scientific_status
    body["reuse_status"] = reuse_status
    reg.write_text(json.dumps(body))
    return rec["model_id"]


def _spec_with_model_id(model_id: str) -> StudySpec:
    return StudySpec.model_validate({
        "study": {"id": "child", "type": "flip_prediction", "description": "d"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state"},
        "target": {"type": "flip", "horizon_seconds": 300},
        "features": {
            "source": "canonical_verified_definition_universe",
            "derived_inputs": [{
                "name": "parent_score", "kind": "frozen_external_model_score",
                "model_id": model_id, "retrain_prohibited": True,
            }],
        },
        "chronology": {"train": [2021], "dev": [2022], "prohibited": [2025, 2026]},
        "execution": {"runtime": "nautilustrader"},
    })


def test_model_id_derived_input_verifies_at_prepare(tmp_path):
    model_id = _register_model(tmp_path)
    spec = _spec_with_model_id(model_id)
    records = verify_derived_causal_inputs(spec, repo_root=tmp_path)
    assert len(records) == 1
    assert records[0]["binding"] == "model_id"
    assert records[0]["model_id"] == model_id
    assert records[0]["verified"] is True
    assert records[0]["ordered_model_inputs"] == ["x", "y"]


def test_missing_model_id_fails_closed(tmp_path):
    (tmp_path / "studies" / "model_registry").mkdir(parents=True)
    spec = _spec_with_model_id("0" * 64)
    with pytest.raises(DerivedInputBindingError, match="MODEL_ID_UNRESOLVED"):
        verify_derived_causal_inputs(spec, repo_root=tmp_path)


def test_tampered_artifact_fails_closed(tmp_path):
    model_id = _register_model(tmp_path)
    reg = json.loads((tmp_path / "studies" / "model_registry" / f"{model_id}.json").read_text())
    artifact = tmp_path / "studies" / reg["artifact_path"]
    artifact.write_bytes(artifact.read_bytes() + b"tamper")
    spec = _spec_with_model_id(model_id)
    with pytest.raises(DerivedInputBindingError, match="MODEL_ID_UNRESOLVED"):
        verify_derived_causal_inputs(spec, repo_root=tmp_path)


def test_reuse_prohibited_fails_closed(tmp_path):
    model_id = _register_model(tmp_path, reuse_status="PROHIBITED")
    spec = _spec_with_model_id(model_id)
    with pytest.raises(DerivedInputBindingError, match="REUSE_PROHIBITED"):
        verify_derived_causal_inputs(spec, repo_root=tmp_path)


def test_invalid_target_scientific_status_fails_closed(tmp_path):
    model_id = _register_model(tmp_path, scientific_status="INVALID_TARGET")
    spec = _spec_with_model_id(model_id)
    with pytest.raises(DerivedInputBindingError, match="SCIENTIFICALLY_INVALID"):
        verify_derived_causal_inputs(spec, repo_root=tmp_path)


def test_unassessed_scientific_status_fails_closed(tmp_path):
    model_id = _register_model(tmp_path, scientific_status="UNASSESSED")
    spec = _spec_with_model_id(model_id)
    with pytest.raises(DerivedInputBindingError, match="SCIENTIFICALLY_INVALID"):
        verify_derived_causal_inputs(spec, repo_root=tmp_path)


def test_legacy_parent_study_binding_still_works(tmp_path):
    """The model_id branch must not disturb the existing parent-freeze binding path."""
    di = DerivedCausalInputSpec.model_validate({
        "name": "x", "kind": "frozen_external_model_score",
        "parent_study_id": "p", "parent_train_freeze_artifact": "artifacts/train_experiment_freeze.json",
        "parent_train_freeze_artifact_sha256": "a" * 64,
        "parent_frozen_execution_composite_sha256": "b" * 64,
        "model_hashes": {"C": "c" * 64}, "preprocessing_hash": "d" * 64,
        "retrain_prohibited": True,
    })
    assert di.model_id is None and di.parent_study_id == "p"
