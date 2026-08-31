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


def _resolve_relative_or_root(study_dir: Path, rel_path: str) -> Path:
    p = Path(rel_path)
    if p.is_absolute():
        return p
    for candidate in [
        study_dir.parent / rel_path,
        study_dir / rel_path,
        REPO_ROOT / rel_path,
        study_dir.parent.parent / rel_path,
    ]:
        if candidate.exists():
            return candidate.resolve()
    return (study_dir / rel_path).resolve()


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

    if ident.get("result_body_sha256"):
        body_keys = {k: v for k, v in payload.items() if k != "oos_analysis_identity"}
        computed_body = _sha_bytes(json.dumps(body_keys, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if computed_body != ident["result_body_sha256"]:
            return {"state": "INVALID", "reasons": ["experiment_analysis result body tampered"]}

    freeze_path = study_dir / "artifacts" / "train_experiment_freeze.json"
    if not freeze_path.is_file():
        return {"state": "INVALID", "reasons": ["the TRAIN freeze this analysis bound to is gone"]}

    current_freeze_sha = _file_sha(freeze_path)
    try:
        cur_freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "INVALID", "reasons": ["current TRAIN freeze is unreadable"]}

    if current_freeze_sha != ident.get("train_experiment_freeze_sha256"):
        reasons.append("TRAIN freeze changed since this analysis was produced")
    if cur_freeze.get("freeze_sha256") != ident.get("train_freeze_internal_sha256"):
        reasons.append("TRAIN internal freeze hash changed")

    cur_lineage = cur_freeze.get("stage_scoped_lineage") or {}
    if cur_lineage.get("MODELING_EXECUTION_CLOSURE") != ident.get("modeling_execution_closure_sha256"):
        reasons.append("modeling execution closure moved")
    if cur_lineage.get("COLLECTION_PRODUCER_CLOSURE") != ident.get("collection_producer_closure_sha256"):
        reasons.append("collection producer closure moved")
    if cur_lineage.get("TARGET_RUNTIME_CLOSURE") != ident.get("target_runtime_closure_sha256"):
        reasons.append("target runtime closure moved")
    if sorted(_model_ids_from_freeze(cur_freeze)) != list(ident.get("model_ids") or []):
        reasons.append("frozen model identity changed")
    if cur_freeze.get("authorization_sha256") != ident.get("oos_authorization_sha256"):
        reasons.append("OOS authorization changed")

    # Re-resolve model registry records and artifacts
    model_ids = list(ident.get("model_ids") or _model_ids_from_freeze(cur_freeze))
    for mid in model_ids:
        # Search model registry in parent or local
        reg_candidates = [
            study_dir.parent / "model_registry" / f"{mid}.json",
            study_dir / "model_registry" / f"{mid}.json",
            REPO_ROOT / "studies" / "model_registry" / f"{mid}.json",
        ]
        reg_file = next((rc for rc in reg_candidates if rc.is_file()), None)
        if reg_file is None:
            return {"state": "INVALID", "reasons": [f"bound model registry record missing: {mid}"]}
        try:
            reg_body = json.loads(reg_file.read_text(encoding="utf-8"))
        except Exception:
            return {"state": "INVALID", "reasons": [f"bound model registry record unreadable: {mid}"]}

        # Model artifact verification
        art_rel = reg_body.get("artifact_path")
        if art_rel:
            art_file = _resolve_relative_or_root(study_dir, art_rel)
            if not art_file.is_file() or _file_sha(art_file) != reg_body.get("artifact_sha256"):
                return {"state": "INVALID", "reasons": [f"bound model artifact corrupt/missing for {mid}"]}

        # Golden fixture verification
        golden_rel = reg_body.get("golden_fixture_path")
        if golden_rel:
            gold_file = _resolve_relative_or_root(study_dir, golden_rel)
            if not gold_file.is_file() or _file_sha(gold_file) != reg_body.get("golden_fixture_sha256"):
                return {"state": "INVALID", "reasons": [f"bound golden fixture corrupt/missing for {mid}"]}

        # Preprocessing artifact verification if bound
        prep_rel = reg_body.get("preprocessing_artifact_path")
        if prep_rel:
            prep_file = _resolve_relative_or_root(study_dir, prep_rel)
            if not prep_file.is_file() or _file_sha(prep_file) != reg_body.get("preprocessing_artifact_sha256"):
                return {"state": "INVALID", "reasons": [f"bound preprocessing artifact corrupt/missing for {mid}"]}

    # OOS authorization artifact re-resolution
    auth_path = study_dir / "artifacts" / "experiment_authorization.json"
    if not auth_path.is_file():
        return {"state": "INVALID", "reasons": ["experiment_authorization.json is missing"]}
    try:
        auth_data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "INVALID", "reasons": ["experiment_authorization.json is unreadable"]}
    if auth_data.get("authorization_sha256") != ident.get("oos_authorization_sha256"):
        reasons.append("current OOS authorization does not match analysis binding")

    # Reconciliation artifacts if bound in analysis identity
    rec_file_sha = ident.get("oos_reconciliation_artifact_file_sha256")
    if rec_file_sha:
        rec_path = study_dir / "artifacts" / "oos_lineage_reconciliation.json"
        if not rec_path.is_file() or _file_sha(rec_path) != rec_file_sha:
            return {"state": "INVALID", "reasons": ["oos_lineage_reconciliation.json missing or tampered"]}

    rec_auth_id = ident.get("oos_reconciled_authority_identity_sha256")
    if rec_auth_id:
        rec_auth_path = study_dir / "artifacts" / "oos_reconciled_authority.json"
        if not rec_auth_path.is_file():
            return {"state": "INVALID", "reasons": ["oos_reconciled_authority.json is missing"]}

    if analysis_implementation_sha256(repo_root) != ident.get("analysis_implementation_sha256"):
        reasons.append("analysis implementation changed since this artifact was produced")

    return {"state": "STALE" if reasons else "FRESH", "reasons": reasons}


def classify_stage17_decision(study_dir: str | Path, *, repo_root: Path | None = None) -> Optional[Dict[str, Any]]:
    """Return ``{"state": FRESH|STALE|INVALID, "reasons": [...]}`` for the study's Stage 17
    decision artifact, or ``None`` when there is no decision artifact."""
    study_dir = Path(study_dir).resolve()
    artifact = study_dir / "artifacts" / "research_decision_stage17.json"
    if not artifact.is_file():
        return None

    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except ValueError:
        return {"state": "INVALID", "reasons": ["research_decision_stage17.json is not valid JSON"]}

    if payload.get("study_id") != study_dir.name:
        return {"state": "INVALID", "reasons": [f"decision study_id {payload.get('study_id')!r} != {study_dir.name!r}"]}

    # Stage 17 depends strictly on Stage 16 FRESH identity when OOS is bound or present
    lineage = payload.get("bound_lineage") or {}
    s16_bound = bool(lineage.get("stage16_analysis_artifact_file_sha256") or lineage.get("stage16_analysis_identity_sha256"))
    s16_file = study_dir / "artifacts" / "experiment_analysis.json"
    if s16_bound or s16_file.is_file():
        oos_verdict = classify_oos_analysis(study_dir, repo_root=repo_root)
        if oos_verdict is None:
            return {"state": "INVALID", "reasons": ["Stage 16 experiment_analysis.json is missing"]}
        if oos_verdict["state"] == "INVALID":
            return {"state": "INVALID", "reasons": [f"Stage 16 analysis is INVALID: {oos_verdict['reasons']}"]}
        if oos_verdict["state"] == "STALE":
            return {"state": "STALE", "reasons": [f"Stage 16 analysis is STALE: {oos_verdict['reasons']}"]}

    reasons: list[str] = []
    if lineage.get("stage16_analysis_artifact_file_sha256"):
        if _file_sha(s16_file) != lineage["stage16_analysis_artifact_file_sha256"]:
            reasons.append("Stage 16 analysis artifact file sha moved")

    return {"state": "STALE" if reasons else "FRESH", "reasons": reasons}


__all__ = [
    "analysis_implementation_sha256",
    "build_oos_analysis_identity",
    "classify_oos_analysis",
    "classify_stage17_decision",
]
