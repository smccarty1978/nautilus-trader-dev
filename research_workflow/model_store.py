"""Model artifact contract v2: canonical representation, exports, golden frame, tiers.

Layout under the configured ``model_root`` (research_workflow.roots):

    <model_root>/models/<model_id>/
        manifest.json                 schema_version 2 (immutable identity; representations appended)
        canonical/<file>              the family's canonical representation
        exports/<format>.<ext>        governed exports (joblib, onnx, ...)
        golden/frame.parquet          deterministic >=256-row TRAIN sample (feature columns only)
        golden/expected.json          canonical predictions on the golden frame
        equivalence/<format>.json     export-vs-canonical evidence

    <model_root>/ledger/<study_id>/<fit_id>/   bytes of every fit (candidate/fold/config)

Tiers
-----
``registry``  reusable scientific models (selected / final_validation / anything whose scores
              feed a persisted downstream artifact) -- resolvable by ``model_id`` from other studies.
``ledger``    every other actual fit: bytes + permanent manifest row, NO reuse rights.

Family authority
----------------
The canonical representation is the family's native format where one exists; sklearn has
none, so its canonical representation is an environment-bound pickle (joblib) and the
manifest says so. Exports never determine training success; an export is ``verified``
only after prediction equivalence on the golden frame within the format's tolerance.

``model_id`` never depends on any export and never changes after creation.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from research.analysis.identity import canonical_sha256

SCHEMA_VERSION = 2
GOLDEN_MIN_ROWS = 256

FAMILY_AUTHORITY: Dict[str, Dict[str, Any]] = {
    "lightgbm": {"canonical_format": "lightgbm_text", "archival_safety": "portable", "file": "model.txt"},
    "xgboost": {"canonical_format": "xgboost_ubj", "archival_safety": "portable", "file": "model.ubj"},
    "catboost": {"canonical_format": "catboost_cbm", "archival_safety": "portable", "file": "model.cbm"},
    # sklearn families: no native format -> environment-bound pickle is the canonical form.
    "gradient_boosting": {"canonical_format": "sklearn_pickle", "archival_safety": "environment_bound", "file": "estimator.joblib"},
    "logistic_regression": {"canonical_format": "sklearn_pickle", "archival_safety": "environment_bound", "file": "estimator.joblib"},
    "sklearn": {"canonical_format": "sklearn_pickle", "archival_safety": "environment_bound", "file": "estimator.joblib"},
}

EXPORT_TOLERANCES: Dict[str, Dict[str, float]] = {
    "joblib": {"abs": 1e-12},
    "lightgbm_text": {"abs": 1e-12},
    "xgboost_ubj": {"abs": 1e-12},
    "onnx": {"rel": 1e-6, "abs": 1e-6},
}
EXPORT_STATES = ("unavailable", "candidate", "verified", "failed")
SELECTION_STATES = ("candidate", "selected", "rejected", "final_validation")
TIERS = ("registry", "ledger")


class ModelStoreError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Family authority and canonical (de)serialization
# ---------------------------------------------------------------------------

def family_authority(family: str) -> Dict[str, Any]:
    fam = str(family)
    if fam in FAMILY_AUTHORITY:
        return {"family": fam, **FAMILY_AUTHORITY[fam]}
    return {"family": fam, **FAMILY_AUTHORITY["sklearn"]}


def _unwrap(estimator: Any) -> Any:
    """Return the underlying library estimator (FittedModel -> estimator)."""
    return getattr(estimator, "estimator", estimator)


def save_canonical(estimator: Any, family: str, dest_dir: Path) -> Dict[str, Any]:
    """Write the canonical representation; returns its record."""
    auth = family_authority(family)
    est = _unwrap(estimator)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / auth["file"]
    fmt = auth["canonical_format"]
    if fmt == "lightgbm_text":
        booster = getattr(est, "booster_", None) or est
        booster.save_model(str(path))
    elif fmt == "xgboost_ubj":
        booster = est.get_booster() if hasattr(est, "get_booster") else est
        booster.save_model(str(path))
    elif fmt == "catboost_cbm":
        est.save_model(str(path))
    else:
        import joblib
        joblib.dump(est, path)
    return {"format": fmt, "archival_safety": auth["archival_safety"], "path": path.name,
            "byte_sha256": _sha(path), "logical_sha256": _sha(path) if auth["archival_safety"] == "portable" else None,
            "library_versions": _library_versions()}


class _Scorer:
    """Uniform ``predict_proba`` over any representation."""
    def __init__(self, kind: str, obj: Any, ordered_inputs: Sequence[str]):
        self.kind, self.obj, self.inputs = kind, obj, list(ordered_inputs)

    def scores(self, frame: pd.DataFrame) -> np.ndarray:
        X = frame[self.inputs]
        if self.kind == "lightgbm_booster":
            return np.asarray(self.obj.predict(X.to_numpy(dtype=np.float64)), dtype=np.float64)
        if self.kind == "xgboost_booster":
            import xgboost as xgb
            return np.asarray(self.obj.predict(xgb.DMatrix(X.to_numpy(dtype=np.float32))), dtype=np.float64)
        if self.kind == "onnx":
            name = self.obj.get_inputs()[0].name
            out = self.obj.run(None, {name: X.to_numpy(dtype=np.float32)})
            probs = out[1] if len(out) > 1 else out[0]
            if isinstance(probs, list):  # zipmap output
                return np.asarray([p.get(1, p.get("1")) for p in probs], dtype=np.float64)
            probs = np.asarray(probs)
            return probs[:, 1] if probs.ndim == 2 else probs.astype(np.float64)
        est = self.obj
        return np.asarray(est.predict_proba(X)[:, 1], dtype=np.float64)


def load_canonical(manifest: Mapping[str, Any], model_dir: Path) -> _Scorer:
    canon = manifest["canonical"]
    path = model_dir / "canonical" / canon["path"]
    if _sha(path) != canon["byte_sha256"]:
        raise ModelStoreError(f"CANONICAL_BYTES_CORRUPT: {path}")
    fmt = canon["format"]
    inputs = manifest["lineage"]["ordered_inputs"]
    if fmt == "lightgbm_text":
        import lightgbm as lgb
        return _Scorer("lightgbm_booster", lgb.Booster(model_file=str(path)), inputs)
    if fmt == "xgboost_ubj":
        import xgboost as xgb
        b = xgb.Booster(); b.load_model(str(path))
        return _Scorer("xgboost_booster", b, inputs)
    if fmt == "catboost_cbm":
        from catboost import CatBoostClassifier
        m = CatBoostClassifier(); m.load_model(str(path))
        return _Scorer("sklearn", m, inputs)
    import joblib
    return _Scorer("sklearn", joblib.load(path), inputs)


def _load_export(fmt: str, path: Path, inputs: Sequence[str]) -> _Scorer:
    if fmt == "joblib":
        import joblib
        obj = joblib.load(path)
        if isinstance(obj, dict) and len(obj) == 1:  # legacy {arm: {estimator,...}} bundle
            inner = next(iter(obj.values()))
            obj = inner["estimator"] if isinstance(inner, dict) else inner
        obj = _unwrap(obj)
        kind = type(obj).__module__.split(".")[0]
        if kind == "lightgbm" and not hasattr(obj, "predict_proba"):
            return _Scorer("lightgbm_booster", obj, inputs)
        if kind == "xgboost" and not hasattr(obj, "predict_proba"):
            return _Scorer("xgboost_booster", obj, inputs)
        return _Scorer("sklearn", obj, inputs)
    if fmt == "onnx":
        import onnxruntime as ort
        return _Scorer("onnx", ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]), inputs)
    raise ModelStoreError(f"EXPORT_FORMAT_UNSUPPORTED: {fmt}")


def _library_versions() -> Dict[str, Optional[str]]:
    try:
        from research.analysis.modeling import library_versions
        return dict(library_versions())
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Golden frame
# ---------------------------------------------------------------------------

def build_golden_frame(train_frame: pd.DataFrame, ordered_inputs: Sequence[str], model_id: str,
                       n_rows: int = GOLDEN_MIN_ROWS) -> pd.DataFrame:
    """Deterministic sample of real TRAIN rows (feature columns only), seeded from model_id."""
    cols = list(ordered_inputs)
    missing = [c for c in cols if c not in train_frame.columns]
    if missing:
        raise ModelStoreError(f"GOLDEN_FRAME_COLUMNS_MISSING: {missing}")
    if len(train_frame) < n_rows:
        raise ModelStoreError(f"GOLDEN_FRAME_TOO_SMALL: {len(train_frame)} < {n_rows}")
    seed = int(hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:8], 16)
    idx = np.sort(np.random.default_rng(seed).choice(len(train_frame), size=n_rows, replace=False))
    frame = train_frame.iloc[idx][cols].reset_index(drop=True)
    return frame.astype({c: "float64" for c in cols})


def _frame_sha(frame: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Manifest and store operations
# ---------------------------------------------------------------------------

@dataclass
class ModelLineage:
    study_id: str
    cell_id: Optional[str]
    direction: Optional[str]
    target_arm: Optional[str]
    fold_id: Optional[str]
    config_id: Optional[str]
    seed: Optional[int]
    ordered_inputs: List[str]
    feature_contract_sha256: Optional[str]
    preprocessing_contract_sha256: Optional[str]
    target_contract_sha256: Optional[str]
    target_frame_identity: Optional[str]
    training_population_identity: Optional[str]
    train_years: List[int] = field(default_factory=list)
    validation_years: List[int] = field(default_factory=list)
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    family: str = "lightgbm"
    fit_identity_sha256: Optional[str] = None
    closure_identities: Dict[str, Any] = field(default_factory=dict)
    model_role: Optional[str] = None


def model_store_root(model_root: Optional[Path] = None, *, create: bool = True) -> Path:
    if model_root is None:
        from research_workflow.roots import resolve_model_root
        model_root = resolve_model_root()
    if model_root is None:
        raise ModelStoreError("MODEL_ROOT_UNCONFIGURED: set model_root in ~/.nt_research/config.yaml")
    root = Path(model_root)
    if create:
        (root / "models").mkdir(parents=True, exist_ok=True)
        (root / "ledger").mkdir(parents=True, exist_ok=True)
    return root


def model_dir(model_id: str, model_root: Optional[Path] = None) -> Path:
    return model_store_root(model_root, create=False) / "models" / model_id


def read_manifest(model_id: str, model_root: Optional[Path] = None) -> Dict[str, Any]:
    p = model_dir(model_id, model_root) / "manifest.json"
    if not p.is_file():
        raise ModelStoreError(f"MODEL_NOT_IN_STORE: {model_id}")
    return _read(p)


def store_model(*, model_id: str, estimator: Any, lineage: ModelLineage, tier: str, selection_status: str,
                metrics: Mapping[str, Any], golden_train_frame: Optional[pd.DataFrame], model_root: Optional[Path] = None,
                scientific_status: str = "UNASSESSED", legacy_registry_record: Optional[Mapping[str, Any]] = None,
                canonical_source_file: Optional[Path] = None) -> Dict[str, Any]:
    """Persist a model into the store (idempotent: identical model_id must reproduce identical canonical bytes)."""
    if tier not in TIERS or selection_status not in SELECTION_STATES:
        raise ModelStoreError(f"MODEL_TIER_OR_STATUS_INVALID: {tier}/{selection_status}")
    root = model_store_root(model_root)
    mdir = root / "models" / model_id
    manifest_path = mdir / "manifest.json"
    if manifest_path.is_file():
        existing = _read(manifest_path)
        return existing  # immutable; representations are appended through add_export
    auth = family_authority(lineage.family)
    if canonical_source_file is not None:
        (mdir / "canonical").mkdir(parents=True, exist_ok=True)
        dest = mdir / "canonical" / auth["file"]
        shutil.copyfile(canonical_source_file, dest)
        canonical = {"format": auth["canonical_format"], "archival_safety": auth["archival_safety"], "path": dest.name,
                     "byte_sha256": _sha(dest), "logical_sha256": _sha(dest) if auth["archival_safety"] == "portable" else None,
                     "library_versions": _library_versions(), "source": str(canonical_source_file)}
    else:
        canonical = save_canonical(estimator, lineage.family, mdir / "canonical")
    manifest: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "model_id": model_id, "tier": tier, "selection_status": selection_status,
        "scientific_status": scientific_status, "created_at_utc": _now(),
        "lineage": {**lineage.__dict__},
        "metrics": dict(metrics or {}),
        "canonical": canonical,
        "golden": None, "exports": [],
        "legacy_registry_record": dict(legacy_registry_record) if legacy_registry_record else None,
        "score_semantics": "predict_proba_positive",
    }
    # Golden frame from real TRAIN rows, scored by the canonical representation.
    if golden_train_frame is not None:
        frame = build_golden_frame(golden_train_frame, lineage.ordered_inputs, model_id)
        (mdir / "golden").mkdir(parents=True, exist_ok=True)
        frame.to_parquet(mdir / "golden" / "frame.parquet", index=False)
        _json(manifest_path, manifest)  # load_canonical needs the manifest on disk
        scorer = load_canonical(manifest, mdir)
        expected = scorer.scores(frame)
        _json(mdir / "golden" / "expected.json", {"model_id": model_id, "n_rows": int(len(frame)), "expected_scores": [float(v) for v in expected]})
        manifest["golden"] = {"frame_path": "golden/frame.parquet", "frame_sha256": _sha(mdir / "golden" / "frame.parquet"),
                              "frame_content_sha256": _frame_sha(frame), "n_rows": int(len(frame)),
                              "expected_path": "golden/expected.json", "expected_sha256": _sha(mdir / "golden" / "expected.json"),
                              "source": "train_rows_deterministic_sample", "seed_source": "sha256(model_id)[:8]"}
    _json(manifest_path, manifest)
    return manifest


def validate_golden(model_id: str, model_root: Optional[Path] = None, tolerance: float = 1e-12) -> Dict[str, Any]:
    manifest = read_manifest(model_id, model_root); mdir = model_dir(model_id, model_root)
    g = manifest.get("golden")
    if not g:
        raise ModelStoreError(f"GOLDEN_FRAME_MISSING: {model_id}")
    frame = pd.read_parquet(mdir / g["frame_path"])
    if _sha(mdir / g["frame_path"]) != g["frame_sha256"]:
        raise ModelStoreError("GOLDEN_FRAME_CORRUPT")
    expected = np.asarray(_read(mdir / g["expected_path"])["expected_scores"], dtype=np.float64)
    got = load_canonical(manifest, mdir).scores(frame)
    diff = float(np.max(np.abs(got - expected))) if len(got) else 0.0
    if len(got) != len(expected) or diff > tolerance:
        raise ModelStoreError(f"GOLDEN_PREDICTION_MISMATCH: max_abs_diff={diff}")
    return {"model_id": model_id, "n_rows": int(len(frame)), "max_abs_diff": diff, "status": "PASS"}


def add_export(model_id: str, fmt: str, *, model_root: Optional[Path] = None, exporter_version: Optional[str] = None) -> Dict[str, Any]:
    """Export the canonical model to ``fmt`` and verify equivalence on the golden frame.

    Never raises for an export failure: the manifest records ``status: failed`` with the
    error, and the canonical model is untouched.
    """
    manifest = read_manifest(model_id, model_root); mdir = model_dir(model_id, model_root)
    existing = [e for e in manifest.get("exports", []) if e.get("format") == fmt and e.get("status") == "verified"]
    if existing:
        return existing[0]
    record: Dict[str, Any] = {"format": fmt, "status": "candidate", "created_at_utc": _now(), "source_model_id": model_id,
                              "source_canonical_sha256": manifest["canonical"]["byte_sha256"], "exporter": None, "exporter_version": exporter_version}
    (mdir / "exports").mkdir(parents=True, exist_ok=True)
    inputs = manifest["lineage"]["ordered_inputs"]
    try:
        scorer = load_canonical(manifest, mdir)
        if fmt == "joblib":
            import joblib
            path = mdir / "exports" / "model.joblib"
            joblib.dump(scorer.obj, path)
            record["exporter"] = "joblib"; record["exporter_version"] = exporter_version or joblib.__version__
        elif fmt == "onnx":
            path = mdir / "exports" / "model.onnx"
            _export_onnx(manifest, scorer, path, len(inputs))
            import onnxmltools
            record["exporter"] = "onnxmltools/skl2onnx"; record["exporter_version"] = exporter_version or onnxmltools.__version__
        else:
            raise ModelStoreError(f"EXPORT_FORMAT_UNSUPPORTED: {fmt}")
        record["path"] = f"exports/{path.name}"; record["byte_sha256"] = _sha(path)
        g = manifest.get("golden")
        if not g:
            record["status"] = "candidate"; record["equivalence"] = {"status": "NO_GOLDEN_FRAME"}
        else:
            frame = pd.read_parquet(mdir / g["frame_path"])
            expected = np.asarray(_read(mdir / g["expected_path"])["expected_scores"], dtype=np.float64)
            got = _load_export(fmt, path, inputs).scores(frame)
            tol = EXPORT_TOLERANCES.get(fmt, {"abs": 1e-9})
            abs_diff = np.abs(got - expected)
            rel_diff = abs_diff / np.maximum(np.abs(expected), 1e-12)
            ok = len(got) == len(expected) and (bool(np.all(abs_diff <= tol.get("abs", np.inf))) or bool(np.all(rel_diff <= tol.get("rel", -1))))
            equivalence = {"status": "PASS" if ok else "FAIL", "n_rows": int(len(frame)), "max_abs_diff": float(abs_diff.max()) if len(got) else 0.0,
                           "max_rel_diff": float(rel_diff.max()) if len(got) else 0.0, "tolerance": tol, "golden_frame_sha256": g["frame_sha256"],
                           "source_canonical_sha256": manifest["canonical"]["byte_sha256"], "export_sha256": record["byte_sha256"], "checked_at_utc": _now()}
            _json(mdir / "equivalence" / f"{fmt}.json", equivalence)
            record["equivalence"] = equivalence; record["status"] = "verified" if ok else "failed"
    except Exception as exc:  # export failure must not invalidate the canonical model
        record["status"] = "failed"; record["error"] = f"{type(exc).__name__}: {exc}"
    manifest["exports"] = [e for e in manifest.get("exports", []) if e.get("format") != fmt] + [record]
    _json(mdir / "manifest.json", manifest)
    return record


def _export_onnx(manifest: Mapping[str, Any], scorer: _Scorer, path: Path, n_inputs: int) -> None:
    from onnxmltools.convert.common.data_types import FloatTensorType
    initial = [("input", FloatTensorType([None, n_inputs]))]
    fmt = manifest["canonical"]["format"]
    if fmt == "lightgbm_text":
        from onnxmltools.convert import convert_lightgbm
        onx = convert_lightgbm(scorer.obj, initial_types=initial, zipmap=False)
    elif fmt == "xgboost_ubj":
        from onnxmltools.convert import convert_xgboost
        onx = convert_xgboost(scorer.obj, initial_types=initial)
    else:
        from skl2onnx import convert_sklearn
        onx = convert_sklearn(scorer.obj, initial_types=initial, options={id(scorer.obj): {"zipmap": False}})
    path.write_bytes(onx.SerializeToString())


def resolve(model_id: str, *, required_format: str = "canonical", model_root: Optional[Path] = None) -> Dict[str, Any]:
    """Resolve a model by id and required runtime format. ``canonical`` or a verified export name."""
    manifest = read_manifest(model_id, model_root); mdir = model_dir(model_id, model_root)
    if required_format == "canonical":
        return {"model_id": model_id, "format": manifest["canonical"]["format"], "path": str(mdir / "canonical" / manifest["canonical"]["path"]),
                "sha256": manifest["canonical"]["byte_sha256"], "tier": manifest["tier"], "scientific_status": manifest["scientific_status"]}
    for e in manifest.get("exports", []):
        if e.get("format") == required_format and e.get("status") == "verified":
            return {"model_id": model_id, "format": required_format, "path": str(mdir / e["path"]), "sha256": e["byte_sha256"], "tier": manifest["tier"], "scientific_status": manifest["scientific_status"]}
    raise ModelStoreError(f"MODEL_FORMAT_UNAVAILABLE: {model_id} has no verified {required_format} export")


def score(model_id: str, frame: pd.DataFrame, *, required_format: str = "canonical", model_root: Optional[Path] = None) -> np.ndarray:
    manifest = read_manifest(model_id, model_root); mdir = model_dir(model_id, model_root)
    if required_format == "canonical":
        return load_canonical(manifest, mdir).scores(frame)
    r = resolve(model_id, required_format=required_format, model_root=model_root)
    return _load_export(required_format, Path(r["path"]), manifest["lineage"]["ordered_inputs"]).scores(frame)


# ---------------------------------------------------------------------------
# Fit ledger
# ---------------------------------------------------------------------------

def ledger_dir(study_id: str, fit_id: str, model_root: Optional[Path] = None) -> Path:
    return model_store_root(model_root) / "ledger" / study_id / fit_id


def record_fit(*, study_path: Path, fit_id: str, estimator: Any, family: str, row: Mapping[str, Any],
               model_root: Optional[Path] = None) -> Dict[str, Any]:
    """Persist bytes for one actual fit (ledger tier) and append a permanent manifest row in the study."""
    study = Path(study_path).resolve()
    try:
        ldir = ledger_dir(study.name, fit_id, model_root)
        canonical = save_canonical(estimator, family, ldir)
        bytes_ref = {"ledger_dir": str(ldir), **{k: canonical[k] for k in ("format", "path", "byte_sha256", "archival_safety")}}
    except ModelStoreError as exc:
        # No model_root: keep the row (permanent) and say bytes were not durably stored.
        bytes_ref = {"ledger_dir": None, "error": str(exc)}
    entry = {"schema_version": SCHEMA_VERSION, "tier": "ledger", "fit_id": fit_id, "study_id": study.name, "family": family,
             "selection_status": row.get("selection_status", "candidate"), "recorded_at_utc": _now(), "bytes": bytes_ref, **{k: v for k, v in row.items() if k != "selection_status"}}
    out = study / "artifacts" / "fits" / f"{fit_id}.json"
    _json(out, entry)
    return entry


def list_store(model_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = model_store_root(model_root, create=False)
    out = []
    for p in sorted((root / "models").glob("*/manifest.json")) if (root / "models").is_dir() else []:
        m = _read(p)
        out.append({"model_id": m["model_id"], "tier": m["tier"], "selection_status": m["selection_status"], "scientific_status": m["scientific_status"],
                    "family": m["lineage"].get("family"), "study_id": m["lineage"].get("study_id"), "canonical_format": m["canonical"]["format"],
                    "exports": {e["format"]: e["status"] for e in m.get("exports", [])}, "golden": bool(m.get("golden"))})
    return out


__all__ = ["SCHEMA_VERSION", "GOLDEN_MIN_ROWS", "FAMILY_AUTHORITY", "EXPORT_TOLERANCES", "EXPORT_STATES", "SELECTION_STATES", "TIERS",
           "ModelStoreError", "ModelLineage", "family_authority", "build_golden_frame", "store_model", "validate_golden", "add_export",
           "resolve", "score", "record_fit", "list_store", "read_manifest", "model_dir", "model_store_root", "load_canonical", "save_canonical"]
