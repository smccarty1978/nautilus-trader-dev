"""Robustness battery for static P4 baseline.

Inputs (all from existing NT P4 trades.parquet per year):
  backtests/hmm_state_filtered/results/nq_hmm_4_s3_pt2p0_{Y}/trades.parquet
  + nq_hmm_4_s3_pt1p5_{Y}/   (PT 1.5 sensitivity sweep)
  + nq_hmm_4_s3_pt1p8_{Y}/   (PT 1.8 sensitivity sweep)
  + nq_hmm_4_s3_pt2p5_{Y}/   (PT 2.5 sensitivity sweep)

Battery (5 tests, all on the bar1_confirm + hmm_4=3 + PT entries):
  1. PT sensitivity: per-year and pooled $/tr at PT 1.5, 1.8, 2.0, 2.5
  2. Long/short split: PnL per direction per year + pooled
  3. Year bootstrap: 2000 resamples per year, distribution of mean PnL
  4. Rolling 50 / 100-trade equity + Sharpe in chronological order (pooled OOS)
  5. 2024 drawdown cluster: max DD sequence, time clustering of losers

Success bar: "real but regime-sensitive" if year-positive count and bootstrap
year-significance survive; "fragile" if year-mean P(<= 0) > 30% in any year.
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
    """Load NT P4 trades for a given PT level across all years."""
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


def report_pt_sensitivity():
    print(f"\n{'='*92}\n  [1] PT SENSITIVITY  (bar1_confirm + hmm_4=3, regime-exit fallback)\n{'='*92}")
    cohorts = {p: load_pt_trades(p) for p in PT_LEVELS}
    have = [p for p, df in cohorts.items() if len(df)]
    if not have:
        print("  no PT sensitivity cohorts found (sweeps may not have completed)")
        return cohorts

    print(f"  {'year':<6}", end="")
    for p in PT_LEVELS:
        if p in have:
            print(f"{'PT'+str(p):>14}", end="")
    print()
    print(f"  {'':>6}", end="")
    for p in PT_LEVELS:
        if p in have:
            print(f"{'n / $/tr':>14}", end="")
    print()

    for y in ALL_YEARS:
        marker = " IS" if y in IS_YEARS else "   "
        print(f"  {y:<6}", end="")
        for p in PT_LEVELS:
            if p in have:
                sub = cohorts[p][cohorts[p]["year"] == y]
                if not len(sub):
                    print(f"{'-':>14}", end="")
                else:
                    print(f"{len(sub):>5} {sub['pnl_$'].mean():>+7.1f}", end="")
        print(f" {marker}")

    print(f"  {'OOS':<6}", end="")
    for p in PT_LEVELS:
        if p in have:
            sub = cohorts[p][cohorts[p]["year"].isin(OOS_YEARS)]
            if not len(sub):
                print(f"{'-':>14}", end="")
            else:
                yp = sum(1 for y in OOS_YEARS
                         if (sub_y := sub[sub["year"] == y])["pnl_$"].mean() > 0
                            if len(sub_y))
                print(f"{len(sub):>5} {sub['pnl_$'].mean():>+7.1f}", end="")
    print(f" {'':<6}")
    print(f"  yrs+ ", end=" ")
    for p in PT_LEVELS:
        if p in have:
            sub = cohorts[p][cohorts[p]["year"].isin(OOS_YEARS)]
            yp = sum(1 for y in OOS_YEARS
                     if (sub_y := sub[sub["year"] == y])["pnl_$"].mean() > 0
                        if len(sub_y))
            print(f"{yp:>13}/4", end="")
    print()
    return cohorts


def report_long_short_split(df: pd.DataFrame, label: str):
    print(f"\n{'='*92}\n  [2] LONG / SHORT split  ({label})\n{'='*92}")
    print(f"  {'year':<6}"
          f"{'long n':>8}{'long_$':>10}{'long_WR':>10}"
          f"{'short n':>9}{'short_$':>10}{'short_WR':>10}")
    pool_l, pool_s = [], []
    for y in ALL_YEARS:
        sub = df[df["year"] == y]
        if not len(sub):
            continue
        lo = sub[sub["signal_direction"] == 1]
        sh = sub[sub["signal_direction"] == -1]
        marker = " IS" if y in IS_YEARS else "   "
        print(f"  {y:<6}"
              f"{len(lo):>8}{lo['pnl_$'].mean():>+10.2f}{(lo['pnl_$']>0).mean():>10.1%}"
              f"{len(sh):>9}{sh['pnl_$'].mean():>+10.2f}{(sh['pnl_$']>0).mean():>10.1%}"
              f" {marker}")
        if y in OOS_YEARS:
            pool_l.append(lo)
            pool_s.append(sh)
    lo = pd.concat(pool_l) if pool_l else df.iloc[:0]
    sh = pd.concat(pool_s) if pool_s else df.iloc[:0]
    print(f"  {'OOS':<6}"
          f"{len(lo):>8}{lo['pnl_$'].mean():>+10.2f}{(lo['pnl_$']>0).mean():>10.1%}"
          f"{len(sh):>9}{sh['pnl_$'].mean():>+10.2f}{(sh['pnl_$']>0).mean():>10.1%}")


def report_year_bootstrap(df: pd.DataFrame, n_boot: int = 2000):
    print(f"\n{'='*92}\n  [3] YEAR BOOTSTRAP  ({n_boot} resamples per year, with replacement)\n{'='*92}")
    print(f"  {'year':<6}{'n':>6}{'obs_$/tr':>10}"
          f"{'boot_mean':>11}{'boot_p5':>10}{'boot_p95':>10}{'P(<=0)':>10}")
    rng = np.random.default_rng(42)
    for y in ALL_YEARS:
        sub = df[df["year"] == y]
        if not len(sub):
            continue
        pnl = sub["pnl_$"].to_numpy()
        means = np.zeros(n_boot)
        for i in range(n_boot):
            samp = rng.choice(pnl, size=len(pnl), replace=True)
            means[i] = samp.mean()
        marker = " IS" if y in IS_YEARS else "   "
        p_neg = (means <= 0).mean()
        print(f"  {y:<6}{len(sub):>6}{pnl.mean():>+10.2f}"
              f"{means.mean():>+11.2f}{np.percentile(means, 5):>+10.2f}"
              f"{np.percentile(means, 95):>+10.2f}{p_neg:>10.1%} {marker}")


def report_rolling_equity(df: pd.DataFrame, windows=(50, 100)):
    """OOS chronological pooled rolling stats."""
    print(f"\n{'='*92}\n  [4] ROLLING TRADE-WINDOW STATS  (OOS chronological, windows {windows})\n{'='*92}")
    oos = df[df["year"].isin(OOS_YEARS)].sort_values("entry_ts").copy()
    oos["cum_$"] = oos["pnl_$"].cumsum()
    print(f"  total OOS trades: {len(oos)}")
    print(f"  cumulative OOS $: {oos['pnl_$'].sum():+,.0f}")

    for w in windows:
        rmean = oos["pnl_$"].rolling(w, min_periods=w).mean()
        rstd  = oos["pnl_$"].rolling(w, min_periods=w).std()
        rsharpe = rmean / rstd
        valid = rsharpe.dropna()
        if not len(valid):
            continue
        print(f"\n  Rolling {w}-trade window:")
        print(f"    mean $/tr: median {rmean.dropna().median():+.2f}, "
              f"5th {np.percentile(rmean.dropna(), 5):+.2f}, "
              f"95th {np.percentile(rmean.dropna(), 95):+.2f}")
        print(f"    Sharpe   : median {valid.median():+.3f}, "
              f"5th {np.percentile(valid, 5):+.3f}, "
              f"95th {np.percentile(valid, 95):+.3f}")
        # % of rolling windows positive
        print(f"    % windows with mean > 0: {(rmean.dropna() > 0).mean():.1%}")
        # worst window
        worst_idx = rmean.idxmin()
        if worst_idx is not None and worst_idx in oos.index:
            ts = pd.to_datetime(oos.loc[worst_idx, "entry_ts"])
            print(f"    worst {w}-trade window: ${rmean.min():+.2f}/tr  (centered ~{ts.date()})")
        best_idx = rmean.idxmax()
        if best_idx is not None and best_idx in oos.index:
            ts = pd.to_datetime(oos.loc[best_idx, "entry_ts"])
            print(f"    best  {w}-trade window: ${rmean.max():+.2f}/tr  (centered ~{ts.date()})")


def report_2024_drawdown(df: pd.DataFrame):
    print(f"\n{'='*92}\n  [5] 2024 DRAWDOWN CLUSTER ANALYSIS\n{'='*92}")
    y24 = df[df["year"] == 2024].sort_values("entry_ts").copy().reset_index(drop=True)
    if not len(y24):
        print("  no 2024 trades found"); return
    y24["cum_$"] = y24["pnl_$"].cumsum()
    print(f"  2024 trades: {len(y24)}, total PnL ${y24['pnl_$'].sum():+,.0f}, "
          f"mean ${y24['pnl_$'].mean():+.2f}/tr")

    # Max drawdown: peak-to-trough on cumulative equity
    running_max = y24["cum_$"].cummax()
    dd = y24["cum_$"] - running_max
    max_dd = dd.min()
    max_dd_end = dd.idxmin()
    max_dd_start = y24["cum_$"][:max_dd_end + 1].idxmax() if max_dd_end is not None else 0
    print(f"  Max drawdown: ${max_dd:+,.0f}")
    if max_dd_start is not None and max_dd_end is not None:
        ts_s = pd.to_datetime(y24.loc[max_dd_start, "entry_ts"])
        ts_e = pd.to_datetime(y24.loc[max_dd_end, "entry_ts"])
        dur_trades = max_dd_end - max_dd_start
        print(f"  DD window: trade {max_dd_start}..{max_dd_end} "
              f"({ts_s.date()} → {ts_e.date()}, {dur_trades} trades)")

    # Longest losing streak
    is_loss = (y24["pnl_$"] < 0).astype(int)
    streaks = []
    cur = 0
    for v in is_loss:
        if v: cur += 1
        else:
            if cur: streaks.append(cur)
            cur = 0
    if cur: streaks.append(cur)
    if streaks:
        print(f"  Longest losing streak: {max(streaks)} consecutive losers")

    # Monthly breakdown
    y24["month"] = pd.to_datetime(y24["entry_ts"]).dt.to_period("M").astype(str)
    monthly = y24.groupby("month")["pnl_$"].agg(["count", "mean", "sum"])
    print(f"\n  Monthly 2024 PnL:")
    print(f"  {'month':<10}{'n':>6}{'$/tr':>10}{'total$':>12}")
    for m, r in monthly.iterrows():
        marker = "  <<<" if r["sum"] < -3000 else ""
        print(f"  {m:<10}{int(r['count']):>6}{r['mean']:>+10.2f}{r['sum']:>+12.0f}{marker}")


def main():
    # Load PT 2.0 baseline (always present)
    base = load_pt_trades(2.0)
    if not len(base):
        print("ERR: PT 2.0 baseline trades not found"); return
    print(f"Loaded {len(base):,} PT 2.0 baseline trades across "
          f"years {sorted(base['year'].unique())}")

    # [1] PT sensitivity (will show only PT 2.0 if other sweeps not done yet)
    report_pt_sensitivity()

    # [2] Long/short split
    report_long_short_split(base, "PT 2.0 baseline")

    # [3] Year bootstrap
    report_year_bootstrap(base)

    # [4] Rolling trade window stats
    report_rolling_equity(base)

    # [5] 2024 drawdown cluster
    report_2024_drawdown(base)


if __name__ == "__main__":
    main()
