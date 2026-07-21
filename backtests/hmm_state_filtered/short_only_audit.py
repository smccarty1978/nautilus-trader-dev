"""Short-only audit on static P4 hmm_4=3 cohort.

The headline robustness battery found that 2024's break was entirely on the
LONG side (longs -$95/tr, shorts +$15/tr) and shorts were positive in every
OOS year (2023-2026). This script asks: is short-only a deployable claim?

Critical flag: IS years (2020-2022) had shorts NEGATIVE in all 3 (-$43, -$26,
-$7) but OOS years had shorts POSITIVE in all 4 (+$10, +$15, +$50, +$22).
That IS->OOS divergence is the wrong direction (usually IS overfits to
positive). Need to understand why before any deployment claim.

Battery (shorts-only on hmm_4=3 + bar1_confirm cohort):
  1. PT sensitivity shorts-only (PT 1.5/1.8/2.0/2.5 trades already exist)
  2. Year bootstrap shorts-only (2000 resamples, P(<=0) per year)
  3. Rolling 50/100-trade Sharpe shorts (OOS chronological)
  4. Monthly PnL shorts ALL 7 years (any short-collapse cluster?)
  5. IS->OOS divergence diagnostic
  6. Worst-window analysis (find the bad cluster if any)
  7. PT-vs-regime exit split shorts
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NQ_MULT = 20.0
COMM = 5.0
RES = Path("backtests/hmm_state_filtered/results")
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)
ALL_YEARS = IS_YEARS + OOS_YEARS
PT_LEVELS = [1.5, 1.8, 2.0, 2.5]


def load_pt_trades(pt_level: float) -> pd.DataFrame:
    tag = f"pt{pt_level}".replace(".", "p")
    rows = []
    for y in ALL_YEARS:
        p = RES / f"nq_hmm_4_s3_{tag}_{y}/trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not len(df):
            continue
        df["year"] = y
        df["pnl_$"] = ((df["exit_px"] - df["entry_px"])
                        * df["signal_direction"] * NQ_MULT - COMM)
        df["pnl_atr"] = ((df["exit_px"] - df["entry_px"])
                          * df["signal_direction"] / df["entry_atr"])
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def report_pt_sensitivity_shorts():
    print(f"\n{'='*92}\n  [1] PT SENSITIVITY — SHORTS ONLY\n{'='*92}")
    cohorts = {p: load_pt_trades(p) for p in PT_LEVELS}
    shorts = {p: df[df["signal_direction"] == -1] for p, df in cohorts.items() if len(df)}
    if not shorts:
        print("  no PT cohorts found"); return

    print(f"  {'year':<6}{'PT1.5':>14}{'PT1.8':>14}{'PT2.0':>14}{'PT2.5':>14}")
    print(f"  {'':>6}{'n/$/tr':>14}{'n/$/tr':>14}{'n/$/tr':>14}{'n/$/tr':>14}")
    for y in ALL_YEARS:
        line = f"  {y:<6}"
        for p in PT_LEVELS:
            sub = shorts[p][shorts[p]["year"] == y] if p in shorts else pd.DataFrame()
            if not len(sub):
                line += f"{'-':>14}"
            else:
                line += f"{len(sub):>5} {sub['pnl_$'].mean():>+7.1f}"
        marker = " IS" if y in IS_YEARS else ""
        print(line + marker)

    # IS pool
    print(f"  {'IS':<6}", end="")
    for p in PT_LEVELS:
        if p in shorts:
            sub = shorts[p][shorts[p]["year"].isin(IS_YEARS)]
            if len(sub):
                print(f"{len(sub):>5} {sub['pnl_$'].mean():>+7.1f}", end="")
            else:
                print(f"{'-':>14}", end="")
    print()
    # OOS pool
    print(f"  {'OOS':<6}", end="")
    for p in PT_LEVELS:
        if p in shorts:
            sub = shorts[p][shorts[p]["year"].isin(OOS_YEARS)]
            if len(sub):
                yp = sum(1 for y in OOS_YEARS
                         if (s_y := sub[sub["year"] == y])["pnl_$"].mean() > 0 if len(s_y))
                print(f"{len(sub):>5} {sub['pnl_$'].mean():>+7.1f}", end="")
            else:
                print(f"{'-':>14}", end="")
    print()
    # OOS years positive
    print(f"  yrs+ ", end=" ")
    for p in PT_LEVELS:
        if p in shorts:
            sub = shorts[p][shorts[p]["year"].isin(OOS_YEARS)]
            yp = sum(1 for y in OOS_YEARS
                     if (s_y := sub[sub["year"] == y])["pnl_$"].mean() > 0 if len(s_y))
            print(f"{yp:>13}/4", end="")
    print()
    return shorts


def report_year_bootstrap_shorts(shorts_p4: pd.DataFrame, n_boot: int = 2000):
    print(f"\n{'='*92}\n  [2] YEAR BOOTSTRAP — SHORTS @ PT 2.0  ({n_boot} resamples)\n{'='*92}")
    print(f"  {'year':<6}{'n':>6}{'obs $/tr':>10}{'boot_mean':>11}"
          f"{'boot_p5':>10}{'boot_p95':>10}{'P(<=0)':>10}")
    rng = np.random.default_rng(42)
    for y in ALL_YEARS:
        sub = shorts_p4[shorts_p4["year"] == y]
        if not len(sub):
            continue
        pnl = sub["pnl_$"].to_numpy()
        means = np.array([
            rng.choice(pnl, size=len(pnl), replace=True).mean()
            for _ in range(n_boot)
        ])
        marker = " IS" if y in IS_YEARS else "   "
        p_neg = (means <= 0).mean()
        print(f"  {y:<6}{len(sub):>6}{pnl.mean():>+10.2f}"
              f"{means.mean():>+11.2f}{np.percentile(means, 5):>+10.2f}"
              f"{np.percentile(means, 95):>+10.2f}{p_neg:>10.1%} {marker}")


def report_rolling_shorts(shorts_p4: pd.DataFrame, windows=(50, 100)):
    print(f"\n{'='*92}\n  [3] ROLLING WINDOW STATS — SHORTS @ PT 2.0  (OOS chronological)\n{'='*92}")
    oos = shorts_p4[shorts_p4["year"].isin(OOS_YEARS)].sort_values("entry_ts").copy()
    print(f"  total OOS short trades: {len(oos)}")
    print(f"  cumulative OOS $: {oos['pnl_$'].sum():+,.0f}")
    print(f"  mean $/tr: {oos['pnl_$'].mean():+.2f}")
    for w in windows:
        rmean = oos["pnl_$"].rolling(w, min_periods=w).mean()
        rstd  = oos["pnl_$"].rolling(w, min_periods=w).std()
        rsharpe = rmean / rstd
        valid = rsharpe.dropna()
        if not len(valid):
            continue
        print(f"\n  Rolling {w}-trade:")
        print(f"    mean $/tr: median {rmean.dropna().median():+.2f}, "
              f"5th {np.percentile(rmean.dropna(), 5):+.2f}, "
              f"95th {np.percentile(rmean.dropna(), 95):+.2f}")
        print(f"    Sharpe   : median {valid.median():+.3f}, "
              f"5th {np.percentile(valid, 5):+.3f}, "
              f"95th {np.percentile(valid, 95):+.3f}")
        print(f"    % windows mean > 0: {(rmean.dropna() > 0).mean():.1%}")
        if rmean.notna().any():
            wid = rmean.idxmin()
            ts = pd.to_datetime(oos.loc[wid, "entry_ts"])
            print(f"    worst {w}-trade window: ${rmean.min():+.2f}/tr  centered ~{ts.date()}")
            bid = rmean.idxmax()
            ts = pd.to_datetime(oos.loc[bid, "entry_ts"])
            print(f"    best  {w}-trade window: ${rmean.max():+.2f}/tr  centered ~{ts.date()}")


def report_monthly_shorts_all_years(shorts_p4: pd.DataFrame):
    print(f"\n{'='*92}\n  [4] MONTHLY PnL — SHORTS @ PT 2.0 ALL YEARS\n{'='*92}")
    df = shorts_p4.copy()
    df["month"] = pd.to_datetime(df["entry_ts"]).dt.to_period("M").astype(str)
    monthly = df.groupby("month")["pnl_$"].agg(["count", "mean", "sum"]).reset_index()
    # Flag months with sum < -3000 (~bad cluster equivalent of 2024 long collapse)
    bad_mo = monthly[monthly["sum"] < -3000]
    print(f"  Total months: {len(monthly)}")
    print(f"  Mean monthly $: {monthly['sum'].mean():+,.0f}, "
          f"median: {monthly['sum'].median():+,.0f}")
    print(f"  Months with sum > 0: {(monthly['sum'] > 0).mean():.1%}")
    print(f"  Worst 5 months:")
    for _, r in monthly.nsmallest(5, "sum").iterrows():
        print(f"    {r['month']:<10} n={int(r['count']):>4} $/tr={r['mean']:>+8.1f} "
              f"total$={r['sum']:>+9,.0f}")
    print(f"  Best 5 months:")
    for _, r in monthly.nlargest(5, "sum").iterrows():
        print(f"    {r['month']:<10} n={int(r['count']):>4} $/tr={r['mean']:>+8.1f} "
              f"total$={r['sum']:>+9,.0f}")
    if len(bad_mo):
        print(f"\n  Months with sum < -$3,000 (short-collapse equivalents):")
        for _, r in bad_mo.iterrows():
            print(f"    {r['month']:<10} n={int(r['count']):>4} $/tr={r['mean']:>+8.1f} "
                  f"total$={r['sum']:>+9,.0f}")
    else:
        print(f"\n  No months with sum < -$3,000 — shorts have no equivalent of long collapse.")


def report_is_oos_divergence(shorts_p4: pd.DataFrame):
    print(f"\n{'='*92}\n  [5] IS->OOS DIVERGENCE DIAGNOSTIC — SHORTS @ PT 2.0\n{'='*92}")
    is_ = shorts_p4[shorts_p4["year"].isin(IS_YEARS)]
    oos = shorts_p4[shorts_p4["year"].isin(OOS_YEARS)]
    print(f"  IS  shorts: n={len(is_)}, $/tr={is_['pnl_$'].mean():+.2f}, "
          f"WR={(is_['pnl_$']>0).mean():.1%}")
    print(f"  OOS shorts: n={len(oos)}, $/tr={oos['pnl_$'].mean():+.2f}, "
          f"WR={(oos['pnl_$']>0).mean():.1%}")
    # ATR distribution shift
    print(f"\n  Entry ATR distribution shift:")
    print(f"    IS  mean ATR: {is_['entry_atr'].mean():.3f}  median {is_['entry_atr'].median():.3f}")
    print(f"    OOS mean ATR: {oos['entry_atr'].mean():.3f}  median {oos['entry_atr'].median():.3f}")
    # PT-vs-regime mix
    print(f"\n  Exit-reason mix:")
    for label, df in [("IS", is_), ("OOS", oos)]:
        ex = df["exit_reason"].value_counts(normalize=True)
        print(f"    {label}: PT={ex.get('PT', 0):.1%}, regime_flip={ex.get('regime_flip', 0):.1%}, "
              f"max_hold={ex.get('max_hold', 0):.1%}")
    # Per-year exit mix
    print(f"\n  Per-year PT-hit rate (shorts):")
    for y in ALL_YEARS:
        sub = shorts_p4[shorts_p4["year"] == y]
        if not len(sub):
            continue
        pt_rate = (sub["exit_reason"] == "PT").mean()
        marker = " IS" if y in IS_YEARS else "   "
        print(f"    {y}: PT-hit={pt_rate:.1%}  n={len(sub):>4}  {marker}")
    print(f"\n  Hypothesis check: if IS shorts lose because PT hits less,")
    print(f"  we'd see lower PT-hit rate in IS than OOS. Let's see.")


def report_pt_vs_regime_split(shorts_p4: pd.DataFrame):
    print(f"\n{'='*92}\n  [6] PT VS REGIME-EXIT split — SHORTS @ PT 2.0\n{'='*92}")
    print(f"  {'year':<6}{'n':>6}"
          f"{'PT n':>6}{'PT $/tr':>10}"
          f"{'reg n':>7}{'reg $/tr':>10}"
          f"{'PT%':>7}")
    for y in ALL_YEARS:
        sub = shorts_p4[shorts_p4["year"] == y]
        if not len(sub):
            continue
        pt = sub[sub["exit_reason"] == "PT"]
        rg = sub[sub["exit_reason"] == "regime_flip"]
        marker = " IS" if y in IS_YEARS else ""
        pt_rate = len(pt) / len(sub) if len(sub) else 0
        print(f"  {y:<6}{len(sub):>6}"
              f"{len(pt):>6}{pt['pnl_$'].mean():>+10.2f}"
              f"{len(rg):>7}{rg['pnl_$'].mean():>+10.2f}"
              f"{pt_rate:>7.1%}  {marker}")


def main():
    base = load_pt_trades(2.0)
    if not len(base):
        print("ERR: PT 2.0 trades not found"); return
    shorts_p4 = base[base["signal_direction"] == -1].copy()
    print(f"Loaded {len(base):,} PT 2.0 trades, "
          f"of which {len(shorts_p4):,} are SHORTS ({len(shorts_p4)/len(base):.1%})")

    report_pt_sensitivity_shorts()
    report_year_bootstrap_shorts(shorts_p4)
    report_rolling_shorts(shorts_p4)
    report_monthly_shorts_all_years(shorts_p4)
    report_is_oos_divergence(shorts_p4)
    report_pt_vs_regime_split(shorts_p4)


if __name__ == "__main__":
    main()
