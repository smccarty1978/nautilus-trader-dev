"""Gates V1-V14 and the computed verdict.

The verdict is **computed from the gate table**, never asserted in prose, and an
unrun gate is a FAILURE rather than a pass. This is the pattern the canonical
store established: `determine_verdict` accepts only when every required
condition holds simultaneously.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.p90_5s_regime_impulse.implementation.policy import OUTCOMES

ARMED_REQUIRED = 8950
SEALED_YEAR = 2026


def _gate(name: str, expected, observed, ok: bool, note: str = "") -> dict:
    return {"gate": name, "expected": expected, "observed": observed,
            "pass": bool(ok), "note": note}


def run_gates(*, arms: pl.DataFrame, walks_s1: pl.DataFrame,
              walks_s075: pl.DataFrame, walks_placebo: pl.DataFrame,
              lineage: dict, r5_meta: dict, align: pl.DataFrame) -> list[dict]:
    g: list[dict] = []

    g.append(_gate("V1_armed_population", ARMED_REQUIRED, arms.height,
                   arms.height == ARMED_REQUIRED,
                   "the frozen Top-10 arm population, consumed not rebuilt"))

    g.append(_gate("V2_lineage_targets_reproduced", True,
                   lineage["all_targets_reproduced"],
                   bool(lineage["all_targets_reproduced"]),
                   "SPEC 2.2; a miss is an ABORT, not a caveat"))

    g.append(_gate("V3_5s_grid_reconciles",
                   {"buckets": True, "rows": True},
                   {"buckets": r5_meta["buckets_reconcile"],
                    "rows": r5_meta["rows_reconcile"]},
                   bool(r5_meta["buckets_reconcile"] and r5_meta["rows_reconcile"]),
                   "every 1s path row absorbed; bucket count == distinct 5s slots"))

    # V4: the arm grid and the 5s bucket grid are the same clock grid, so the
    # bucket closing exactly at the arm is complete and legally readable.
    off_grid = int((arms["arm_top10_ns"].to_numpy() % 5_000_000_000 != 0).sum())
    g.append(_gate("V4_arms_on_5s_clock_grid", 0, off_grid, off_grid == 0,
                   "SPEC 3.3; if false the availability argument collapses"))

    for name, w in (("S1", walks_s1), ("S075", walks_s075),
                    ("PLACEBO_EXIT", walks_placebo)):
        e = w.filter(pl.col("entered") & pl.col("gross_atr").is_finite())

        # V5: no entry fills at or before its own decision timestamp.
        bad = int((e["entry_ns"].to_numpy() <= e["arm_ns"].to_numpy()).sum())
        g.append(_gate(f"V5_{name}_entry_after_decision", 0, bad, bad == 0,
                       "entry fill must be the open of a bar strictly after the arm"))

        # V6: no exit fills at or before the signal that caused it.
        flip = e["five_s_flip_ns"].to_numpy().astype("float64")
        ex = e["exit_ns"].to_numpy().astype("float64")
        has = np.isfinite(flip)
        five = (e["outcome"] == "FIVE_S_EXIT").to_numpy()
        bad6 = int((has & five & (ex <= flip)).sum())
        g.append(_gate(f"V6_{name}_exit_after_signal", 0, bad6, bad6 == 0,
                       "5s exit fills strictly after the flip bucket's close_ts"))

        # V7: confirmation never became a management term.
        labels = set(e["outcome"].unique().to_list())
        g.append(_gate(f"V7_{name}_outcome_set", sorted(OUTCOMES), sorted(labels),
                       labels <= OUTCOMES,
                       "SPEC 8.5; any other label means confirmation leaked in"))

        # V8: the denominator never shrinks.
        g.append(_gate(f"V8_{name}_denominator", ARMED_REQUIRED, w.height,
                       w.height == ARMED_REQUIRED,
                       "non-entered arms are retained, not filtered away"))

        # V11: every entered trade terminated.
        g.append(_gate(f"V11_{name}_no_open_trades", 0,
                       int(e["exit_ns"].is_null().sum()),
                       int(e["exit_ns"].is_null().sum()) == 0))

        # V12: hold is always at least the 5s the grid guarantees.
        neg = int((e["hold_s"].to_numpy() <= 0).sum())
        g.append(_gate(f"V12_{name}_positive_hold", 0, neg, neg == 0))

    # V9: entry eligibility depends only on the arm and the 5s state, never on a
    # future confirmation label. Proven by construction AND checked: the entered
    # set must be exactly the ALIGNED set, independent of outcome.
    aligned_ids = set(walks_s1.filter(pl.col("alignment") == "ALIGNED")["regime_id"].to_list())
    entered_ids = set(walks_s1.filter(pl.col("entered"))["regime_id"].to_list())
    extra = entered_ids - aligned_ids
    g.append(_gate("V9_entry_set_is_alignment_only", 0, len(extra), len(extra) == 0,
                   "entered set == ALIGNED set minus no-fill-bar censoring"))

    # V10: 2026 sealed.
    years = sorted(int(y) for y in arms["entry_year"].unique().to_list())
    g.append(_gate("V10_2026_sealed", "max <= 2025", max(years),
                   max(years) < SEALED_YEAR, "the sealed year is never read"))

    # V13: alignment classes partition the arm population exactly once.
    row = align.filter(pl.col("group") == "ALL").to_dicts()[0]
    total = row["n_aligned"] + row["n_opposite"] + row["n_uninit"]
    g.append(_gate("V13_alignment_partitions_arms", ARMED_REQUIRED, total,
                   total == ARMED_REQUIRED))

    # V14: S1 and S075 differ ONLY by the stop, so they must share their entries.
    e1 = set(walks_s1.filter(pl.col("entered"))["regime_id"].to_list())
    e2 = set(walks_s075.filter(pl.col("entered"))["regime_id"].to_list())
    g.append(_gate("V14_stop_variants_share_entries", 0, len(e1 ^ e2), e1 == e2,
                   "a stop distance may not change who is eligible to enter"))
    return g


def determine_verdict(*, gates: list[dict], e_a: dict, e_s1: dict, e_s075: dict,
                      e_plac: dict, placebo_ci: dict, preservation: pl.DataFrame,
                      failure: pl.DataFrame, by_year: pl.DataFrame,
                      by_side: pl.DataFrame, nonentry: pl.DataFrame) -> dict:
    """SPEC 6.1. Computed, not asserted. An unrun gate is a failure."""
    if not gates or not all(x["pass"] for x in gates):
        return {"verdict": "ABORT_LINEAGE_FAILURE",
                "reason": "one or more validation gates failed",
                "failed_gates": [x["gate"] for x in gates if not x["pass"]]}

    best = max((e_s1, e_s075), key=lambda e: e["exp_per_arm_net"])
    name = "S1" if best is e_s1 else "S075"

    beats_a = best["exp_per_arm_net"] > e_a["net_atr_per_arm"]
    positive = best["exp_per_arm_net"] > 0
    beats_placebo = bool(placebo_ci.get("s1_minus_placebo_ci_excludes_zero", False))

    yr = by_year.filter(pl.col("policy") == name)
    years_positive = int((yr["exp_per_arm_net"] > 0).sum())
    sd = by_side.filter(pl.col("policy") == name)
    side_vals = sd["exp_per_arm_net"].to_list()
    no_inversion = len(side_vals) == 2 and (side_vals[0] > 0) == (side_vals[1] > 0)

    frow = failure.filter(pl.col("policy") == name).to_dicts()[0]
    accepted_fail = frow["accepted_net_atr_per_failure_arm"]
    failure_cheaper = frow["net_atr_per_failure_arm"] > accepted_fail
    failure_materially_cheaper = (
        frow["net_atr_per_failure_arm"] - accepted_fail) > 0.10

    prow = preservation.filter(pl.col("policy") == name).to_dicts()[0]
    preservation_ok = prow["pct_5s_exit_before_confirm"] < 0.50

    facts = {
        "best_variant": name,
        "exp_per_arm_net": best["exp_per_arm_net"],
        "benchmark_a_per_arm_net": e_a["net_atr_per_arm"],
        "beats_benchmark_a": bool(beats_a),
        "positive_after_cost": bool(positive),
        "separates_from_placebo_exit": beats_placebo,
        "years_positive": years_positive,
        "no_side_inversion": bool(no_inversion),
        "failure_cost_cheaper": bool(failure_cheaper),
        "failure_cost_materially_cheaper": bool(failure_materially_cheaper),
        "pct_confirmers_cut_before_confirm": prow["pct_5s_exit_before_confirm"],
        "confirmer_preservation_ok": bool(preservation_ok),
        "entry_coverage": best["entry_coverage"],
    }

    if (beats_a and positive and beats_placebo and years_positive >= 4
            and no_inversion and failure_materially_cheaper):
        verdict = "F1_STRONG_5S_IMPULSE_EDGE"
    elif failure_materially_cheaper and preservation_ok and not (beats_a and positive):
        verdict = "F3_5S_USEFUL_ONLY_AS_LOSS_CONTROL"
    elif (placebo_ci.get("aligned_beats_entry_placebo_band", False)
          and not (beats_a and positive)
          and float(nonentry.filter(pl.col("bucket") != "never")["pct"].sum()) > 0.50):
        verdict = "F2_PROMISING_ENTRY_TIMING_NEEDS_WORK"
    else:
        verdict = "F4_NO_USEFUL_5S_EDGE"
    return {"verdict": verdict, "facts": facts}
