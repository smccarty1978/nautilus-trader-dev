"""RT-13 -- immutable lineage identity for a governed OOS analysis artifact.

``artifacts/experiment_analysis.json`` bound only ``study_id`` / ``authorization_sha256``
/ ``rows``, so it stayed apparently authoritative after the exact TRAIN freeze, model, or
OOS run it summarises changed. This module:

* ``build_oos_analysis_identity`` -- the block ``analyze_results`` now stamps into the
  artifact, binding the freeze file bytes, the model ids, the stage-scoped closures, the
  OOS authorization + run/dataset identity, and this analysis code's own identity;
* ``classify_oos_analysis`` -- re-resolves that block against on-disk state and returns
  ``FRESH`` / ``STALE`` / ``INVALID`` so workflow state never presents a stale analysis as
  authoritative. Historical analysis artifacts are never deleted.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# The analysis code whose behaviour an OOS analysis result depends on. A change here means
# an existing artifact was produced by a different implementation -> STALE.
_ANALYSIS_IMPL_SEEDS = (
    "research_workflow/analysis.py",
    "research/analysis/metrics.py",
    "research/analysis/slices.py",
    "research/analysis/reporting.py",
    "research/analysis/modeling.py",
    "research/analysis/identity.py",
)


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _file_sha(p: Path) -> Optional[str]:
    return _sha_bytes(p.read_bytes()) if p.is_file() else None


def analysis_implementation_sha256(repo_root: Path | None = None) -> str:
    root = repo_root or REPO_ROOT
    parts = {
        rel: _file_sha(root / rel) for rel in _ANALYSIS_IMPL_SEEDS
    }
    return _sha_bytes(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _model_ids_from_freeze(freeze: Mapping[str, Any]) -> list[str]:
    arts = freeze.get("model_artifacts") or []
    ids = [a.get("model_id") for a in arts if isinstance(a, Mapping) and a.get("model_id")]
    if ids:
        return sorted(ids)
    # legacy freezes: fall back to the per-arm fit identities
    return sorted(str(v) for v in (freeze.get("model_hashes") or {}).values() if v)


_IDENTITY_FIELDS = (
    "study_id", "train_experiment_freeze_sha256", "train_freeze_internal_sha256",
    "model_ids", "modeling_execution_closure_sha256", "collection_producer_closure_sha256",
    "target_runtime_closure_sha256", "oos_authorization_sha256", "oos_run_id",
    "oos_dataset_identity_sha256", "analysis_implementation_sha256",
)


def build_oos_analysis_identity(
    study_dir: str | Path,
    *,
    freeze: Mapping[str, Any],
    oos_run_id: Optional[str],
    oos_dataset_identity_sha256: Optional[str],
    repo_root: Path | None = None,
) -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    lineage = freeze.get("stage_scoped_lineage") or {}
    body = {
        "schema_version": 1,
        "study_id": study_dir.name,
        "train_experiment_freeze_sha256": _file_sha(study_dir / "artifacts" / "train_experiment_freeze.json"),
        "train_freeze_internal_sha256": freeze.get("freeze_sha256"),
        "model_ids": _model_ids_from_freeze(freeze),
        "modeling_execution_closure_sha256": lineage.get("MODELING_EXECUTION_CLOSURE"),
        "collection_producer_closure_sha256": lineage.get("COLLECTION_PRODUCER_CLOSURE"),
        "target_runtime_closure_sha256": lineage.get("TARGET_RUNTIME_CLOSURE"),
        "oos_authorization_sha256": freeze.get("authorization_sha256"),
        "oos_run_id": oos_run_id,
        "oos_dataset_identity_sha256": oos_dataset_identity_sha256,
        "analysis_implementation_sha256": analysis_implementation_sha256(repo_root),
    }
    body["identity_sha256"] = _sha_bytes(
        json.dumps({k: body[k] for k in _IDENTITY_FIELDS}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return body


def classify_oos_analysis(study_dir: str | Path, *, repo_root: Path | None = None) -> Optional[Dict[str, Any]]:
    """Return ``{"state": FRESH|STALE|INVALID, "reasons": [...]}`` for the study's OOS
    analysis artifact, or ``None`` when there is no artifact to classify."""
    study_dir = Path(study_dir).resolve()
    artifact = study_dir / "artifacts" / "experiment_analysis.json"
    if not artifact.is_file():
        return None

    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except ValueError:
        return {"state": "INVALID", "reasons": ["experiment_analysis.json is not valid JSON"]}

    ident = payload.get("oos_analysis_identity")
    if not isinstance(ident, Mapping):
        return {"state": "INVALID", "reasons": ["no oos_analysis_identity block (pre-RT-13 artifact)"]}

    reasons: list[str] = []
    # self-binding integrity
    recomputed = _sha_bytes(
        json.dumps({k: ident.get(k) for k in _IDENTITY_FIELDS}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if ident.get("identity_sha256") != recomputed:
        return {"state": "INVALID", "reasons": ["oos_analysis_identity was edited (self-hash mismatch)"]}
    if ident.get("study_id") != study_dir.name:
        return {"state": "INVALID", "reasons": [f"identity study_id {ident.get('study_id')!r} != {study_dir.name!r}"]}

    freeze_path = study_dir / "artifacts" / "train_experiment_freeze.json"
    if not freeze_path.is_file():
        return {"state": "INVALID", "reasons": ["the TRAIN freeze this analysis bound to is gone"]}

    current_freeze_sha = _file_sha(freeze_path)
    if current_freeze_sha != ident.get("train_experiment_freeze_sha256"):
        reasons.append("TRAIN freeze changed since this analysis was produced")
        try:
            cur = json.loads(freeze_path.read_text(encoding="utf-8"))
            cur_lineage = cur.get("stage_scoped_lineage") or {}
            if cur_lineage.get("MODELING_EXECUTION_CLOSURE") != ident.get("modeling_execution_closure_sha256"):
                reasons.append("modeling execution closure moved")
            if sorted(_model_ids_from_freeze(cur)) != list(ident.get("model_ids") or []):
                reasons.append("frozen model identity changed")
            if cur.get("authorization_sha256") != ident.get("oos_authorization_sha256"):
                reasons.append("OOS authorization changed")
        except ValueError:
            reasons.append("current TRAIN freeze is unreadable")

    if analysis_implementation_sha256(repo_root) != ident.get("analysis_implementation_sha256"):
        reasons.append("analysis implementation changed since this artifact was produced")

    return {"state": "STALE" if reasons else "FRESH", "reasons": reasons}


__all__ = [
    "analysis_implementation_sha256",
    "build_oos_analysis_identity",
    "classify_oos_analysis",
]
