"""RT-09 -- model reuse as a derived causal input is authorized by the parent study's CLOSURE
(generalised 2026-09-10: the registry ``scientific_status`` never grants reuse; the hard block is
``reuse_status: PROHIBITED``), enforces the recorded runtime identity, and can recover a LightGBM
model natively when joblib cannot load it.
"""
from __future__ import annotations

import json
import hashlib

import pandas as pd
import pytest

from research.analysis.identity import canonical_sha256
from research.analysis.modeling import FittedModel, FitProvenance
from research_workflow.model_artifacts import (
    ModelArtifactError,
    assert_scientific_status_reusable,
    load_model_bundle,
    persist_models,
    register_historical_model,
    resolve_model,
)
from research.schemas.study_spec import DerivedCausalInputSpec
from research_workflow.external_model_scoring import FrozenExternalModelScorer
from research_workflow.tests.closure_reuse_support import (
    refresh_closure_identity as _refresh_closure_identity,
    reuse_policy_for as _diagnostic_reuse_policy,
    write_reuse_closure as _write_diagnostic_reuse_closure,
)


# --------------------------------------------------------------------------- #
# scientific_status
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", ["INVALID_TARGET", "INVALID", "REJECTED"])
def test_explicitly_invalid_status_is_never_reusable(status):
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        assert_scientific_status_reusable({"model_id": "m", "scientific_status": status})


def test_reuse_prohibited_is_the_hard_block_and_is_checked_first():
    with pytest.raises(ModelArtifactError, match="REUSE_PROHIBITED"):
        assert_scientific_status_reusable({"model_id": "m", "reuse_status": "PROHIBITED", "scientific_status": "UNASSESSED"})


@pytest.mark.parametrize("status", ["VALID_PRIMARY", "VALID_DIAGNOSTIC", "UNASSESSED", None])
def test_no_registry_status_value_grants_reuse_without_the_closure(status):
    rec = {"model_id": "m", "reuse_status": "PERMITTED"}
    if status:
        rec["scientific_status"] = status
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        assert_scientific_status_reusable(rec)
    # a bare policy that pins no closure is not authorization either
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        assert_scientific_status_reusable(rec, {"kind": "diagnostic_derived_causal_input", "model_id": "m"})


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


def test_model_binds_only_to_its_authenticated_parent_closure(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _write_diagnostic_reuse_closure(study, rec)
    policy = _diagnostic_reuse_policy(study, rec)
    resolved = resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                             reuse_intent="derived_causal_input", reuse_policy=policy)
    assert resolved["model_id"] == rec["model_id"]
    spec = DerivedCausalInputSpec.model_validate({"name": "upstream", "model_id": rec["model_id"],
                                                  "diagnostic_reuse_policy": policy})
    scorer = FrozenExternalModelScorer.bind(spec, parent_dir=study)
    score = scorer.score({"x": 0.0, "y": 1.0}, checkpoint_ts=1, direction="LONG",
                         availability_ts={"x": 1, "y": 1})
    assert 0.0 <= score.score <= 1.0


@pytest.mark.parametrize("mutation, error", [
    ("sha", "CLOSURE_SHA_MISMATCH"), ("identity", "CLOSURE_IDENTITY_MISMATCH"),
    ("status", "CLOSURE_INVALID"), ("assessment", "ASSESSMENT_MISMATCH"),
    ("model", "CLOSURE_INVALID"), ("artifact", "MODEL_BINDING_MISMATCH"),
    ("audit", "AUDIT_EVIDENCE_MISSING"), ("authorization", "NOT_AUTHORIZED"),
])
def test_closure_reuse_evidence_mismatches_fail_closed(tmp_path, mutation, error):
    study, rec = _persist_lgbm(tmp_path)
    _write_diagnostic_reuse_closure(study, rec)
    policy = _diagnostic_reuse_policy(study, rec)
    path = study / "artifacts" / "study_closure.json"; body = json.loads(path.read_text())
    if mutation == "sha":
        policy["parent_closure_sha256"] = "0" * 64
    elif mutation == "identity":
        policy["parent_closure_identity_sha256"] = "0" * 64
    else:
        if mutation == "status": body["status"] = "OPEN"
        elif mutation == "assessment": body["model_scientific_assessment"]["assessment"] = "INVALID"
        elif mutation == "model": body["models"]["A"]["model_id"] = "other"
        elif mutation == "artifact": body["models"]["A"]["artifact_sha256"] = "0" * 64
        elif mutation == "audit": body["bound_evidence"].pop("causal_audit")
        elif mutation == "authorization": body["model_scientific_assessment"]["reuse_policy"] = "not authorized"
        path.write_text(json.dumps(body)); _refresh_closure_identity(study)
        policy = _diagnostic_reuse_policy(study, rec)
    with pytest.raises(ModelArtifactError, match=error):
        resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                      reuse_intent="derived_causal_input", reuse_policy=policy)


def test_invalid_registry_status_never_yields_to_closure_evidence(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _write_diagnostic_reuse_closure(study, rec); policy = _diagnostic_reuse_policy(study, rec)
    _promote(study, rec["model_id"], scientific_status="INVALID")
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                      reuse_intent="derived_causal_input", reuse_policy=policy)


def test_prohibited_record_hard_blocks_even_with_authenticated_closure_evidence(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _write_diagnostic_reuse_closure(study, rec); policy = _diagnostic_reuse_policy(study, rec)
    _promote(study, rec["model_id"], reuse_status="PROHIBITED")
    with pytest.raises(ModelArtifactError, match="REUSE_PROHIBITED"):
        resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                      reuse_intent="derived_causal_input", reuse_policy=policy)
    # the block does not depend on the caller's intent
    with pytest.raises(ModelArtifactError, match="REUSE_PROHIBITED"):
        resolve_model(rec["model_id"], registry_root=study.parent / "model_registry")


def test_historical_invalid_target_registration_hard_blocks_with_closure_evidence(tmp_path):
    """C2: the historical writer records the block in reuse_status (the field resolve_model reads
    first) with the informational reason beside it; closure evidence cannot lift it."""
    study, rec = _persist_lgbm(tmp_path)
    import os
    hist = register_historical_model(study_dir=study, artifact_relpath=os.path.relpath(
        study.parent / rec["artifact_path"], study))
    assert hist["reuse_status"] == "PROHIBITED" and hist["scientific_status"] == "INVALID_TARGET"
    assert "INVALID_TARGET" in hist["reuse_prohibited_reason"]
    _write_diagnostic_reuse_closure(study, hist); policy = _diagnostic_reuse_policy(study, hist)
    with pytest.raises(ModelArtifactError, match="REUSE_PROHIBITED"):
        resolve_model(hist["model_id"], registry_root=study.parent / "model_registry",
                      reuse_intent="derived_causal_input", reuse_policy=policy)


def test_valid_primary_in_the_registry_does_not_bypass_the_closure(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _promote(study, rec["model_id"], scientific_status="VALID_PRIMARY")
    with pytest.raises(ModelArtifactError, match="SCIENTIFICALLY_INVALID"):
        resolve_model(rec["model_id"], registry_root=study.parent / "model_registry", reuse_intent="derived_causal_input")
    # with the parent closure pinned it resolves, whatever the informational column says
    _write_diagnostic_reuse_closure(study, rec)
    resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                  reuse_intent="derived_causal_input", reuse_policy=_diagnostic_reuse_policy(study, rec))


def test_closure_runtime_drift_requires_hash_bound_parent_evidence(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _write_diagnostic_reuse_closure(study, rec); policy = _diagnostic_reuse_policy(study, rec)
    _promote(study, rec["model_id"], runtime_identity_sha256="deadbeef" * 8)
    with pytest.raises(ModelArtifactError, match="RUNTIME_IDENTITY_DRIFT"):
        resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                      reuse_intent="derived_causal_input", reuse_policy=policy)
    evidence = study / "artifacts" / "runtime_drift_parity.json"; evidence.write_text("verified")
    policy.update({"allow_runtime_drift": True,
                   "runtime_drift_evidence_path": "artifacts/runtime_drift_parity.json",
                   "runtime_drift_evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()})
    resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                  reuse_intent="derived_causal_input", reuse_policy=policy)


# --------------------------------------------------------------------------- #
# runtime identity drift
# --------------------------------------------------------------------------- #
def test_resolve_records_runtime_identity(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    body = json.loads((study.parent / "model_registry" / f"{rec['model_id']}.json").read_text())
    assert body["library_versions"] and body["runtime_identity_sha256"]


def test_runtime_identity_drift_is_refused_for_derived_input(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _write_diagnostic_reuse_closure(study, rec); policy = _diagnostic_reuse_policy(study, rec)
    _promote(study, rec["model_id"], runtime_identity_sha256="deadbeef" * 8)
    root = study.parent / "model_registry"
    with pytest.raises(ModelArtifactError, match="RUNTIME_IDENTITY_DRIFT"):
        resolve_model(rec["model_id"], registry_root=root, reuse_intent="derived_causal_input", reuse_policy=policy)
    # a bare override is not an override: the drift evidence must be hash-bound to the parent
    with pytest.raises(ModelArtifactError, match="RUNTIME_DRIFT_EVIDENCE_REQUIRED"):
        resolve_model(rec["model_id"], registry_root=root, reuse_intent="derived_causal_input",
                      reuse_policy={**policy, "allow_runtime_drift": True})
    # never checked for a non-derived load
    resolve_model(rec["model_id"], registry_root=root)


def test_missing_runtime_identity_is_unverifiable_not_blocked(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    _write_diagnostic_reuse_closure(study, rec); policy = _diagnostic_reuse_policy(study, rec)
    body = json.loads((study.parent / "model_registry" / f"{rec['model_id']}.json").read_text())
    body.pop("runtime_identity_sha256", None)
    (study.parent / "model_registry" / f"{rec['model_id']}.json").write_text(json.dumps(body))
    resolve_model(rec["model_id"], registry_root=study.parent / "model_registry",
                  reuse_intent="derived_causal_input", reuse_policy=policy)  # no raise


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
    artifact = study.parent / body["artifact_path"]
    artifact.write_bytes(b"unloadable-but-authoritatively-registered")
    body["artifact_sha256"] = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    reg.write_text(json.dumps(body))
    _write_diagnostic_reuse_closure(study, body)   # the closure binds the registered (unloadable) bytes
    spec = DerivedCausalInputSpec.model_validate({"name": "upstream", "model_id": rec["model_id"],
                                                  "diagnostic_reuse_policy": _diagnostic_reuse_policy(study, body)})
    scorer = FrozenExternalModelScorer.bind(spec, parent_dir=study)
    got = scorer.score({"x": 0.0, "y": 1.0}, checkpoint_ts=1, direction="LONG",
                       availability_ts={"x": 1, "y": 1})
    assert 0.0 <= got.score <= 1.0


def test_native_recovery_scorer_bind_rejects_golden_mismatch(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    reg = study.parent / "model_registry" / f"{rec['model_id']}.json"
    body = json.loads(reg.read_text())
    artifact = study.parent / body["artifact_path"]; artifact.write_bytes(b"unloadable")
    body["artifact_sha256"] = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    golden = study.parent / body["golden_fixture_path"]
    fixture = json.loads(golden.read_text()); fixture["expected_scores"] = [0.0, 0.0]
    golden.write_text(json.dumps(fixture)); body["golden_fixture_sha256"] = __import__("hashlib").sha256(golden.read_bytes()).hexdigest()
    reg.write_text(json.dumps(body))
    _write_diagnostic_reuse_closure(study, body)
    spec = DerivedCausalInputSpec.model_validate({"name": "upstream", "model_id": rec["model_id"],
                                                  "diagnostic_reuse_policy": _diagnostic_reuse_policy(study, body)})
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
