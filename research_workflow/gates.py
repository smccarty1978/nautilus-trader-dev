"""Machine-enforced pre-freeze gates (StudySpec.required_gates).

A study may declare a required gate -- e.g. ``TRAIN_TARGET_BALANCE_PASS`` -- that must be
satisfied by a specific, schema-versioned, scope-bound artifact before PREPARE,
READINESS, PREFLIGHT, SEAL, PRE FIT, or TRAIN FREEZE may proceed. Never an arbitrary shell
command: always a structured JSON artifact this module validates and hashes against the
study's own current population/target/chronology declaration, so a gate that ran against
an earlier version of the study is caught as stale, not silently accepted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from research.analysis.identity import canonical_sha256
from research.schemas.study_spec import GateScopeField, RequiredGateSpec, StudySpec

_STAGE_ORDER = ["prepare", "readiness", "preflight", "seal", "pre_fit", "train_freeze"]

_REQUIRED_ARTIFACT_KEYS = (
    "gate_id",
    "schema_version",
    "status",
    "scope_sha256",
    "producer",
    "created_at_utc",
)


class RequiredGateNotSatisfied(RuntimeError):
    """Raised when a declared gate's artifact is missing."""


class RequiredGateStale(RuntimeError):
    """Raised when a declared gate's artifact no longer matches the study's current scope."""


class RequiredGateArtifactMalformed(RuntimeError):
    """Raised when a gate artifact is missing a required, minimally-specified key."""


def compute_population_scope_sha256(spec: StudySpec, scope_fields: List[GateScopeField]) -> str:
    """Hashes the named StudySpec sections -- this recomputation IS the staleness check."""
    payload: Dict[str, Any] = {}
    for field in scope_fields:
        value = getattr(spec, field.value, None)
        payload[field.value] = value.model_dump() if value is not None else None
    return canonical_sha256(payload)


def validate_gate_artifact_schema(payload: Dict[str, Any], expected_schema_version: int) -> None:
    missing = [k for k in _REQUIRED_ARTIFACT_KEYS if k not in payload]
    if missing:
        raise RequiredGateArtifactMalformed(
            f"gate artifact missing required key(s): {missing}"
        )
    if payload["schema_version"] != expected_schema_version:
        raise RequiredGateArtifactMalformed(
            f"gate artifact schema_version={payload['schema_version']!r} does not match "
            f"declared artifact_schema_version={expected_schema_version!r}"
        )
    if payload["status"] not in ("PASS", "FAIL"):
        raise RequiredGateArtifactMalformed(
            f"gate artifact status must be PASS or FAIL, got {payload['status']!r}"
        )


def assert_gates_satisfied(
    study_dir: str | Path,
    spec: StudySpec,
    stage: str,
    *,
    dataset_identity_sha256: str | None = None,
) -> List[Dict[str, Any]]:
    """Fails closed for every declared gate whose stage is at or before ``stage``.

    Returns evidence records for every satisfied gate. Raises on the first violation:
    ``RequiredGateNotSatisfied`` (missing artifact), ``RequiredGateStale`` (scope hash no
    longer matches the study's current declaration), or ``RequiredGateArtifactMalformed``
    (the artifact does not carry the minimum required fields).
    """
    if stage not in _STAGE_ORDER:
        raise ValueError(f"unknown lifecycle stage: {stage!r}")
    stage_idx = _STAGE_ORDER.index(stage)
    study_path = Path(study_dir).resolve()

    evidence: List[Dict[str, Any]] = []
    for gate in spec.required_gates or []:
        if _STAGE_ORDER.index(gate.stage) > stage_idx:
            continue
        artifact_path = study_path / gate.artifact_path
        if not artifact_path.is_file():
            raise RequiredGateNotSatisfied(
                f"REQUIRED_GATE_NOT_SATISFIED: gate {gate.id!r} (stage={gate.stage!r}) "
                f"declares artifact_path={gate.artifact_path!r}, which does not exist"
            )
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        validate_gate_artifact_schema(payload, gate.artifact_schema_version)

        if gate.stage == "pre_fit":
            if not dataset_identity_sha256:
                raise RequiredGateNotSatisfied(
                    f"REQUIRED_GATE_DATASET_BINDING_REQUIRED: pre_fit gate {gate.id!r} "
                    "requires the merged TRAIN dataset_identity_sha256"
                )
            artifact_dataset_identity = payload.get("dataset_identity_sha256")
            if not artifact_dataset_identity:
                raise RequiredGateArtifactMalformed(
                    f"pre_fit gate {gate.id!r} artifact is missing "
                    "dataset_identity_sha256"
                )
            if artifact_dataset_identity != dataset_identity_sha256:
                raise RequiredGateStale(
                    f"REQUIRED_GATE_STALE: pre_fit gate {gate.id!r} binds merged TRAIN "
                    f"dataset {artifact_dataset_identity!r}, not current dataset "
                    f"{dataset_identity_sha256!r}"
                )

        expected_scope_sha256 = compute_population_scope_sha256(spec, gate.scope_fields)
        if payload["scope_sha256"] != expected_scope_sha256:
            raise RequiredGateStale(
                f"REQUIRED_GATE_STALE: gate {gate.id!r}'s artifact scope_sha256="
                f"{payload['scope_sha256']!r} no longer matches the study's current "
                f"declared scope {expected_scope_sha256!r} -- the population/target/"
                f"chronology this gate ran against has since changed"
            )
        if payload["status"] != "PASS":
            raise RequiredGateNotSatisfied(
                f"REQUIRED_GATE_NOT_SATISFIED: gate {gate.id!r}'s artifact status is "
                f"{payload['status']!r}, not PASS"
            )
        evidence.append({"gate_id": gate.id, "stage": gate.stage, "artifact_path": gate.artifact_path, **payload})
    return evidence


__all__ = [
    "RequiredGateNotSatisfied",
    "RequiredGateStale",
    "RequiredGateArtifactMalformed",
    "compute_population_scope_sha256",
    "validate_gate_artifact_schema",
    "assert_gates_satisfied",
]
