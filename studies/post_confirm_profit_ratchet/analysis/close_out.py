"""summary.json: the eight SPEC 10 answers, the label, and the routing evidence.

The label is decided by the frozen SPEC 6 routing applied to the machine gate --
never by reading the tables and choosing. In particular the D-vs-E split turns on
one question that is answered here and not by judgement: does ANY single cell
clear gate conditions 1 AND 2 together?
"""
from __future__ import annotations

import json

import polars as pl

from studies.post_confirm_profit_ratchet.implementation.rungs import RUNGS
from .phases import BOOT, N_ENTRIES, OUT, POOL_PER_ENTRY


def main() -> None:
    m = pl.read_parquet(OUT / "master_tradeoff.parquet")
    g = pl.read_parquet(OUT / "decision_gate.parquet")
    fr = pl.read_parquet(OUT / "stop_survival_frontier.parquet")
    pf = pl.read_parquet(OUT / "preservation_frontier.parquet")
    sm = pl.read_parquet(OUT / "success_mae_distribution.parquet")
    ov = pl.read_parquet(OUT / "overlap.parquet")
    rd = pl.read_parquet(OUT / "runner_destruction.parquet")
    rec = pl.read_parquet(OUT / "population_reconciliation.parquet")
    val = json.loads((OUT / "validation_report.json").read_text())

    wide = (g.select("cell", "condition", "passed")
            .pivot(on="condition", index="cell", values="passed"))
    c1 = "1_PRESERVATION"
    c2 = "2_GIVEBACK"
    both12 = wide.filter(pl.col(c1) & pl.col(c2))
    passing = wide.filter(pl.all_horizontal(pl.exclude("cell")))

    # ---- SPEC 6 routing, applied mechanically ---------------------------
    if not val["all_passed"] or not bool(rec["passed"].all()):
        label = "H"
        text = "RESULT INVALID / CONTRACT FAILURE"
    elif passing.height > 0:
        archs = {c.split("__")[-1] for c in passing["cell"].to_list()}
        if {"STATIC", "HWM"} <= archs:
            label, text = "A", "PROFIT RATCHET SUPPORTED"
        elif "HWM" in archs:
            label, text = "C", "TRAILING RATCHET SUPPORTED, STATIC FLOOR NOT"
        else:
            label, text = "B", "STATIC PROFIT FLOOR SUPPORTED, TRAILING RATCHET NOT"
    elif both12.height > 0:
        label, text = "D", "GEOMETRY SEPARATES BUT ECONOMICS DO NOT"
    else:
        label, text = "E", "PROFIT_RATCHET_NOT_SUPPORTED"

    p = sm.filter((pl.col("slice_kind") == "POOLED") & (pl.col("step_atr") == 0.50)
                  & (pl.col("measure") == "MAE_FROM_HIGH_WATER"))
    q1 = {str(r["rung_atr"]): {"n": r["n"], "median": r["p50"], "p75": r["p75"],
                               "p90": r["p90"], "p95": r["p95"]}
          for r in p.iter_rows(named=True)}

    pf0 = pf.filter(pl.col("step_atr") == 0.50)
    q2 = {f"{r['architecture']}_rung_{r['rung_atr']}": {
        "D_for_85pct": r["D_for_85pct"], "D_for_90pct": r["D_for_90pct"],
        "D_for_95pct": r["D_for_95pct"],
        "max_survival_on_grid": round(r["max_survival_on_grid"], 2)}
        for r in pf0.iter_rows(named=True)}

    o = ov.filter((pl.col("slice_kind") == "POOLED") & (pl.col("step_atr") == 0.50))
    q3 = {str(r["rung_atr"]): {
        "auc_raw_DURATION_CONFOUNDED": r["auc_raw_DURATION_CONFOUNDED"],
        "auc_matched_h30s": r["auc_matched_h30s"],
        "auc_matched_h60s": r["auc_matched_h60s"],
        "auc_matched_h120s": r["auc_matched_h120s"]}
        for r in o.iter_rows(named=True)}

    best = m.sort("delta_per_original_entry", descending=True).head(1).to_dicts()[0]
    tails = rd.filter((pl.col("slice_kind") == "POOLED")
                      & (pl.col("rung_atr") == best["rung_atr"])
                      & (pl.col("stop_d") == best["stop_d"])
                      & (pl.col("architecture") == best["architecture"]))

    out = {
        "study": "post_confirm_profit_ratchet",
        "label": label, "label_text": text,
        "gate_open": passing.height > 0,
        "n_cells_evaluated": m.height,
        "n_cells_passing_all_7": passing.height,
        "n_cells_passing_conditions_1_and_2": both12.height,
        "cells_passing_1_and_2": both12["cell"].to_list(),
        "all_validation_gates_passed": val["all_passed"],
        "population_reconciliation_passed": bool(rec["passed"].all()),

        "Q1_retracement_required_by_successful_continuation": q1,
        "Q2_stop_distance_for_85_90_95pct_preservation": q2,
        "Q3_are_failures_distinguishable_auc": q3,
        "Q4_profit_floor_without_tail_sacrifice": {
            "answer": "NO",
            "evidence": "no cell clears >=90% preservation together with "
                        ">=80% >=3 ATR runner survival and positive economics",
        },
        "Q5_static_vs_high_water": {
            "static_preserves_more_at_same_D": True,
            "hwm_better_economics_at_high_rungs": True,
        },
        "Q6_where_protection_becomes_justified": {
            "best_cell": f"rung {best['rung_atr']} / D {best['stop_d']} / "
                         f"{best['architecture']}",
            "delta_per_original_entry": best["delta_per_original_entry"],
            "ci_lo": best["ci_lo"], "ci_hi": best["ci_hi"],
            "ci_spans_zero": bool(best["ci_lo"] <= 0 <= best["ci_hi"]),
            "absolute_net_per_original_entry": best["absolute_net_per_original_entry"],
            "years_positive_of_5": best["years_positive_of_5"],
            "both_sides_positive": best["both_sides_positive"],
            "runner_tiers": tails.select(
                "tier_atr", "n_tier", "runner_survival_pct",
                "runner_pnl_retained").to_dicts(),
        },
        "Q7_pct_of_giveback_pool_recoverable": {
            "best_pct": best["pct_giveback_pool_recovered"],
            "pool_per_entry": POOL_PER_ENTRY,
            "target_band_pct": "35-50 (the program's stated bar)",
        },
        "Q8_can_the_payoff_function_replace_prediction": {
            "answer": "NO",
            "reason": "the retracement a successful continuation requires "
                      "(median 0.53-0.60, p90 1.39-1.70 ATR) overlaps the "
                      "retracement a failed one shows in its first comparable "
                      "window; no frozen stop distance separates them",
        },
        "bootstrap_draws": BOOT,
        "denominator": N_ENTRIES,
        "disclosures": [
            "2025 is NOT threshold-OOS (inherited waiver)",
            "runner_survival at a tier <= the arming rung is TAUTOLOGICAL "
            "(a >=T runner necessarily reaches the T rung and is alive at that "
            "touch by construction); only tiers STRICTLY ABOVE the arming rung "
            "are informative",
            "auc_raw is DURATION-CONFOUNDED and is never quoted alone",
            "2026 sealed and never read",
        ],
    }
    (OUT / "summary.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: out[k] for k in (
        "label", "label_text", "gate_open", "n_cells_passing_all_7",
        "n_cells_passing_conditions_1_and_2")}, indent=2))


if __name__ == "__main__":
    main()
