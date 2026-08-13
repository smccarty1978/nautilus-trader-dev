"""Staged runner for the post-confirmation retracement/recovery study.

Stages are independent and resumable, so a failure in the economics does not
force a re-walk of 4,656 one-second paths:

    build       walk every trade -> arm_panel + recovery_state_panel + lineage
    descriptive Phases 1, 3, 4, 5, 10
    economics   Phases 8, 9, 11
    diagnostics Phases 12, 13, 14
    validate    the fourteen SPEC gates -> validation_report.json
    summary     terminal label + Q1-Q13 answers -> summary.json

Phase 0 is a HARD GATE: if the accepted predecessor population does not
reproduce, the run stops. This study does not repair a predecessor silently.

    python -m studies.post_confirm_retracement_recovery.run_study --stage all
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import polars as pl

from studies.post_confirm_retracement_recovery.implementation import (
    build, diagnostics, phases, validate,
)
from studies.post_confirm_retracement_recovery.implementation.common import (
    RESULTS, write_csv, write_parquet,
)

STAGES = ("build", "descriptive", "economics", "diagnostics", "validate", "summary")


def _load(name: str) -> pl.DataFrame:
    return pl.read_parquet(RESULTS / name)


def stage_build(limit: int | None) -> dict:
    lin = build.main(limit=limit)
    if lin["lineage_status"] != "REPRODUCED":
        raise SystemExit(
            "PHASE 0 LINEAGE FAILURE -- stopping.\n"
            + json.dumps(lin["failed"], indent=2)
            + "\nDo not repair silently. Resolve the discrepancy first.")
    return {"lineage": lin["lineage_status"], **lin["build_diagnostics"]}


def stage_descriptive() -> dict:
    arms = _load("arm_panel.parquet")
    write_csv(phases.retracement_frequency(arms), "retracement_frequency.csv")
    write_csv(phases.recovery_probability(arms), "recovery_probability.csv")
    write_csv(phases.recovery_timing(arms), "recovery_timing.csv")
    write_csv(phases.adverse_before_recovery(arms), "adverse_before_recovery.csv")
    write_parquet(phases.recovery_curves(arms), "recovery_curves.parquet")
    return {"arm_rows": arms.height}


def stage_economics() -> dict:
    states = _load("recovery_state_panel.parquet")
    write_csv(phases.failed_recovery_economics(states),
              "failed_recovery_economics.csv")
    write_csv(phases.runner_interception(states), "runner_interception.csv")
    write_csv(phases.conditional_value_curve(states), "conditional_value_curve.csv")
    return {"state_rows": states.height}


def stage_diagnostics() -> dict:
    arms = _load("arm_panel.parquet")
    states = _load("recovery_state_panel.parquet")
    write_csv(diagnostics.price_only_diagnostics(states),
              "price_only_diagnostics.csv")
    write_csv(diagnostics.placebo_controls(arms, states), "placebo_controls.csv")
    write_csv(diagnostics.by_side(states), "by_side.csv")
    write_csv(diagnostics.by_year(states), "by_year.csv")
    return {"ok": True}


def stage_validate() -> dict:
    arms = _load("arm_panel.parquet")
    states = _load("recovery_state_panel.parquet")
    lin = json.loads((RESULTS / "lineage_reconciliation.json").read_text("utf-8"))
    rep = validate.run_gates(arms, states, lin)
    return {"gates_passed": rep["n_passed"], "of": rep["n_gates"],
            "all_passed": rep["all_passed"]}


# The six §7.5 controls minus RANDOM_TIMING. RANDOM_TIMING's population
# conditions only on `retracement_d` -- the arm panel carries no horizon
# dimension -- so it is not a like-for-like comparison at a given
# (horizon, level) and is reported but never used to decide the label
# (lookahead-auditor pass 2, note N2).
DECISIVE_CONTROLS = ("RETRACEMENT_ONLY", "CURRENT_RETURN_ONLY",
                     "TIME_SINCE_CONFIRM_ONLY", "DRAWDOWN_FROM_HWM_ONLY",
                     "TIME_SINCE_RUNG_ONLY")

# Below this, a mean CME difference is not an exit edge at any size. One tick on
# NQ is 0.25 pt against a ~9.6 pt RTH ATR, so ~0.026 ATR is a single tick.
MATERIAL_ATR = 0.05


def _terminal_label() -> dict:
    """Derive the §8.1 label from the frozen conditions, not from prose.

    Every clause is emitted with the number that decided it, so the label can be
    recomputed and disputed without re-reading the report.
    """
    import numpy as np

    pc = pl.read_csv(RESULTS / "placebo_controls.csv")
    fre = pl.read_csv(RESULTS / "failed_recovery_economics.csv").filter(
        pl.col("reason").is_null())
    ri = pl.read_csv(RESULTS / "runner_interception.csv")
    bs = pl.read_csv(RESULTS / "by_side.csv").filter(pl.col("reason").is_null())
    by = pl.read_csv(RESULTS / "by_year.csv").filter(pl.col("reason").is_null())

    rules = pc.unique(subset=["rule_id"], keep="first")
    n_rules = rules.height
    ci_excl = int(((rules["rule_ci95_lo"] > 0) | (rules["rule_ci95_hi"] < 0)).sum())
    # At 95% confidence, ~5% of cells clear zero by chance alone.
    expected_by_chance = 0.05 * n_rules

    # C1 -- does the RECOVERY condition add anything over the retracement alone?
    ret_only = pc.filter(pl.col("control_id") == "RETRACEMENT_ONLY")
    ret_only_gap = float(ret_only["rule_minus_control"].mean())

    # C2 -- ordered deterioration across >=3 adjacent horizons.
    mono = []
    for key, g in fre.group_by(["state", "recovery_level", "rung_atr",
                                "retracement_d"], maintain_order=True):
        v = g.sort("horizon_s")["cme_mark_mean"].to_numpy()
        if v.size >= 3 and np.all(np.diff(v) <= 0):
            mono.append({"state": key[0], "recovery_level": key[1],
                         "rung_atr": float(key[2]), "retracement_d": float(key[3]),
                         "cme_by_horizon": [round(float(x), 4) for x in v]})
    n_cells_ge3 = sum(
        1 for _, g in fre.group_by(["state", "recovery_level", "rung_atr",
                                    "retracement_d"]) if g.height >= 3)

    # C3 -- beats the decisive controls.
    dec = pc.filter(pl.col("control_id").is_in(list(DECISIVE_CONTROLS)))
    control_beats = float(dec["control_beats_rule"].mean())
    worst = (dec.group_by("control_id")
             .agg(pl.col("control_beats_rule").mean().alias("pct_beats"),
                  pl.col("rule_minus_control").mean().alias("mean_gap"))
             .sort("pct_beats", descending=True))

    # C4 -- same sign LONG and SHORT.
    pct_inverted = float(bs["sign_inverted"].mean())

    # C5 -- runner destruction.
    lw_median = float(ri["loser_winner_ratio"].median())
    ge3_median = float(ri["pct_runners_ge3_0_intercepted"].median())

    years_all5 = int((by["years_consistent"] >= 5).sum())

    checks = {
        "recovery_condition_adds_value": bool(abs(ret_only_gap) >= MATERIAL_ATR),
        "ordered_deterioration": bool(len(mono) >= 2),
        "beats_decisive_controls": bool(control_beats < 0.25),
        "sign_stable_across_sides": bool(pct_inverted < 0.5),
        "runners_preserved": bool(lw_median >= 2.0),
        "more_significant_than_chance": bool(ci_excl > expected_by_chance),
        "year_consistent": bool(years_all5 > 0),
    }

    if all(checks.values()):
        label = "R1_STRONG_FAILED_RECOVERY_STATE"
    elif checks["ordered_deterioration"] and checks["more_significant_than_chance"] \
            and not checks["recovery_condition_adds_value"]:
        label = "R2_PRICE_ONLY_RULE_SUFFICIENT"
    elif checks["ordered_deterioration"] and checks["sign_stable_across_sides"] \
            and not checks["more_significant_than_chance"]:
        label = "R3_PLAUSIBLE_BUT_UNDERPOWERED"
    else:
        label = "R4_NO_USEFUL_FAILED_RECOVERY_STATE"

    return {
        "terminal_label": label,
        "checks": checks,
        "evidence": {
            "n_rules": n_rules,
            "rules_ci_excludes_zero": ci_excl,
            "expected_by_chance_at_95pct": round(expected_by_chance, 1),
            "best_rule_cme_atr": float(rules["rule_cme_mean"].min()),
            "median_rule_cme_atr": float(rules["rule_cme_mean"].median()),
            "retracement_only_gap_atr": round(ret_only_gap, 5),
            "material_threshold_atr": MATERIAL_ATR,
            "cells_with_ge3_horizons": n_cells_ge3,
            "cells_monotonically_worsening": len(mono),
            "monotone_cells": mono,
            "pct_decisive_control_beats_rule": round(control_beats, 4),
            "per_control": worst.to_dicts(),
            "pct_side_sign_inverted": round(pct_inverted, 4),
            "median_loser_winner_ratio": round(lw_median, 4),
            "median_pct_runners_ge3_intercepted": round(ge3_median, 2),
            "cells_consistent_across_all_5_years": years_all5,
        },
    }


def stage_summary() -> dict:
    arms = _load("arm_panel.parquet")
    lin = json.loads((RESULTS / "lineage_reconciliation.json").read_text("utf-8"))
    val = json.loads((RESULTS / "validation_report.json").read_text("utf-8"))
    rf = pl.read_csv(RESULTS / "retracement_frequency.csv").filter(
        pl.col("reason").is_null())
    rp = pl.read_csv(RESULTS / "recovery_probability.csv").filter(
        pl.col("reason").is_null())
    rt = pl.read_csv(RESULTS / "recovery_timing.csv").filter(
        pl.col("reason").is_null())

    verdict = _terminal_label()
    hwm = rp.filter(pl.col("recovery_level") == "R100")
    hwm_t = rt.filter(pl.col("recovery_level") == "R100")

    summary = {
        "study": "post_confirm_retracement_recovery",
        **verdict,
        "population": {
            "original_top10_entries": 8950,
            "confirmed": 4705,
            "measurable_confirmed": 4656,
            "arm_rows": arms.height,
            "lineage_status": lin["lineage_status"],
            "lineage_checks_failed": lin["n_failed"],
        },
        "gates": {"passed": val["n_passed"], "of": val["n_gates"],
                  "all_passed": val["all_passed"]},
        "headline": {
            "pct_retracing_min": round(float(rf["pct_retracing_fresh"].min()), 2),
            "pct_retracing_max": round(float(rf["pct_retracing_fresh"].max()), 2),
            "p_reclaim_hwm_min": round(float(hwm["p_recover_before_terminal"].min()), 4),
            "p_reclaim_hwm_max": round(float(hwm["p_recover_before_terminal"].max()), 4),
            "median_secs_to_hwm_reclaim": float(hwm_t["secs_median"].median()),
        },
        "answers": ANSWERS,
    }
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2),
                                          encoding="utf-8")
    return {"terminal_label": summary["terminal_label"],
            "checks_passed": sum(verdict["checks"].values()),
            "of": len(verdict["checks"])}


ANSWERS = {
    "Q1": "Near-universally. 93.1-99.4% of trades reaching a rung retrace by D; "
          "at D=1.00 ATR it is 98.8-99.4%. Retracement is not a state, it is what "
          "always happens.",
    "Q2": "Usually. P(reclaim the full HWM) before terminal is 0.752-0.792 and "
          "P(new HWM) 0.743-0.782; R25 is 0.925-0.937.",
    "Q3": "Fast. Median 5-6s to R25 and 55-57s to full HWM reclaim; p90 267-280s.",
    "Q4": "Little. Median additional adverse excursion before recovery is well "
          "under 0.5 ATR, p90 ~1.10 and p95 ~1.44 ATR. Arms that never recover "
          "fall a median ~1.60 ATR further.",
    "Q5": "No. Only 5 of 125 cells with >=3 horizons worsen monotonically -- "
          "roughly the chance rate for 4-point sequences -- and they do not form "
          "a neighbourhood.",
    "Q6": "Nowhere reliably. Best of 96 rules is -0.098 ATR (CI -0.201 to -0.006); "
          "median -0.015. Only 1 of 96 CIs excludes zero, fewer than the ~4.8 "
          "expected by chance at 95%.",
    "Q7": "No. The rule beats RETRACEMENT_ONLY by 0.002 ATR on average -- far "
          "under one tick. The recovery condition is decoration on the "
          "retracement.",
    "Q8": "No. Simple drawdown, trade age, rung age and current return controls "
          "match the rule to within 0.008-0.019 ATR; each beats it outright in "
          "21-38% of cells.",
    "Q9": "Too many. The states intercept a median 13.3% of >=3 ATR runners and "
          "21.2% of >=4 ATR runners, at a median loser:winner ratio of only 1.38 "
          "-- close to destroying winners and losers in equal measure.",
    "Q10": "No. 40 of 48 side-split cells (83.3%) invert sign between LONG and "
           "SHORT; LONG frequently favours continuing where SHORT favours exiting.",
    "Q11": "No knee. The few coherent-looking cells are isolated and no cell is "
           "consistent across all five years (best is 4 of 5).",
    "Q12": "R4. Retracement is universal, recovery is the norm, the recovery "
           "condition adds nothing over the retracement, controls match it, sign "
           "inverts by side, and runner destruction is near-symmetric.",
    "Q13": "Abandonment of this axis. Do not train an ML recovery/failure model "
           "and do not build a price-only exit architecture on this state. Local "
           "post-confirmation retracement geometry does not carry terminal "
           "deterioration.",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=("all", *STAGES))
    ap.add_argument("--limit", type=int, default=None,
                    help="smoke-test trade cap; NEVER used for a reported result")
    a = ap.parse_args(argv)

    todo = STAGES if a.stage == "all" else (a.stage,)
    card = {"study": "post_confirm_retracement_recovery", "stages": {}}
    for s in todo:
        t0 = time.time()
        if s == "build":
            out = stage_build(a.limit)
        elif s == "descriptive":
            out = stage_descriptive()
        elif s == "economics":
            out = stage_economics()
        elif s == "diagnostics":
            out = stage_diagnostics()
        elif s == "validate":
            out = stage_validate()
        elif s == "summary":
            out = stage_summary()
        else:
            continue
        card["stages"][s] = {**out, "seconds": round(time.time() - t0, 1)}
        print(json.dumps({s: card["stages"][s]}), flush=True)

    print(json.dumps(card, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
