"""Two/three-phase, direction-independent TRAIN-only model selection.

Makes research_decision.yaml's `inner_train_selection_protocol` /
`architecture_selection_protocol` / `bounded_tuning_protocol` executable and inspectable,
per researcher instruction (correction dated 2026-08-26). No generic multi-phase
composition mechanism exists elsewhere in the repo -- `research_workflow.model_selection
.run_model_selection` is a single-call, single-phase primitive (confirmed: it has no
callers anywhere in the repo besides its own tests before this file). This module
orchestrates that existing governed primitive across the researcher-mandated phases; it
implements no fitting, feature, target, or threshold logic of its own.

    PHASE 1: untuned A/B/C comparison, fit=2021 -> val=2022 ONLY. 2023 rows are asserted
             physically absent from the frame before any governed call is made.
    PHASE 2: bounded hyperparameter search on ONLY the Phase-1 winning arm, same
             fit=2021/val=2022 fold.
    PHASE 3: reject-only scoring of that single already-selected winner against 2023.

Phases 2 and 3 are one `run_model_selection` call because that function's own call graph
already gives the property the researcher requires: `_evaluate_final_validation` takes the
already-selected winner as a plain argument and has no path back into the candidate loop,
so 2023 is structurally incapable of influencing which architecture or which hyperparameter
trial was chosen. Splitting them into two separate governed calls would not strengthen that
guarantee -- it would just invoke the same code twice.

Only two governed APIs are called: `research_workflow.model_selection.run_model_selection`
and the `research.schemas.study_spec` spec types it consumes. No custom trainer, no direct
catalog access, no custom feature/target/threshold logic anywhere in this file.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

from research.schemas.study_spec import ModelFamilySpec, ModelSelectionSpec
from research_workflow.model_selection import run_model_selection

# The parent study's (clean_maturity_flip_model_rolling_productivity) exact frozen
# hyperparameters, verified by direct joblib deserialization -- see research_decision.yaml
# :model_family_resolution. Phase 1 must reuse ALL of these as FIXED values, never the
# partially-tunable ModelFamilySpec study.yaml declares for phase 2/3.
#
# `random_state` is deliberately NOT included here: research.analysis.modeling
# ._build_estimator always constructs the estimator as `LGBMClassifier(random_state=seed,
# **hyperparameters)` -- if a hyperparameters dict also carries `random_state`, the
# constructor call raises `TypeError: got multiple values for keyword argument
# 'random_state'` (caught by this module's own bounded-fixture test suite before this
# was ever run against real data). The parent's seed (42) is instead supplied via
# ModelSelectionSpec.random_seed, which `run_model_selection` passes through as `seed=`.
PARENT_FIXED_HYPERPARAMETERS: Dict[str, Any] = {
    "n_estimators": 200,
    "learning_rate": 0.05,
    "max_depth": 3,
    "num_leaves": 8,
    "verbosity": -1,
}
PARENT_RANDOM_SEED = 42

TUNING_YEARS = (2021, 2022)
FINAL_VALIDATION_YEARS = (2023,)
TIE_TOLERANCE_PR_AUC = 0.005  # predeclared, research_decision.yaml:architecture_selection_protocol


class TwoPhaseSelectionError(RuntimeError):
    """A required invariant of the phased selection protocol was violated."""


def _assert_no_years_outside(meta: pd.DataFrame, allowed_years: tuple, *, phase: str) -> None:
    """Defense-in-depth: fail before any governed call rather than rely solely on
    `run_model_selection`'s own internal `_assert_partition_and_years`."""
    if "_year" not in meta.columns:
        raise TwoPhaseSelectionError(f"{phase}: meta carries no '_year' column")
    present = set(pd.Series(meta["_year"]).dropna().unique().tolist())
    bad = present - set(allowed_years)
    if bad:
        raise TwoPhaseSelectionError(
            f"{phase}: rows carry years {sorted(bad)} outside the allowed set {sorted(allowed_years)}"
        )


def phase1_family_spec() -> ModelFamilySpec:
    """The parent's exact frozen hyperparameters, ALL fixed, NONE tunable.

    Deliberately a separate object from study.yaml's declared `model.selection
    .allowed_families[0]` (which fixes only verbosity/random_state and leaves
    num_leaves/max_depth/learning_rate/n_estimators tunable for phase 2/3) -- reusing
    that object here with search_method='none' would silently fall back to LightGBM
    library defaults for four of six "frozen" hyperparameters, defeating the requirement
    that the untuned comparison isolate the target-horizon change as the sole
    experimental variable (caught by independent causal review, pass 05).
    """
    return ModelFamilySpec(
        family="lightgbm",
        fixed_hyperparameters=dict(PARENT_FIXED_HYPERPARAMETERS),
        tunable_hyperparameters=None,
    )


def phase1_selection_spec(*, primary_metric: str, direction: str) -> ModelSelectionSpec:
    return ModelSelectionSpec(
        allowed_families=[phase1_family_spec()],
        search_method="none",
        random_seed=PARENT_RANDOM_SEED,
        tuning_years=list(TUNING_YEARS),
        final_train_validation_years=None,  # <-- structurally excludes 2023 from this call
        primary_selection_metric=primary_metric,
        primary_selection_metric_direction=direction,
        final_validation_policy="report_only",
    )


@dataclass
class Phase1Result:
    winning_arm: str
    per_arm_pr_auc: Dict[str, Optional[float]]
    per_arm_brier: Dict[str, Optional[float]]
    per_arm_feature_count: Dict[str, int]
    tie_break_applied: bool
    tie_break_trace: List[str] = field(default_factory=list)
    pr_auc_manifest: Dict[str, Any] = field(default_factory=dict)
    brier_manifest: Dict[str, Any] = field(default_factory=dict)


def run_phase1_architecture_selection(
    study_path: str | Path,
    X_by_arm: Mapping[str, pd.DataFrame],
    y: pd.Series,
    meta: pd.DataFrame,
    *,
    feature_counts: Mapping[str, int],
) -> Phase1Result:
    """PHASE 1: untuned A/B/C comparison, fit=2021 -> val=2022 ONLY.

    `meta` MUST carry only years in TUNING_YEARS -- asserted before any governed call,
    so 2023 cannot leak into architecture selection even via a caller mistake. Two
    governed calls are made (one scored on pr_auc, one on brier) because
    `run_model_selection`'s internal `_fit_and_score` evaluates exactly one metric per
    call; this is two invocations of the same existing function, never new fitting code.
    """
    _assert_no_years_outside(meta, TUNING_YEARS, phase="PHASE1")

    pr_auc_manifest = run_model_selection(
        study_path, X_by_arm, y, meta,
        phase1_selection_spec(primary_metric="pr_auc", direction="maximize"),
    )
    brier_manifest = run_model_selection(
        study_path, X_by_arm, y, meta,
        phase1_selection_spec(primary_metric="brier", direction="minimize"),
    )

    per_arm_pr_auc = {a: w["inner_validation_score"] for a, w in pr_auc_manifest["winner"].items()}
    per_arm_brier = {a: w["inner_validation_score"] for a, w in brier_manifest["winner"].items()}

    arms = sorted(X_by_arm.keys())
    scored = [a for a in arms if per_arm_pr_auc.get(a) is not None]
    if not scored:
        raise TwoPhaseSelectionError("PHASE1: no arm produced a scoreable pr_auc")

    best_pr_auc = max(per_arm_pr_auc[a] for a in scored)
    trace = [f"pr_auc per arm: {per_arm_pr_auc}"]
    tied = [a for a in scored if (best_pr_auc - per_arm_pr_auc[a]) <= TIE_TOLERANCE_PR_AUC]
    tie_break_applied = len(tied) > 1
    trace.append(f"within tie_tolerance_pr_auc={TIE_TOLERANCE_PR_AUC}: {tied}")

    winner = tied[0]
    if tie_break_applied:
        briers = [per_arm_brier.get(a) for a in tied]
        if all(b is not None for b in briers):
            best_brier = min(briers)
            tied2 = [a for a in tied if per_arm_brier[a] == best_brier]
        else:
            tied2 = tied
        trace.append(f"brier tie-break -> {tied2}")
        winner = tied2[0]
        if len(tied2) > 1:
            fewest = min(feature_counts[a] for a in tied2)
            tied3 = [a for a in tied2 if feature_counts[a] == fewest]
            trace.append(f"feature-count tie-break -> {tied3}")
            winner = sorted(tied3)[0]  # lexical arm name, last resort
            trace.append(f"lexical tie-break -> {winner}")

    return Phase1Result(
        winning_arm=winner,
        per_arm_pr_auc=per_arm_pr_auc,
        per_arm_brier=per_arm_brier,
        per_arm_feature_count=dict(feature_counts),
        tie_break_applied=tie_break_applied,
        tie_break_trace=trace,
        pr_auc_manifest=pr_auc_manifest,
        brier_manifest=brier_manifest,
    )


@dataclass
class Phase2Phase3Result:
    winning_arm: str
    tuned_hyperparameters: Dict[str, Any]
    inner_validation_score: Optional[float]
    final_validation_status: str  # "PASS" | "FAIL"
    final_validation_metrics: Dict[str, Any]
    final_validation_reasons: List[str]
    manifest: Dict[str, Any]
    manifest_path: str


def run_phase2_tuning_and_phase3_final_validation(
    study_path: str | Path,
    X_winner: pd.DataFrame,
    y: pd.Series,
    meta: pd.DataFrame,
    *,
    winning_arm: str,
    selection_spec: ModelSelectionSpec,
    output_manifest_name: str,
) -> Phase2Phase3Result:
    """PHASE 2 (bounded hyperparameter search, fit=2021->val=2022 fold ONLY) followed,
    inside the SAME governed call, by PHASE 3 (reject-only scoring of the single
    resulting winner against 2023).

    `X_winner`/`y`/`meta` MUST describe exactly ONE arm end-to-end. `meta` MUST carry
    `_selection_role` tagging 2021/2022 rows 'tuning' and 2023 rows 'final_validation'
    -- `run_model_selection`'s own `_assert_partition_and_years` enforces this from
    inside the governed call; asserted again here for a clearer failure at this layer.
    """
    if selection_spec.final_train_validation_years != list(FINAL_VALIDATION_YEARS):
        raise TwoPhaseSelectionError(
            "PHASE2/3: selection_spec.final_train_validation_years must be exactly "
            f"{list(FINAL_VALIDATION_YEARS)}, got {selection_spec.final_train_validation_years}"
        )
    _assert_no_years_outside(meta, TUNING_YEARS + FINAL_VALIDATION_YEARS, phase="PHASE2/3")

    manifest = run_model_selection(study_path, {winning_arm: X_winner}, y, meta, selection_spec)

    if set(manifest["winner"].keys()) != {winning_arm}:
        raise TwoPhaseSelectionError(
            f"PHASE2/3: expected exactly one winner arm {winning_arm!r}, "
            f"got {sorted(manifest['winner'])}"
        )

    study_dir = Path(study_path).resolve()
    default_path = study_dir / "artifacts" / "model_selection_manifest.json"
    out_path = study_dir / "artifacts" / output_manifest_name
    if default_path.resolve() != out_path.resolve():
        default_path.replace(out_path)

    w = manifest["winner"][winning_arm]
    return Phase2Phase3Result(
        winning_arm=winning_arm,
        tuned_hyperparameters=w["hyperparameters"],
        inner_validation_score=w["inner_validation_score"],
        final_validation_status=manifest["final_validation_status"],
        final_validation_metrics=manifest["final_validation_metric"].get(winning_arm, {}),
        final_validation_reasons=manifest["final_validation_reasons"].get(winning_arm, []),
        manifest=manifest,
        manifest_path=str(out_path),
    )


@dataclass
class DirectionResult:
    direction: str
    status: str  # "PASS_DIRECTION" | "FAIL_DIRECTION"
    phase1: Phase1Result
    phase2_phase3: Phase2Phase3Result
    summary: str


def run_direction_two_phase_selection(
    study_path: str | Path,
    direction: str,
    *,
    X_by_arm_tuning: Mapping[str, pd.DataFrame],
    y_tuning: pd.Series,
    meta_tuning: pd.DataFrame,  # 2021/2022 only
    feature_counts: Mapping[str, int],
    X_final_by_arm: Mapping[str, pd.DataFrame],  # keyed by arm name; 2021-2023 rows
    y_final: pd.Series,
    meta_final: pd.DataFrame,  # 2021-2023, _selection_role tagged
    selection_spec_template: ModelSelectionSpec,  # study.yaml's declared bounded spec
) -> DirectionResult:
    """Runs Phase 1 then Phase 2/3 for ONE direction (LONG or SHORT), independently.

    On a Phase-3 (2023 gate) FAIL, this function returns immediately with status
    FAIL_DIRECTION. There is no retry loop anywhere in this call graph: nothing here
    can re-select an architecture, re-run a trial, or derive a threshold for this
    direction after a FAIL.
    """
    phase1 = run_phase1_architecture_selection(
        study_path, X_by_arm_tuning, y_tuning, meta_tuning, feature_counts=feature_counts,
    )
    winning_arm = phase1.winning_arm

    if winning_arm not in X_final_by_arm:
        raise TwoPhaseSelectionError(
            f"{direction}: Phase-1 winner {winning_arm!r} has no corresponding frame in "
            f"X_final_by_arm ({sorted(X_final_by_arm)})"
        )

    phase23 = run_phase2_tuning_and_phase3_final_validation(
        study_path, X_final_by_arm[winning_arm], y_final, meta_final,
        winning_arm=winning_arm, selection_spec=selection_spec_template,
        output_manifest_name=f"model_selection_manifest_{direction.lower()}.json",
    )

    if phase23.final_validation_status != "PASS":
        return DirectionResult(
            direction=direction, status="FAIL_DIRECTION", phase1=phase1, phase2_phase3=phase23,
            summary=(
                f"{direction}_FAIL: arm {winning_arm} failed the 2023 reject-only gate "
                f"({phase23.final_validation_reasons}). STOP -- no re-selection, no "
                f"different trial, no threshold derivation for {direction}."
            ),
        )

    return DirectionResult(
        direction=direction, status="PASS_DIRECTION", phase1=phase1, phase2_phase3=phase23,
        summary=(
            f"{direction}_PASS: arm {winning_arm} passed the 2023 reject-only gate with "
            f"hyperparameters {phase23.tuned_hyperparameters}."
        ),
    )


def run_study_two_phase_selection(
    study_path: str | Path, *, long_inputs: Dict[str, Any], short_inputs: Dict[str, Any],
) -> Dict[str, DirectionResult]:
    """Runs LONG and SHORT as fully independent governed modeling problems.

    Reports both directions' status explicitly (LONG_PASS/LONG_FAIL, SHORT_PASS/
    SHORT_FAIL) -- never pooled, never hidden inside an aggregate metric. One
    direction's failure never blocks or alters the other's result.
    """
    results = {
        "LONG": run_direction_two_phase_selection(study_path, "LONG", **long_inputs),
        "SHORT": run_direction_two_phase_selection(study_path, "SHORT", **short_inputs),
    }
    study_dir = Path(study_path).resolve()
    report_path = study_dir / "artifacts" / "two_phase_selection_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "LONG_status": results["LONG"].status,
                "SHORT_status": results["SHORT"].status,
                "LONG_winning_arm": results["LONG"].phase1.winning_arm,
                "SHORT_winning_arm": results["SHORT"].phase1.winning_arm,
                "LONG_summary": results["LONG"].summary,
                "SHORT_summary": results["SHORT"].summary,
            },
            indent=2, default=str,
        ),
        encoding="utf-8",
    )
    return results


__all__ = [
    "TwoPhaseSelectionError",
    "PARENT_FIXED_HYPERPARAMETERS",
    "TUNING_YEARS",
    "FINAL_VALIDATION_YEARS",
    "TIE_TOLERANCE_PR_AUC",
    "phase1_family_spec",
    "phase1_selection_spec",
    "Phase1Result",
    "run_phase1_architecture_selection",
    "Phase2Phase3Result",
    "run_phase2_tuning_and_phase3_final_validation",
    "DirectionResult",
    "run_direction_two_phase_selection",
    "run_study_two_phase_selection",
]
