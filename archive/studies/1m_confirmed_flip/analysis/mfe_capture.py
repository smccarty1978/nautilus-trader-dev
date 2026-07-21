"""MFE Capture Analysis — which exit trigger captures the most MFE?

For each exit trigger on each trade, compute:
  - Exit PnL at bar close
  - Captured MFE at exit (peak MFE reached from entry to exit bar)
  - Give-back = captured MFE - exit PnL
  - Remaining MFE after exit = peak full-trade MFE - captured MFE
  - Remain/Captured ratio

Uses MFE milestone data (bars_to_XXX_mfe) as quantized proxy for
running peak MFE at each exit bar.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

MFE_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]
EXITS = ["hh1_stall", "hh2_stall", "hh3_stall",
         "first_ll", "second_ll", "first_lh",
         "first_lh_ll", "hl_break"]


def estimate_captured_mfe(row, exit_bar_col):
    """Estimate captured MFE at exit by finding the highest MFE
    milestone reached before the exit bar (converted to 1s bars)."""
    exit_bar_1m = row[exit_bar_col]
    if pd.isna(exit_bar_1m):
        return None
    # Convert 1m bar number to approximate 1s bars elapsed
    # Bar 1 = entry bar (bar+1), so bar N = N-1 minutes elapsed
    # But PathTracker starts from bar+1 close, so bar 2 = 60s elapsed, etc.
    # Use bar_1m * 60 as conservative estimate
    exit_1s = int(exit_bar_1m) * 60

    # Find highest MFE level reached by exit_1s
    captured = 0.0
    for lv in MFE_LEVELS:
        col = f"bars_to_{int(lv*100):03d}_mfe"
        bar_reached = row[col]
        if pd.notna(bar_reached) and bar_reached <= exit_1s:
            captured = lv
    return captured


def compute_exit_metrics(df, exit_name):
    """Compute all exit metrics for trades where this exit triggered."""
    bar_col = f"{exit_name}_bar"
    price_col = f"{exit_name}_price"
    pnl_col = f"{exit_name}_pnl_dollars"
    pnl_pts_col = f"{exit_name}_pnl_pts"

    sub = df[df[bar_col].notna()].copy()
    if len(sub) == 0:
        return None

    # Exit PnL in ATR
    sub["exit_pnl_atr"] = sub[pnl_pts_col] / sub["atr_at_flip"]

    # Captured MFE — highest milestone reached before exit bar
    sub["captured_mfe_atr"] = sub.apply(
        lambda r: estimate_captured_mfe(r, bar_col), axis=1)

    # Give-back = captured - exit (in ATR)
    sub["give_back_atr"] = sub["captured_mfe_atr"] - sub["exit_pnl_atr"]
    # Give-back should be >= 0 (captured MFE is peak favorable)
    # Negative values mean exit PnL > captured MFE, which can happen
    # if captured is quantized low. Clip at 0.
    sub["give_back_atr"] = sub["give_back_atr"].clip(lower=0)

    # Remaining MFE after exit = full trade peak MFE - captured
    sub["remaining_mfe_atr"] = (sub["mfe_atr"] - sub["captured_mfe_atr"]).clip(
        lower=0)

    # Remain/captured ratio
    sub["remain_vs_captured"] = np.where(
        sub["captured_mfe_atr"] > 0,
        sub["remaining_mfe_atr"] / sub["captured_mfe_atr"],
        np.nan)

    # Exited before peak — peak MFE time in 1s bars
    # bars_to_peak isn't directly stored, but we know it's between
    # the last achieved milestone and regime end.
    # For simplicity: "exited before peak" = remaining MFE > 0.25 ATR
    # (i.e., more than a quantization tick remains)
    sub["exited_before_peak"] = (sub["remaining_mfe_atr"] > 0.25).astype(int)

    return sub


def main():
    df = pd.read_parquet("studies/1m_confirmed_flip/results/trades_all.parquet")
    n = len(df)
    print("=" * 90)
    print(f"MFE CAPTURE ANALYSIS ({n:,} trades)")
    print("=" * 90)
    print()

    # Compute for each exit
    results = {}
    for exit_name in EXITS:
        sub = compute_exit_metrics(df, exit_name)
        if sub is not None:
            results[exit_name] = sub

    # Also add regime_flip baseline
    # For regime flip, exit bar = regime_duration_bars, exit PnL = regime_pnl_dollars
    df_rf = df.copy()
    df_rf["exit_pnl_atr"] = df_rf["regime_pnl_pts"] / df_rf["atr_at_flip"]
    # Captured for regime = peak MFE of full trade (since it's the whole trade)
    df_rf["captured_mfe_atr"] = df_rf["mfe_atr"]
    df_rf["give_back_atr"] = (
        df_rf["captured_mfe_atr"] - df_rf["exit_pnl_atr"]).clip(lower=0)
    df_rf["remaining_mfe_atr"] = 0.0
    df_rf["remain_vs_captured"] = 0.0
    df_rf["exited_before_peak"] = 0
    # Rename pnl for consistency
    df_rf["regime_flip_pnl_dollars"] = df_rf["regime_pnl_dollars"]
    results["regime_flip"] = df_rf

    # ==================================================================
    # TABLE 1: Exit Trigger Overview
    # ==================================================================
    print("TABLE 1: EXIT TRIGGER OVERVIEW")
    print()
    print(f"{'Exit':<14} {'N':>7} {'ExitPnL$':>9} {'Cap MFE':>8} "
          f"{'GiveBack':>9} {'Remain':>8} {'R/C':>6} {'Early%':>7}")
    print("-" * 78)

    # Sort by exit PnL
    sorted_exits = sorted(
        [(name, sub) for name, sub in results.items()],
        key=lambda x: -(x[1][f"{x[0]}_pnl_dollars"].mean()
                        if f"{x[0]}_pnl_dollars" in x[1].columns
                        else x[1]["regime_pnl_dollars"].mean()))

    for name, sub in sorted_exits:
        pnl_col = (f"{name}_pnl_dollars"
                   if name != "regime_flip" else "regime_pnl_dollars")
        nn = len(sub)
        avg_pnl = sub[pnl_col].mean()
        avg_cap = sub["captured_mfe_atr"].mean()
        avg_gb = sub["give_back_atr"].mean()
        avg_rem = sub["remaining_mfe_atr"].mean()
        rc = sub["remain_vs_captured"].mean() if name != "regime_flip" else 0
        early = sub["exited_before_peak"].mean() * 100

        print(f"{name:<14} {nn:>7,} ${avg_pnl:>+7.1f} "
              f"{avg_cap:>7.3f} {avg_gb:>8.3f} {avg_rem:>7.3f} "
              f"{rc:>5.2f} {early:>6.1f}%")
    print()

    # ==================================================================
    # TABLE 2: Best Exit by MFE Bucket
    # ==================================================================
    print("=" * 90)
    print("TABLE 2: EXIT PnL BY FULL-TRADE PEAK MFE BUCKET")
    print("=" * 90)
    print()
    print(f"For each MFE bucket, which exit captures the most?")
    print()

    buckets = [(0, 0.50, "<0.50"), (0.50, 1.00, "0.50-1.00"),
               (1.00, 2.00, "1.00-2.00"), (2.00, 99, ">2.00")]

    print(f"{'MFE Bucket':<12}", end="")
    for name in EXITS + ["regime_flip"]:
        print(f"{name[:10]:>11}", end="")
    print()
    print("-" * (12 + 11 * 9))

    for lo, hi, label in buckets:
        bucket_df = df[(df["mfe_atr"] >= lo) & (df["mfe_atr"] < hi)]
        print(f"{label:<12}", end="")
        for name in EXITS + ["regime_flip"]:
            pnl_col = (f"{name}_pnl_dollars"
                       if name != "regime_flip" else "regime_pnl_dollars")
            if pnl_col in bucket_df.columns:
                vals = bucket_df[pnl_col].dropna()
                if len(vals) > 0:
                    print(f"{vals.mean():>+10.0f}", end=" ")
                else:
                    print(f"{'--':>10}", end=" ")
            else:
                print(f"{'--':>10}", end=" ")
        print()

    # Show counts
    print()
    print("Bucket counts:")
    for lo, hi, label in buckets:
        bucket_df = df[(df["mfe_atr"] >= lo) & (df["mfe_atr"] < hi)]
        print(f"  {label}: {len(bucket_df):,} trades "
              f"({len(bucket_df)/n*100:.1f}%)")
    print()

    # ==================================================================
    # TABLE 3: Year-by-Year for Top 3 Exits
    # ==================================================================
    print("=" * 90)
    print("TABLE 3: YEAR-BY-YEAR (TOP EXITS)")
    print("=" * 90)

    # Get top 3 by average PnL
    pnl_by_exit = {}
    for name in EXITS + ["regime_flip"]:
        pnl_col = (f"{name}_pnl_dollars"
                   if name != "regime_flip" else "regime_pnl_dollars")
        if pnl_col in df.columns:
            # Use fallback for triggers that don't fire: use regime exit
            vals = df[pnl_col].fillna(df["regime_pnl_dollars"])
            pnl_by_exit[name] = vals.mean()

    top3 = sorted(pnl_by_exit.items(), key=lambda x: -x[1])[:3]
    print(f"\nTop 3 exits (using regime fallback for non-triggered):")
    for name, pnl in top3:
        print(f"  {name}: ${pnl:+.1f}/trade")
    print()

    print(f"{'Year':>6}", end="")
    for name, _ in top3:
        print(f" {name[:12]:>13}", end="")
    print(f" {'regime_flip':>13}")
    print("-" * (6 + 14 * 4))

    for year in sorted(df["year"].unique()):
        ydf = df[df["year"] == year]
        print(f"{year:>6}", end="")
        for name, _ in top3:
            pnl_col = (f"{name}_pnl_dollars"
                       if name != "regime_flip" else "regime_pnl_dollars")
            vals = ydf[pnl_col].fillna(ydf["regime_pnl_dollars"])
            print(f" {vals.mean():>+12.1f}", end="")
        vals_rf = ydf["regime_pnl_dollars"]
        print(f" {vals_rf.mean():>+12.1f}")
    print()

    # ==================================================================
    # TABLE 4: RTH vs ETH
    # ==================================================================
    print("=" * 90)
    print("TABLE 4: RTH vs ETH (TOP 3 + REGIME)")
    print("=" * 90)
    print()

    for session_val, label in [(1, "RTH"), (0, "ETH")]:
        sdf = df[df["is_rth"] == session_val]
        print(f"{label}: {len(sdf):,} trades")
        for name, _ in top3 + [("regime_flip", 0)]:
            pnl_col = (f"{name}_pnl_dollars"
                       if name != "regime_flip" else "regime_pnl_dollars")
            vals = sdf[pnl_col].fillna(sdf["regime_pnl_dollars"])
            print(f"  {name:<14}: ${vals.mean():+.1f}/trade, "
                  f"total ${vals.sum():+,.0f}")
        print()

    # ==================================================================
    # TABLE 5: Give-Back Distribution (top 3)
    # ==================================================================
    print("=" * 90)
    print("TABLE 5: GIVE-BACK DISTRIBUTION (captured MFE - exit PnL, in ATR)")
    print("=" * 90)

    for name, _ in top3:
        sub = results[name]
        gb = sub["give_back_atr"]
        print(f"\n{name}:")
        print(f"  P25={gb.quantile(0.25):.3f} P50={gb.median():.3f} "
              f"P75={gb.quantile(0.75):.3f} P90={gb.quantile(0.90):.3f}")
        print(f"  Give-back > 0.25 ATR: {(gb > 0.25).mean()*100:.1f}%")
        print(f"  Give-back > 0.50 ATR: {(gb > 0.50).mean()*100:.1f}%")
        print(f"  Give-back > 1.00 ATR: {(gb > 1.00).mean()*100:.1f}%")
    print()

    # ==================================================================
    # TABLE 6: Remaining MFE Distribution
    # ==================================================================
    print("=" * 90)
    print("TABLE 6: REMAINING MFE AFTER EXIT (left on the table, in ATR)")
    print("=" * 90)

    for name, _ in top3:
        sub = results[name]
        rem = sub["remaining_mfe_atr"]
        pct_nothing = (rem < 0.25).mean() * 100
        pct_small = ((rem >= 0.25) & (rem < 0.50)).mean() * 100
        pct_mod = ((rem >= 0.50) & (rem < 1.00)).mean() * 100
        pct_big = (rem >= 1.00).mean() * 100
        print(f"\n{name}:")
        print(f"  Remaining < 0.25 ATR: {pct_nothing:.1f}%  (good - exit timed well)")
        print(f"  Remaining 0.25-0.50:  {pct_small:.1f}%")
        print(f"  Remaining 0.50-1.00:  {pct_mod:.1f}%")
        print(f"  Remaining > 1.00:     {pct_big:.1f}%  (bad - exited too early)")
    print()

    # ==================================================================
    # TABLE 7: Exit Bar Number Distribution (how fast does exit fire?)
    # ==================================================================
    print("=" * 90)
    print("TABLE 7: EXIT BAR NUMBER DISTRIBUTION (1m bars from entry)")
    print("=" * 90)
    print()

    print(f"{'Exit':<14} {'P25':>5} {'P50':>5} {'P75':>5} {'P90':>5} {'Mean':>6}")
    print("-" * 45)
    for name in EXITS:
        sub = df[df[f"{name}_bar"].notna()]
        bars = sub[f"{name}_bar"]
        print(f"{name:<14} {bars.quantile(0.25):>5.0f} "
              f"{bars.median():>5.0f} {bars.quantile(0.75):>5.0f} "
              f"{bars.quantile(0.90):>5.0f} {bars.mean():>6.1f}")
    # Regime flip uses regime_duration_bars
    bars = df["regime_duration_bars"]
    print(f"{'regime_flip':<14} {bars.quantile(0.25):>5.0f} "
          f"{bars.median():>5.0f} {bars.quantile(0.75):>5.0f} "
          f"{bars.quantile(0.90):>5.0f} {bars.mean():>6.1f}")
    print()

    # ==================================================================
    # SUMMARY — Best strategy
    # ==================================================================
    print("=" * 90)
    print("SUMMARY: STRATEGY COMPARISON (including regime fallback for non-triggered)")
    print("=" * 90)
    print()
    print(f"{'Strategy':<25} {'Avg$':>8} {'Total$':>12} {'Trig%':>7}")
    print("-" * 54)

    for name in EXITS + ["regime_flip"]:
        pnl_col = (f"{name}_pnl_dollars"
                   if name != "regime_flip" else "regime_pnl_dollars")
        if pnl_col not in df.columns:
            continue
        # Strategy = trigger PnL if fired, else regime exit
        vals = df[pnl_col].fillna(df["regime_pnl_dollars"])
        trig = df[pnl_col].notna().sum()
        print(f"{name + ' (+regime fallback)':<25} "
              f"${vals.mean():>+7.1f} ${vals.sum():>+11,.0f} "
              f"{trig/n*100:>6.1f}%")

    print()
    print("Trailing stop simulation (MFE-0.50, regime fallback):")
    # For trades that reached 0.50 MFE, exit at MFE - 0.50 in ATR
    ts_pnl = []
    for _, t in df.iterrows():
        if t["mfe_atr"] >= 0.50:
            # Capture MFE - 0.50 ATR in dollars
            pnl = (t["mfe_atr"] - 0.50) * t["atr_at_flip"] * 20 - 5
        else:
            pnl = t["regime_pnl_dollars"]
        ts_pnl.append(pnl)
    ts_pnl = np.array(ts_pnl)
    print(f"  Trailing (MFE-0.50):       ${ts_pnl.mean():>+7.1f}  "
          f"${ts_pnl.sum():>+11,.0f}")

    # Save report
    out_path = Path(
        "studies/1m_confirmed_flip/results/mfe_capture_analysis.md")
    print(f"\n(Full report summary above — key tables and numbers)")
    print(f"Output: {out_path} (optional)")


if __name__ == "__main__":
    main()
