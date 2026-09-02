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
                   direction_routing: Mapping[str, str] | None = None, tier_v2: str = "registry",
                   selection_status_v2: str = "selected", golden_train_frame: Any = None) -> dict[str, Any]:
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
        # Model contract v2: mirror the reusable model into the configured model store
        # (research_workflow.model_store) under the SAME model_id. Store failure never
        # invalidates the fit; the v1 record above remains authoritative for legacy readers.
        try:
            from research_workflow.roots import resolve_model_root
            if resolve_model_root() is not None:
                from research_workflow import model_store as _ms
                _lin = _ms.ModelLineage(study_id=study.name, cell_id=None, direction=None, target_arm=None, fold_id=None, config_id=None,
                    seed=rec.get("seed"), ordered_inputs=list(rec.get("ordered_features") or []), feature_contract_sha256=feature_contract_identity,
                    preprocessing_contract_sha256=(preprocessing_identity or {}).get("identity") if isinstance(preprocessing_identity, dict) else None,
                    target_contract_sha256=target_identity, target_frame_identity=None, training_population_identity=train_frame_identity,
                    train_years=list(training_years or []), validation_years=[], hyperparameters=dict(rec.get("hyperparameters") or {}),
                    family=str(rec.get("estimator") or "sklearn"), fit_identity_sha256=rec.get("fit_identity_sha256"), closure_identities=dict(closures or {}), model_role=arm)
                _ms.store_model(model_id=immutable, estimator=estimator, lineage=_lin, tier=tier_v2, selection_status=selection_status_v2,
                                metrics=dict(rec.get("metrics") or {}), golden_train_frame=golden_train_frame,
                                legacy_registry_record={k: record.get(k) for k in ("artifact_path","artifact_sha256","golden_fixture_path","golden_fixture_sha256","native_booster_path","native_booster_sha256")})
                records[-1]["model_store_v2"] = True
        except Exception as _exc:  # pragma: no cover - the store is additive
            records[-1]["model_store_v2_error"] = f"{type(_exc).__name__}: {_exc}"
    return {"records":records, "registry_dir":str(root)}

# scientific_status handling for reuse AS A DERIVED CAUSAL INPUT (RT-09). Validity is
# never inferred from "the artifact loads" + "reuse_status == PERMITTED":
#   * an explicitly-invalid status is a HARD block, always;
#   * VALID_DIAGNOSTIC is reusable only under an explicit policy;
#   * VALID_PRIMARY passes; UNASSESSED is not scientific approval and is blocked.
_SCIENTIFIC_STATUS_BLOCKED = frozenset({"INVALID_TARGET", "INVALID", "REJECTED", "SCIENTIFICALLY_INVALID", "UNASSESSED"})
_SCIENTIFIC_STATUS_POLICY_GATED = frozenset({"VALID_DIAGNOSTIC"})


def _assert_parent_runtime_drift_evidence(policy: Mapping[str, Any], parent_dir: Path) -> None:
    """A closure-bound UNASSESSED exception cannot turn runtime drift into a boolean
    override.  Its evidence is an exact, contained file from the declared parent."""
    if not policy.get("allow_runtime_drift"):
        return
    rel, expected = policy.get("runtime_drift_evidence_path"), policy.get("runtime_drift_evidence_sha256")
    if not isinstance(rel, str) or not isinstance(expected, str):
        raise ModelArtifactError("DIAGNOSTIC_REUSE_RUNTIME_DRIFT_EVIDENCE_REQUIRED")
    evidence = (parent_dir / rel).resolve()
    if parent_dir.resolve() not in evidence.parents or not evidence.is_file() or _sha(evidence) != expected:
        raise ModelArtifactError("DIAGNOSTIC_REUSE_RUNTIME_DRIFT_EVIDENCE_MISMATCH")


def _assert_unassessed_diagnostic_reuse(record: Mapping[str, Any], policy: Mapping[str, Any] | None,
                                        *, studies_root: Path) -> None:
    """Authenticate the sole exception to the UNASSESSED derived-input block.

    The closure's model and assessment fields are structured.  Schema v1 closures have
    no structured reuse boolean, so the dedicated ``reuse_policy`` field is checked
    only after the closed structured evidence set has authenticated the closure.
    """
    pol = policy or {}
    required = ("parent_study_id", "parent_closure_path", "parent_closure_sha256",
                "parent_closure_identity_sha256", "expected_assessment", "artifact_sha256")
    if (pol.get("kind") != "diagnostic_derived_causal_input" or pol.get("model_id") != record.get("model_id")
            or any(not pol.get(k) for k in required)):
        raise ModelArtifactError("PRESERVED_MODEL_SCIENTIFICALLY_INVALID: UNASSESSED_REUSE_EVIDENCE_REQUIRED")
    parent_id = str(pol["parent_study_id"])
    parent_dir = (studies_root / parent_id).resolve()
    if parent_dir.parent != studies_root.resolve() or parent_dir.name != parent_id:
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_PARENT_INVALID")
    if pol.get("parent_closure_path") != "artifacts/study_closure.json":
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_CLOSURE_NOT_CANONICAL")
    closure_path = (parent_dir / pol["parent_closure_path"]).resolve()
    if not closure_path.is_file() or _sha(closure_path) != pol["parent_closure_sha256"]:
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_CLOSURE_SHA_MISMATCH")
    from research.analysis.identity import canonical_sha256
    from research_workflow.study_closure import StudyClosureInvalid, load_study_closure
    try:
        closure = load_study_closure(parent_dir)
    except StudyClosureInvalid as exc:
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_CLOSURE_INVALID") from exc
    if not closure or closure.get("closure_identity_sha256") != pol["parent_closure_identity_sha256"]:
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_CLOSURE_IDENTITY_MISMATCH")
    # The terminal-closure writer deliberately excludes its wall-clock timestamp and
    # inserts closure_identity_sha256 only after hashing.  Match that canonical
    # identity convention; file bytes are independently pinned above.
    if canonical_sha256({k: v for k, v in closure.items()
                         if k not in {"closed_at_utc", "closure_identity_sha256"}}) != closure["closure_identity_sha256"]:
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_CLOSURE_IDENTITY_MISMATCH")
    models = closure.get("models")
    assessment = closure.get("model_scientific_assessment")
    if not isinstance(models, Mapping) or not isinstance(assessment, Mapping):
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_CLOSURE_EVIDENCE_MISSING")
    matching = [m for m in models.values() if isinstance(m, Mapping) and m.get("model_id") == record.get("model_id")]
    if len(matching) != 1 or matching[0].get("artifact_sha256") != record.get("artifact_sha256") or pol["artifact_sha256"] != record.get("artifact_sha256"):
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_MODEL_BINDING_MISMATCH")
    if assessment.get("assessment") != pol["expected_assessment"] or assessment.get("assessment") != "VALID_DIAGNOSTIC":
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_ASSESSMENT_MISMATCH")
    # v1's only authorization carrier is this dedicated closure field.  Do not infer
    # permission from outcome, rationale, or registry reuse_status.
    authorization = assessment.get("reuse_policy")
    if not (isinstance(authorization, Mapping) and authorization.get("allows_governed_diagnostic_derived_input") is True) and not (
        isinstance(authorization, str)
        and "GOVERNED derived-input use" in authorization
        and "explicitly permits diagnostic-derived input" in authorization
    ):
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_NOT_AUTHORIZED")
    bound = closure.get("bound_evidence")
    if not isinstance(bound, Mapping) or not all(isinstance(bound.get(k), Mapping) and bound[k].get("verdict") == "CLEAR" for k in ("causal_audit", "contract_audit")) or not bound.get("train_freeze_sha256"):
        raise ModelArtifactError("PRESERVED_MODEL_UNASSESSED_REUSE_AUDIT_EVIDENCE_MISSING")
    _assert_parent_runtime_drift_evidence(pol, parent_dir)


def assert_scientific_status_reusable(record: Mapping[str, Any], policy: Mapping[str, Any] | None = None,
                                      *, studies_root: Path | None = None) -> None:
    """Fail closed unless the model's ``scientific_status`` permits reuse as a derived
    causal input. A VALID_DIAGNOSTIC model needs the closed, model-specific derived
    input policy; UNASSESSED is never implicit scientific approval."""
    status = str(record.get("scientific_status") or "UNASSESSED")
    mid = record.get("model_id")
    if status == "UNASSESSED":
        if studies_root is None:
            raise ModelArtifactError(
                f"PRESERVED_MODEL_SCIENTIFICALLY_INVALID: model {mid} scientific_status="
                "'UNASSESSED' is never reusable without closure-bound diagnostic evidence"
            )
        _assert_unassessed_diagnostic_reuse(record, policy, studies_root=studies_root)
        return
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
        assert_scientific_status_reusable(rec, reuse_policy, studies_root=studies_root)
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
