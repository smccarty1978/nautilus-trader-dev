"""Immutable, non-destructive registry for governed fitted models."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any, Mapping
import joblib
import pandas as pd
from research.analysis.identity import canonical_sha256

class ModelArtifactError(RuntimeError): pass
def _sha(p: Path) -> str: return hashlib.sha256(p.read_bytes()).hexdigest()
def _library_versions() -> dict:
    try:
        from research.analysis.modeling import library_versions
        return dict(library_versions())
    except Exception:
        return {}
def _relative(studies_root: Path, path: Path) -> str:
    return path.resolve().relative_to(studies_root.resolve()).as_posix()
def _resolve(studies_root: Path, value: str) -> Path:
    p=Path(value); candidate=(studies_root / p).resolve() if not p.is_absolute() else p.resolve()
    if not p.is_absolute() and studies_root.resolve() not in candidate.parents and candidate != studies_root.resolve():
        raise ModelArtifactError("PRESERVED_MODEL_PATH_ESCAPE")
    return candidate

def persist_models(study_path: str | Path, models: Mapping[str, Any], manifest: Mapping[str, Any], *,
                   feature_contract_identity: str | None = None, target_identity: str | None = None,
                   preprocessing_identity: str | None = None, train_frame_identity: str | None = None,
                   training_years: list[int] | None = None, closures: Mapping[str, Any] | None = None,
                   direction_routing: Mapping[str, str] | None = None) -> dict[str, Any]:
    study = Path(study_path).resolve(); studies_root = study.parents[0]; root = studies_root / "model_registry"; root.mkdir(parents=True, exist_ok=True)
    artifact_dir = study / "artifacts" / "models"; artifact_dir.mkdir(parents=True, exist_ok=True)
    bundle = {arm: {"estimator": m.estimator, "fit_identity_sha256": m.provenance.fit_identity_sha256} for arm, m in models.items()}
    routing = dict(direction_routing or ({"BOTH": next(iter(bundle))} if len(bundle) == 1 else {}))
    if len(bundle) > 1 and set(routing) != {"LONG", "SHORT"}:
        raise ModelArtifactError("MODEL_DIRECTION_ROUTING_REQUIRED")
    records=[]
    for arm, rec in manifest.get("arms", {}).items():
        immutable = canonical_sha256({"study_id": study.name, "arm": arm, "fit_identity": rec.get("fit_identity_sha256"), "closures": dict(closures or {})})
        model_path = artifact_dir / f"{immutable}.joblib"
        # immutable names avoid overwriting a historical fit; a repeated identical fit
        # reuses only identical bytes.
        if not model_path.exists(): joblib.dump({arm: bundle[arm]}, model_path)
        golden_rows = [[0.0 for _ in rec.get("ordered_features", [])], [1.0 for _ in rec.get("ordered_features", [])]]
        estimator = bundle[arm]["estimator"]
        golden_frame = pd.DataFrame(golden_rows, columns=rec.get("ordered_features", []))
        scores = [float(v) for v in estimator.predict_proba(golden_frame)[:, 1]]
        golden = artifact_dir / f"{immutable}.golden.json"
        golden_body=json.dumps({"model_id": immutable, "arm": arm, "ordered_inputs": rec.get("ordered_features", []), "rows": golden_rows, "expected_scores": scores}, indent=2)+"\n"
        if golden.exists() and golden.read_text(encoding="utf-8") != golden_body:
            raise ModelArtifactError("IMMUTABLE_MODEL_GOLDEN_CONFLICT")
        if not golden.exists(): golden.write_text(golden_body, encoding="utf-8")
        _libs = _library_versions()
        record={"schema_version":1,"model_id":immutable,"study_id":study.name,"model_role":arm,"artifact_path":_relative(studies_root, model_path),"artifact_sha256":_sha(model_path),"golden_fixture_path":_relative(studies_root, golden),"golden_fixture_sha256":_sha(golden),"model_family":rec.get("estimator"),"hyperparameters":rec.get("hyperparameters"),"ordered_model_inputs":rec.get("ordered_features"),"feature_contract_identity":feature_contract_identity,"target_identity":target_identity,"preprocessing_identity":preprocessing_identity or {"kind":"identity","identity":"identity"},"train_frame_population_identity":train_frame_identity,"training_years":training_years or [],"closure_identities":dict(closures or {}),"score_semantics":"predict_proba_positive","direction_routing":routing,"scientific_status":"UNASSESSED","artifact_status":"PRESERVED_AND_LOADABLE","reuse_status":"PERMITTED","library_versions":_libs,"runtime_identity_sha256":canonical_sha256(_libs)}
        # LightGBM's native representation is independently portable.
        if rec.get("estimator") == "lightgbm" and hasattr(estimator, "booster_"):
            native = artifact_dir / f"{immutable}.booster.txt"
            if not native.exists(): estimator.booster_.save_model(str(native))
            record["native_booster_path"], record["native_booster_sha256"] = _relative(studies_root, native), _sha(native)
        registry = root / f"{immutable}.json"; registry_body=json.dumps(record, indent=2, sort_keys=True)+"\n"
        if registry.exists() and registry.read_text(encoding="utf-8") != registry_body:
            raise ModelArtifactError("IMMUTABLE_MODEL_REGISTRY_CONFLICT")
        if not registry.exists(): registry.write_text(registry_body, encoding="utf-8")
        records.append({**record, "_studies_root": str(studies_root), "_artifact_path": str(model_path)})
    return {"records":records, "registry_dir":str(root)}

# scientific_status handling for reuse AS A DERIVED CAUSAL INPUT (RT-09). Validity is
# never inferred from "the artifact loads" + "reuse_status == PERMITTED":
#   * an explicitly-invalid status is a HARD block, always;
#   * VALID_DIAGNOSTIC is reusable only under an explicit policy;
#   * VALID_PRIMARY passes; UNASSESSED is not scientific approval and is blocked.
_SCIENTIFIC_STATUS_BLOCKED = frozenset({"INVALID_TARGET", "INVALID", "REJECTED", "SCIENTIFICALLY_INVALID", "UNASSESSED"})
_SCIENTIFIC_STATUS_POLICY_GATED = frozenset({"VALID_DIAGNOSTIC"})


def assert_scientific_status_reusable(record: Mapping[str, Any], policy: Mapping[str, Any] | None = None) -> None:
    """Fail closed unless the model's ``scientific_status`` permits reuse as a derived
    causal input. A VALID_DIAGNOSTIC model needs the closed, model-specific derived
    input policy; UNASSESSED is never implicit scientific approval."""
    status = str(record.get("scientific_status") or "UNASSESSED")
    mid = record.get("model_id")
    if status in _SCIENTIFIC_STATUS_BLOCKED:
        raise ModelArtifactError(
            f"PRESERVED_MODEL_SCIENTIFICALLY_INVALID: model {mid} scientific_status="
            f"{status!r} is never reusable as a scientifically valid derived causal input"
        )
    if status in _SCIENTIFIC_STATUS_POLICY_GATED:
        pol = policy or {}
        if (pol.get("kind") == "diagnostic_derived_causal_input"
                and pol.get("model_id") == mid):
            return
        raise ModelArtifactError(
            f"PRESERVED_MODEL_SCIENTIFIC_STATUS_REQUIRES_POLICY: model {mid} is "
            f"{status}; consuming a diagnostic-derived model as a causal input requires "
            f"an explicit closed diagnostic_reuse_policy bound to this model_id"
        )


def resolve_model(model_id: str, *, registry_root: str | Path,
                  reuse_intent: str | None = None,
                  reuse_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    p=Path(registry_root).resolve()/f"{model_id}.json"
    if not p.is_file(): raise ModelArtifactError(f"PRESERVED_MODEL_MISSING: {model_id}")
    rec=json.loads(p.read_text(encoding="utf-8")); studies_root=Path(registry_root).resolve().parent; artifact=_resolve(studies_root, rec["artifact_path"])
    if rec.get("reuse_status") != "PERMITTED": raise ModelArtifactError("PRESERVED_MODEL_REUSE_PROHIBITED")
    # RT-09: reuse AS A DERIVED CAUSAL INPUT additionally requires a compatible
    # scientific_status. Other callers (golden self-check, an internal load) keep the
    # historical reuse_status-only gate.
    if reuse_intent == "derived_causal_input":
        assert_scientific_status_reusable(rec, reuse_policy)
        # RT-09: also verify the recorded environment/library identity. A record with no
        # library_versions predates the field -> unverifiable, allowed (conservative). A
        # recorded-but-drifted identity is refused unless the policy allows it.
        recorded_runtime = rec.get("runtime_identity_sha256")
        if recorded_runtime and recorded_runtime != canonical_sha256(_library_versions()):
            if not (reuse_policy or {}).get("allow_runtime_drift"):
                raise ModelArtifactError(
                    f"MODEL_RUNTIME_IDENTITY_DRIFT: model {model_id} was fit under "
                    f"{rec.get('library_versions')!r}; the current environment differs. "
                    f"Set reuse_policy.allow_runtime_drift to override after verifying "
                    f"score parity."
                )
    preprocessing = rec.get("preprocessing_identity") or {"kind": "identity"}
    if not isinstance(preprocessing, Mapping) or preprocessing.get("kind") != "identity":
        # No transform artifact/loader is yet part of the governed reusable-model
        # contract. Refuse rather than silently score untransformed inputs.
        raise ModelArtifactError("MODEL_PREPROCESSING_UNAVAILABLE")
    if not artifact.is_file() or _sha(artifact) != rec.get("artifact_sha256"): raise ModelArtifactError("PRESERVED_MODEL_CORRUPT")
    rec["_studies_root"] = str(studies_root); rec["_artifact_path"] = str(artifact)
    golden = _resolve(studies_root, rec["golden_fixture_path"])
    if not golden.is_file() or _sha(golden) != rec.get("golden_fixture_sha256"):
        raise ModelArtifactError("MODEL_GOLDEN_FIXTURE_CORRUPT")
    if rec.get("native_booster_path"):
        native = _resolve(studies_root, rec["native_booster_path"])
        if not native.is_file() or _sha(native) != rec.get("native_booster_sha256"):
            raise ModelArtifactError("PRESERVED_MODEL_NATIVE_BOOSTER_CORRUPT")
    return rec


def load_model_bundle(record: Mapping[str, Any]) -> dict:
    """Load the fitted-estimator bundle for a resolved registry ``record``.

    RT-09 native recovery: if ``joblib.load`` fails (a pickle broken by a library
    upgrade) and a native LightGBM booster was preserved, rebuild the bundle from the
    booster and require the golden fixture to reproduce before returning it -- otherwise
    fail closed. No generic migration is attempted.
    """
    artifact = record.get("_artifact_path", record["artifact_path"])
    try:
        bundle = joblib.load(artifact)
    except Exception as joblib_err:
        native_rel = record.get("native_booster_path")
        if not native_rel:
            raise ModelArtifactError(f"PRESERVED_MODEL_UNLOADABLE: {joblib_err}") from joblib_err
        studies_root = Path(record.get("_studies_root", Path.cwd())).resolve()
        native = _resolve(studies_root, native_rel)
        if not native.is_file() or _sha(native) != record.get("native_booster_sha256"):
            raise ModelArtifactError("PRESERVED_MODEL_NATIVE_BOOSTER_CORRUPT") from joblib_err
        try:
            import lightgbm as lgb
        except Exception as e:  # pragma: no cover
            raise ModelArtifactError("PRESERVED_MODEL_NATIVE_RECOVERY_UNAVAILABLE") from e

        class _BoosterProbaShim:
            def __init__(self, booster): self._b = booster
            def predict_proba(self, X):
                import numpy as _np
                p = _np.asarray(self._b.predict(X), dtype=float)
                return _np.column_stack([1.0 - p, p])

        arm = record["model_role"]
        bundle = {arm: {"estimator": _BoosterProbaShim(lgb.Booster(model_file=str(native))),
                        "fit_identity_sha256": None}}
        try:
            validate_golden_prediction(record, bundle=bundle)
        except ModelArtifactError as exc:
            raise ModelArtifactError("PRESERVED_MODEL_NATIVE_RECOVERY_GOLDEN_MISMATCH") from exc
        return bundle
    # A loadable artifact is authoritative. Its golden mismatch is a model-integrity
    # failure, not an artifact-load failure, so native fallback is forbidden.
    validate_golden_prediction(record, bundle=bundle)
    return bundle

def score_preserved_model(model_id: str, frame: pd.DataFrame, *, registry_root: str | Path) -> list[float]:
    rec = resolve_model(model_id, registry_root=registry_root)
    bundle = load_model_bundle(rec); estimator = bundle[rec["model_role"]]["estimator"]
    return [float(v) for v in estimator.predict_proba(frame[list(rec["ordered_model_inputs"])])[:, 1]]

def validate_golden_prediction(record: Mapping[str, Any], bundle: Mapping[str, Any] | None = None) -> bool:
    # New paths are relative to studies/, while historical absolute records remain readable.
    studies_root=Path(record.get("_studies_root", Path.cwd())).resolve()
    golden=_resolve(studies_root, record["golden_fixture_path"]); artifact=Path(record.get("_artifact_path", _resolve(studies_root, record["artifact_path"])))
    if not golden.is_file() or _sha(golden)!=record.get("golden_fixture_sha256"): raise ModelArtifactError("MODEL_GOLDEN_FIXTURE_CORRUPT")
    g=json.loads(golden.read_text()); bundle=bundle if bundle is not None else joblib.load(artifact); arm=record["model_role"]; est=bundle[arm]["estimator"]
    got=est.predict_proba(pd.DataFrame(g["rows"], columns=g["ordered_inputs"]))[:,1]
    if len(got)!=len(g["expected_scores"]) or any(abs(float(a)-float(b))>1e-12 for a,b in zip(got,g["expected_scores"])): raise ModelArtifactError("MODEL_GOLDEN_PREDICTION_MISMATCH")
    return True


def assign_scientific_status(*, model_id: str, registry_root: str | Path, scientific_status: str,
                             closure_evidence_path: str | Path, decision_evidence_path: str | Path) -> dict:
    """Governed scientific-status assignment without changing model/artifact identity."""
    if scientific_status not in {"VALID_PRIMARY", "VALID_DIAGNOSTIC", "INVALID_TARGET", "INVALID", "REJECTED"}:
        raise ModelArtifactError("SCIENTIFIC_STATUS_INVALID")
    registry = Path(registry_root).resolve(); path = registry / f"{model_id}.json"
    if not path.is_file(): raise ModelArtifactError("PRESERVED_MODEL_MISSING")
    closure, decision = Path(closure_evidence_path).resolve(), Path(decision_evidence_path).resolve()
    if not closure.is_file() or not decision.is_file(): raise ModelArtifactError("SCIENTIFIC_STATUS_EVIDENCE_MISSING")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("model_id") != model_id: raise ModelArtifactError("SCIENTIFIC_STATUS_MODEL_ID_MISMATCH")
    source_study_id = record.get("study_id")
    if not source_study_id:
        raise ModelArtifactError("SCIENTIFIC_STATUS_SOURCE_STUDY_UNKNOWN")

    # Promotion authority is the CANONICAL governed closure of the source study --
    # ``<studies>/<study_id>/artifacts/study_closure.json`` -- never a copy elsewhere.
    study_dir = (registry.parent / str(source_study_id)).resolve()
    canonical_closure = (study_dir / "artifacts" / "study_closure.json").resolve()
    if closure != canonical_closure:
        raise ModelArtifactError(
            "SCIENTIFIC_STATUS_CLOSURE_NOT_CANONICAL: promotion requires the source study's "
            f"own artifacts/study_closure.json ({canonical_closure}), not {closure}"
        )

    # Full terminal-closure authentication: schema, CLOSED, study_id == dir, declared
    # closure identity, and every bound-evidence artifact (seal / TRAIN freeze / Stage 16
    # freshness / Stage 17 freshness / reconciliation / model artifacts).
    from research_workflow.study_closure import StudyClosureInvalid, load_study_closure
    try:
        closure_body = load_study_closure(study_dir)
    except StudyClosureInvalid as exc:
        raise ModelArtifactError(f"SCIENTIFIC_STATUS_CLOSURE_NOT_AUTHENTICATED: {exc}") from exc
    if not isinstance(closure_body, dict):
        raise ModelArtifactError("SCIENTIFIC_STATUS_CLOSURE_NOT_AUTHENTICATED: no closure record")
    try:
        decision_body = json.loads(decision.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelArtifactError("SCIENTIFIC_STATUS_EVIDENCE_MALFORMED") from exc
    if closure_body.get("study_id") != source_study_id or study_dir.name != source_study_id:
        raise ModelArtifactError("SCIENTIFIC_STATUS_CLOSURE_STUDY_ID_MISMATCH")

    # model_id must be named in the authoritative closure evidence.
    bound_evidence = closure_body.get("bound_evidence") or {}
    named_models = set(closure_body.get("model_ids") or ()) | set(bound_evidence.get("model_ids") or ())
    for container in (closure_body.get("models"), bound_evidence.get("refreshed_model_ids"),
                      closure_body.get("bound_evidence", {}).get("refreshed_model_ids")):
        if isinstance(container, Mapping):
            for v in container.values():
                if isinstance(v, Mapping) and v.get("model_id"): named_models.add(v["model_id"])
                elif isinstance(v, str): named_models.add(v)
    if model_id not in named_models:
        raise ModelArtifactError("SCIENTIFIC_STATUS_CLOSURE_MODEL_UNBOUND")

    # Stage 17 decision must be bound by the closure, resolve to the canonical decision
    # artifact, match byte-for-byte, and be internally self-consistent.
    bound = bound_evidence.get("stage17_research_decision")
    if not isinstance(bound, Mapping) or not bound.get("path") or not bound.get("sha256"):
        raise ModelArtifactError("SCIENTIFIC_STATUS_DECISION_UNBOUND")
    canonical_decision = (study_dir / "artifacts" / "research_decision_stage17.json").resolve()
    bound_path = Path(str(bound["path"]))
    resolved_bound = bound_path.resolve() if bound_path.is_absolute() else (study_dir / bound_path).resolve()
    if decision != canonical_decision or resolved_bound != canonical_decision or _sha(decision) != bound.get("sha256"):
        raise ModelArtifactError("SCIENTIFIC_STATUS_DECISION_BINDING_MISMATCH")
    if decision_body.get("study_id") != source_study_id:
        raise ModelArtifactError("SCIENTIFIC_STATUS_DECISION_STUDY_ID_MISMATCH")
    declared_decision_identity = decision_body.get("decision_identity_sha256")
    if not declared_decision_identity:
        raise ModelArtifactError("SCIENTIFIC_STATUS_DECISION_IDENTITY_MISSING")
    computed = canonical_sha256({k: v for k, v in decision_body.items() if k != "decision_identity_sha256"})
    if computed != declared_decision_identity:
        raise ModelArtifactError("SCIENTIFIC_STATUS_DECISION_IDENTITY_MISMATCH")
    declared_closure_identity = closure_body.get("closure_identity_sha256")
    if declared_closure_identity:
        computed = canonical_sha256({k: v for k, v in closure_body.items() if k != "closure_identity_sha256"})
        if computed != declared_closure_identity:
            raise ModelArtifactError("SCIENTIFIC_STATUS_CLOSURE_IDENTITY_MISMATCH")
    assignment = {"scientific_status": scientific_status,
                  "closure_evidence_path": str(closure), "closure_evidence_sha256": _sha(closure),
                  "closure_identity_sha256": declared_closure_identity,
                  "decision_evidence_path": str(decision), "decision_evidence_sha256": _sha(decision),
                  "decision_identity_sha256": declared_decision_identity}
    assignment["assignment_sha256"] = canonical_sha256(assignment)
    record["scientific_status"] = scientific_status
    record.setdefault("scientific_status_audit_history", []).append(assignment)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record

def register_historical_model(*, study_dir: str | Path, artifact_relpath: str,
                              model_role: str = "HISTORICAL", scientific_status: str = "INVALID_TARGET") -> dict[str, Any]:
    """Byte-register an existing model without loading, scoring, or changing its study."""
    study = Path(study_dir).resolve(); artifact = study / artifact_relpath
    if not artifact.is_file(): raise ModelArtifactError(f"HISTORICAL_MODEL_MISSING: {artifact}")
    model_id = canonical_sha256({"historical_study": study.name, "artifact_sha256": _sha(artifact)})
    root = study.parents[0] / "model_registry"; root.mkdir(parents=True, exist_ok=True)
    rec = {"schema_version": 1, "model_id": model_id, "study_id": study.name, "model_role": model_role,
           "artifact_path": str(artifact), "artifact_sha256": _sha(artifact), "model_family": "historical_unknown",
           "hyperparameters": None, "ordered_model_inputs": None, "feature_contract_identity": "historical",
           "target_identity": "legacy_flip_runtime_WRONG_TARGET", "preprocessing_identity": None,
           "train_frame_population_identity": None, "training_years": [], "closure_identities": {},
           "score_semantics": "historical_unknown", "direction_routing": {}, "scientific_status": scientific_status,
           "artifact_status": "PRESERVED_AND_LOADABLE", "reuse_status": "PROHIBITED", "historical_registration": True}
    (root / f"{model_id}.json").write_text(json.dumps(rec, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return rec
