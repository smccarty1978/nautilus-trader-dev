"""Re-compute 1s vs tick gap on 2025 EXCLUDING roll windows.

NQ quarterly expiries (3rd Friday of Mar/Jun/Sep/Dec 2025):
  Mar 21, Jun 20, Sep 19, Dec 19

NQ.v.0 (volume-weighted continuous) and NQ.c.0 (calendar-front
continuous) track DIFFERENT contracts within ~10 days of expiry as
volume migrates to back month. Outside that window they should be
on the SAME underlying contract month.

Filter: drop trades whose entry_ts falls within ±10 days of any
quarterly expiry. Compute remaining gap.

This isn't a perfect same-contract comparison (chain progression on
filtered data isn't exactly what a date-filtered NT run would
produce), but per-trade PnL on matching trades should be cleaner.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/level_momentum_continuation/results_breakout")
NQ_MULT = 20.0

# NQ 2025 quarterly expiries (3rd Friday)
NQ_EXPIRIES_2025 = [
    date(2025, 3, 21),
    date(2025, 6, 20),
    date(2025, 9, 19),
    date(2025, 12, 19),
]


def in_roll_window(d: date, window_days: int) -> bool:
    return any(abs((d - e).days) <= window_days for e in NQ_EXPIRIES_2025)


def main():
    df_1s = pd.read_parquet(OUT / "nt_v0_2025_clean_1s_trades.parquet")
    df_tk = pd.read_parquet(OUT / "nt_v0_2025_clean_tick_trades.parquet")

    df_1s["entry_dt"] = pd.to_datetime(df_1s["c1_fill_ts"], unit="ns",
                                          utc=True)
    df_tk["entry_dt"] = pd.to_datetime(df_tk["c1_fill_ts"], unit="ns",
                                          utc=True)
    df_1s["entry_date"] = df_1s["entry_dt"].dt.date
    df_tk["entry_date"] = df_tk["entry_dt"].dt.date

    print(f"Original counts:")
    print(f"  1s NT: {len(df_1s):,} trades")
    print(f"  tick NT: {len(df_tk):,} trades")

    print(f"\nGap analysis with progressively WIDER exclusion windows around")
    print(f"NQ 2025 quarterly expiries (Mar 21, Jun 20, Sep 19, Dec 19):")
    print(f"\n  {'window':<10} {'1s_n':>6} {'1s_$':>10} {'tk_n':>6} "
          f"{'tk_$':>10} {'Δ':>10} {'Δ$/tr_1s':>10} {'Δ$/tr_match':>12}")

    for w in [0, 3, 5, 7, 10, 14, 21]:
        if w == 0:
            df_1s_f = df_1s.copy()
            df_tk_f = df_tk.copy()
        else:
            df_1s_f = df_1s[
                ~df_1s["entry_date"].apply(lambda d: in_roll_window(d, w))
            ].copy()
            df_tk_f = df_tk[
                ~df_tk["entry_date"].apply(lambda d: in_roll_window(d, w))
            ].copy()
        n_1s = len(df_1s_f); n_tk = len(df_tk_f)
        # Recompute PnL: c1_pnl_pts * NQ_MULT - 5 (commission)
        pnl_1s = float(df_1s_f["c1_pnl_pts"].sum() * NQ_MULT
                         - 5.0 * n_1s)
        pnl_tk = float(df_tk_f["c1_pnl_pts"].sum() * NQ_MULT
                         - 5.0 * n_tk)
        delta = pnl_tk - pnl_1s
        delta_per_1s = delta / max(1, n_1s)
        # Per-trade gap on AVERAGE (using mean of n's as denominator)
        delta_per_match = delta / max(1, (n_1s + n_tk) / 2)
        print(f"  ±{w:>2}d      {n_1s:>6,} {pnl_1s:>+9,.0f} {n_tk:>6,} "
              f"{pnl_tk:>+9,.0f} {delta:>+9,.0f} {delta_per_1s:>+9.2f} "
              f"{delta_per_match:>+11.2f}")

    # Per-group at ±10 day exclusion
    w = 10
    df_1s_f = df_1s[
        ~df_1s["entry_date"].apply(lambda d: in_roll_window(d, w))
    ].copy()
    df_tk_f = df_tk[
        ~df_tk["entry_date"].apply(lambda d: in_roll_window(d, w))
    ].copy()

    print(f"\n{'='*78}")
    print(f"PER-GROUP AT ±10d ROLL EXCLUSION")
    print(f"{'='*78}")
    print(f"  {'group':<14} {'1s_n':>5} {'1s_$':>10} {'1s_$/tr':>9}  "
          f"{'tk_n':>5} {'tk_$':>10} {'tk_$/tr':>9}  {'Δ_$/tr':>8}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g1 = df_1s_f[df_1s_f["group"] == grp]
        gt = df_tk_f[df_tk_f["group"] == grp]
        n1 = len(g1); nt = len(gt)
        if n1 == 0 or nt == 0: continue
        p1 = float(g1["c1_pnl_pts"].sum() * NQ_MULT - 5.0 * n1)
        pt = float(gt["c1_pnl_pts"].sum() * NQ_MULT - 5.0 * nt)
        print(f"  {grp:<14} {n1:>5,} {p1:>+9,.0f} {p1/n1:>+8.2f}  "
              f"{nt:>5,} {pt:>+9,.0f} {pt/nt:>+8.2f}  "
              f"{(pt/nt - p1/n1):>+7.2f}")

    # Monthly PnL pattern post-filter
    print(f"\n{'='*78}")
    print(f"MONTHLY PnL AT ±10d EXCLUSION (months that survive)")
    print(f"{'='*78}")
    df_1s_f["month"] = df_1s_f["entry_dt"].dt.to_period("M")
    df_tk_f["month"] = df_tk_f["entry_dt"].dt.to_period("M")
    months_keep = sorted(set(df_1s_f["month"]) & set(df_tk_f["month"]))
    print(f"  {'month':<10} {'1s_n':>5} {'1s_$':>10} {'tk_n':>5} {'tk_$':>10}  {'Δ':>9}")
    for m in months_keep:
        g1 = df_1s_f[df_1s_f["month"] == m]
        gt = df_tk_f[df_tk_f["month"] == m]
        n1 = len(g1); nt = len(gt)
        p1 = float(g1["c1_pnl_pts"].sum() * NQ_MULT - 5.0 * n1)
        pt = float(gt["c1_pnl_pts"].sum() * NQ_MULT - 5.0 * nt)
        print(f"  {str(m):<10} {n1:>5,} {p1:>+9,.0f} {nt:>5,} {pt:>+9,.0f}  "
              f"{pt-p1:>+8,.0f}")


if __name__ == "__main__":
    main()
