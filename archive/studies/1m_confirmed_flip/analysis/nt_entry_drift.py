"""Quantify entry-price and timestamp drift between NT and collector."""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

NT_FILE = "studies/1m_confirmed_flip/results/nt_trail_q4_2025_tight.parquet"
COL_FILE = "studies/1m_confirmed_flip/results/trades_all.parquet"


def main():
    nt = pd.read_parquet(NT_FILE).copy()
    col = pd.read_parquet(COL_FILE).copy()
    col["entry_dt"] = pd.to_datetime(col["entry_ts"], unit="ns", utc=True)
    col_q4 = col[
        (col["entry_dt"] >= "2025-10-01") &
        (col["entry_dt"] < "2026-01-01")
    ].copy()

    nt["flip_min"] = pd.to_datetime(nt["flip_time"]).dt.floor("min")
    col_q4["flip_min"] = pd.to_datetime(
        col_q4["flip_time"]).dt.floor("min")

    nt_idx = nt.set_index(["flip_min", "direction"])
    col_idx = col_q4.set_index(["flip_min", "direction"])
    common = nt_idx.index.intersection(col_idx.index)
    nt_m = nt_idx.loc[common].copy()
    col_m = col_idx.loc[common].copy()

    # Direction-aware entry diff
    # For long: positive d_entry = NT bought higher = WORSE
    # For short: positive d_entry = NT sold higher = BETTER
    direction = nt_m.index.get_level_values("direction").values
    raw_diff = nt_m["entry_price"].values - col_m["entry_price"].values
    adverse_pts = raw_diff * direction  # positive = NT worse

    # Timestamp drift
    nt_ts = pd.to_datetime(nt_m["entry_time"]).astype("int64").values
    col_ts = pd.to_datetime(col_m["entry_time"]).astype("int64").values
    ts_drift_s = (nt_ts - col_ts) / 1e9

    print(f"Matched trades: {len(nt_m):,}")

    print(f"\n  Adverse entry slippage (positive = NT got worse fill):")
    print(f"    mean={adverse_pts.mean():+.3f} pts  "
          f"median={np.median(adverse_pts):+.3f}  "
          f"std={adverse_pts.std():.3f}")
    print(f"    P10={np.percentile(adverse_pts, 10):+.2f}  "
          f"P50={np.percentile(adverse_pts, 50):+.2f}  "
          f"P90={np.percentile(adverse_pts, 90):+.2f}  "
          f"P99={np.percentile(adverse_pts, 99):+.2f}")

    # How many entries are within tick (0.25)
    within_tick = (np.abs(raw_diff) <= 0.25).sum()
    within_2ticks = (np.abs(raw_diff) <= 0.5).sum()
    within_pt = (np.abs(raw_diff) <= 1.0).sum()
    big = (np.abs(raw_diff) > 5.0).sum()
    huge = (np.abs(raw_diff) > 10.0).sum()
    print(f"\n  Entry price match:")
    print(f"    Within 1 tick (0.25): {within_tick:,} "
          f"({within_tick/len(nt_m)*100:.1f}%)")
    print(f"    Within 2 ticks (0.50): {within_2ticks:,} "
          f"({within_2ticks/len(nt_m)*100:.1f}%)")
    print(f"    Within 1 pt: {within_pt:,} "
          f"({within_pt/len(nt_m)*100:.1f}%)")
    print(f"    >5 pts off: {big:,} ({big/len(nt_m)*100:.1f}%)")
    print(f"    >10 pts off: {huge:,} ({huge/len(nt_m)*100:.1f}%)")

    print(f"\n  Timestamp drift (NT - collector entry_time, seconds):")
    print(f"    mean={ts_drift_s.mean():+.2f}s  "
          f"median={np.median(ts_drift_s):+.2f}s")
    print(f"    P10={np.percentile(ts_drift_s, 10):+.1f}  "
          f"P50={np.percentile(ts_drift_s, 50):+.1f}  "
          f"P90={np.percentile(ts_drift_s, 90):+.1f}  "
          f"P99={np.percentile(ts_drift_s, 99):+.1f}")
    print(f"    Max drift: {ts_drift_s.max():.0f}s")

    big_drift = (ts_drift_s > 60).sum()
    print(f"    > 60s drift: {big_drift:,} "
          f"({big_drift/len(nt_m)*100:.1f}%)")

    # Show worst adverse-slippage trades
    nt_m["adverse_pts"] = adverse_pts
    nt_m["col_entry"] = col_m["entry_price"].values
    nt_m["ts_drift_s"] = ts_drift_s
    worst = nt_m.nlargest(10, "adverse_pts")
    print(f"\n  Top 10 worst adverse slippages:")
    for idx, r in worst.iterrows():
        d_str = "L" if idx[1] == 1 else "S"
        print(f"    {idx[0]} {d_str}  "
              f"NT_entry={r['entry_price']:.2f}  "
              f"COL_entry={r['col_entry']:.2f}  "
              f"adverse={r['adverse_pts']:+.2f} pts  "
              f"ts_drift={r['ts_drift_s']:+.0f}s  "
              f"NT_pnl=${r['pnl_dollars']:+.0f}  "
              f"reason={r['exit_reason']}")

    # PnL impact: split matched trades by adverse slippage
    nt_m["abs_adv"] = np.abs(adverse_pts)
    bins = [0, 0.25, 1.0, 5.0, 100]
    nt_m["adv_bin"] = pd.cut(nt_m["abs_adv"], bins,
                              include_lowest=True,
                              labels=["≤0.25", "≤1pt", "≤5pt", ">5pt"])
    print(f"\n  PnL by absolute slippage magnitude:")
    print(f"    {'Bin':>6} {'N':>6} {'%':>6} {'Avg$':>8} {'Trail%':>8}")
    for b, g in nt_m.groupby("adv_bin", observed=True):
        trail_pct = (g["exit_reason"] == "trail_hit").mean() * 100
        print(f"    {str(b):>6} {len(g):>6,} "
              f"{len(g)/len(nt_m)*100:>5.1f}% "
              f"{g['pnl_dollars'].mean():>+7.1f} "
              f"{trail_pct:>7.1f}%")


if __name__ == "__main__":
    main()
