"""Closed, machine-readable contracts for the governed-study controller."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ControllerState(str, Enum):
    NEEDS_COMPILE = "NEEDS_COMPILE"
    NEEDS_PREPARE = "NEEDS_PREPARE"
    NEEDS_READINESS = "NEEDS_READINESS"
    NEEDS_PREFLIGHT = "NEEDS_PREFLIGHT"
    NEEDS_TESTS = "NEEDS_TESTS"
    NEEDS_CAUSAL_AUDIT = "NEEDS_CAUSAL_AUDIT"
    NEEDS_CONTRACT_AUDIT = "NEEDS_CONTRACT_AUDIT"
    READY_TO_SEAL = "READY_TO_SEAL"
    READY_TO_COLLECT = "READY_TO_COLLECT"
    COLLECTION_RUNNING = "COLLECTION_RUNNING"
    READY_TO_RECONCILE = "READY_TO_RECONCILE"
    READY_TO_ANALYZE = "READY_TO_ANALYZE"
    PHASE_D_MODELING_READY_NOT_AUTHORIZED = "PHASE_D_MODELING_READY_NOT_AUTHORIZED"
    COMPLETE = "COMPLETE"


class BlockerType(str, Enum):
    SEMANTIC_BLOCKER = "SEMANTIC_BLOCKER"
    CAUSALITY_BLOCKER = "CAUSALITY_BLOCKER"
    CONTRACT_BLOCKER = "CONTRACT_BLOCKER"
    DATA_AUTH_BLOCKER = "DATA_AUTH_BLOCKER"
    CAPABILITY_BLOCKER = "CAPABILITY_BLOCKER"
    RUNTIME_FAILURE = "RUNTIME_FAILURE"
    WORKTREE_CONTAMINATION = "WORKTREE_CONTAMINATION"


@dataclass(frozen=True)
class FailurePacket:
    study_id: str
    current_stage: str
    blocker_type: str
    exact_reason: str
    affected_artifacts: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    hashes: dict[str, str | None] = field(default_factory=dict)
    last_successful_stage: str | None = None
    allowed_actions: list[str] = field(default_factory=list)
    prohibited_actions: list[str] = field(default_factory=lambda: ["open_oos", "bypass_audit", "bypass_seal"])
    oos_accessed: bool = False
    deterministic_repair_possible: bool = False
    schema_version: int = 1
    identity: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControllerStatus:
    status: str
    state: str
    stage: str
    next_state: str
    blocker_code: str | None = None
    artifact: str | None = None
    sha256: str | None = None
    test_counts: dict[str, int] = field(default_factory=dict)
    schema_version: int = 1
    def as_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class AuditPacket:
    study_id: str
    audit_type: str
    execution_composite_sha256: str | None
    current_execution_composite_sha256: str | None
    hashes: dict[str, str | None]
    contracts: dict[str, Any]
    changed_files: list[str]
    relevant_code_paths: list[str]
    invariants: list[str]
    test_summary: dict[str, Any]
    prior_audit: dict[str, Any]
    schema_version: int = 1
    identity: str | None = None
    def as_dict(self) -> dict[str, Any]: return asdict(self)
