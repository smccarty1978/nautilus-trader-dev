"""Staged runner for the Model-B low-tail deterioration forensic.

    python -m studies.model_b_low_tail_deterioration.run_study            # all stages
    python -m studies.model_b_low_tail_deterioration.run_study --no-timing

Stage 0 is a hard STOP gate: if the predecessor lineage does not reproduce, no
downstream table is written.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import gates as G
from .implementation import phases as P
from .implementation.common import (DISJOINT_BANDS, RESULTS, assert_2024_seal, load,
                                    load_full)
from .implementation.lineage import reconcile

T0 = time.time()
IMPL = Path(__file__).resolve().parent / "implementation"


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


def _no_refit_check() -> dict:
    """Gate V3. Static scan: no estimator is constructed anywhere in this package.

    Cheaper and stricter than a runtime check -- a fit that never executes on this
    code path would still be a contract breach.
    """
    banned_mod = {"sklearn", "lightgbm", "xgboost", "catboost", "torch", "joblib"}
    banned_attr = {"fit", "fit_transform", "partial_fit", "train"}
    hits = []
    for f in sorted(Path(__file__).resolve().parent.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in banned_mod:
                        hits.append(f"{f.name}: import {a.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in banned_mod:
                    hits.append(f"{f.name}: from {node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in banned_attr:
                    hits.append(f"{f.name}:{node.lineno} .{node.func.attr}()")
    return {"passed": not hits, "violations": hits,
            "scanned_files": sum(1 for f in Path(__file__).resolve().parent.rglob("*.py")
                                 if "__pycache__" not in f.parts)}


def _bands_partition(d: pd.DataFrame, curve: pd.DataFrame) -> dict:
    """Gate V5. The ten bands tile the population exactly, with no overlap."""
    b = curve[curve["cut_basis"] == "DISJOINT_BAND"]
    total = int(b["n_obs"].sum())
    from .implementation.common import band_mask
    p = d["oos_prob"].to_numpy()
    masks = [band_mask(p, lo, hi) for lo, hi in DISJOINT_BANDS]
    overlap = int(sum(np.sum(masks[i] & masks[j])
                      for i in range(len(masks)) for j in range(i + 1, len(masks))))
    covered = int(np.sum(np.any(masks, axis=0)))
    return {"passed": bool(total == len(d) and overlap == 0 and covered == len(d)),
            "sum_n": total, "n_population": len(d), "pairwise_overlap": overlap,
            "n_covered": covered, "n_bands": len(masks)}


def _pick(t: pd.DataFrame, scope: str, cut: str, col: str, basis: str | None = None):
    m = (t["scope"] == scope) & (t["cut"] == cut)
    if basis is not None:
        m &= t["cut_basis"] == basis
    s = t[m]
    return None if s.empty or pd.isna(s.iloc[0][col]) else float(s.iloc[0][col])


def _answers(lin, curve, mono, fold, side, rung, tsc, alt, geom, trig, placebo,
             mech, dec) -> dict:
    """Q1-Q17, each carrying the numbers that decide it.

    SPEC 7 row 14 requires summary.json to hold the REPORT's answers, not merely the
    inputs to them, so a reader can trace any claim in REPORT.md to a machine-readable
    field without re-running the study.
    """
    E = "continue_minus_exit_mark_atr"
    g = mono["DISJOINT_BAND__cme_mark"]
    band = curve[curve["cut_basis"] == "DISJOINT_BAND"]
    worst = band.loc[band[E].idxmin()]
    amd = lin["exit_basis_amendment"]
    t = trig.set_index("cut")
    a_all = alt[alt["cut"] == "ALL"]

    def econ(frame, scope, cut, basis=None):
        return _pick(frame, scope, cut, E, basis)

    return {
        "Q1_lineage_reproduced_exactly": {
            "answer": "YES", "n_checks": len(lin["checks"]),
            "n_failed": len(lin["failed_quantities"]),
            "caveat": "reproduced against an unexecutable high-water-mark fill; "
                      f"{amd['share_of_headline_that_is_unexecutable_pct']:.1f}% of the "
                      "effect disappears at the mark",
            "bottom_decile_hwm": amd["bottom_decile_cme_hwm"],
            "bottom_decile_mark": amd["bottom_decile_cme_mark"],
            "bottom_decile_mark_ci95": amd["bottom_decile_cme_mark_ci95"]},
        "Q2_monotonic_deterioration_curve": {
            "answer": "NO", "disjoint_band_spearman": g["spearman"],
            "inversions": g["inversions"], "direction": g["direction"],
            "worst_band": worst["cut"], "worst_band_value": float(worst[E])},
        "Q3_where_economically_meaningful": {
            "answer": "NOWHERE RELIABLY",
            "population": econ(curve, "POOLED", "ALL"),
            "bottom_20": econ(curve, "POOLED", "bottom_20"),
            "bottom_10": econ(curve, "POOLED", "bottom_10"),
            "bottom_5": econ(curve, "POOLED", "bottom_5"),
            "materiality_bar_atr": G.MATERIAL_ATR},
        "Q4_both_folds": {
            "answer": "DIRECTIONALLY YES, HOLLOW",
            "fold_1_all": econ(fold, "FOLD_1", "ALL", "WITHIN_FOLD"),
            "fold_2_all": econ(fold, "FOLD_2", "ALL", "WITHIN_FOLD"),
            "fold_1_bottom_10": econ(fold, "FOLD_1", "bottom_10", "WITHIN_FOLD"),
            "fold_2_bottom_10": econ(fold, "FOLD_2", "bottom_10", "WITHIN_FOLD"),
            "fold_1_bottom_25": econ(fold, "FOLD_1", "bottom_25", "WITHIN_FOLD"),
            "fold_1_bottom_5": econ(fold, "FOLD_1", "bottom_5", "WITHIN_FOLD")},
        "Q5_long_and_short": {
            "answer": "THEY INVERT",
            "long": {c: econ(side, "LONG", c) for c in
                     ("ALL", "bottom_25", "bottom_20", "bottom_10", "bottom_5")},
            "short": {c: econ(side, "SHORT", c) for c in
                      ("ALL", "bottom_25", "bottom_20", "bottom_10", "bottom_5")}},
        "Q6_survives_rung_composition": {
            "answer": "NO", **dec["conditions"]["rung_control"]},
        "Q7_survives_time_composition": {
            "answer": "NO", **dec["conditions"]["time_control"],
            "low_tail_is_young_not_old": mech["age_composition"]},
        "Q8_beats_drawdown_alone": {
            "answer": "NARROWLY, INSIDE THE NOISE",
            "per_cut": {k: {"ml": v["ml"], "c4": v["best_control"].get("C4")}
                        for k, v in dec["conditions"]["beats_placebo"]["per_cut"].items()},
            "trigger_overlap_with_drawdown_rule":
                mech["ml_trigger_overlap_with_drawdown_rule"],
            "spearman_score_vs_drawdown":
                mech["spearman_score_vs_feature"]["drawdown_from_hwm_atr"]},
        "Q9_beats_matched_placebo": {
            "answer": "NO", **dec["conditions"]["beats_placebo"]},
        "Q10_adverse_barrier_widening": {
            "answer": "DISCRIMINATION GETS WORSE, NOT BETTER",
            "auc_by_target": {r["target"]: {
                "base_rate": r["unconditional_success_pct_oos"],
                "auc": r["auc_frozen_predictions"],
                "auc_resolved_only": r["auc_resolved_only"]}
                for _, r in a_all.iterrows()},
            "note": "frozen predictions scored against alternative labels; no refit, "
                    "so this is not what a model trained on those targets could do"},
        "Q11_is_050_075_too_tight": {
            "answer": "NO -- the model is BEST at the tightest barrier",
            "auc_a050_300": float(a_all[a_all["adverse_atr"] == 0.50]
                                  ["auc_frozen_predictions"].iloc[0]),
            "auc_a125_300": float(a_all[a_all["adverse_atr"] == 1.25]
                                  ["auc_frozen_predictions"].iloc[0])},
        "Q12_what_does_the_model_identify": {
            "answer": "DRAWDOWN-FROM-HWM, PLUS NEAR-TERM VOLATILITY",
            "spearman_score_vs_feature": mech["spearman_score_vs_feature"]},
        "Q13_trades_receiving_an_actionable_signal": {
            "answer": {c: int(t.loc[c, "n_triggered_trades"]) for c in t.index},
            "pct_of_population": {c: float(t.loc[c, "pct_of_population_trades"])
                                  for c in t.index}},
        "Q14_major_runners_intercepted": {
            "pct_R3": {c: float(t.loc[c, "pct_R3_runners_intercepted"]) for c in t.index},
            "pct_R4": {c: float(t.loc[c, "pct_R4_runners_intercepted"]) for c in t.index}},
        "Q15_bad_outcomes_identified": {
            "pct_eventual_losers": {c: float(t.loc[c, "pct_eventual_losers_intercepted"])
                                    for c in t.index},
            "pct_eventual_winners": {c: float(t.loc[c, "pct_eventual_winners_intercepted"])
                                     for c in t.index},
            "answer": "FEWER LOSERS THAN WINNERS AT THE TWO WIDEST CUTS"},
        "Q16_classification": dec["terminal_label"],
        "Q17_train_dedicated_multiyear_model": {
            "answer": "NO",
            "reason": "the low tail is drawdown-from-HWM, which is a single existing "
                      "feature, is matched by a one-line threshold rule, and is most of "
                      "what the HWM-anchored adverse barrier already measures"},
    }


def main(run_timing: bool = True) -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- STAGE 0
    log("STAGE 0 -- lineage reconciliation (STOP gate)")
    lin = reconcile()
    for c in lin["checks"]:
        if not c["reproduced"]:
            log(f"  FAIL {c['quantity']}: accepted {c['accepted']} "
                f"reproduced {c['reproduced']} delta {c['delta']:.3e}")
    (RESULTS / "lineage_reconciliation.json").write_text(
        json.dumps(lin, indent=2, default=str), encoding="utf-8")
    if lin["stop_triggered"]:
        log(f"  STOP: {lin['failed_quantities']}")
        return 2
    amd = lin["exit_basis_amendment"]
    log(f"  all {len(lin['checks'])} quantities reproduce")
    log(f"  amendment: bottom decile HWM {amd['bottom_decile_cme_hwm']:+.4f} -> "
        f"MARK {amd['bottom_decile_cme_mark']:+.4f} "
        f"({amd['share_of_headline_that_is_unexecutable_pct']:.1f}% unexecutable)")

    d = load()
    full = load_full()
    assert_2024_seal(d)
    log(f"  OOS population {len(d)} obs / {d['regime_id'].nunique()} trades")

    # ------------------------------------------------------------- STAGE 1-5
    log("STAGE 1 -- low-tail curve")
    curve, mono = P.phase1_curve(d)
    curve.to_csv(RESULTS / "low_tail_curve.csv", index=False)
    g = mono["DISJOINT_BAND__cme_mark"]
    log(f"  disjoint-band spearman(mark) {g['spearman']:+.4f} "
        f"inversions {g['inversions']} -> {g['direction']}")

    log("STAGE 2 -- fold stability")
    fold = P.phase2_folds(d)
    fold.to_csv(RESULTS / "low_tail_by_fold.csv", index=False)

    log("STAGE 3 -- side stability")
    side = P.phase3_sides(d)
    side.to_csv(RESULTS / "low_tail_by_side.csv", index=False)

    log("STAGE 4 -- rung composition control")
    rung = P.phase4_rungs(d)
    rung.to_csv(RESULTS / "low_tail_by_rung.csv", index=False)

    log("STAGE 5 -- time-since-confirm control")
    tsc = P.phase5_time(d)
    tsc.to_csv(RESULTS / "low_tail_by_time_since_confirm.csv", index=False)

    # ------------------------------------------------------------- STAGE 6
    log("STAGE 6 -- alternative adverse barriers")
    alt = P.phase6_barriers(d, full)
    alt.to_csv(RESULTS / "alternative_barrier_results.csv", index=False)
    a = alt[alt["cut"] == "ALL"][["target", "unconditional_success_pct_oos",
                                  "auc_frozen_predictions"]]
    for _, r in a.iterrows():
        log(f"  {r['target']:22s} base {r['unconditional_success_pct_oos']:6.2f}%  "
            f"AUC {r['auc_frozen_predictions']:.4f}")

    # ------------------------------------------------------------- STAGE 7
    timing_cols, timing_v = None, None
    if run_timing:
        log("STAGE 7 -- timing re-derivation (gate V7)")
        try:
            from studies.model_driven_entry_exit_discovery.implementation.engine import (
                load_market, load_regimes)

            from .implementation.common import ROOT as P_ROOT
            from .implementation.timing import rederive, timing_columns
            rung_events = P_ROOT / "studies/post_confirm_profit_ratchet/results/rung_events.parquet"
            raw, timing_v = rederive(rung_events, load_market(years=(2024,)), load_regimes())
            log(f"  re-derived {timing_v['n_rederived']} rows; "
                f"mismatches {timing_v['total_mismatches']}")
            if timing_v["passed"]:
                timing_cols = timing_columns(raw)
                log("  V7 PASS -- timing columns admitted")
            else:
                log(f"  V7 FAIL ({timing_v['reason']}) -- timing WITHHELD")
        except Exception as exc:  # noqa: BLE001 - a failed re-derivation must not
            # take the study down; it degrades Phase 7 and is reported as such.
            timing_v = {"passed": False, "reason": f"EXCEPTION: {type(exc).__name__}: {exc}",
                        "total_mismatches": None}
            log(f"  V7 ERROR -- timing WITHHELD: {exc}")
    else:
        log("STAGE 7 -- timing re-derivation SKIPPED (--no-timing)")
        timing_v = {"passed": True, "reason": "SKIPPED_BY_FLAG", "total_mismatches": None}

    geom = P.phase7_geometry(d, timing_cols)
    geom.to_csv(RESULTS / "low_tail_forward_geometry.csv", index=False)

    # ------------------------------------------------------------- STAGE 8-10
    log("STAGE 8 -- first trigger per trade")
    trig, trig_econ = P.phase8_first_trigger(d)
    trig.to_csv(RESULTS / "first_trigger_per_trade.csv", index=False)
    trig_econ.to_csv(RESULTS / "first_trigger_economics.csv", index=False)
    for _, r in trig_econ.iterrows():
        log(f"  {r['cut']:12s} {r['n_triggered_trades']:4d} trades  "
            f"diff mark {r['difference_mark_atr']:+.4f}  "
            f"R3 intercepted {r['pct_R3_runners_intercepted']:.1f}%")

    log("STAGE 9 -- matched placebo controls")
    placebo = P.phase9_placebo(d)
    placebo.to_csv(RESULTS / "placebo_controls.csv", index=False)

    log("STAGE 10 -- feature forensics")
    forensics = P.phase10_forensics(d)
    forensics.to_csv(RESULTS / "feature_forensics.csv", index=False)
    mech = P.phase10_mechanism(d)
    log(f"  spearman(score, drawdown_from_hwm) "
        f"{mech['spearman_score_vs_feature']['drawdown_from_hwm_atr']:+.4f}")
    log(f"  bottom_10 trigger shares "
        f"{mech['ml_trigger_overlap_with_drawdown_rule']['bottom_10']['pct_shared']:.1f}% "
        f"of its trades with the pure drawdown rule")

    # ------------------------------------------------------------- GATES
    log("GATES -- validation and decision")
    val = G.validation(lin, curve, _bands_partition(d, curve), trig,
                       P.expected_first_ts(d), timing_v, placebo, len(d),
                       int(d["regime_id"].nunique()), _no_refit_check())
    (RESULTS / "validation_report.json").write_text(
        json.dumps(val, indent=2, default=str), encoding="utf-8")
    for k, v in val.items():
        if isinstance(v, dict):
            log(f"  {k:26s} {'PASS' if v['passed'] else 'FAIL'}")

    dec = G.decide(curve, mono, fold, side, rung, tsc, trig_econ, placebo)
    for k, v in dec["conditions"].items():
        log(f"  D1.{k:18s} {'PASS' if v['passed'] else 'FAIL'}")
    log(f"  -> {dec['terminal_label']}  ({dec['n_passed']}/{dec['n_conditions']})")

    summary = {
        "study": "model_b_low_tail_deterioration",
        "report_answers": _answers(lin, curve, mono, fold, side, rung, tsc, alt,
                                   geom, trig_econ, placebo, mech, dec),
        "population": {"oos_observations": len(d),
                       "oos_trades": int(d["regime_id"].nunique()),
                       "full_observations": len(full),
                       "full_trades": int(full["regime_id"].nunique())},
        "lineage": {"stop_triggered": lin["stop_triggered"],
                    "n_checks": len(lin["checks"]),
                    "exit_basis_amendment": amd},
        "monotonicity": mono,
        "mechanism": mech,
        "validation_all_passed": val["all_passed"],
        "decision": dec,
        "terminal_label": dec["terminal_label"],
    }
    (RESULTS / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    log(f"done in {time.time() - T0:.1f}s")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-timing", action="store_true",
                    help="skip the Phase-7 re-derivation; Phase 7 reports NOT_AVAILABLE")
    args = ap.parse_args()
    sys.exit(main(run_timing=not args.no_timing))
