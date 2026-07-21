"""Task 3B — Monthly block bootstrap on production OOS.

Critic's point: with 70% of edge in 2 clusters, IID per-trade bootstrap is
wrong. Re-cast on monthly P&L blocks: the effective n is ~48 (OOS months),
not 1,252 (OOS trades), and the t-stat is much smaller.

Method:
  - Aggregate production OOS trades to monthly P&L (sum per UTC month)
  - Block-bootstrap: resample MONTHS with replacement, 10,000 iterations
  - Report: mean monthly $, mean implied $/tr, 5th/95th pct, P(<=0)
  - Compare to naive trade-level bootstrap to show the difference
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
OOS_YEARS = (2023, 2024, 2025, 2026)


def load_production():
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
        df["month"] = df["entry_dt"].dt.to_period("M").astype(str)
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def monthly_aggregate(tr: pd.DataFrame) -> pd.DataFrame:
    monthly = tr.groupby("month").agg(
        n_trades=("pnl_$", "count"),
        total_dollars=("pnl_$", "sum"),
        mean_dollars_per_tr=("pnl_$", "mean"),
    ).reset_index()
    monthly = monthly.rename(columns={"total_dollars": "total_$",
                                       "mean_dollars_per_tr": "mean_$_per_tr"})
    return monthly


def block_bootstrap_monthly(monthly: pd.DataFrame, n_iter=10000, seed=42):
    """Resample MONTHS with replacement, n_iter times. Report distribution of
    pooled mean $/tr (weighted by month n_trades)."""
    rng = np.random.default_rng(seed)
    n_months = len(monthly)
    n_trades_arr = monthly["n_trades"].to_numpy()
    total_arr    = monthly["total_$"].to_numpy()

    means = np.zeros(n_iter)
    yearly_pnl = np.zeros(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n_months, size=n_months)
        tot = total_arr[idx].sum()
        n = n_trades_arr[idx].sum()
        means[i] = tot / n if n > 0 else 0
        yearly_pnl[i] = tot / (n_months / 12.0)   # annualized

    return means, yearly_pnl


def iid_trade_bootstrap(tr: pd.DataFrame, n_iter=10000, seed=42):
    rng = np.random.default_rng(seed)
    pnl = tr["pnl_$"].to_numpy()
    n = len(pnl)
    means = np.array([rng.choice(pnl, size=n, replace=True).mean()
                      for _ in range(n_iter)])
    return means


def main():
    tr = load_production()
    print(f"Production OOS trades: {len(tr):,}")
    print(f"Pooled obs $/tr: ${tr['pnl_$'].mean():+.2f}")
    print(f"Pooled obs total$: ${tr['pnl_$'].sum():+,.0f}")

    monthly = monthly_aggregate(tr)
    print(f"\nMonthly aggregate: {len(monthly)} OOS months")
    print(f"  monthly mean: ${monthly['total_$'].mean():+,.0f}")
    print(f"  monthly std:  ${monthly['total_$'].std():+,.0f}")
    print(f"  monthly min:  ${monthly['total_$'].min():+,.0f}")
    print(f"  monthly max:  ${monthly['total_$'].max():+,.0f}")
    print(f"\n  Top-5 best months:")
    for _, r in monthly.nlargest(5, "total_$").iterrows():
        print(f"    {r['month']:<10} n={int(r['n_trades']):>3}  "
              f"$/tr={r['mean_$_per_tr']:>+7.2f}  total=${r['total_$']:>+9,.0f}")
    print(f"\n  Top-5 worst months:")
    for _, r in monthly.nsmallest(5, "total_$").iterrows():
        print(f"    {r['month']:<10} n={int(r['n_trades']):>3}  "
              f"$/tr={r['mean_$_per_tr']:>+7.2f}  total=${r['total_$']:>+9,.0f}")

    # Naive monthly t-stat
    monthly_mu = monthly["total_$"].mean()
    monthly_sd = monthly["total_$"].std()
    n_mo = len(monthly)
    naive_t_monthly = monthly_mu / (monthly_sd / np.sqrt(n_mo))
    print(f"\nNaive monthly t-stat: {naive_t_monthly:.2f}")
    print(f"  (vs naive trade-level z=14.4 the critic flagged)")

    # Monthly block bootstrap (the proper test)
    print(f"\n=== MONTHLY BLOCK BOOTSTRAP (10,000 iter, resample months with replacement) ===")
    means, yearly = block_bootstrap_monthly(monthly, n_iter=10000)
    print(f"  Bootstrap mean $/tr:")
    print(f"    mean:    ${means.mean():+.2f}")
    print(f"    std:     ${means.std():.2f}")
    print(f"    5th:     ${np.percentile(means, 5):+.2f}")
    print(f"    25th:    ${np.percentile(means, 25):+.2f}")
    print(f"    median:  ${np.percentile(means, 50):+.2f}")
    print(f"    75th:    ${np.percentile(means, 75):+.2f}")
    print(f"    95th:    ${np.percentile(means, 95):+.2f}")
    print(f"    P(<=0):  {(means <= 0).mean():.1%}")
    print(f"    P(<=$5): {(means <= 5).mean():.1%}")
    print(f"    P(<=$10):{(means <= 10).mean():.1%}")

    print(f"\n  Bootstrap annualized PnL ($):")
    print(f"    mean:    ${yearly.mean():+,.0f}")
    print(f"    5th:     ${np.percentile(yearly, 5):+,.0f}")
    print(f"    median:  ${np.percentile(yearly, 50):+,.0f}")
    print(f"    95th:    ${np.percentile(yearly, 95):+,.0f}")
    print(f"    P(annualized PnL <=0): {(yearly <= 0).mean():.1%}")

    # IID trade-level bootstrap (the WRONG test for comparison)
    print(f"\n=== IID TRADE-LEVEL BOOTSTRAP (the WRONG test) ===")
    iid_means = iid_trade_bootstrap(tr, n_iter=10000)
    print(f"  Trade-IID bootstrap mean $/tr:")
    print(f"    mean:    ${iid_means.mean():+.2f}")
    print(f"    std:     ${iid_means.std():.2f}")
    print(f"    5th:     ${np.percentile(iid_means, 5):+.2f}")
    print(f"    95th:    ${np.percentile(iid_means, 95):+.2f}")
    print(f"    P(<=0):  {(iid_means <= 0).mean():.1%}")
    print(f"\n  Note: trade-level CI is ~{iid_means.std():.2f} wide;")
    print(f"  monthly-block CI is ~{means.std():.2f} wide — {means.std()/iid_means.std():.1f}x")
    print(f"  The IID assumption understates uncertainty by that factor.")

    # Per-year monthly bootstrap
    print(f"\n=== PER-YEAR MONTHLY BLOCK BOOTSTRAP ===")
    print(f"  {'year':<6}{'obs $/tr':>10}{'boot mean':>11}{'5th':>9}{'95th':>9}"
          f"{'P(<=0)':>10}")
    for y in OOS_YEARS:
        y_mo = monthly[monthly["month"].str.startswith(str(y))]
        if not len(y_mo):
            continue
        ym, _ = block_bootstrap_monthly(y_mo, n_iter=10000, seed=42+y)
        obs = tr[tr["year"] == y]["pnl_$"].mean()
        print(f"  {y:<6}{obs:>+10.2f}{ym.mean():>+11.2f}"
              f"{np.percentile(ym, 5):>+9.2f}{np.percentile(ym, 95):>+9.2f}"
              f"{(ym <= 0).mean():>10.1%}")


if __name__ == "__main__":
    main()
