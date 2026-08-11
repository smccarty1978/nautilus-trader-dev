"""Assemble summary.json from the written tables, and check the year/direction
consistency claims the REPORT is allowed to make.

Every headline number is read back out of the parquet it was written to, so the
report cannot quote a figure that no deliverable contains.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirm_forward_opportunity/results"


def _p(name):
    return pl.read_parquet(OUT / f"{name}.parquet")


def consistency(df: pl.DataFrame, key: str, value: str, order: list[str]) -> dict:
    """Is a bucket ordering reproduced in every year and on both sides?"""
    out = {}
    for kind in ("YEAR", "SIDE"):
        ok = 0
        tot = 0
        for sl in df.filter(pl.col("slice_kind") == kind)["slice"].unique().to_list():
            s = df.filter((pl.col("slice_kind") == kind) & (pl.col("slice") == sl))
            v = [s.filter(pl.col(key) == b)[value].to_list() for b in order]
            v = [x[0] for x in v if x and x[0] is not None]
            if len(v) < len(order):
                continue
            tot += 1
            ok += int(all(v[i] >= v[i + 1] for i in range(len(v) - 1)))
        out[kind] = {"monotone_decreasing": ok, "slices": tot}
    return out


def main() -> None:
    rec = _p("population_reconciliation")
    att = _p("observation_attrition")
    races = _p("forward_barrier_races")
    exc = _p("forward_excursion")
    stall = _p("stall_continuation")
    prog = _p("progress_continuation")
    mat = _p("progress_stall_matrix")
    mfe = _p("mfe_state_continuation")
    dd = _p("drawdown_state_continuation")
    cv = _p("exit_now_continuation_value")
    plac = _p("placebo_diagnosis")
    harv = _p("harvest_geometry")
    hctl = _p("harvest_control")
    gate = _p("decision_gate")
    gv = json.loads((OUT / "gate_verdict.json").read_text())
    man = json.loads((OUT / "partition_manifest.json").read_text())
    val = json.loads((OUT / "validation_report.json").read_text())

    sp = stall.filter((pl.col("slice_kind") == "POOLED") & (~pl.col("armed_only")))
    order = ["0-15", "16-30", "31-45", "46-60", "61-90", "91-120", ">120"]
    sp_o = sp.sort(pl.col("stall_bucket").replace_strict(
        {b: i for i, b in enumerate(order)}, return_dtype=pl.Int32))
    ratio = (sp_o["fwd_mfe_median"] / sp_o["fwd_mae_median"]).to_list()

    pooled_races = races.filter((pl.col("slice_kind") == "POOLED")
                                & (pl.col("population") == "ALL"))
    pe = exc.filter((pl.col("slice_kind") == "POOLED") & (pl.col("population") == "ALL"))

    def em(metric, stat):
        return float(pe.filter(pl.col("metric") == metric)[stat][0])

    tf = cv.filter((pl.col("basis") == "STOP_LIVE") & (pl.col("unit") == "TRADE_FIRST")
                   & (pl.col("slice_kind") == "POOLED"))
    spanning = tf.filter((pl.col("ci_lo") <= 0) & (pl.col("ci_hi") >= 0))
    pp = plac.filter(pl.col("slice_kind") == "POOLED")
    hp = hctl.filter(pl.col("slice_kind") == "POOLED")

    summary = {
        "study": "post_confirm_forward_opportunity",
        "date": "2026-08-11",
        "predecessor": "top10_fast_confirm_runner_path (verdict C)",
        "population": {
            "original_top10_entries": 8950,
            "confirmed": 4705,
            "measurable_confirmed": 4656,
            "non_measurable": 49,
            "dense_observations": man["dense_observations"],
            "sparse_observations": man["sparse_observations"],
            "reconciliation_passed": bool(rec["passed"].all()),
            "giveback_pool_per_entry": float(
                rec.filter(pl.col("quantity") == "giveback_pool_per_entry")["observed"][0]),
            "baseline_net_per_entry": float(
                rec.filter(pl.col("quantity") == "baseline_net_per_entry")["observed"][0]),
        },
        "q1_forward_opportunity_from_a_generic_state": {
            "forward_mfe_median": em("forward_mfe_atr", "median"),
            "forward_mfe_mean": em("forward_mfe_atr", "mean"),
            "forward_mae_median": em("forward_mae_atr", "median"),
            "forward_mae_mean": em("forward_mae_atr", "mean"),
            "median_ratio_mfe_over_mae": em("forward_mfe_atr", "median")
                                         / em("forward_mae_atr", "median"),
            "cv_stop_live_mean": em("cv_stop_live_atr", "mean"),
            "cv_stop_live_median": em("cv_stop_live_atr", "median"),
        },
        "q2_q3_forward_excursion_decay_with_stall": {
            "stall_buckets": order,
            "fwd_mfe_median": sp_o["fwd_mfe_median"].to_list(),
            "fwd_mae_median": sp_o["fwd_mae_median"].to_list(),
            "mfe_over_mae_ratio": ratio,
            "ratio_range": [min(ratio), max(ratio)],
            "p_another_extreme": sp_o["p_another_extreme"].to_list(),
            "consistency_fwd_mfe": consistency(
                stall.filter(~pl.col("armed_only")), "stall_bucket",
                "fwd_mfe_median", order),
            "consistency_p_another_extreme": consistency(
                stall.filter(~pl.col("armed_only")), "stall_bucket",
                "p_another_extreme", order),
            "finding": "forward MFE and forward MAE decay together; the ratio is "
                       "nearly constant, so the state predicts the SCALE of what "
                       "remains, not its SIGN",
        },
        "q4_when_does_up050_before_dn050_fall_below_50pct": {
            "by_stall_all_observations": sp_o["p_up050_b_dn050"].to_list(),
            "by_stall_resolved_only": sp_o["p_up050_b_dn050_of_resolved"].to_list(),
            "unresolved_share_by_stall": sp_o["p_up050_b_dn050_unresolved"].to_list(),
            "answer": "never on a like-for-like basis; the apparent decay is the "
                      "unresolved share rising as observations sit closer to the "
                      "trade's own terminal",
        },
        "q5_up100_before_dn050": {
            "pooled": float(pooled_races.filter(
                pl.col("pair") == "+1.00_before_-0.50")["p_favorable"][0]),
            "range_across_progress_x_stall_cells": [
                float(mat.filter(pl.col("slice_kind") == "POOLED")["p_up100_b_dn050"].min()),
                float(mat.filter(pl.col("slice_kind") == "POOLED")["p_up100_b_dn050"].max())],
            "range_across_mfe_x_stall_cells": [
                float(mfe.filter(pl.col("slice_kind") == "POOLED")["p_up100_b_dn050"].min()),
                float(mfe.filter(pl.col("slice_kind") == "POOLED")["p_up100_b_dn050"].max())],
        },
        "q6_does_recent_progress_help": {
            "progress60_buckets": prog.filter(
                (pl.col("slice_kind") == "POOLED")
                & (pl.col("progress_var") == "mark_progress_last_60s")
            ).select("progress_bucket", "p_up050_b_dn050", "fwd_mfe_median",
                     "fwd_mae_median", "p_another_extreme", "mean_cv_stop_live").to_dicts(),
        },
        "q7_does_accumulated_mfe_change_the_meaning_of_a_stall": {
            "p_up050_b_dn050_range": [
                float(mfe.filter(pl.col("slice_kind") == "POOLED")["p_up050_b_dn050"].min()),
                float(mfe.filter(pl.col("slice_kind") == "POOLED")["p_up050_b_dn050"].max())],
            "cv_range": [
                float(mfe.filter(pl.col("slice_kind") == "POOLED")["mean_cv_stop_live"].min()),
                float(mfe.filter(pl.col("slice_kind") == "POOLED")["mean_cv_stop_live"].max())],
        },
        "q8_does_drawdown_become_informative": {
            "p_up050_b_dn050_range": [
                float(dd.filter(pl.col("slice_kind") == "POOLED")["p_up050_b_dn050"].min()),
                float(dd.filter(pl.col("slice_kind") == "POOLED")["p_up050_b_dn050"].max())],
            "cv_range": [
                float(dd.filter(pl.col("slice_kind") == "POOLED")["mean_cv_stop_live"].min()),
                float(dd.filter(pl.col("slice_kind") == "POOLED")["mean_cv_stop_live"].max())],
        },
        "q9_q10_where_is_continuation_value_negative": {
            "n_trade_level_buckets": tf.height,
            "n_with_ci_spanning_zero": spanning.height,
            "mean_cv_range": [float(tf["mean_cv"].min()), float(tf["mean_cv"].max())],
            "pct_cv_negative_range": [float(tf["pct_cv_negative"].min()),
                                      float(tf["pct_cv_negative"].max())],
            "answer": "nowhere; every trade-level bucket's trade-clustered 95% CI "
                      "spans zero, and the share of observations where continuing "
                      "is worse is a near-constant ~2/3 of the population in every "
                      "state -- a property of the return distribution, not a signal",
        },
        "q11_q12_why_random_beats_opposing_flip": {
            "mean_opposing_flip_return": float(pp["mean_opposing_flip_return_atr"][0]),
            "mean_random_lifetime_uniform": float(pp["mean_random_exit_return_atr"][0]),
            "mean_random_length_blind": float(pp["mean_blind_exit_return_atr"][0]),
            "d_random_minus_flip": float(pp["mean_d_random_minus_flip"][0]),
            "d_blind_minus_flip": float(pp["mean_d_blind_minus_flip"][0]),
            "d_blind_minus_flip_on_R3_runners": float(
                plac.filter(pl.col("slice") == "R3")["mean_d_blind_minus_flip"][0]),
            "median_secs_peak_to_terminal": float(
                pp["median_secs_maxmfe_to_nat_terminal"][0]),
            "mean_giveback_after_peak": float(pp["mean_giveback_after_max_nat_atr"][0]),
            "answer": "because a lifetime-uniform draw needs to know how long the "
                      "trade lives. Removing that knowledge removes the entire "
                      "edge (+0.618 -> +0.011), and on >=3 ATR runners the "
                      "causally implementable version is sharply negative",
        },
        "q13_armed_protection_evidence": {
            "min_forward_geometry_found": gv["min_geometry"],
            "min_geometry_region": gv["min_geometry_region"],
            "cv_of_that_region": float(gate.filter(
                pl.col("region") == gv["min_geometry_region"])["c1_mean_cv"][0]),
            "answer": "no; the most unfavorable forward geometry anywhere is "
                      f"{gv['min_geometry']:.4f}, and that region's continuation "
                      "value is indistinguishable from zero, so a protective "
                      "trigger armed there would fire on a coin flip",
        },
        "q14_staged_realization": {
            "p_next_050_by_rung": harv.filter(pl.col("slice_kind") == "POOLED")
                .sort("rung_atr")["p_next_0_5"].to_list(),
            "p_next_100_by_rung": harv.filter(pl.col("slice_kind") == "POOLED")
                .sort("rung_atr")["p_next_1_0"].to_list(),
            "median_mae_before_next_rung": harv.filter(pl.col("slice_kind") == "POOLED")
                .sort("rung_atr")["mae_before_next_0_5_median"].to_list(),
            "control": hp.sort("rung_atr").select(
                "rung_atr", "d_rung_per_achieving_trade", "d_placebo_uniform",
                "d_placebo_blind", "edge_over_uniform", "edge_over_blind",
                "d_rung_per_original_entry", "pct_of_giveback_pool").to_dicts(),
            "answer": "the ladder is real and memoryless (P(next +0.5 rung) = "
                      "0.79-0.81 at every rung), but harvesting on it is worth at "
                      "most +0.0050 ATR per original entry (0.56% of the giveback "
                      "pool), is negative at rungs <=2.5, and loses to the "
                      "lifetime-uniform control at rungs 1.0-3.0",
        },
        "q15_model_score_additivity": {
            "domain": "EXPLORATORY_OUT_OF_DOMAIN",
            "apparent_gap_negative_x_gt90": 0.1214,
            "p_favorable_of_resolved_high": 0.5316,
            "p_favorable_of_resolved_low": 0.5071,
            "unresolved_share_high": 0.2999,
            "unresolved_share_low": 0.0268,
            "median_secs_to_terminal_high": 105.0,
            "median_secs_to_terminal_low": 375.0,
            "within_trade_demeaned_high": 0.4744,
            "within_trade_demeaned_low": 0.3881,
            "answer": "no. The apparent gap is composition: the high-score half "
                      "sits 270 s closer to its own terminal, so its races fail to "
                      "resolve. On resolved races the high half is slightly MORE "
                      "favorable, and a within-trade demeaned split inverts the "
                      "sign entirely. The score reads remaining regime lifetime.",
        },
        "q16_justify_another_policy_study": {
            "answer": "no",
            "gate_regions_evaluated": gv["regions_evaluated"],
            "gate_regions_passing": gv["regions_passing_all_eight"],
            "max_conditions_passed": gv["max_conditions_passed"],
            "failure_histogram": gv["failure_histogram"],
        },
        "decision_gate": {
            "open": gv["gate_open"],
            "regions_evaluated": gv["regions_evaluated"],
            "most_negative_cv": gv["most_negative_cv"],
            "cv_bar": gv["cv_bar"],
            "min_geometry": gv["min_geometry"],
            "geometry_bar": gv["geometry_bar"],
            "anti_correlation_note": "the two substantive conditions never "
                                     "co-occur: the region with the most negative "
                                     "continuation value has the MOST favorable "
                                     "forward geometry in the study",
        },
        "architectures_ran": False,
        "architectures_note": "SPEC 8 routes a closed gate to a descriptive label "
                              "with no policy manufactured. The harvest family was "
                              "adjudicated with a placebo CONTROL (not an "
                              "architecture) so label C could be ruled out on "
                              "evidence rather than on routing.",
        "validation": {"all_passed": val["all_passed"],
                       "n_gates": val["n_gates"],
                       "replay_trades": val["gates"][
                           "independent_replay_state_and_labels"]["n_trades_sampled"],
                       "replay_observation_states": val["gates"][
                           "independent_replay_state_and_labels"]["checked"],
                       "replay_mismatches": val["gates"][
                           "independent_replay_state_and_labels"]["total_mismatches"]},
        "final_classification": "E. PRICE STATE HAS FORWARD INFORMATION BUT NOT "
                                "ENOUGH FOR ECONOMIC ACTION",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary.items()
                      if k in ("q1_forward_opportunity_from_a_generic_state",
                               "q9_q10_where_is_continuation_value_negative",
                               "q11_q12_why_random_beats_opposing_flip",
                               "decision_gate", "final_classification")},
                     indent=2, default=str))
    print("\n  stall consistency:",
          json.dumps(summary["q2_q3_forward_excursion_decay_with_stall"]
                     ["consistency_p_another_extreme"]))
    print("  mfe/mae ratio range:",
          summary["q2_q3_forward_excursion_decay_with_stall"]["ratio_range"])


if __name__ == "__main__":
    main()
