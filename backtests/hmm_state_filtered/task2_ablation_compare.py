"""Task 2 — HMM ablation comparison.

(A) Production: HMM state-3 filter + bar1_confirm + PT 2.0 ATR + regime exit
(B) Ablation:   bar1_confirm + PT 2.0 ATR + regime exit (no state filter)

Decision rule per the brief: if (B) tracks (A) within noise, the HMM is
decorative and we should reframe around the trend-follow entry itself.

Reports:
  - Per-year + pooled: n, WR, $/tr, total$
  - Long/short split per year
  - Aug-Oct 2024 long cluster for both
  - Year bootstrap P(<=0) for both
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
CRASH_MO = ["2024-08", "2024-09", "2024-10"]


def load(prefix: str) -> pd.DataFrame:
    rows = []
    for y in OOS_YEARS:
        p = RES / f"{prefix}_{y}/trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not len(df):
            continue
        df["year"] = y
        df["pnl_$"] = ((df["exit_px"] - df["entry_px"])
                        * df["signal_direction"] * NQ_MULT - COMM)
        df["entry_dt"] = pd.to_datetime(df["entry_ts"])
        df["month"] = df["entry_dt"].dt.to_period("M").astype(str)
        rows.append(df)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def report_headline(prod, abl):
    print(f"\n{'='*92}\n  HEADLINE: (A) state-3 + bar1 vs (B) bar1 only (no state filter)\n{'='*92}")
    print(f"  {'year':<6}{'(A) n':>7}{'(A) WR':>9}{'(A) $/tr':>10}{'(A) tot$':>11}"
          f"{'(B) n':>7}{'(B) WR':>9}{'(B) $/tr':>10}{'(B) tot$':>11}")
    pa, pb = [], []
    yp_a, yp_b = 0, 0
    for y in OOS_YEARS:
        a = prod[prod["year"] == y]
        b = abl[abl["year"] == y]
        if not len(a) and not len(b):
            continue
        a_mean = a["pnl_$"].mean() if len(a) else float("nan")
        b_mean = b["pnl_$"].mean() if len(b) else float("nan")
        a_wr = (a["pnl_$"] > 0).mean() if len(a) else float("nan")
        b_wr = (b["pnl_$"] > 0).mean() if len(b) else float("nan")
        print(f"  {y:<6}"
              f"{len(a):>7}{a_wr:>9.1%}{a_mean:>+10.2f}{a['pnl_$'].sum():>+11,.0f}"
              f"{len(b):>7}{b_wr:>9.1%}{b_mean:>+10.2f}{b['pnl_$'].sum():>+11,.0f}")
        if len(a):
            pa.append(a);
            if a_mean > 0: yp_a += 1
        if len(b):
            pb.append(b)
            if b_mean > 0: yp_b += 1
    if pa and pb:
        a = pd.concat(pa); b = pd.concat(pb)
        print(f"  {'OOS':<6}"
              f"{len(a):>7}{(a['pnl_$']>0).mean():>9.1%}{a['pnl_$'].mean():>+10.2f}{a['pnl_$'].sum():>+11,.0f}"
              f"{len(b):>7}{(b['pnl_$']>0).mean():>9.1%}{b['pnl_$'].mean():>+10.2f}{b['pnl_$'].sum():>+11,.0f}")
        print(f"  yrs+  ({yp_a}/4)                                ({yp_b}/4)")


def report_long_short(prod, abl):
    print(f"\n{'='*92}\n  LONG / SHORT split — (A) production vs (B) ablation\n{'='*92}")
    for side, dir_ in [("LONGS", 1), ("SHORTS", -1)]:
        print(f"\n  {side}:")
        print(f"  {'year':<6}{'(A) n':>7}{'(A) $/tr':>10}{'(A) tot$':>11}"
              f"{'(B) n':>7}{'(B) $/tr':>10}{'(B) tot$':>11}")
        for y in OOS_YEARS:
            a = prod[(prod["year"] == y) & (prod["signal_direction"] == dir_)]
            b = abl[(abl["year"] == y) & (abl["signal_direction"] == dir_)]
            if not len(a) and not len(b):
                continue
            print(f"  {y:<6}"
                  f"{len(a):>7}{a['pnl_$'].mean() if len(a) else 0:>+10.2f}"
                  f"{a['pnl_$'].sum() if len(a) else 0:>+11,.0f}"
                  f"{len(b):>7}{b['pnl_$'].mean() if len(b) else 0:>+10.2f}"
                  f"{b['pnl_$'].sum() if len(b) else 0:>+11,.0f}")
        # OOS pool
        a = prod[prod["signal_direction"] == dir_]
        b = abl[abl["signal_direction"] == dir_]
        print(f"  {'OOS':<6}"
              f"{len(a):>7}{a['pnl_$'].mean():>+10.2f}{a['pnl_$'].sum():>+11,.0f}"
              f"{len(b):>7}{b['pnl_$'].mean():>+10.2f}{b['pnl_$'].sum():>+11,.0f}")


def report_2024_crash(prod, abl):
    print(f"\n{'='*92}\n  Aug-Oct 2024 LONGS — does removing state filter help/hurt the cluster?\n{'='*92}")
    for label, df in [("(A) production", prod), ("(B) ablation", abl)]:
        crash = df[(df["year"] == 2024)
                    & (df["signal_direction"] == 1)
                    & (df["month"].isin(CRASH_MO))]
        if not len(crash):
            continue
        print(f"  {label:<18} n={len(crash):>4} WR={(crash['pnl_$']>0).mean():.1%} "
              f"$/tr={crash['pnl_$'].mean():>+8.2f} total${crash['pnl_$'].sum():>+9,.0f}")


def report_bootstrap(prod, abl, n_boot=2000):
    print(f"\n{'='*92}\n  YEAR BOOTSTRAP P(<=0) — production vs ablation\n{'='*92}")
    print(f"  {'year':<6}{'(A) obs $/tr':>15}{'(A) P(<=0)':>14}"
          f"{'(B) obs $/tr':>15}{'(B) P(<=0)':>14}")
    rng = np.random.default_rng(42)
    for y in OOS_YEARS:
        a = prod[prod["year"] == y]["pnl_$"].to_numpy()
        b = abl[abl["year"] == y]["pnl_$"].to_numpy()
        if not len(a) or not len(b):
            continue
        a_means = np.array([rng.choice(a, size=len(a), replace=True).mean()
                            for _ in range(n_boot)])
        b_means = np.array([rng.choice(b, size=len(b), replace=True).mean()
                            for _ in range(n_boot)])
        a_p = (a_means <= 0).mean()
        b_p = (b_means <= 0).mean()
        print(f"  {y:<6}{a.mean():>+15.2f}{a_p:>14.1%}{b.mean():>+15.2f}{b_p:>14.1%}")


def main():
    prod = load("nq_hmm_4_s3_pt2p0")
    abl  = load("nq_hmm_4_s-1_pt2p0_noStFilter")
    print(f"Production (state-3 filter): {len(prod):,} OOS trades")
    print(f"Ablation   (no state filter): {len(abl):,} OOS trades")
    print(f"Ablation expansion ratio: {len(abl)/len(prod):.2f}x trade count")
    report_headline(prod, abl)
    report_long_short(prod, abl)
    report_2024_crash(prod, abl)
    report_bootstrap(prod, abl)


if __name__ == "__main__":
    main()
