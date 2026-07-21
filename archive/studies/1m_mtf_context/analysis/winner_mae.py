"""Peak MAE analysis for WINNERS (regime_pnl > 0).

Shows:
  - Full-trade peak MAE percentiles
  - Peak MAE at 30/60/90/120/180/300s
  - % of winners exceeding 0.50, 0.75, 1.00, 1.25 ATR MAE at any point
"""

import sys
import os
import time as _time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
from numba import njit

from nautilus_trader.persistence.catalog import ParquetDataCatalog


@njit(cache=True)
def peak_mae_at_t(entry_px, entry_ts, direction, atr,
                   target_offset_s,
                   ts_arr, h_arr, l_arr, i_start, i_end):
    if atr <= 0 or i_end <= i_start:
        return np.nan
    target_ts = entry_ts + target_offset_s * 1_000_000_000
    peak = 0.0
    for i in range(i_start, i_end):
        if ts_arr[i] >= target_ts:
            return peak
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            mae = (entry_px - l) / atr
        else:
            mae = (h - entry_px) / atr
        if mae > peak:
            peak = mae
    return peak


def percentiles(label, vals):
    vals = np.asarray(vals)
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return f"  {label}: no data"
    return (f"  {label:<20} N={len(vals):>6,}  "
            f"P10={np.percentile(vals, 10):>6.3f}  "
            f"P25={np.percentile(vals, 25):>6.3f}  "
            f"P50={np.percentile(vals, 50):>6.3f}  "
            f"P75={np.percentile(vals, 75):>6.3f}  "
            f"P90={np.percentile(vals, 90):>6.3f}  "
            f"P95={np.percentile(vals, 95):>6.3f}  "
            f"mean={vals.mean():>6.3f}")


def main():
    print("Loading trades + 1s bars...")
    trades = pd.read_parquet(
        "studies/1m_mtf_context/results/trades_all.parquet").copy()
    print(f"  {len(trades):,} trades")

    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  {len(bars_1s):,} 1s bars ({_time.time()-t0:.0f}s)")

    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    h_arr = np.empty(n)
    l_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        h_arr[i] = float(b.high)
        l_arr[i] = float(b.low)
    del bars_1s

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values

    # JIT warmup
    peak_mae_at_t(100.0, 0, 1, 1.0, 60,
                   np.array([0, 1], dtype=np.int64),
                   np.array([100.0, 100.0]), np.array([100.0, 100.0]),
                   0, 2)

    # Compute MAE at 90s, 180s, 300s (30, 60, 120 already pre-computed)
    print("Computing mae at 90s, 180s, 300s...")
    n_t = len(trades)
    mae_90 = np.empty(n_t)
    mae_180 = np.empty(n_t)
    mae_300 = np.empty(n_t)
    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        mae_90[k] = peak_mae_at_t(
            entry_px[k], entry_ts[k], direction[k], atr[k],
            90, ts_arr, h_arr, l_arr, i_start, i_end)
        mae_180[k] = peak_mae_at_t(
            entry_px[k], entry_ts[k], direction[k], atr[k],
            180, ts_arr, h_arr, l_arr, i_start, i_end)
        mae_300[k] = peak_mae_at_t(
            entry_px[k], entry_ts[k], direction[k], atr[k],
            300, ts_arr, h_arr, l_arr, i_start, i_end)
    trades["mae_at_90s"] = mae_90
    trades["mae_at_180s"] = mae_180
    trades["mae_at_300s"] = mae_300
    print("  Done")

    # Classify
    trades["is_winner_regime"] = trades["regime_pnl_dollars"] > 0
    win = trades[trades["is_winner_regime"]].copy()
    print(f"\n  Winners (regime_pnl > 0): {len(win):,}")

    print("\n" + "=" * 95)
    print("WINNERS — Peak MAE (ATR) analysis")
    print("=" * 95)

    print("\n--- Full-trade peak MAE ---")
    print(percentiles("Full-trade peak MAE",
                        win["peak_mae_atr"].values))

    print("\n--- Peak MAE at time snapshots ---")
    for col, lbl in [("mae_at_30s", " 30s"),
                      ("mae_at_60s", " 60s"),
                      ("mae_at_90s", " 90s"),
                      ("mae_at_120s", "120s"),
                      ("mae_at_180s", "180s"),
                      ("mae_at_300s", "300s")]:
        print(percentiles(f"MAE @ {lbl}", win[col].values))

    print("\n--- % of winners with full-trade peak MAE >= threshold ---")
    pm = win["peak_mae_atr"].values
    pm_valid = pm[~np.isnan(pm)]
    print(f"  Total winners: {len(pm_valid):,}")
    for thr in [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]:
        pct = (pm_valid >= thr).mean() * 100
        n_exceed = (pm_valid >= thr).sum()
        print(f"  MAE >= {thr:.2f} ATR: {n_exceed:>6,} "
              f"({pct:>5.2f}%)")

    print("\n--- % of winners with MAE >= threshold at each time ---")
    print(f"  {'Threshold':>10}  "
          f"{'@30s':>7} {'@60s':>7} {'@90s':>7} "
          f"{'@120s':>7} {'@180s':>7} {'@300s':>7} {'full':>7}")
    for thr in [0.25, 0.50, 0.75, 1.00, 1.25]:
        row_cells = []
        for col in ["mae_at_30s", "mae_at_60s", "mae_at_90s",
                     "mae_at_120s", "mae_at_180s", "mae_at_300s",
                     "peak_mae_atr"]:
            vals = win[col].values
            vals = vals[~np.isnan(vals)]
            if len(vals) == 0:
                row_cells.append(f"{'—':>6}")
                continue
            pct = (vals >= thr).mean() * 100
            row_cells.append(f"{pct:>6.2f}%")
        print(f"  {thr:>9.2f}   " + " ".join(row_cells))

    print("\n" + "=" * 95)


if __name__ == "__main__":
    main()
