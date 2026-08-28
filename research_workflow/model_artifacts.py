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
        record={"schema_version":1,"model_id":immutable,"study_id":study.name,"model_role":arm,"artifact_path":_relative(studies_root, model_path),"artifact_sha256":_sha(model_path),"golden_fixture_path":_relative(studies_root, golden),"golden_fixture_sha256":_sha(golden),"model_family":rec.get("estimator"),"hyperparameters":rec.get("hyperparameters"),"ordered_model_inputs":rec.get("ordered_features"),"feature_contract_identity":feature_contract_identity,"target_identity":target_identity,"preprocessing_identity":preprocessing_identity or {"kind":"identity","identity":"identity"},"train_frame_population_identity":train_frame_identity,"training_years":training_years or [],"closure_identities":dict(closures or {}),"score_semantics":"predict_proba_positive","direction_routing":routing,"scientific_status":"UNASSESSED","artifact_status":"PRESERVED_AND_LOADABLE","reuse_status":"PERMITTED"}
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

def resolve_model(model_id: str, *, registry_root: str | Path) -> dict[str, Any]:
    p=Path(registry_root).resolve()/f"{model_id}.json"
    if not p.is_file(): raise ModelArtifactError(f"PRESERVED_MODEL_MISSING: {model_id}")
    rec=json.loads(p.read_text(encoding="utf-8")); studies_root=Path(registry_root).resolve().parent; artifact=_resolve(studies_root, rec["artifact_path"])
    if rec.get("reuse_status") != "PERMITTED": raise ModelArtifactError("PRESERVED_MODEL_REUSE_PROHIBITED")
    preprocessing = rec.get("preprocessing_identity") or {"kind": "identity"}
    if not isinstance(preprocessing, Mapping) or preprocessing.get("kind") != "identity":
        # No transform artifact/loader is yet part of the governed reusable-model
        # contract. Refuse rather than silently score untransformed inputs.
        raise ModelArtifactError("MODEL_PREPROCESSING_UNAVAILABLE")
    if not artifact.is_file() or _sha(artifact) != rec.get("artifact_sha256"): raise ModelArtifactError("PRESERVED_MODEL_CORRUPT")
    rec["_studies_root"] = str(studies_root); rec["_artifact_path"] = str(artifact)
    validate_golden_prediction(rec)
    return rec

def score_preserved_model(model_id: str, frame: pd.DataFrame, *, registry_root: str | Path) -> list[float]:
    rec = resolve_model(model_id, registry_root=registry_root)
    bundle = joblib.load(rec.get("_artifact_path", rec["artifact_path"])); estimator = bundle[rec["model_role"]]["estimator"]
    return [float(v) for v in estimator.predict_proba(frame[list(rec["ordered_model_inputs"])])[:, 1]]

def validate_golden_prediction(record: Mapping[str, Any]) -> bool:
    # New paths are relative to studies/, while historical absolute records remain readable.
    studies_root=Path(record.get("_studies_root", Path.cwd())).resolve()
    golden=_resolve(studies_root, record["golden_fixture_path"]); artifact=Path(record.get("_artifact_path", _resolve(studies_root, record["artifact_path"])))
    if not golden.is_file() or _sha(golden)!=record.get("golden_fixture_sha256"): raise ModelArtifactError("MODEL_GOLDEN_FIXTURE_CORRUPT")
    g=json.loads(golden.read_text()); bundle=joblib.load(artifact); arm=record["model_role"]; est=bundle[arm]["estimator"]
    got=est.predict_proba(pd.DataFrame(g["rows"], columns=g["ordered_inputs"]))[:,1]
    if len(got)!=len(g["expected_scores"]) or any(abs(float(a)-float(b))>1e-12 for a,b in zip(got,g["expected_scores"])): raise ModelArtifactError("MODEL_GOLDEN_PREDICTION_MISMATCH")
    return True

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
