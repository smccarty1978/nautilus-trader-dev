"""RT-09 -- model reuse enforces scientific_status + recorded runtime identity, and can
recover a LightGBM model natively when joblib cannot load it.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from research.analysis.identity import canonical_sha256
from research.analysis.modeling import FittedModel, FitProvenance
from research_workflow.model_artifacts import (
    ModelArtifactError,
    assert_scientific_status_reusable,
    load_model_bundle,
    persist_models,
    resolve_model,
    assign_scientific_status,
)
from research.schemas.study_spec import DerivedCausalInputSpec
from research_workflow.external_model_scoring import FrozenExternalModelScorer


# --------------------------------------------------------------------------- #
# scientific_status
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", ["INVALID_TARGET", "INVALID", "REJECTED"])
def test_explicitly_invalid_status_is_never_reusable(status):
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        assert_scientific_status_reusable({"model_id": "m", "scientific_status": status})


def test_valid_diagnostic_needs_explicit_policy():
    rec = {"model_id": "m", "scientific_status": "VALID_DIAGNOSTIC"}
    with pytest.raises(ModelArtifactError, match="REQUIRES_POLICY"):
        assert_scientific_status_reusable(rec)
    assert_scientific_status_reusable(rec, {"kind": "diagnostic_derived_causal_input", "model_id": "m"})


def test_valid_primary_passes_but_unassessed_is_not_scientific_approval():
    assert_scientific_status_reusable({"model_id": "m", "scientific_status": "VALID_PRIMARY"})
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        assert_scientific_status_reusable({"model_id": "m", "scientific_status": "UNASSESSED"})
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        assert_scientific_status_reusable({"model_id": "m"})


def test_status_assignment_preserves_model_identity_and_binds_evidence(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    decision = tmp_path / "decision.json"
    decision_body = {"study_id": "s", "decision": "valid"}
    decision_body["decision_identity_sha256"] = canonical_sha256(decision_body)
    decision.write_text(json.dumps(decision_body))
    closure = tmp_path / "closure.json"
    closure_body = {"status": "CLOSED", "study_id": "s", "model_ids": [rec["model_id"]],
                    "bound_evidence": {"stage17_research_decision": {
                        "path": "decision.json", "sha256": __import__("hashlib").sha256(decision.read_bytes()).hexdigest()}}}
    closure_body["closure_identity_sha256"] = canonical_sha256(closure_body)
    closure.write_text(json.dumps(closure_body))
    updated = assign_scientific_status(model_id=rec["model_id"], registry_root=study.parent / "model_registry",
                                       scientific_status="VALID_PRIMARY", closure_evidence_path=closure,
                                       decision_evidence_path=decision)
    assert updated["model_id"] == rec["model_id"]
    assert updated["artifact_sha256"] == rec["artifact_sha256"]
    assert updated["scientific_status_audit_history"][-1]["closure_evidence_sha256"]


def test_loadable_joblib_golden_mismatch_never_uses_native_fallback(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    resolved = resolve_model(rec["model_id"], registry_root=study.parent / "model_registry")
    golden = study.parent / resolved["golden_fixture_path"]
    body = json.loads(golden.read_text()); body["expected_scores"] = [0.0, 0.0]
    golden.write_text(json.dumps(body))
    # Use an in-memory record with an updated fixture hash: resolver identity validation
    # has already passed, and only the successful joblib representation is at issue.
    resolved["golden_fixture_sha256"] = __import__("hashlib").sha256(golden.read_bytes()).hexdigest()
    with pytest.raises(ModelArtifactError, match="MODEL_GOLDEN_PREDICTION_MISMATCH"):
        load_model_bundle(resolved)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _persist_lgbm(tmp_path):
    from lightgbm import LGBMClassifier

    study = tmp_path / "studies" / "s"
    study.mkdir(parents=True)
    X = pd.DataFrame({"x": [0.0, 1.0, 0.2, 0.8, 0.5, 0.9], "y": [1.0, 0.0, 0.7, 0.3, 0.5, 0.1]})
    est = LGBMClassifier(n_estimators=4, min_child_samples=1, verbose=-1).fit(X, [0, 1, 0, 1, 0, 1])
    prov = FitProvenance("A", "lightgbm", ["x", "y"], 6, 2, 0, {}, {}, None, None, {}, "x")
    out = persist_models(
        study, {"A": FittedModel(est, prov)},
        {"arms": {"A": {**prov.to_dict(), "fit_identity_sha256": prov.fit_identity_sha256,
                        "estimator": "lightgbm", "ordered_features": ["x", "y"]}}},
    )
    return study, out["records"][0]


def _promote(study, model_id, **fields):
    reg = study.parent / "model_registry" / f"{model_id}.json"
    body = json.loads(reg.read_text())
    body.update(fields)
    reg.write_text(json.dumps(body))


# --------------------------------------------------------------------------- #
# runtime identity drift
# --------------------------------------------------------------------------- #
def test_resolve_records_runtime_identity(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    body = json.loads((study.parent / "model_registry" / f"{rec['model_id']}.json").read_text())
    assert body["library_versions"] and body["runtime_identity_sha256"]


def test_runtime_identity_drift_is_refused_for_derived_input(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _promote(study, rec["model_id"], scientific_status="VALID_PRIMARY",
             runtime_identity_sha256="deadbeef" * 8)
    root = study.parent / "model_registry"
    with pytest.raises(ModelArtifactError, match="RUNTIME_IDENTITY_DRIFT"):
        resolve_model(rec["model_id"], registry_root=root, reuse_intent="derived_causal_input")
    # allowed with an explicit override, and never checked for a non-derived load
    resolve_model(rec["model_id"], registry_root=root, reuse_intent="derived_causal_input",
                  reuse_policy={"allow_runtime_drift": True})
    resolve_model(rec["model_id"], registry_root=root)


def test_missing_runtime_identity_is_unverifiable_not_blocked(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _promote(study, rec["model_id"], scientific_status="VALID_PRIMARY")
    body = json.loads((study.parent / "model_registry" / f"{rec['model_id']}.json").read_text())
    body.pop("runtime_identity_sha256", None)
    (study.parent / "model_registry" / f"{rec['model_id']}.json").write_text(json.dumps(body))
    resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                  reuse_intent="derived_causal_input")  # no raise


# --------------------------------------------------------------------------- #
# native LightGBM recovery
# --------------------------------------------------------------------------- #
def test_native_booster_recovers_when_joblib_fails(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    from pathlib import Path

    resolved = resolve_model(rec["model_id"], registry_root=study.parent / "model_registry")
    assert resolved.get("native_booster_path")
    # break the joblib pickle; the native booster + golden fixture carry the recovery
    Path(resolved["_artifact_path"]).write_bytes(b"not a valid joblib pickle")
    bundle = load_model_bundle(resolved)
    est = bundle[resolved["model_role"]]["estimator"]
    got = est.predict_proba(pd.DataFrame([[0.0, 1.0]], columns=["x", "y"]))
    assert got.shape == (1, 2)


def test_native_recovery_is_reachable_through_real_scorer_bind(tmp_path):
    """Registry bind -> verified native recovery -> golden parity -> usable scorer."""
    study, rec = _persist_lgbm(tmp_path)
    reg = study.parent / "model_registry" / f"{rec['model_id']}.json"
    body = json.loads(reg.read_text())
    body["scientific_status"] = "VALID_PRIMARY"
    artifact = study.parent / body["artifact_path"]
    artifact.write_bytes(b"unloadable-but-authoritatively-registered")
    body["artifact_sha256"] = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    reg.write_text(json.dumps(body))
    spec = DerivedCausalInputSpec.model_validate({"name": "upstream", "model_id": rec["model_id"]})
    scorer = FrozenExternalModelScorer.bind(spec, parent_dir=study)
    got = scorer.score({"x": 0.0, "y": 1.0}, checkpoint_ts=1, direction="LONG",
                       availability_ts={"x": 1, "y": 1})
    assert 0.0 <= got.score <= 1.0


def test_native_recovery_scorer_bind_rejects_golden_mismatch(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    reg = study.parent / "model_registry" / f"{rec['model_id']}.json"
    body = json.loads(reg.read_text()); body["scientific_status"] = "VALID_PRIMARY"
    artifact = study.parent / body["artifact_path"]; artifact.write_bytes(b"unloadable")
    body["artifact_sha256"] = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    golden = study.parent / body["golden_fixture_path"]
    fixture = json.loads(golden.read_text()); fixture["expected_scores"] = [0.0, 0.0]
    golden.write_text(json.dumps(fixture)); body["golden_fixture_sha256"] = __import__("hashlib").sha256(golden.read_bytes()).hexdigest()
    reg.write_text(json.dumps(body))
    spec = DerivedCausalInputSpec.model_validate({"name": "upstream", "model_id": rec["model_id"]})
    with pytest.raises(ModelArtifactError, match="NATIVE_RECOVERY_GOLDEN_MISMATCH"):
        FrozenExternalModelScorer.bind(spec, parent_dir=study)


def test_native_recovery_fails_closed_on_golden_mismatch(tmp_path):
    from pathlib import Path

    study, rec = _persist_lgbm(tmp_path)
    resolved = resolve_model(rec["model_id"], registry_root=study.parent / "model_registry")
    Path(resolved["_artifact_path"]).write_bytes(b"broken")
    golden = Path(resolved["_studies_root"]) / resolved["golden_fixture_path"]
    g = json.loads(golden.read_text())
    g["expected_scores"] = [0.123456, 0.654321]
    golden.write_text(json.dumps(g))
    with pytest.raises(ModelArtifactError, match="NATIVE_RECOVERY_GOLDEN_MISMATCH"):
        load_model_bundle(resolved)


def test_no_native_booster_and_broken_joblib_is_unloadable(tmp_path):
    from pathlib import Path

    study, rec = _persist_lgbm(tmp_path)
    resolved = resolve_model(rec["model_id"], registry_root=study.parent / "model_registry")
    reg = study.parent / "model_registry" / f"{rec['model_id']}.json"
    body = json.loads(reg.read_text())
    body.pop("native_booster_path", None)
    reg.write_text(json.dumps(body))
    resolved2 = resolve_model(rec["model_id"], registry_root=study.parent / "model_registry")
    Path(resolved2["_artifact_path"]).write_bytes(b"broken")
    with pytest.raises(ModelArtifactError, match="UNLOADABLE"):
        load_model_bundle(resolved2)
