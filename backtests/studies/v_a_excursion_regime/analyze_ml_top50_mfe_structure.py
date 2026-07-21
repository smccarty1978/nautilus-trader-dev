"""Analyze MFE structure of the N=40 top-50% ML cohort.

Questions:
  1. Of the top-50% ML-selected V_A trades, how many WON at regime flip?
  2. What % reached MFE >= 0.75 ATR at any point during the trade?
  3. Of trades that reached 0.75 ATR MFE, how many gave it back and
     exited as losers (= V-shape, scalp opportunity)?
  4. If we scalped at PT=0.75 ATR (and otherwise held to regime flip),
     how would PnL compare to the current hold-to-flip strategy?

Data:
  - ml_n40_oos_preds_with_trades.parquet (OOS predictions + trade info)
  - Filtered to top 50% by global threshold (p >= 0.2821 from earlier run)
  - MFE/MAE timing from trades.parquet (joined in)

Simulation:
  - Reached 0.75 ATR MFE: running_mfe >= 0.75 * atr_at_signal
  - Scalp PT: assume we exit at exactly entry + 0.75*ATR (long) or
    entry - 0.75*ATR (short) when MFE crosses that level
  - PT $ value: 0.75 * atr_at_signal * NQ_MULT(20) - 2 * commission($5)
  - If not reached: hold to regime flip (use existing net_pnl)
"""
from __future__ import annotations
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd


OUT = Path("studies/v_a_excursion_regime/results_v0")
NQ_MULT = 20.0
COMMISSION = 5.0
TOP50_THRESHOLD = 0.2821    # from earlier global OOS computation
PT_ATR = 0.75


def load_data():
    """Load ML predictions and join trade timing info."""
    df = pd.read_parquet(OUT / "ml_n40_oos_preds_with_trades.parquet")
    # Join MFE/MAE timestamps from trades.parquet (per year)
    trade_files = []
    for yr in [2024, 2025, 2026]:
        t = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/trades.parquet",
            columns=["decision_ts", "direction",
                       "t_running_mfe_ts", "t_running_mae_ts",
                       "entry_ts"]).rename(columns={
                           "t_running_mfe_ts": "mfe_ts",
                           "t_running_mae_ts": "mae_ts"})
        t["year"] = yr
        trade_files.append(t)
    trades = pd.concat(trade_files, ignore_index=True)
    trades = trades.drop_duplicates(
        subset=["decision_ts", "direction"], keep="first")
    df = df.merge(
        trades[["decision_ts", "direction", "mfe_ts", "mae_ts"]],
        on=["decision_ts", "direction"], how="left")
    return df


def main():
    df = load_data()
    print(f"Loaded {len(df):,} OOS predictions with trade timing")

    # Filter to top 50% by global threshold
    top50 = df[df["p_unr075"] >= TOP50_THRESHOLD].copy().reset_index(drop=True)
    print(f"Top 50% (p >= {TOP50_THRESHOLD}): {len(top50):,} trades")

    # Compute MFE in ATR units (signed by direction... actually MFE is
    # always positive in the strategy.py output; it's the max favorable
    # excursion in the trade's direction)
    top50["mfe_atr"] = top50["running_mfe"] / top50["atr_at_signal"]
    top50["mae_atr"] = top50["running_mae"] / top50["atr_at_signal"]
    top50["net_pnl_atr"] = top50["net_pnl"] / (
        top50["atr_at_signal"] * NQ_MULT)
    top50["reached_pt"] = top50["mfe_atr"] >= PT_ATR
    top50["won_at_flip"] = top50["net_pnl"] > 0
    top50["secs_to_mfe"] = (top50["mfe_ts"] - top50["entry_ts"]) / 1e9
    top50["secs_after_mfe"] = (top50["exit_ts"] - top50["mfe_ts"]) / 1e9

    # Scalp PnL: if reached PT, exit at +0.75 ATR; else hold to flip
    pt_gross_dollars = PT_ATR * top50["atr_at_signal"] * NQ_MULT
    top50["scalp_pnl"] = np.where(
        top50["reached_pt"],
        pt_gross_dollars - 2 * COMMISSION,
        top50["net_pnl"],
    )

    print("\n" + "=" * 78)
    print("BASE METRICS — top 50% ML cohort (all OOS years)")
    print("=" * 78)
    print(f"  n_total          : {len(top50):,}")
    print(f"  won_at_flip      : {top50['won_at_flip'].sum():,}  "
          f"({top50['won_at_flip'].mean():.1%})")
    print(f"  reached 0.75 ATR : {top50['reached_pt'].sum():,}  "
          f"({top50['reached_pt'].mean():.1%})")
    print(f"  reached PT AND won at flip: "
          f"{(top50['reached_pt'] & top50['won_at_flip']).sum():,}  "
          f"({(top50['reached_pt'] & top50['won_at_flip']).mean():.1%})")
    print(f"  reached PT BUT lost at flip (V-shape): "
          f"{(top50['reached_pt'] & ~top50['won_at_flip']).sum():,}  "
          f"({(top50['reached_pt'] & ~top50['won_at_flip']).mean():.1%})")
    print(f"  did NOT reach PT, won at flip: "
          f"{(~top50['reached_pt'] & top50['won_at_flip']).sum():,}")
    print(f"  did NOT reach PT, lost at flip: "
          f"{(~top50['reached_pt'] & ~top50['won_at_flip']).sum():,}")

    print("\n" + "=" * 78)
    print("MFE distribution (in ATR units) — top 50% cohort")
    print("=" * 78)
    print(top50["mfe_atr"].describe().to_string())
    print("\n  MFE quantiles by ATR threshold:")
    for thr in [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]:
        pct = (top50["mfe_atr"] >= thr).mean()
        print(f"    mfe_atr >= {thr:.2f}: {pct:.1%}  "
              f"({(top50['mfe_atr'] >= thr).sum():,} of {len(top50):,})")

    print("\n" + "=" * 78)
    print("V-SHAPE STRUCTURE — reached PT but lost at flip")
    print("=" * 78)
    vshape = top50[top50["reached_pt"] & ~top50["won_at_flip"]].copy()
    print(f"  n = {len(vshape):,}  ({len(vshape)/len(top50):.1%} of top-50% cohort)")
    print(f"  mean MFE (atr units): {vshape['mfe_atr'].mean():.2f}")
    print(f"  median MFE: {vshape['mfe_atr'].median():.2f}")
    print(f"  mean MAE (atr units): {vshape['mae_atr'].mean():.2f}")
    print(f"  mean realized PnL (atr units): {vshape['net_pnl_atr'].mean():.2f}")
    print(f"  mean realized PnL ($): ${vshape['net_pnl'].mean():+.2f}")
    print(f"  mean secs_to_mfe (when peak hit): "
          f"{vshape['secs_to_mfe'].mean():.0f}s")
    print(f"  median secs_to_mfe: "
          f"{vshape['secs_to_mfe'].median():.0f}s")
    print(f"  mean secs_after_mfe (hold-out time):"
          f" {vshape['secs_after_mfe'].mean():.0f}s")

    print("\n" + "=" * 78)
    print("SCALP SIMULATION vs HOLD-TO-FLIP — top 50% cohort")
    print("=" * 78)
    print(f"\n  PnL with hold-to-flip (current):")
    print(f"    total: ${top50['net_pnl'].sum():+,.0f}  "
          f"mean: ${top50['net_pnl'].mean():+.2f}/tr  "
          f"WR: {top50['won_at_flip'].mean():.1%}")
    print(f"\n  PnL with PT=0.75 ATR scalp:")
    scalp_wr = (top50["scalp_pnl"] > 0).mean()
    print(f"    total: ${top50['scalp_pnl'].sum():+,.0f}  "
          f"mean: ${top50['scalp_pnl'].mean():+.2f}/tr  "
          f"WR: {scalp_wr:.1%}")
    diff = top50["scalp_pnl"].sum() - top50["net_pnl"].sum()
    print(f"\n  Δ (scalp - hold): ${diff:+,.0f}  "
          f"(${diff/len(top50):+.2f}/tr)")

    print("\n" + "=" * 78)
    print("PER-YEAR BREAKDOWN")
    print("=" * 78)
    print(f"  {'year':>4}  {'n':>5}  {'reach_pt%':>9}  {'WR_flip':>7}  "
          f"{'hold_total':>11}  {'scalp_total':>11}  "
          f"{'hold_mean':>10}  {'scalp_mean':>10}  {'delta_$':>9}")
    for yr in sorted(top50["year"].unique()):
        sub = top50[top50["year"] == yr]
        reach_pct = sub["reached_pt"].mean()
        wr = sub["won_at_flip"].mean()
        h_total = sub["net_pnl"].sum()
        s_total = sub["scalp_pnl"].sum()
        h_mean = sub["net_pnl"].mean()
        s_mean = sub["scalp_pnl"].mean()
        print(f"  {int(yr):>4}  {len(sub):>5,}  {reach_pct:>8.1%}  "
              f"{wr:>6.1%}  ${h_total:>+9,.0f}  ${s_total:>+9,.0f}  "
              f"${h_mean:>+8.2f}  ${s_mean:>+8.2f}  "
              f"${s_total-h_total:>+7,.0f}")

    print("\n" + "=" * 78)
    print("SENSITIVITY — vary PT level")
    print("=" * 78)
    print(f"  {'PT_atr':>6}  {'reach%':>7}  {'scalp_total':>11}  "
          f"{'scalp_mean':>10}  {'scalp_WR':>8}  "
          f"{'2024_total':>10}  {'2025_total':>10}  {'2026_total':>10}")
    for pt in [0.40, 0.50, 0.60, 0.75, 1.00, 1.25, 1.50, 2.00]:
        reached = top50["mfe_atr"] >= pt
        gross = pt * top50["atr_at_signal"] * NQ_MULT
        scalp = np.where(reached, gross - 2 * COMMISSION, top50["net_pnl"])
        total = scalp.sum()
        mean = scalp.mean()
        wr = (scalp > 0).mean()
        by_yr = {}
        for yr in [2024, 2025, 2026]:
            mask = (top50["year"] == yr).to_numpy()
            by_yr[yr] = scalp[mask].sum()
        print(f"  {pt:>6.2f}  {reached.mean():>6.1%}  "
              f"${total:>+9,.0f}  ${mean:>+8.2f}  "
              f"{wr:>7.1%}  ${by_yr[2024]:>+8,.0f}  "
              f"${by_yr[2025]:>+8,.0f}  ${by_yr[2026]:>+8,.0f}")

    # MFE timing detail for V-shape trades
    print("\n" + "=" * 78)
    print("MFE TIMING for V-shape trades (reached PT, lost at flip)")
    print("=" * 78)
    if len(vshape) > 0:
        v = vshape.copy()
        print(f"  When did the V-shape trades reach their peak MFE?")
        bins = [0, 30, 60, 120, 300, 600, 1800, np.inf]
        labels = ["0-30s", "30-60s", "60-120s", "2-5m", "5-10m", "10-30m", "30m+"]
        v["mfe_bin"] = pd.cut(v["secs_to_mfe"], bins=bins, labels=labels,
                                include_lowest=True)
        bin_counts = v["mfe_bin"].value_counts().sort_index()
        for b, c in bin_counts.items():
            print(f"    {b:>10}: {c:>4}  ({c/len(v):.1%})")
        print(f"\n  How long did they hold AFTER peak MFE before flip exit?")
        v["after_bin"] = pd.cut(v["secs_after_mfe"], bins=bins, labels=labels,
                                 include_lowest=True)
        bin_counts = v["after_bin"].value_counts().sort_index()
        for b, c in bin_counts.items():
            print(f"    {b:>10}: {c:>4}  ({c/len(v):.1%})")

    # Save augmented dataframe
    top50.to_parquet(OUT / "ml_n40_top50_mfe_analysis.parquet")
    print(f"\nWrote: {OUT / 'ml_n40_top50_mfe_analysis.parquet'}")


if __name__ == "__main__":
    main()
