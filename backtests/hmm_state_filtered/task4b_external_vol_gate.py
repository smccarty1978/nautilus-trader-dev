"""Task 4(b) — External absolute-volatility gate on production entries.

Hypothesis: the HMM is blind to absolute vol because every feature is
ATR-normalized. Adding an external classifier of absolute-vol regime (computed
strictly from past data) and gating trade-taking on it should detect the
Aug-Oct 2024 long collapse and selectively skip those entries without
destroying 2025 longs (which lived in a similarly high-vol regime but worked).

Method:
  1. From 1m features parquet, compute mean atr_1m per UTC date (daily ATR).
  2. For each date t, compute rolling N-day percentile of daily ATR using
     ONLY days [t-N, t-1] (strictly causal — t excluded).
  3. For each production trade, lookup the percentile of its entry-date's
     daily ATR vs the prior history.
  4. Test gates at multiple cutoffs. Report per-year and pooled OOS.
  5. Test direction-conditional gates (longs only / shorts only).
  6. Test simple position sizing: scale qty proportional to (1 - percentile).

Cautions:
  - The percentile lookup is strictly past-only. No future leakage.
  - Production cohort = state-3 + bar1_confirm + PT 2.0 ATR NT trades.
  - Reported $/tr keeps existing $20 NQ multiplier and $5 RT commission.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
COMM = 5.0
RES = Path("backtests/hmm_state_filtered/results")
FEATS = Path("studies/regime_classification/results/features_nq_1m.parquet")
OOS_YEARS = (2023, 2024, 2025, 2026)


def load_production_trades():
    rows = []
    for y in OOS_YEARS:
        p = RES / f"nq_hmm_4_s3_pt2p0_{y}/trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["year"] = y
        df["pnl_$"] = ((df["exit_px"] - df["entry_px"])
                        * df["signal_direction"] * NQ_MULT - COMM)
        df["entry_dt"] = pd.to_datetime(df["entry_ts"])
        df["entry_date"] = df["entry_dt"].dt.date
        df["month"] = df["entry_dt"].dt.to_period("M").astype(str)
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def compute_daily_atr_history():
    """Return DataFrame indexed by UTC date with mean atr_1m + causal rolling
    percentiles for 30/60/90 days."""
    print("  Loading 1m features (atr_1m, year)...")
    df = pd.read_parquet(FEATS, columns=["atr_1m", "year"])
    df = df.dropna(subset=["atr_1m"])
    df["date"] = df.index.date
    daily = df.groupby("date")["atr_1m"].mean().to_frame("atr_daily")
    daily.index = pd.to_datetime(daily.index)
    print(f"  Daily ATR series: {len(daily)} days, "
          f"{daily.index.min().date()} to {daily.index.max().date()}")

    # Causal rolling percentile: for date t, percentile of daily ATR(t)
    # within window [t-N, t-1]. We use rank within a rolling window
    # EXCLUDING the current day.
    def rolling_past_pct(s: pd.Series, window: int) -> pd.Series:
        # For each point, compute its rank percentile within the
        # PRECEDING `window` days (not including itself).
        out = np.full(len(s), np.nan)
        arr = s.values
        for i in range(window, len(arr)):
            past = arr[i - window:i]
            cur = arr[i]
            # percentile = fraction of past <= current
            out[i] = (past <= cur).mean()
        return pd.Series(out, index=s.index)

    for N in (30, 60, 90):
        daily[f"atr_pct_{N}d"] = rolling_past_pct(daily["atr_daily"], N)

    # ATR ratio: today's daily ATR / N-day past mean (excluding today)
    for N in (30, 90):
        prior_mean = daily["atr_daily"].shift(1).rolling(N).mean()
        daily[f"atr_ratio_{N}d"] = daily["atr_daily"] / prior_mean

    print(f"  Daily atr percentile coverage: {daily['atr_pct_90d'].notna().sum()} days")
    return daily


def join_features_to_trades(tr: pd.DataFrame, daily: pd.DataFrame):
    daily_keyed = daily.copy()
    daily_keyed.index = daily_keyed.index.date
    cols = ["atr_daily", "atr_pct_30d", "atr_pct_60d", "atr_pct_90d",
            "atr_ratio_30d", "atr_ratio_90d"]
    for c in cols:
        tr[c] = tr["entry_date"].map(daily_keyed[c])
    return tr


def report_quartile_distribution(tr: pd.DataFrame, feat: str):
    print(f"\n  Trade distribution by {feat} quartile (OOS pool):")
    sub = tr.dropna(subset=[feat]).copy()
    if not len(sub):
        print("    (no data)"); return
    sub["q"] = pd.qcut(sub[feat], 4, labels=False, duplicates="drop")
    print(f"  {'q':<3}{'n':>6}{'feat_avg':>10}{'$/tr':>10}{'WR':>8}"
          f"{'long $/tr':>11}{'short $/tr':>11}")
    for q in sorted(sub["q"].dropna().unique()):
        rows = sub[sub["q"] == q]
        lo = rows[rows["signal_direction"] == 1]
        sh = rows[rows["signal_direction"] == -1]
        print(f"  {int(q):<3}{len(rows):>6}"
              f"{rows[feat].mean():>+10.3f}{rows['pnl_$'].mean():>+10.2f}"
              f"{(rows['pnl_$']>0).mean():>8.1%}"
              f"{lo['pnl_$'].mean() if len(lo) else 0:>+11.2f}"
              f"{sh['pnl_$'].mean() if len(sh) else 0:>+11.2f}")


def report_gate(tr: pd.DataFrame, feat: str, op: str, threshold: float, label: str):
    """Apply gate: keep trades where tr[feat] op threshold. op is '<', '<=', '>', '>='."""
    sub = tr.dropna(subset=[feat]).copy()
    if op == "<":
        mask = sub[feat] < threshold
    elif op == "<=":
        mask = sub[feat] <= threshold
    elif op == ">":
        mask = sub[feat] > threshold
    elif op == ">=":
        mask = sub[feat] >= threshold
    kept = sub[mask]
    if not len(kept):
        return
    pool_dpt = kept["pnl_$"].mean()
    pool_total = kept["pnl_$"].sum()
    line = f"  {label:<40}n={len(kept):>5} $/tr={pool_dpt:>+8.2f} tot${pool_total:>+9,.0f}"
    # per-year
    yr_str = ""
    yp = 0
    for y in OOS_YEARS:
        s = kept[kept["year"] == y]
        if not len(s):
            yr_str += f"  {y}:--"; continue
        m = s["pnl_$"].mean()
        if m > 0: yp += 1
        yr_str += f"  {y}:{m:>+6.0f}"
    line += yr_str + f"  {yp}/4+"
    print(line)


def report_dir_gate(tr: pd.DataFrame, feat: str, dir_: int, op: str, threshold: float, label: str):
    """Apply gate only to one direction; keep all other trades untouched."""
    sub = tr.dropna(subset=[feat]).copy()
    if op == "<":
        mask_skip = (sub["signal_direction"] == dir_) & (sub[feat] >= threshold)
    elif op == ">":
        mask_skip = (sub["signal_direction"] == dir_) & (sub[feat] <= threshold)
    kept = sub[~mask_skip]
    if not len(kept):
        return
    pool_dpt = kept["pnl_$"].mean()
    pool_total = kept["pnl_$"].sum()
    line = f"  {label:<60}n={len(kept):>5} $/tr={pool_dpt:>+8.2f} tot${pool_total:>+9,.0f}"
    yr_str = ""
    yp = 0
    for y in OOS_YEARS:
        s = kept[kept["year"] == y]
        if not len(s):
            yr_str += f"  {y}:--"; continue
        m = s["pnl_$"].mean()
        if m > 0: yp += 1
        yr_str += f"  {y}:{m:>+6.0f}"
    line += yr_str + f"  {yp}/4+"
    print(line)


def report_position_sizing(tr: pd.DataFrame, feat: str):
    """Scale position by (1 - percentile). Effectively reduces size in high vol."""
    sub = tr.dropna(subset=[feat]).copy()
    sub["weight"] = 1.0 - sub[feat]   # high vol → low weight; clamp at 0.25 min
    sub["weight"] = sub["weight"].clip(lower=0.25, upper=1.0)
    sub["weighted_$"] = sub["pnl_$"] * sub["weight"]
    print(f"\n  Position sizing by (1 - {feat}), clipped [0.25, 1.0]:")
    print(f"  {'metric':<20}{'value':>14}")
    print(f"  {'unweighted $/tr':<20}{sub['pnl_$'].mean():>+14.2f}")
    print(f"  {'weighted $/tr':<20}{sub['weighted_$'].mean():>+14.2f}")
    for y in OOS_YEARS:
        ys = sub[sub["year"] == y]
        print(f"  {y} weighted $/tr   {ys['weighted_$'].mean():>+14.2f}  "
              f"(unweighted {ys['pnl_$'].mean():>+8.2f})")


def aug_oct_2024_check(tr: pd.DataFrame, feat: str):
    """Where do the Aug-Oct 2024 trades land in the vol feature distribution?"""
    sub = tr.dropna(subset=[feat]).copy()
    crash = sub[(sub["year"] == 2024) & sub["month"].isin(["2024-08","2024-09","2024-10"])]
    long_crash = crash[crash["signal_direction"] == 1]
    print(f"\n  Aug-Oct 2024 LONG cohort distribution in {feat}:")
    if not len(long_crash):
        print("    (empty)"); return
    print(f"    n={len(long_crash)}")
    print(f"    {feat} mean: {long_crash[feat].mean():.3f}")
    print(f"    {feat} median: {long_crash[feat].median():.3f}")
    print(f"    {feat} min/max: {long_crash[feat].min():.3f} / {long_crash[feat].max():.3f}")
    # Compare to 2025 LONGS (the "good" high-vol cohort)
    y25_long = sub[(sub["year"] == 2025) & (sub["signal_direction"] == 1)]
    if len(y25_long):
        print(f"\n  2025 LONG cohort (the GOOD high-vol comparison) in {feat}:")
        print(f"    n={len(y25_long)}")
        print(f"    {feat} mean: {y25_long[feat].mean():.3f}")
        print(f"    {feat} median: {y25_long[feat].median():.3f}")
        # KEY QUESTION: can {feat} separate bad-2024-longs from good-2025-longs?
        bad_q75 = long_crash[feat].quantile(0.75)
        good_q25 = y25_long[feat].quantile(0.25)
        good_q75 = y25_long[feat].quantile(0.75)
        print(f"\n  Discrimination test:")
        print(f"    Bad 2024 longs Q75 of {feat}: {bad_q75:.3f}")
        print(f"    Good 2025 longs Q25 of {feat}: {good_q25:.3f}")
        print(f"    Good 2025 longs Q75 of {feat}: {good_q75:.3f}")
        if bad_q75 < good_q25:
            print(f"    -> {feat} CLEANLY separates: bad < good")
        elif bad_q75 < good_q75:
            print(f"    -> {feat} partially separates")
        else:
            print(f"    -> {feat} does NOT separate bad-2024 from good-2025 longs")


def main():
    print("Loading production trades...")
    tr = load_production_trades()
    print(f"  {len(tr):,} OOS trades")

    print("\nComputing daily ATR + causal rolling percentiles...")
    daily = compute_daily_atr_history()
    tr = join_features_to_trades(tr, daily)

    # baseline reference
    baseline = tr.dropna(subset=["atr_pct_30d"])
    print(f"\nBaseline (drop rows without 30d-pct lookup): "
          f"n={len(baseline)} $/tr=+{baseline['pnl_$'].mean():.2f}")

    # ============================================================================
    # 1. Distribution of trades by vol percentile quartile
    # ============================================================================
    print(f"\n{'='*92}\n  QUARTILE DIAGNOSTIC by various absolute-vol features\n{'='*92}")
    for f in ["atr_pct_30d", "atr_pct_60d", "atr_pct_90d",
              "atr_ratio_30d", "atr_ratio_90d", "atr_daily"]:
        report_quartile_distribution(tr, f)

    # ============================================================================
    # 2. Discrimination test: bad-2024-longs vs good-2025-longs
    # ============================================================================
    print(f"\n{'='*92}\n  DISCRIMINATION: bad Aug-Oct 2024 longs vs good 2025 longs\n{'='*92}")
    for f in ["atr_pct_30d", "atr_pct_60d", "atr_pct_90d",
              "atr_ratio_30d", "atr_daily"]:
        aug_oct_2024_check(tr, f)

    # ============================================================================
    # 3. Simple gates — skip extremes
    # ============================================================================
    print(f"\n{'='*92}\n  SIMPLE GATES (apply to ALL trades, both directions)\n{'='*92}")
    print(f"  {'gate':<40}n           $/tr            year-by-year                  yrs+")
    report_gate(tr, "atr_pct_30d", "<", 1.0, "baseline (all trades)")
    for thr in [0.95, 0.90, 0.80, 0.75, 0.50]:
        report_gate(tr, "atr_pct_30d", "<", thr,
                    f"skip atr_pct_30d >= {thr:.2f}")
    for thr in [0.95, 0.90, 0.80, 0.75]:
        report_gate(tr, "atr_pct_90d", "<", thr,
                    f"skip atr_pct_90d >= {thr:.2f}")
    for thr in [1.5, 1.3, 1.2, 1.1]:
        report_gate(tr, "atr_ratio_30d", "<", thr,
                    f"skip atr_ratio_30d >= {thr:.1f}")

    # ============================================================================
    # 4. Direction-conditional gates (longs only or shorts only)
    # ============================================================================
    print(f"\n{'='*92}\n  DIRECTION-CONDITIONAL GATES\n{'='*92}")
    print(f"  Longs-only skip when high vol (shorts kept):")
    for thr in [0.95, 0.90, 0.80, 0.75]:
        report_dir_gate(tr, "atr_pct_30d", 1, "<", thr,
                        f"skip LONGS when atr_pct_30d >= {thr:.2f}")
    print(f"\n  Shorts-only skip when low vol (longs kept):")
    for thr in [0.10, 0.25, 0.50]:
        report_dir_gate(tr, "atr_pct_30d", -1, ">", thr,
                        f"skip SHORTS when atr_pct_30d <= {thr:.2f}")

    # ============================================================================
    # 5. Position sizing
    # ============================================================================
    print(f"\n{'='*92}\n  POSITION SIZING by (1 - percentile)\n{'='*92}")
    report_position_sizing(tr, "atr_pct_30d")
    report_position_sizing(tr, "atr_pct_90d")


if __name__ == "__main__":
    main()
