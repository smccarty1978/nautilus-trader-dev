"""Failure taxonomy for the analysis harness.

Every failure mode declared in `ANALYSIS_HARNESS_A0_CONTRACT.md` §7 has exactly one
exception class here, and every one fails closed. Nothing in this package degrades
silently: a check either passes, or raises with the contract's own failure code.

The code string is the stable identifier (used in `validation.json` and in tests);
the class hierarchy is a convenience for catching families.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class AnalysisError(Exception):
    """Base class. `code` is the contract failure mode."""

    code = "ANALYSIS_ERROR"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(f"{self.code}: {message}")
        self.message = message
        self.context: Dict[str, Any] = context

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


# --- artifact / identity -------------------------------------------------


class MissingArtifact(AnalysisError):
    code = "MISSING_ARTIFACT"


class InvalidRunId(MissingArtifact):
    """`run_id` is not a plain directory name inside `runs_root`.

    A subclass of MissingArtifact so existing callers that catch "this run cannot be
    resolved" keep working, while the code stays precise: a traversal attempt is a
    rejected identity, not an absent file.
    """

    code = "INVALID_RUN_ID"


class CollectionNotSuccessful(AnalysisError):
    code = "COLLECTION_NOT_SUCCESSFUL"


class ArtifactHashMismatch(AnalysisError):
    code = "ARTIFACT_HASH_MISMATCH"


class StaleCompiledStudy(AnalysisError):
    """study.yaml no longer matches compiled_study.json (study dir inconsistent now)."""

    code = "STALE_COMPILED_STUDY"


class SpecDrift(AnalysisError):
    """compiled_study.json no longer matches the run's recorded spec_sha256."""

    code = "SPEC_DRIFT"


class IdentityMismatch(AnalysisError):
    code = "IDENTITY_MISMATCH"


class UnsealedCollection(AnalysisError):
    code = "UNSEALED_COLLECTION"


# --- schema --------------------------------------------------------------


class FeatureOrderMismatch(AnalysisError):
    code = "FEATURE_ORDER_MISMATCH"


class FeatureHashMismatch(AnalysisError):
    code = "FEATURE_HASH_MISMATCH"


class SchemaSurplus(AnalysisError):
    code = "SCHEMA_SURPLUS"


class SchemaMissing(AnalysisError):
    code = "SCHEMA_MISSING"


class DuplicateColumns(AnalysisError):
    code = "DUPLICATE_COLUMNS"


class DuplicateKeys(AnalysisError):
    code = "DUPLICATE_KEYS"


class TargetMissing(AnalysisError):
    code = "TARGET_MISSING"


class JoinKeyMissing(AnalysisError):
    code = "JOIN_KEY_MISSING"


class EmptyObservations(AnalysisError):
    code = "EMPTY_OBSERVATIONS"


class JoinRowLoss(AnalysisError):
    code = "JOIN_ROW_LOSS"


class RowCountMismatch(AnalysisError):
    code = "ROW_COUNT_MISMATCH"


# --- partitions ----------------------------------------------------------


class WarmupLeakage(AnalysisError):
    code = "WARMUP_LEAKAGE"


class ProhibitedPartitionPresent(AnalysisError):
    code = "PROHIBITED_PARTITION_PRESENT"


class OOSLocked(AnalysisError):
    code = "OOS_LOCKED"


class PartitionMixing(AnalysisError):
    code = "PARTITION_MIXING"


class PartitionProvenanceMissing(PartitionMixing):
    """A fit was requested with no record of which partition the rows came from.

    Absence of provenance is not evidence of a single partition. A subclass of
    PartitionMixing because it is the same hazard one step earlier: without
    `_partition` the mixing guard cannot run at all.
    """

    code = "PARTITION_PROVENANCE_MISSING"


class CrossStudyPooling(AnalysisError):
    code = "CROSS_STUDY_POOLING"


# --- spec / metrics ------------------------------------------------------


class InvalidAnalysisSpec(AnalysisError):
    code = "INVALID_ANALYSIS_SPEC"


class MetricNotComputable(AnalysisError):
    """Raised only where a caller demands a scalar; the metrics layer returns a
    structured `not_computable` result instead of raising by default."""

    code = "METRIC_NOT_COMPUTABLE"


class ValidationNotRun(AnalysisError):
    code = "VALIDATION_NOT_RUN"


ALL_FAILURE_CODES = tuple(
    sorted(
        cls.code
        for cls in (
            MissingArtifact, InvalidRunId, CollectionNotSuccessful, ArtifactHashMismatch,
            StaleCompiledStudy, SpecDrift, IdentityMismatch, UnsealedCollection,
            FeatureOrderMismatch, FeatureHashMismatch, SchemaSurplus, SchemaMissing,
            DuplicateColumns, DuplicateKeys, TargetMissing, JoinKeyMissing,
            EmptyObservations, JoinRowLoss, RowCountMismatch, WarmupLeakage,
            ProhibitedPartitionPresent, OOSLocked, PartitionMixing,
            PartitionProvenanceMissing, CrossStudyPooling,
            InvalidAnalysisSpec, MetricNotComputable, ValidationNotRun,
        )
    )
)
