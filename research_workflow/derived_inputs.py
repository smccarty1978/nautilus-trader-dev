"""Provenance verification for derived causal inputs (non-FeatureInstance inputs).

A derived causal input is never a canonical market ``FeatureInstance`` -- the initial
supported kind, ``frozen_external_model_score``, is another study's frozen TRAIN
artifact, consumed as a first-class input. This module is the fail-closed gate that
proves the declared binding actually matches what is on disk before a study is allowed
to PREPARE: exact parent artifact identity, non-invalidation, model/preprocessing
identity, and the parent's audited execution composite. No warning mode, mirroring
``research_workflow/forward_outcomes/guard.py``'s posture.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from research.schemas.study_spec import DerivedCausalInputSpec, StudySpec

REPO_ROOT = Path(__file__).resolve().parent.parent

# The exact convention already used by TRAIN_OOS_ARTIFACT_INVALIDATION.md /
# SMOKE_ACCEPTANCE_INVALIDATION.md: an "Invalidated artifacts" heading followed by a
# bullet list of backtick-quoted filenames. This is a generic scan of that existing
# repo convention, not something invented for one study.
_INVALIDATED_HEADING_RE = re.compile(r"Invalidated artifacts", re.IGNORECASE)
_BACKTICK_FILENAME_RE = re.compile(r"`([^`]+)`")


class DerivedInputBindingError(RuntimeError):
    """Raised when a declared derived causal input does not match on-disk provenance."""


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _invalidated_basenames(parent_dir: Path) -> set[str]:
    """Basenames listed under an 'Invalidated artifacts' heading in any
    ``artifacts/*_INVALIDATION.md`` file under the parent study."""
    names: set[str] = set()
    artifacts_dir = parent_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return names
    for md in artifacts_dir.glob("*_INVALIDATION.md"):
        text = md.read_text(encoding="utf-8")
        heading = _INVALIDATED_HEADING_RE.search(text)
        if not heading:
            continue
        # Only bullet lines after the heading count -- a file may mention a filename
        # in prose elsewhere (e.g. explaining what superseded it) without invalidating it.
        after = text[heading.end():]
        for line in after.splitlines():
            stripped = line.strip()
            if not stripped.startswith("-"):
                if stripped and not stripped.startswith("`") and names:
                    # A non-bullet, non-empty line ends the list.
                    break
                continue
            names.update(_BACKTICK_FILENAME_RE.findall(stripped))
    return names


def _verify_model_id(di: DerivedCausalInputSpec, repo_root: Path) -> Dict[str, Any]:
    """RT-03: a registry-only ``model_id`` binding. PREPARE verifies it against the
    immutable model registry (no parent-study lifecycle is consulted), mirroring what
    ``FrozenExternalModelScorer.bind`` already does at collection time."""
    from research_workflow.model_artifacts import ModelArtifactError, resolve_model

    registry_root = repo_root / "studies" / "model_registry"
    try:
        rec = resolve_model(
            di.model_id, registry_root=registry_root,
            reuse_intent="derived_causal_input",
        )
    except ModelArtifactError as exc:
        raise DerivedInputBindingError(
            f"DERIVED_INPUT_MODEL_ID_UNRESOLVED: {di.name!r} binds model_id="
            f"{di.model_id!r}: {exc}"
        ) from exc

    # resolve_model already proved: registry record exists, artifact present +
    # hash-valid, reuse_status == PERMITTED, preprocessing contract available, golden
    # prediction reproduces, scientific_status compatible. Additionally require the
    # ordered model inputs so a child study can bind its causal snapshot to them.
    if not rec.get("ordered_model_inputs"):
        raise DerivedInputBindingError(
            f"DERIVED_INPUT_MODEL_INPUTS_MISSING: {di.name!r} model_id={di.model_id!r} "
            f"registry record has no ordered_model_inputs"
        )
    return {
        "name": di.name,
        "binding": "model_id",
        "model_id": di.model_id,
        "artifact_sha256": rec.get("artifact_sha256"),
        "golden_fixture_sha256": rec.get("golden_fixture_sha256"),
        "ordered_model_inputs": list(rec["ordered_model_inputs"]),
        "scientific_status": rec.get("scientific_status"),
        "reuse_status": rec.get("reuse_status"),
        "availability_reference": di.availability_reference,
        "verified": True,
    }


def _verify_one(di: DerivedCausalInputSpec, repo_root: Path) -> Dict[str, Any]:
    if di.model_id:
        return _verify_model_id(di, repo_root)
    parent_dir = repo_root / "studies" / di.parent_study_id
    artifact_path = parent_dir / di.parent_train_freeze_artifact

    if not artifact_path.is_file():
        raise DerivedInputBindingError(
            f"PARENT_ARTIFACT_MISSING: {di.name!r} declares "
            f"{di.parent_train_freeze_artifact!r} under study {di.parent_study_id!r}, "
            f"but no such file exists at {artifact_path}"
        )

    invalidated = _invalidated_basenames(parent_dir)
    basename = artifact_path.name
    if basename in invalidated:
        raise DerivedInputBindingError(
            f"PARENT_ARTIFACT_INVALIDATED: {di.name!r} binds to {basename!r}, which is "
            f"listed as an invalidated artifact under studies/{di.parent_study_id}/artifacts/"
        )

    actual_sha256 = _file_sha256(artifact_path)
    if actual_sha256 != di.parent_train_freeze_artifact_sha256:
        raise DerivedInputBindingError(
            f"PARENT_ARTIFACT_SHA_MISMATCH: {di.name!r} declares sha256="
            f"{di.parent_train_freeze_artifact_sha256!r} for {di.parent_train_freeze_artifact!r}, "
            f"but the file on disk hashes to {actual_sha256!r}"
        )

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if payload.get("partition") != "train":
        raise DerivedInputBindingError(
            f"MODEL_OR_PREPROCESSING_MISMATCH: {di.name!r}'s parent artifact is not a "
            f"TRAIN-partition freeze (partition={payload.get('partition')!r})"
        )
    parent_hashes = payload.get("model_hashes") or {}
    for arm, declared_hash in di.model_hashes.items():
        actual = parent_hashes.get(arm)
        if actual != declared_hash:
            raise DerivedInputBindingError(
                f"MODEL_OR_PREPROCESSING_MISMATCH: {di.name!r} declares model_hashes[{arm!r}]="
                f"{declared_hash!r}, but the parent freeze records {actual!r}"
            )
    if payload.get("preprocessing_hash") != di.preprocessing_hash:
        raise DerivedInputBindingError(
            f"MODEL_OR_PREPROCESSING_MISMATCH: {di.name!r} declares preprocessing_hash="
            f"{di.preprocessing_hash!r}, but the parent freeze records "
            f"{payload.get('preprocessing_hash')!r}"
        )

    status_path = parent_dir / "audit" / "status.json"
    if not status_path.is_file():
        raise DerivedInputBindingError(
            f"EXECUTION_COMPOSITE_MISMATCH: {di.name!r}'s parent study "
            f"{di.parent_study_id!r} has no audit/status.json to verify the declared "
            f"parent_frozen_execution_composite_sha256 against"
        )
    status = json.loads(status_path.read_text(encoding="utf-8"))
    audited_composite = status.get("audited_execution_composite_sha256")
    if audited_composite != di.parent_frozen_execution_composite_sha256:
        raise DerivedInputBindingError(
            f"EXECUTION_COMPOSITE_MISMATCH: {di.name!r} declares "
            f"parent_frozen_execution_composite_sha256={di.parent_frozen_execution_composite_sha256!r}, "
            f"but the parent's audit/status.json records {audited_composite!r}"
        )

    if di.score_artifact_path:
        score_path = parent_dir / di.score_artifact_path
        if not score_path.is_file():
            raise DerivedInputBindingError(
                f"PARENT_ARTIFACT_MISSING: {di.name!r} declares score_artifact_path="
                f"{di.score_artifact_path!r}, but no such file exists at {score_path}"
            )
        actual_score_sha = _file_sha256(score_path)
        if actual_score_sha != di.score_artifact_sha256:
            raise DerivedInputBindingError(
                f"PARENT_ARTIFACT_SHA_MISMATCH: {di.name!r} declares score_artifact_sha256="
                f"{di.score_artifact_sha256!r}, but the file on disk hashes to {actual_score_sha!r}"
            )

    return {
        "name": di.name,
        "parent_study_id": di.parent_study_id,
        "parent_train_freeze_artifact": di.parent_train_freeze_artifact,
        "parent_train_freeze_artifact_sha256": actual_sha256,
        "parent_frozen_execution_composite_sha256": audited_composite,
        "model_hashes": dict(di.model_hashes),
        "preprocessing_hash": di.preprocessing_hash,
        "availability_reference": di.availability_reference,
        "verified": True,
    }


def verify_derived_causal_inputs(spec: StudySpec, repo_root: Path | None = None) -> List[Dict[str, Any]]:
    """Verifies every declared ``features.derived_inputs`` entry against on-disk provenance.

    Fail-closed, raises ``DerivedInputBindingError`` on the first violation -- there is
    no warning mode. Returns one verification record per declared input on success.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    declared = (spec.features.derived_inputs if spec.features else None) or []
    return [_verify_one(di, root) for di in declared]


__all__ = ["DerivedInputBindingError", "verify_derived_causal_inputs"]
