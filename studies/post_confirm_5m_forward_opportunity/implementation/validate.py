"""Gates and the computed C1-C5/ABORT verdict (SPEC sections 3.1, 6, 8).

The verdict is derived from the gate table and the measured quantities. An
unrun gate is a FAILURE, not a pass -- mirrors both predecessors' validate.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
IMPL_DIR = ROOT / "studies/post_confirm_5m_forward_opportunity/implementation"

MEASURABLE_CONFIRMED_REQUIRED = 4656
SEALED_YEAR = 2026

CONFIRMATION_TIME_ONLY_COLS = {
    "side", "entry_year", "confirm_mfe_bucket", "confirm_mae_bucket",
    "confirm_return_bucket", "confirm_seconds_bucket", "arm_score_quartile", "time_of_day",
}


def _gate(name, expected, observed, ok, note="") -> dict:
    return {"gate": name, "expected": expected, "observed": observed,
            "pass": bool(ok), "note": note}


def run_gates(*, lineage: dict, confirmation_state: pl.DataFrame,
              landmark_attrition: pl.DataFrame, adverse_path: pl.DataFrame,
              phase12_strata_cols: tuple[str, ...], all_output_frames: dict[str, pl.DataFrame],
              race_pairs: dict[str, str]) -> list[dict]:
    g: list[dict] = []

    # V1/V2: Phase 0 reproduction
    g.append(_gate("V1_V2_predecessor_reproduction", True, lineage.get("all_reproduced"),
                   bool(lineage.get("all_reproduced"))))

    # V-ANCHOR: every landmark table keyed off walk_a_confirm_ns (structural --
    # confirmation_state IS keyed by it; the panel's offset_s is confirm-relative
    # by construction, inherited from the already-audited predecessor).
    has_confirm_ns = "walk_a_confirm_ns" in confirmation_state.columns
    g.append(_gate("V_ANCHOR_time_zero_is_confirmation", True, has_confirm_ns, has_confirm_ns))

    # V-CAUSAL: age-at-confirmation never negative / never NaN treated as negative
    age = confirmation_state["regime_age_s_at_confirm"].to_numpy()
    finite = age[~np.isnan(age)]
    bad = int((finite < 0).sum())
    g.append(_gate("V_CAUSAL_age_at_confirm_nonnegative", 0, bad, bad == 0))

    # V-NOFUTURE: grouping columns are boolean, sourced from with_5m_at_p90/
    # with_5m_at_confirm only -- verified structurally by source scan: this
    # study's own implementation/*.py must never reassign those two names.
    reassign_pattern = re.compile(r"with_5m_at_(p90|confirm)\s*=")
    bad_files = []
    for p in sorted(IMPL_DIR.glob("*.py")):
        if p.name == "join.py":
            continue  # join.py legitimately READS them via select/join, not reassignment
        text = p.read_text(encoding="utf-8")
        if reassign_pattern.search(text):
            bad_files.append(p.name)
    g.append(_gate("V_NOFUTURE_no_reclassification", [], bad_files, len(bad_files) == 0,
                   "with_5m_at_p90/at_confirm must only ever be read, never recomputed, in this study"))

    # V-LABEL: label_only fields never define `group`; Phase 11's mfe_bucket
    # is a permitted descriptive crosstab (SPEC section 3.1 item 4's carve-out) --
    # checked by confirming `group` values are always exactly WITH_5M/AGAINST_5M
    # in every output frame that carries a `group` column, never a bucket label.
    bad_group_values = {}
    for name, df in all_output_frames.items():
        if "group" in df.columns:
            vals = set(df["group"].drop_nulls().unique().to_list())
            if not vals <= {"WITH_5M", "AGAINST_5M"}:
                bad_group_values[name] = sorted(vals)
    g.append(_gate("V_LABEL_group_values_clean", {}, bad_group_values, len(bad_group_values) == 0))

    # V-SURVIVAL: landmark_attrition carries n_denominator/n_alive/n_terminal/
    # attrition_pct at every landmark, against the constant denominator.
    required_cols = {"n_denominator", "n_alive_unconstrained", "n_terminal", "attrition_pct"}
    has_cols = required_cols <= set(landmark_attrition.columns)
    denom_consistent = bool(
        (landmark_attrition["n_denominator"]
         == landmark_attrition["n_alive_unconstrained"] + landmark_attrition["n_terminal"]).all()
    )
    g.append(_gate("V_SURVIVAL_attrition_reported", True, has_cols and denom_consistent,
                   has_cols and denom_consistent))

    # V-MATCH: Phase 12 strata are confirmation-time-only.
    bad_strata = set(phase12_strata_cols) - CONFIRMATION_TIME_ONLY_COLS
    g.append(_gate("V_MATCH_confirmation_time_only", [], sorted(bad_strata), len(bad_strata) == 0))

    # V-SEALED: 2026 never appears.
    years = sorted(int(y) for y in confirmation_state["entry_year"].unique().to_list())
    g.append(_gate("V_SEALED_2026", "max <= 2025", max(years), max(years) < SEALED_YEAR))

    # V-RACE: the 3-way categorical + ambiguous sub-flag sum correctly.
    race_bad = []
    for pair_label in race_pairs:
        cols = ("p_adverse_before_favorable_" + pair_label,
               "p_favorable_before_adverse_" + pair_label,
               "p_unresolved_" + pair_label)
        if not all(c in adverse_path.columns for c in cols):
            race_bad.append(pair_label)
            continue
        total = (adverse_path[cols[0]] + adverse_path[cols[1]] + adverse_path[cols[2]]).drop_nulls()
        if total.len() and not np.allclose(total.to_numpy(), 1.0, atol=1e-6):
            race_bad.append(pair_label)
    g.append(_gate("V_RACE_probabilities_sum_to_one", [], race_bad, len(race_bad) == 0))

    return g


def determine_verdict(*, gates: list[dict], primary_table: pl.DataFrame,
                      phase12: pl.DataFrame, phase6_threshold: pl.DataFrame,
                      phase9_giveback: pl.DataFrame, phase13: pl.DataFrame,
                      phase11: pl.DataFrame) -> dict:
    if not gates or not all(x["pass"] for x in gates):
        return {"verdict": "ABORT_LINEAGE_FAILURE", "facts": {},
               "failed_gates": [x["gate"] for x in gates if not x["pass"]]}

    def _pt_metric(metric: str, group: str) -> float:
        row = primary_table.filter((pl.col("population_definition") == "TRANSITION")
                                   & (pl.col("group") == group) & (pl.col("metric") == metric))
        return float(row["value"][0]) if row.height else float("nan")

    # ---- Phase 12: does the majority of outcome metrics survive stratification?
    p12 = phase12.filter(pl.col("population_definition") == "TRANSITION")
    n_metrics = p12.height
    n_survive = int(p12["ci_excludes_zero"].sum())
    phase12_majority_survives = n_survive > n_metrics / 2 if n_metrics else False

    # ---- C1 facts: capture-curve timing gap, remaining-MFE gap, giveback-onset gap
    def _median_time(threshold: float, group: str) -> float:
        r = phase6_threshold.filter((pl.col("population_definition") == "TRANSITION")
                                    & (pl.col("group") == group) & (pl.col("threshold_pct") == threshold))
        return float(r["median_time_to_threshold_s"][0]) if r.height else float("nan")

    time_to_50_with = _median_time(0.50, "WITH_5M")
    time_to_50_against = _median_time(0.50, "AGAINST_5M")
    timing_gap_s = (time_to_50_with - time_to_50_against
                    if np.isfinite(time_to_50_with) and np.isfinite(time_to_50_against) else float("nan"))

    remaining_300_with = _pt_metric("remaining_mfe_median_300s", "WITH_5M")
    remaining_300_against = _pt_metric("remaining_mfe_median_300s", "AGAINST_5M")
    remaining_gap = remaining_300_with - remaining_300_against

    def _giveback_onset(group: str) -> float:
        sub = phase9_giveback.filter((pl.col("population_definition") == "TRANSITION")
                                     & (pl.col("group") == group)).sort("offset_s")
        hit = sub.filter(pl.col("giveback_median") > 0.10)
        return float(hit["offset_s"][0]) if hit.height else float("inf")

    onset_gap_s = _giveback_onset("WITH_5M") - _giveback_onset("AGAINST_5M")

    p12_confirm_delta = p12.filter(pl.col("outcome_metric").str.starts_with("incremental_mfe"))
    p12_direction_consistent = bool(
        (p12_confirm_delta["stratified_delta"] > 0).all() if p12_confirm_delta.height else False
    )

    years_stable = True  # computed from phase13 below
    year_rows = phase13.filter((pl.col("population_definition") == "TRANSITION")
                               & (pl.col("slice_kind") == "year") & (pl.col("metric") == "incr_mfe")
                               & (pl.col("offset_s") == 300))
    if year_rows.height:
        wide = year_rows.pivot(on="group", index="slice", values="value")
        if "WITH_5M" in wide.columns and "AGAINST_5M" in wide.columns:
            delta = (wide["WITH_5M"] - wide["AGAINST_5M"]).drop_nulls()
            years_stable = bool((delta > 0).sum() >= 4) if delta.len() else False

    side_rows = phase13.filter((pl.col("population_definition") == "TRANSITION")
                               & (pl.col("slice_kind") == "side") & (pl.col("metric") == "incr_mfe")
                               & (pl.col("offset_s") == 300))
    no_side_inversion = True
    if side_rows.height:
        wide = side_rows.pivot(on="group", index="slice", values="value")
        if "WITH_5M" in wide.columns and "AGAINST_5M" in wide.columns:
            delta = (wide["WITH_5M"] - wide["AGAINST_5M"]).drop_nulls().to_numpy()
            no_side_inversion = bool(delta.size == 2 and ((delta > 0).all() or (delta < 0).all()))

    facts = {
        "phase12_n_metrics": n_metrics, "phase12_n_ci_excludes_zero": n_survive,
        "phase12_majority_survives": phase12_majority_survives,
        "timing_gap_50pct_s": timing_gap_s, "remaining_mfe_gap_300s": remaining_gap,
        "giveback_onset_gap_s": onset_gap_s, "years_stable": years_stable,
        "no_side_inversion": no_side_inversion,
    }

    # ---- C1: strong context-specific timing
    c1 = bool(
        np.isfinite(timing_gap_s) and timing_gap_s >= 60
        and remaining_gap >= 0.15
        and np.isfinite(onset_gap_s) and onset_gap_s >= 60
        and phase12_majority_survives
        and years_stable and no_side_inversion
    )

    # ---- C3: explained by confirmation quality (checked before C2/C4)
    c3 = not phase12_majority_survives

    # ---- C2: runner quality not timing (within-runner_bucket capture shapes similar)
    p11_incr = phase11.filter((pl.col("metric") == "incr_mfe_median")
                              & (pl.col("population_definition") == "TRANSITION"))
    c2 = False
    if p11_incr.height:
        wide = p11_incr.pivot(on="group", index=["runner_bucket", "offset_s"], values="value")
        if "WITH_5M" in wide.columns and "AGAINST_5M" in wide.columns:
            rel = ((wide["WITH_5M"] - wide["AGAINST_5M"]).abs()
                  / wide["WITH_5M"].abs().clip(lower_bound=1e-6))
            c2 = bool((rel.drop_nulls() < 0.20).mean() > 0.5) if rel.drop_nulls().len() else False

    # ---- C4: weak/unstable
    c4 = bool((not years_stable or not no_side_inversion)
             and not c3)

    # ---- C5: no information (checked last, residual)
    pooled_flat = bool(
        abs(remaining_gap) < 0.05
        and (not np.isfinite(timing_gap_s) or abs(timing_gap_s) < 15)
    )

    if c1:
        verdict = "C1_STRONG_CONTEXT_SPECIFIC_TIMING"
    elif c3:
        verdict = "C3_EXPLAINED_BY_CONFIRMATION_QUALITY"
    elif c2:
        verdict = "C2_RUNNER_QUALITY_NOT_TIMING"
    elif c4:
        verdict = "C4_WEAK_UNSTABLE_CONTEXT_EFFECT"
    elif pooled_flat:
        verdict = "C5_NO_POST_CONFIRM_5M_INFORMATION"
    else:
        verdict = "C4_WEAK_UNSTABLE_CONTEXT_EFFECT"

    return {"verdict": verdict, "facts": facts}
