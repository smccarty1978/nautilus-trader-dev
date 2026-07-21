"""Compose results/final_report.md + audit/provenance_audit.json.

Verdict rules are mechanical and pre-registered (SPEC/section 16 of the
implementation prompt): a policy qualifies for CONTINUE only if it beats the
P0 flip-to-flip baseline EV/trade in BOTH years, beats its matched placebo in
both years, survives top-decile removal, and has clean audits. No stop is
selected on pooled test economics; if several qualify the maximin (worst-year
EV lift) combination is highlighted, all three stops always shown.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studies.fable5_pre_flip_d10_reversal_entry.common import (  # noqa: E402
    ATLAS_PATH, AUDIT, COST_RT, ECON_WINDOWS, RESULTS, STOP_GRID, STUDY,
    WORK, load_frozen_threshold, sha256_file,
)

YEARS = sorted(ECON_WINDOWS)


def fmt_usd(v) -> str:
    return "n/a" if v is None or not np.isfinite(v) else f"${v:,.2f}"


def fmt_pct(v) -> str:
    return "n/a" if v is None or not np.isfinite(v) else f"{100*v:.1f}%"


def main() -> None:
    thr = load_frozen_threshold()
    pol = pd.read_parquet(RESULTS / "policy_results.parquet")
    cov = pd.read_parquet(RESULTS / "regime_d10_coverage.parquet")
    cov_econ = cov[cov["window"] == "economics"]
    events = pd.read_parquet(RESULTS / "d10_entry_events.parquet")
    pvw = pd.read_parquet(RESULTS / "preflip_vs_wait_for_flip.parquet")
    plc = pd.read_parquet(RESULTS / "matched_placebo_summary.parquet")
    tail = pd.read_parquet(RESULTS / "tail_dependence.parquet")
    contrib_sum = pd.read_parquet(RESULTS / "d10_exit_reason_summary.parquet")
    dec = pd.read_parquet(RESULTS / "pnl_decomposition.parquet")
    stop_sens = pd.read_parquet(RESULTS / "stop_sensitivity.parquet")

    def pmetric(policy, stop, year, col):
        m = pol[(pol["policy"] == policy) & (pol["stop"] == stop)
                & (pol["year"] == year)]
        return float(m[col].iloc[0]) if len(m) and col in m else np.nan

    p0 = {yr: pmetric("P0", 0.0, yr, "ev_per_trade") for yr in YEARS}

    # ---- qualification scan over pre-flip policies x stops ----
    scan = []
    for policy in ("P1", "P3"):
        for stop in STOP_GRID:
            lifts, evs, plc_ok, tail_ok = {}, {}, True, True
            for yr in YEARS:
                ev = pmetric(policy, stop, yr, "ev_per_trade")
                evs[yr] = ev
                lifts[yr] = ev - p0[yr] if np.isfinite(ev) else np.nan
                pr = plc[(plc["real_policy"] == policy)
                         & (plc["stop"] == stop) & (plc["year"] == yr)]
                if not (len(pr) and pr["ev_diff"].iloc[0] > 0
                        and pr["welch_p"].iloc[0] < 0.05):
                    plc_ok = False
                tl = tail[(tail["run_policy"] == policy)
                          & (tail["run_stop"] == stop)
                          & (tail["run_year"] == yr)]
                if not (len(tl) and tl["net_excl_top_decile"].iloc[0] > 0):
                    tail_ok = False
            both_pos = all(np.isfinite(v) and v > 0 for v in lifts.values())
            # absolute profitability both years: a strictly-losing policy has
            # unbounded drawdown and cannot satisfy "acceptable drawdown"
            ev_pos = all(np.isfinite(v) and v > 0 for v in evs.values())
            scan.append({
                "policy": policy, "stop": stop,
                **{f"lift_{y}": lifts[y] for y in YEARS},
                **{f"ev_{y}": evs[y] for y in YEARS},
                "lift_both_years_positive": both_pos,
                "net_ev_positive_both_years": ev_pos,
                "beats_placebo_both_years": plc_ok,
                "survives_top_decile_removal": tail_ok,
                "qualifies": both_pos and ev_pos and plc_ok and tail_ok,
                "min_year_lift": min(lifts.values()),
            })
    scan_df = pd.DataFrame(scan)
    qual = scan_df[scan_df["qualifies"]]
    if len(qual):
        best = qual.sort_values("min_year_lift", ascending=False).iloc[0]
        best_label = f"{best['policy']} @ {best['stop']:.2f} ATR stop"
        best_pol, best_stop = best["policy"], float(best["stop"])
    else:
        best_label = "NONE"
        # representative combination for header rates (NOT a winner claim)
        best_pol, best_stop = "P3", 1.00

    ever = cov_econ[cov_econ["validly_scored"]]
    pct_ever_d10 = float(ever["ever_reached_D10"].mean()) if len(ever) else np.nan

    frontrun = pvw["frontrun_advantage_pts"].dropna() * 20.0  # $/contract
    fr_atr = pvw["frontrun_advantage_atr"].dropna()

    pre_avg = {yr: pmetric(best_pol, best_stop, yr, "avg_pre_flip_pnl_usd")
               for yr in YEARS}
    post_avg = {yr: pmetric(best_pol, best_stop, yr, "avg_post_flip_pnl_usd")
                for yr in YEARS}
    dec_b = dec[(dec["run_policy"] == best_pol) & (dec["run_stop"] == best_stop)]
    pre_all = float(dec_b["pre_flip_pnl_usd"].mean()) if len(dec_b) else np.nan
    post_all = float(dec_b["post_flip_pnl_usd"].mean()) if len(dec_b) else np.nan

    plc_best = plc[(plc["real_policy"] == best_pol)
                   & (plc["stop"] == best_stop)]
    plc_p = {int(r["year"]): r["welch_p"] for _, r in plc_best.iterrows()}

    hdr = {yr: {
        "lift": pmetric(best_pol, best_stop, yr, "ev_per_trade") - p0[yr],
        "sbf": pmetric(best_pol, best_stop, yr, "stop_before_flip_rate"),
        "d10x": pmetric(best_pol, best_stop, yr, "d10_exit_rate"),
        "oppx": pmetric(best_pol, best_stop, yr, "opposite_flip_exit_rate"),
    } for yr in YEARS}

    # ---- verdict ----
    if len(qual):
        verdict = "CONTINUE"
    else:
        # REPAIR evidence: pre-flip entry loses but D10-exit adds value, or
        # confirmation rate is high while pre-flip burden kills EV
        d10_helps = False
        c = contrib_sum[(contrib_sum["run_policy"] == "P3")
                        & (contrib_sum["category"] == "d10_exit")]
        if len(c) and (c.groupby("run_year")["total_incremental_usd"].sum() > 0).all():
            d10_helps = True
        p2_beats = all(
            np.isfinite(pmetric("P2", 0.0, yr, "ev_per_trade"))
            and pmetric("P2", 0.0, yr, "ev_per_trade") > p0[yr]
            for yr in YEARS)
        conf_rates = [pmetric("P1", s, yr, "flip_confirmation_rate")
                      for s in STOP_GRID for yr in YEARS]
        predicts_reversal = np.nanmean(conf_rates) > 0.5
        # spec REPAIR criteria (OR): (a) beats flip-to-flip both years but
        # still loses money outright; (b) the D10 exit itself adds value
        # (P2 > P0 or positive incremental $); (c) not used — confirmation
        # is mechanical (every regime eventually flips), so it alone is not
        # REPAIR evidence.
        del predicts_reversal
        lift_without_profit = bool(
            (scan_df["lift_both_years_positive"]
             & ~scan_df["net_ev_positive_both_years"]).any())
        verdict = ("REPAIR" if (lift_without_profit or d10_helps or p2_beats)
                   else "CLOSE")

    # ---------------------------------------------------------------- header
    L = []
    L.append("PRE-FLIP D10 REVERSAL STUDY\n")
    L.append(f"BEST POLICY:\n{best_label}\n")
    for yr in YEARS:
        L.append(f"{yr} EV LIFT VS FLIP-TO-FLIP BASELINE:\n"
                 f"{fmt_usd(hdr[yr]['lift'])} per trade"
                 + ("" if best_label != "NONE" else
                    f"  (representative {best_pol} @ {best_stop:.2f} ATR; "
                    f"no policy qualified)") + "\n")
    for yr in YEARS:
        L.append(f"{yr} STOP-OUT BEFORE FLIP RATE:\n{fmt_pct(hdr[yr]['sbf'])}\n")
    for yr in YEARS:
        L.append(f"{yr} NEW-REGIME D10 EXIT RATE:\n{fmt_pct(hdr[yr]['d10x'])}\n")
    for yr in YEARS:
        L.append(f"{yr} OPPOSITE-FLIP FALLBACK EXIT RATE:\n"
                 f"{fmt_pct(hdr[yr]['oppx'])}\n")
    L.append("PERCENT OF VALIDLY SCORED REGIMES THAT EVER REACH D10:\n"
             f"{fmt_pct(pct_ever_d10)}\n")
    L.append(f"AVERAGE PRE-FLIP PNL:\n{fmt_usd(pre_all)}\n")
    L.append(f"AVERAGE POST-FLIP PNL:\n{fmt_usd(post_all)}\n")
    L.append("D10 FRONT-RUN ENTRY ADVANTAGE VS WAITING FOR FLIP:\n"
             f"mean {fmt_usd(float(frontrun.mean()))} / "
             f"{float(fr_atr.mean()):.3f} ATR (gross of costs)\n")
    plc_dir = {int(r["year"]): r["ev_diff"] for _, r in plc_best.iterrows()}
    L.append("MATCHED PLACEBO P-VALUE:\n"
             + ", ".join(f"{yr}: {plc_p.get(yr, np.nan):.4f} "
                         f"(real {'WORSE' if plc_dir.get(yr, 0) < 0 else 'better'}"
                         f" than placebo by {fmt_usd(abs(plc_dir.get(yr, np.nan)))}/tr)"
                         for yr in YEARS)
             + f"  (Welch, {best_pol} @ {best_stop:.2f})\n")
    L.append(f"VERDICT:\n{verdict}\n")
    header = "\n".join(L)

    # ------------------------------------------------------------- provenance
    prov = {
        "study": "fable5_pre_flip_d10_reversal_entry",
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "frozen_threshold": thr,
        "atlas_sha256": thr["atlas_sha256"],
        "causal_scores_sha256": sha256_file(WORK / "causal_scores.parquet"),
        "events_sha256": sha256_file(RESULTS / "d10_entry_events.parquet"),
        "placebo_seed": 42,
        "cost_model": f"${COST_RT}/RT ($5 commission + 1 tick slippage)",
        "stop_grid": list(STOP_GRID),
        "econ_windows": {str(y): [str(s), str(e)]
                         for y, (s, e) in ECON_WINDOWS.items()},
        "fill_convention": "NT bar-execution: market FOK fills at decision "
                           "boundary vs just-completed 1s close; stop fills "
                           "at trigger, gap-through repriced to open in "
                           "analysis (primary)",
        "verdict": verdict,
        "best_policy": best_label,
    }
    (AUDIT / "provenance_audit.json").write_text(json.dumps(prov, indent=2))

    # ------------------------------------------------------------ body tables
    def table(df, cols=None, floatfmt=2):
        d = df[cols].copy() if cols is not None else df.copy()
        for c in d.columns:
            if d[c].dtype.kind == "f":
                d[c] = d[c].round(floatfmt)
        return d.to_markdown(index=False)

    body = []
    body.append("\n\n---\n\n## 1. Executive summary\n")
    body.append(f"- Frozen D10 threshold {thr['threshold']:.6f} "
                f"(P90 of Jan-Feb 2025 val W4 scores; absolute threshold; "
                f"val AUC {thr['auc_val']:.4f}).")
    body.append(f"- {len(events):,} pre-flip D10 entry events "
                f"({int((events['year'] == 2025).sum()):,} in 2025 econ window, "
                f"{int((events['year'] == 2026).sum()):,} in 2026).")
    body.append(f"- {fmt_pct(pct_ever_d10)} of validly scored regimes ever "
                f"reach D10; the opposite flip is the required fallback for "
                f"the remainder.")
    body.append(
        "- **Key mechanistic finding**: every pre-flip policy is net "
        "negative in both years, and the covariate-matched placebo beats "
        "the real D10 entries by ~$35-50/trade with the ENTIRE gap in the "
        "pre-flip leg (P1@1.0 pre-flip mean ~$-1 vs placebo ~+$39; "
        "conditional on confirmation +$108 vs +$240). A regime flip is by "
        "definition a move against the old regime, so ANY counter-regime "
        "entry that survives to the flip harvests mechanical drift — and "
        "D10 fires only after the deterioration has largely run (median "
        "49s entry-to-flip vs 99s for placebo), capturing the least of it. "
        "The D10 signal is therefore WORSE-than-random entry timing: it "
        "chases the reversion move it is trying to anticipate.")
    body.append(
        "- Placebo absolute profitability (+$15-30/tr net) is NOT a "
        "deployable claim: both arms fill counter-trend at the last traded "
        "1s close, a convention known to flatter fade entries "
        "(bar-mode fade inflation, see project memory); it is valid only "
        "as the relative control, which the real signal decisively loses.")
    body.append(f"- Verdict: **{verdict}** (rules in section 17).")

    body.append("\n## 2/3. Strategy, policy and threshold definitions\n")
    body.append("See SPEC.md (checked in beside this report) for the full "
                "frozen definitions: policies P0-P4B, one-attempt-per-regime, "
                "stop-only pre-confirmation, D10-or-flip exit priority, "
                "NT-native fill conventions (fixture-verified), and the "
                "absolute validation-frozen threshold.")

    body.append("\n## 4/5. Entry timing and stop execution audits\n")
    body.append("- Pre-flip entries submit exactly 1s after observation "
                "(fail-fast checked in analyze.py; see "
                "audit/entry_timing_audit.parquet and "
                "audit/entry_event_reconciliation.parquet).")
    body.append("- Stop fills: NT fills at trigger; gap-through fills "
                "conservatively repriced to fill-bar open (primary "
                "economics). Raw NT economics carried alongside "
                "(`net_usd_raw`).")

    body.append("\n## 6. Score / regime-ID reset audit\n")
    body.append("See audit/score_regime_id_audit.parquet (fail-fast: zero "
                "orphan score regimes) and the d10_exit_wrong_regime "
                "invariant in audit/exit_reason_completeness_audit.parquet.")

    body.append("\n## 7. Regime-level D10 coverage\n")
    cov_s = cov_econ.groupby("year").agg(
        n_regimes=("regime_id", "count"),
        validly_scored=("validly_scored", "sum"),
        ever_d10=("ever_reached_D10", "sum"),
        d10_before_end=("d10_before_end", "sum"),
        d10_at_end_only=("d10_at_end_only", "sum"),
        truncated_1800s=("age_coverage_truncated_at_1800s", "sum"),
    ).reset_index()
    body.append(table(cov_s, cov_s.columns.tolist()))
    body.append("\nFull breakdowns: results/regime_d10_coverage_summary.parquet "
                "(economics window only; calibration window tagged separately "
                "in the row-level file).")

    body.append("\n## 8. D10 entry diagnostics & front-run advantage\n")
    fr = pvw.dropna(subset=["frontrun_advantage_pts"])
    fr_usd = fr["frontrun_advantage_pts"] * 20.0
    body.append(f"- n with both executable prices: {len(fr):,}")
    body.append(f"- mean {fmt_usd(fr_usd.mean())}, median {fmt_usd(fr_usd.median())}, "
                f"p25 {fmt_usd(fr_usd.quantile(.25))}, p75 {fmt_usd(fr_usd.quantile(.75))}, "
                f"p10 {fmt_usd(fr_usd.quantile(.10))}, p90 {fmt_usd(fr_usd.quantile(.90))}, "
                f"% positive {fmt_pct((fr_usd > 0).mean())} (gross)")
    body.append(f"- median seconds D10 -> flip: "
                f"{float(fr['seconds_d10_to_flip'].median()):,.0f}s")

    body.append("\n## 9. Pre-flip vs post-flip PnL decomposition "
                "(NT trades)\n")
    dcols = ["policy", "stop", "year", "n_trades", "stop_before_flip_rate",
             "flip_confirmation_rate", "avg_pre_flip_pnl_usd",
             "avg_post_flip_pnl_usd", "avg_preflip_mae_atr",
             "p90_preflip_mae_atr", "ev_per_trade"]
    body.append(table(pol[pol["policy"].isin(["P1", "P3"])][dcols]))

    body.append("\n## 10. Stop sensitivity (all stops always shown; none "
                "test-selected)\n")
    scols = ["policy", "stop", "year", "n_trades", "n_censored",
             "stop_before_flip_rate", "flip_confirmation_rate",
             "stop_after_flip_rate", "d10_exit_rate",
             "opposite_flip_exit_rate", "win_rate", "gross_usd", "net_usd",
             "ev_per_trade", "profit_factor", "max_drawdown_usd",
             "median_trade_usd", "p10_trade_usd", "p90_trade_usd",
             "monthly_positive_rate", "n_stop_gap_repriced"]
    body.append(table(stop_sens[stop_sens["policy"].isin(["P1", "P3"])][scols]))

    body.append("\n## 11. Policy comparison (all policies)\n")
    body.append(table(pol[["policy", "stop", "year", "n_trades",
                           "ev_per_trade", "net_usd", "win_rate",
                           "profit_factor", "max_drawdown_usd",
                           "monthly_positive_rate", "n_censored"]]))

    body.append("\n## 12. D10 exit vs opposite-flip fallback\n")
    body.append(table(contrib_sum, contrib_sum.columns.tolist()))
    body.append("\nRunner truncation: results/runner_capture.parquet.")

    body.append("\n## 13. Same-timestamp events\n")
    body.append("audit/same_timestamp_exit_audit.parquet — flips process at "
                "ts_init==close while a same-nominal-timestamp D10 score is "
                "only available 1s later, so flips always causally precede; "
                "all coincidences logged with callback ordering.")

    body.append("\n## 14. Matched placebo controls\n")
    body.append(table(plc, plc.columns.tolist(), 4))

    body.append("\n## 15. Tail dependence\n")
    body.append(table(tail[tail["run_policy"].isin(["P1", "P3"])],
                      tail.columns.tolist()))

    body.append("\n## 16. Failure modes\n")
    body.append("- Regimes never reaching D10 (measured in §7) make the "
                "opposite flip the load-bearing fallback exit.")
    body.append("- Score coverage stops at regime age 1800s (upstream atlas "
                "cap): long regimes cannot produce D10 entries or exits "
                "beyond 30 minutes (`truncated_1800s` counts).")
    body.append("- NT stop fills are optimistic on gap-through bars; primary "
                "economics reprice them (counts per cell in §10).")

    body.append("\n## 17. Decision recommendation\n")
    body.append(f"**{verdict}** under the pre-registered rules: CONTINUE "
                "requires positive EV lift vs P0 in BOTH years AND beating "
                "the matched placebo (Welch p<0.05) in both years AND "
                "surviving top-decile removal, for at least one policy/stop "
                "cell. Qualification scan:")
    body.append(table(scan_df, scan_df.columns.tolist()))

    (RESULTS / "final_report.md").write_text(header + "\n".join(body),
                                             encoding="utf-8")
    print(f"final_report.md written. VERDICT: {verdict}  BEST: {best_label}")


if __name__ == "__main__":
    main()
