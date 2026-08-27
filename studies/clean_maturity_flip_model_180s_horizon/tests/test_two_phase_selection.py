"""Bounded-fixture proof of the two/three-phase TRAIN-only selection invariant.

Synthetic data only -- no TRAIN collection has occurred for this study; these tests
exercise `implementation/two_phase_selection.py` against small, deterministic fixtures to
prove the required assertions hold BEFORE any real data is ever passed through it:

  - Phase 1 uses only 2021/2022 rows; a 2023 row present anywhere raises before any fit.
  - Phase 1 uses the parent's exact fixed hyperparameters (all six), never a partially
    tunable object.
  - Phase 2/3 accepts exactly one arm (structural: the function signature takes a single
    DataFrame, not a mapping) and rejects a final_train_validation_years mismatch.
  - A failed 2023 gate returns FAIL_DIRECTION and performs no further action for that
    direction.
  - LONG and SHORT are fully independent: one direction's failure does not alter or block
    the other's result, and both are reported explicitly, never pooled.
  - study.yaml's OWN declared secondary_metrics are all registry-supported -- a
    `secondary_metrics: [brier_score, precision_at_p90, ...]` mismatch against
    research_workflow.model_selection's actual metric registry raised
    UnsupportedSelectionMetric the first time a real Phase 2/3 dispatch ran, uncaught by
    any test until this one was added (per AGENTS.md's "prove a multi-call protocol
    before it's authoritative" -- this regression is what that principle is for).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

STUDY_DIR = Path(__file__).resolve().parents[1]


def _repo_root() -> Path:
    for candidate in [STUDY_DIR, *STUDY_DIR.parents]:
        if (candidate / "features" / "registry.py").exists() and (candidate / "research").is_dir():
            return candidate
    import features
    return Path(features.__file__).resolve().parents[1]


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
IMPLEMENTATION_DIR = STUDY_DIR / "implementation"
if str(IMPLEMENTATION_DIR) not in sys.path:
    sys.path.insert(0, str(IMPLEMENTATION_DIR))

from research.schemas.study_spec import ModelFamilySpec, ModelSelectionSpec  # noqa: E402
from two_phase_selection import (  # noqa: E402
    FINAL_VALIDATION_YEARS,
    PARENT_FIXED_HYPERPARAMETERS,
    TUNING_YEARS,
    TwoPhaseSelectionError,
    phase1_family_spec,
    run_direction_two_phase_selection,
    run_phase1_architecture_selection,
    run_phase2_tuning_and_phase3_final_validation,
    run_study_two_phase_selection,
)


def _synthetic_arm_frame(rng: np.random.Generator, n: int, n_features: int, signal: float) -> pd.DataFrame:
    cols = {f"f{i}": rng.normal(size=n) for i in range(n_features)}
    df = pd.DataFrame(cols)
    df.attrs["_signal_col"] = "f0"
    df.attrs["_signal_strength"] = signal
    return df


def _synthetic_direction_dataset(seed: int, *, years: tuple, arm_feature_counts=None, arm_signal=None):
    """Builds X_by_arm/y/meta for `years` (a subset of (2021, 2022, 2023)).

    2021/2022 rows are tagged `_selection_role='tuning'`; any 2023 rows are tagged
    `_selection_role='final_validation'`. All rows are `_partition='train'`.
    """
    arm_feature_counts = arm_feature_counts or {"A": 2, "B": 3, "C": 4}
    arm_signal = arm_signal or {"A": 0.6, "B": 0.9, "C": 0.9}
    rng = np.random.default_rng(seed)
    n_per_year = 60

    rows_year = []
    rows_role = []
    y_vals = []
    per_arm_rows = {arm: [] for arm in arm_feature_counts}

    for yr in years:
        role = "tuning" if yr in TUNING_YEARS else "final_validation"
        latent = rng.normal(size=n_per_year)
        labels = (latent > 0).astype(int)
        for arm, n_feat in arm_feature_counts.items():
            signal = arm_signal[arm]
            block = {f"f{i}": rng.normal(size=n_per_year) for i in range(n_feat)}
            block["f0"] = latent * signal + rng.normal(scale=1.0 - signal, size=n_per_year)
            per_arm_rows[arm].append(pd.DataFrame(block))
        rows_year.extend([yr] * n_per_year)
        rows_role.extend([role] * n_per_year)
        y_vals.extend(labels.tolist())

    X_by_arm = {arm: pd.concat(frames, ignore_index=True) for arm, frames in per_arm_rows.items()}
    y = pd.Series(y_vals, name="y")
    meta = pd.DataFrame({
        "_partition": ["train"] * len(rows_year),
        "_year": rows_year,
        "_selection_role": rows_role,
    })
    return X_by_arm, y, meta


def _bounded_search_spec(*, gate_impossible: bool) -> ModelSelectionSpec:
    # random_state deliberately absent -- see two_phase_selection.PARENT_FIXED_HYPERPARAMETERS
    # docstring: the fitting layer always supplies random_state=seed itself.
    family = ModelFamilySpec(
        family="lightgbm",
        fixed_hyperparameters={"verbosity": -1},
        tunable_hyperparameters=[
            {"name": "num_leaves", "kind": "choice", "values": [4, 8]},
            {"name": "n_estimators", "kind": "choice", "values": [50, 100]},
        ],
    )
    req = (
        {"primary_metric_bound": {"metric": "pr_auc", "minimum": 0.999}}
        if gate_impossible
        else {"primary_metric_bound": {"metric": "pr_auc", "minimum": 0.0}}
    )
    return ModelSelectionSpec(
        allowed_families=[family],
        search_method="random",
        max_trials=4,
        random_seed=7,
        tuning_years=list(TUNING_YEARS),
        final_train_validation_years=list(FINAL_VALIDATION_YEARS),
        primary_selection_metric="pr_auc",
        primary_selection_metric_direction="maximize",
        final_validation_policy="gated",
        final_validation_requirements=req,
    )


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------

def test_phase1_rejects_2023_rows_present():
    X_by_arm, y, meta = _synthetic_direction_dataset(1, years=(2021, 2022, 2023))
    with pytest.raises(TwoPhaseSelectionError, match="PHASE1"):
        run_phase1_architecture_selection(
            tempfile.mkdtemp(), X_by_arm, y, meta,
            feature_counts={a: X_by_arm[a].shape[1] for a in X_by_arm},
        )


def test_phase1_selects_a_winner_using_only_2021_2022():
    X_by_arm, y, meta = _synthetic_direction_dataset(2, years=(2021, 2022))
    result = run_phase1_architecture_selection(
        tempfile.mkdtemp(), X_by_arm, y, meta,
        feature_counts={a: X_by_arm[a].shape[1] for a in X_by_arm},
    )
    assert result.winning_arm in X_by_arm
    assert set(result.per_arm_pr_auc) == set(X_by_arm)
    assert set(result.per_arm_brier) == set(X_by_arm)
    # exactly one walk-forward fold (fit=2021, val=2022) was scored
    for arm_attempts in result.pr_auc_manifest["attempts"].values():
        assert len(arm_attempts[0]["fold_scores"]) == 1


def test_phase1_uses_parent_fixed_hyperparameters_not_defaults():
    spec = phase1_family_spec()
    assert spec.fixed_hyperparameters == PARENT_FIXED_HYPERPARAMETERS
    assert not spec.tunable_hyperparameters


def test_phase1_manifests_do_not_clobber_across_directions_or_metrics():
    """Independent contract review (pass 09) found all four Phase-1 calls (LONG/SHORT x
    pr_auc/brier) wrote to the same hardcoded run_model_selection default path, so only
    the last call's manifest survived on disk. Prove each call now leaves its own file."""
    tmp = tempfile.mkdtemp()
    for direction, seed in (("LONG", 10), ("SHORT", 11)):
        X_by_arm, y, meta = _synthetic_direction_dataset(seed, years=(2021, 2022))
        run_phase1_architecture_selection(
            tmp, X_by_arm, y, meta,
            feature_counts={a: X_by_arm[a].shape[1] for a in X_by_arm},
            direction=direction,
        )
    artifacts_dir = Path(tmp) / "artifacts"
    expected = {
        "model_selection_manifest_phase1_long_prauc.json",
        "model_selection_manifest_phase1_long_brier.json",
        "model_selection_manifest_phase1_short_prauc.json",
        "model_selection_manifest_phase1_short_brier.json",
    }
    present = {p.name for p in artifacts_dir.glob("model_selection_manifest_phase1_*.json")}
    assert expected <= present, f"missing: {expected - present}"
    # The shared default path must not be left behind either -- every call renamed it.
    assert not (artifacts_dir / "model_selection_manifest.json").exists()


# ---------------------------------------------------------------------------
# Phase 2 / 3
# ---------------------------------------------------------------------------

def test_phase2_rejects_years_outside_2021_2022_2023():
    X_by_arm, y, meta = _synthetic_direction_dataset(3, years=(2021, 2022, 2023))
    meta = meta.copy()
    meta.loc[0, "_year"] = 2020
    meta.loc[0, "_selection_role"] = "tuning"
    with pytest.raises(TwoPhaseSelectionError, match="PHASE2/3"):
        run_phase2_tuning_and_phase3_final_validation(
            tempfile.mkdtemp(), X_by_arm["A"], y, meta,
            winning_arm="A", selection_spec=_bounded_search_spec(gate_impossible=False),
            output_manifest_name="model_selection_manifest_test.json",
        )


def test_phase2_rejects_final_validation_years_mismatch():
    X_by_arm, y, meta = _synthetic_direction_dataset(4, years=(2021, 2022, 2023))
    bad_spec = _bounded_search_spec(gate_impossible=False).model_copy(
        update={"final_train_validation_years": [2024]}
    )
    with pytest.raises(TwoPhaseSelectionError, match="final_train_validation_years must be exactly"):
        run_phase2_tuning_and_phase3_final_validation(
            tempfile.mkdtemp(), X_by_arm["A"], y, meta,
            winning_arm="A", selection_spec=bad_spec,
            output_manifest_name="model_selection_manifest_test.json",
        )


def test_phase2_produces_exactly_one_winner_and_gates_against_2023():
    X_by_arm, y, meta = _synthetic_direction_dataset(5, years=(2021, 2022, 2023))
    result = run_phase2_tuning_and_phase3_final_validation(
        tempfile.mkdtemp(), X_by_arm["B"], y, meta,
        winning_arm="B", selection_spec=_bounded_search_spec(gate_impossible=False),
        output_manifest_name="model_selection_manifest_test.json",
    )
    assert set(result.manifest["winner"].keys()) == {"B"}
    assert result.final_validation_status in ("PASS", "FAIL")
    assert result.manifest["no_retuning_after_final_validation_assertion"] is True


# ---------------------------------------------------------------------------
# Direction-level: gate failure stops, cannot fall back
# ---------------------------------------------------------------------------

def _direction_inputs(seed: int, *, gate_impossible: bool):
    X_tuning, y_tuning, meta_tuning = _synthetic_direction_dataset(seed, years=(2021, 2022))
    X_final, y_final, meta_final = _synthetic_direction_dataset(seed, years=(2021, 2022, 2023))
    return dict(
        X_by_arm_tuning=X_tuning, y_tuning=y_tuning, meta_tuning=meta_tuning,
        feature_counts={a: X_tuning[a].shape[1] for a in X_tuning},
        X_final_by_arm=X_final, y_final=y_final, meta_final=meta_final,
        selection_spec_template=_bounded_search_spec(gate_impossible=gate_impossible),
    )


def test_direction_fails_gate_and_stops_with_no_fallback():
    result = run_direction_two_phase_selection(
        tempfile.mkdtemp(), "LONG", **_direction_inputs(6, gate_impossible=True),
    )
    assert result.status == "FAIL_DIRECTION"
    assert result.phase2_phase3.final_validation_status == "FAIL"
    assert "STOP" in result.summary


def test_direction_passes_gate():
    result = run_direction_two_phase_selection(
        tempfile.mkdtemp(), "SHORT", **_direction_inputs(7, gate_impossible=False),
    )
    assert result.status in ("PASS_DIRECTION", "FAIL_DIRECTION")
    if result.status == "PASS_DIRECTION":
        assert result.phase2_phase3.final_validation_status == "PASS"


def test_run_study_reports_both_directions_independently_never_pooled():
    tmp = tempfile.mkdtemp()
    results = run_study_two_phase_selection(
        tmp,
        long_inputs=_direction_inputs(8, gate_impossible=True),   # forced FAIL
        short_inputs=_direction_inputs(9, gate_impossible=False),  # not forced
    )
    assert results["LONG"].status == "FAIL_DIRECTION"
    # SHORT's gate is independent of LONG's forced failure: LONG's impossible bound
    # (pr_auc >= 0.999) must never appear in SHORT's own failure reasons, and the two
    # directions must be bound to distinct manifest files, never one shared object.
    assert results["LONG"].phase2_phase3.manifest_path != results["SHORT"].phase2_phase3.manifest_path
    assert not any("0.999" in r for r in results["SHORT"].phase2_phase3.final_validation_reasons)
    report_path = Path(tmp) / "artifacts" / "two_phase_selection_report.json"
    assert report_path.exists()
    import json
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["LONG_status"] == "FAIL_DIRECTION"
    assert report["SHORT_status"] == results["SHORT"].status
    assert "LONG_winning_arm" in report and "SHORT_winning_arm" in report


# ---------------------------------------------------------------------------
# study.yaml fidelity: declared secondary_metrics must be registry-supported
# ---------------------------------------------------------------------------

def test_study_yaml_secondary_metrics_are_registry_supported():
    """A metric name in study.yaml that the fitting layer cannot score is a defect that
    only surfaces the first time a REAL Phase 2/3 run reaches _evaluate_final_validation
    -- by then a gate has already been consumed. Assert it here instead."""
    from research_workflow.model_selection import _METRIC_FNS

    data = yaml.safe_load((STUDY_DIR / "study.yaml").read_text(encoding="utf-8"))
    declared = (data.get("model", {}).get("selection", {}) or {}).get("secondary_metrics") or []
    unsupported = [m for m in declared if m not in _METRIC_FNS]
    assert not unsupported, (
        f"study.yaml declares secondary_metrics {unsupported!r} not in "
        f"research_workflow.model_selection._METRIC_FNS ({sorted(_METRIC_FNS)}) -- these "
        f"would raise UnsupportedSelectionMetric the first time final validation actually "
        f"runs, not at compile/preflight time."
    )
    primary = (data.get("model", {}).get("selection", {}) or {}).get("primary_selection_metric")
    if primary:
        assert primary in _METRIC_FNS, (
            f"study.yaml's primary_selection_metric {primary!r} is not in _METRIC_FNS "
            f"({sorted(_METRIC_FNS)})"
        )
