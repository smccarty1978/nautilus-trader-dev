"""RT-09 -- model reuse enforces scientific_status + recorded runtime identity, and can
recover a LightGBM model natively when joblib cannot load it.
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


def _write_canonical_closure(study, rec, *, extra_bound=None):
    """Write the source study's own artifacts/study_closure.json + Stage 17 decision."""
    import hashlib
    arts = study / "artifacts"; arts.mkdir(parents=True, exist_ok=True)
    decision = arts / "research_decision_stage17.json"
    decision_body = {"schema_version": 1, "artifact_kind": "research_decision_stage17", "stage": 17,
                     "study_id": study.name, "terminal_decision": "valid",
                     "bound_lineage": {
                         "train_freeze_sha256": "synthetic-train-freeze",
                         "model_ids": [rec["model_id"]],
                         "modeling_execution_closure_sha256": "synthetic-modeling-closure",
                         "authorization_sha256": "synthetic-auth"}}
    decision_body["decision_identity_sha256"] = canonical_sha256(
        {k: v for k, v in decision_body.items() if k != "decision_identity_sha256"})
    decision.write_text(json.dumps(decision_body))
    bound = {"stage17_research_decision": {
        "path": "artifacts/research_decision_stage17.json",
        "sha256": hashlib.sha256(decision.read_bytes()).hexdigest()}}
    bound.update(extra_bound or {})
    closure = arts / "study_closure.json"
    closure_body = {"schema_version": 1, "study_id": study.name, "status": "CLOSED",
                    "outcome": "DIAGNOSTIC_POSITIVE", "terminal_decision": "valid",
                    "model_ids": [rec["model_id"]], "bound_evidence": bound}
    closure_body["closure_identity_sha256"] = canonical_sha256(closure_body)
    closure.write_text(json.dumps(closure_body))
    return closure, decision


def test_status_assignment_preserves_model_identity_and_binds_evidence(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    closure, decision = _write_canonical_closure(study, rec)
    updated = assign_scientific_status(model_id=rec["model_id"], registry_root=study.parent / "model_registry",
                                       scientific_status="VALID_PRIMARY", closure_evidence_path=closure,
                                       decision_evidence_path=decision)
    assert updated["model_id"] == rec["model_id"]
    assert updated["artifact_sha256"] == rec["artifact_sha256"]
    assert updated["scientific_status_audit_history"][-1]["closure_evidence_sha256"]


def test_status_assignment_rejects_noncanonical_closure_copy(tmp_path):
    """Fix 2: a self-consistent closure file placed anywhere but the study's own
    artifacts/study_closure.json cannot authorize promotion."""
    study, rec = _persist_lgbm(tmp_path)
    canonical_closure, decision = _write_canonical_closure(study, rec)
    copy = tmp_path / "elsewhere_study_closure.json"
    copy.write_text(canonical_closure.read_text())
    with pytest.raises(ModelArtifactError, match="CLOSURE_NOT_CANONICAL"):
        assign_scientific_status(model_id=rec["model_id"], registry_root=study.parent / "model_registry",
                                 scientific_status="VALID_PRIMARY", closure_evidence_path=copy,
                                 decision_evidence_path=decision)


def test_status_assignment_rejects_model_id_not_in_closure_evidence(tmp_path):
    study, rec = _persist_lgbm(tmp_path)
    closure, decision = _write_canonical_closure(study, rec)
    body = json.loads(closure.read_text()); body["model_ids"] = ["some_other_model"]
    body["closure_identity_sha256"] = canonical_sha256({k: v for k, v in body.items() if k != "closure_identity_sha256"})
    closure.write_text(json.dumps(body))
    with pytest.raises(ModelArtifactError, match="CLOSURE_MODEL_UNBOUND"):
        assign_scientific_status(model_id=rec["model_id"], registry_root=study.parent / "model_registry",
                                 scientific_status="VALID_PRIMARY", closure_evidence_path=closure,
                                 decision_evidence_path=decision)


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


def _diagnostic_reuse_policy(study, rec):
    closure = study / "artifacts" / "study_closure.json"
    body = json.loads(closure.read_text())
    return {
        "kind": "diagnostic_derived_causal_input", "model_id": rec["model_id"],
        "parent_study_id": study.name, "parent_closure_path": "artifacts/study_closure.json",
        "parent_closure_sha256": hashlib.sha256(closure.read_bytes()).hexdigest(),
        "parent_closure_identity_sha256": body["closure_identity_sha256"],
        "expected_assessment": "VALID_DIAGNOSTIC", "artifact_sha256": rec["artifact_sha256"],
    }


def _write_diagnostic_reuse_closure(study, rec):
    arts = study / "artifacts"; arts.mkdir(exist_ok=True)
    for name in ("causal.md", "contract.md"):
        (arts / name).write_text(name)
    freeze = arts / "train_experiment_freeze.json"
    freeze.write_text(json.dumps({"freeze_sha256": "synthetic-freeze"}))
    closure = {
        "schema_version": 1, "study_id": study.name, "status": "CLOSED",
        "closed_at_utc": "2026-01-01T00:00:00+00:00",
        "outcome": "DIAGNOSTIC", "terminal_decision": "diagnostic",
        "models": {"A": {"model_id": rec["model_id"], "artifact_sha256": rec["artifact_sha256"]}},
        "model_scientific_assessment": {
            "assessment": "VALID_DIAGNOSTIC",
            "reuse_policy": "Discoverable for future GOVERNED derived-input use if a child study's reuse policy explicitly permits diagnostic-derived input.",
        },
        "bound_evidence": {
            "train_freeze_sha256": hashlib.sha256(freeze.read_bytes()).hexdigest(),
            "causal_audit": {"verdict": "CLEAR", "report": "artifacts/causal.md"},
            "contract_audit": {"verdict": "CLEAR", "report": "artifacts/contract.md"},
        },
    }
    closure["closure_identity_sha256"] = canonical_sha256(
        {k: v for k, v in closure.items() if k != "closed_at_utc"})
    (arts / "study_closure.json").write_text(json.dumps(closure))


def _refresh_closure_identity(study):
    path = study / "artifacts" / "study_closure.json"
    body = json.loads(path.read_text())
    body["closure_identity_sha256"] = canonical_sha256(
        {k: v for k, v in body.items()
         if k not in {"closed_at_utc", "closure_identity_sha256"}})
    path.write_text(json.dumps(body))


def test_unassessed_model_can_bind_only_to_authenticated_diagnostic_closure(tmp_path):
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
def test_unassessed_reuse_evidence_mismatches_fail_closed(tmp_path, mutation, error):
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


def test_unassessed_runtime_drift_requires_hash_bound_parent_evidence(tmp_path):
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
