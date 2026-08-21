"""Frozen reporting grid and terminal classification contract."""
from __future__ import annotations


MODELS = (
    "BASELINE",
    "BASELINE_PLUS_STRUCTURAL",
    "BASELINE_PLUS_STRUCTURAL_PLUS_ROLLING_5M",
)
DIRECTIONS = ("SHORT", "LONG")
BUCKETS = ("300-600s", "600-900s", "900-1800s")
THRESHOLDS = ("P90", "P95", "P97_5")
TERMINAL_LABELS = (
    "R1_CLEAN_BROAD_IMPROVEMENT",
    "R2_YOUNG_REGIME_IMPROVEMENT",
    "R3_TIMING_IMPROVES_ECONOMICS_DO_NOT",
    "R4_ECONOMIC_TAIL_WITHOUT_LARGE_AUC_GAIN",
    "R5_ROLLING_PRODUCTIVITY_ADDS_NOTHING",
    "R6_NO_CLEAN_INCREMENTAL_INFORMATION",
    "ABORT_CONTRACT_OR_CAUSAL_FAILURE",
)
REQUIRED_MANIFESTS = (
    "artifacts/phase0_source_manifest.json",
    "artifacts/collection_manifest.json",
    "artifacts/frozen_feature_manifest.json",
    "artifacts/model_manifest.json",
    "artifacts/score_manifest.json",
    "artifacts/crossing_manifest.json",
    "artifacts/decile_manifest.json",
    "artifacts/validation.json",
    "artifacts/result_seal.json",
    "artifacts/promotion_gate.json",
    "STUDY_REPORT.md",
)


def expected_directional_cells() -> set[tuple[str, str, str]]:
    return {(model, direction, bucket) for model in MODELS for direction in DIRECTIONS for bucket in BUCKETS}


def expected_pooled_cells() -> set[tuple[str, str]]:
    """Required descriptive pooled rows; never inputs to terminal classification."""
    return {(model, bucket) for model in MODELS for bucket in BUCKETS}


def classify_terminal(*, audit_clean: bool, broad_improvement: bool,
                      young_improvement: bool, timing_only: bool,
                      economic_tail_only: bool, rolling_adds_nothing: bool) -> str:
    """Reach every frozen terminal state without using pooled diagnostics."""
    if not audit_clean:
        return "ABORT_CONTRACT_OR_CAUSAL_FAILURE"
    if broad_improvement:
        return "R1_CLEAN_BROAD_IMPROVEMENT"
    if young_improvement:
        return "R2_YOUNG_REGIME_IMPROVEMENT"
    if timing_only:
        return "R3_TIMING_IMPROVES_ECONOMICS_DO_NOT"
    if economic_tail_only:
        return "R4_ECONOMIC_TAIL_WITHOUT_LARGE_AUC_GAIN"
    if rolling_adds_nothing:
        return "R5_ROLLING_PRODUCTIVITY_ADDS_NOTHING"
    return "R6_NO_CLEAN_INCREMENTAL_INFORMATION"
