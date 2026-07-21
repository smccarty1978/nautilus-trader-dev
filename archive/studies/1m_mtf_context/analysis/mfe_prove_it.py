"""Peak MFE analysis — losers vs winners.

For losers and winners (classified by regime_pnl):
  - Peak MFE at 30/60/90/120/180/300s + full-trade
  - % exceeding 0.25/0.50/0.75/1.00/1.25 ATR MFE at any point
  - Time evolution: % exceeding threshold by time T
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
def peak_mfe_at_t(entry_px, entry_ts, direction, atr,
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
            mfe = (h - entry_px) / atr
        else:
            mfe = (entry_px - l) / atr
        if mfe > peak:
            peak = mfe
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


def threshold_table(df, cols, thresholds, group_label):
    print(f"\n--- % of {group_label} with MFE >= threshold at each time ---")
    print(f"  {'Threshold':>10}  " +
          " ".join(f"{c.replace('mfe_at_', '@').replace('peak_mfe_atr', 'full'):>7}"
                   for c in cols))
    for thr in thresholds:
        cells = []
        for col in cols:
            vals = df[col].values
            vals = vals[~np.isnan(vals)]
            if len(vals) == 0:
                cells.append(f"{'—':>7}")
                continue
            pct = (vals >= thr).mean() * 100
            cells.append(f"{pct:>6.2f}%")
        print(f"  {thr:>9.2f}   " + " ".join(cells))


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
    peak_mfe_at_t(100.0, 0, 1, 1.0, 60,
                   np.array([0, 1], dtype=np.int64),
                   np.array([100.0, 100.0]), np.array([100.0, 100.0]),
                   0, 2)

    # Compute MFE at 90s, 180s, 300s (30/60/120 pre-computed)
    print("Computing mfe at 90s, 180s, 300s...")
    n_t = len(trades)
    mfe_90 = np.empty(n_t)
    mfe_180 = np.empty(n_t)
    mfe_300 = np.empty(n_t)
    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        mfe_90[k] = peak_mfe_at_t(
            entry_px[k], entry_ts[k], direction[k], atr[k],
            90, ts_arr, h_arr, l_arr, i_start, i_end)
        mfe_180[k] = peak_mfe_at_t(
            entry_px[k], entry_ts[k], direction[k], atr[k],
            180, ts_arr, h_arr, l_arr, i_start, i_end)
        mfe_300[k] = peak_mfe_at_t(
            entry_px[k], entry_ts[k], direction[k], atr[k],
            300, ts_arr, h_arr, l_arr, i_start, i_end)
    trades["mfe_at_90s"] = mfe_90
    trades["mfe_at_180s"] = mfe_180
    trades["mfe_at_300s"] = mfe_300

    # Classify
    trades["is_winner_regime"] = trades["regime_pnl_dollars"] > 0
    win = trades[trades["is_winner_regime"]].copy()
    lose = trades[~trades["is_winner_regime"]].copy()

    print(f"\n  Winners: {len(win):,}  Losers: {len(lose):,}")

    mfe_cols = ["mfe_at_30s", "mfe_at_60s", "mfe_at_90s",
                "mfe_at_120s", "mfe_at_180s", "mfe_at_300s",
                "peak_mfe_atr"]

    # ----- LOSERS -----
    print("\n" + "=" * 105)
    print(f"LOSERS (regime_pnl ≤ 0) — N={len(lose):,}")
    print("=" * 105)

    print("\n--- Full-trade peak MFE percentiles ---")
    print(percentiles("Full peak MFE", lose["peak_mfe_atr"].values))

    print("\n--- Peak MFE at time snapshots ---")
    for col, lbl in [("mfe_at_30s", " 30s"), ("mfe_at_60s", " 60s"),
                     ("mfe_at_90s", " 90s"), ("mfe_at_120s", "120s"),
                     ("mfe_at_180s", "180s"), ("mfe_at_300s", "300s")]:
        print(percentiles(f"MFE @ {lbl}", lose[col].values))

    print("\n--- % of losers with full-trade peak MFE >= threshold ---")
    pm = lose["peak_mfe_atr"].values
    pm_valid = pm[~np.isnan(pm)]
    for thr in [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]:
        n_exc = (pm_valid >= thr).sum()
        pct = n_exc / len(pm_valid) * 100
        print(f"  MFE >= {thr:.2f} ATR: {n_exc:>6,} ({pct:>5.2f}%)")

    threshold_table(lose, mfe_cols, [0.25, 0.50, 0.75, 1.00, 1.25],
                     "LOSERS")

    # ----- WINNERS -----
    print("\n" + "=" * 105)
    print(f"WINNERS (regime_pnl > 0) — N={len(win):,}")
    print("=" * 105)

    print("\n--- Full-trade peak MFE percentiles ---")
    print(percentiles("Full peak MFE", win["peak_mfe_atr"].values))

    print("\n--- Peak MFE at time snapshots ---")
    for col, lbl in [("mfe_at_30s", " 30s"), ("mfe_at_60s", " 60s"),
                     ("mfe_at_90s", " 90s"), ("mfe_at_120s", "120s"),
                     ("mfe_at_180s", "180s"), ("mfe_at_300s", "300s")]:
        print(percentiles(f"MFE @ {lbl}", win[col].values))

    print("\n--- % of winners with full-trade peak MFE >= threshold ---")
    pm = win["peak_mfe_atr"].values
    pm_valid = pm[~np.isnan(pm)]
    for thr in [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]:
        n_exc = (pm_valid >= thr).sum()
        pct = n_exc / len(pm_valid) * 100
        print(f"  MFE >= {thr:.2f} ATR: {n_exc:>6,} ({pct:>5.2f}%)")

    threshold_table(win, mfe_cols, [0.25, 0.50, 0.75, 1.00, 1.25],
                     "WINNERS")

    # ----- COMBINED: prove-it gate comparison -----
    print("\n" + "=" * 105)
    print("GATE COMPARISON: if we kept only trades with MFE >= X at time T,")
    print("  % WINNERS kept vs % LOSERS kept at each (time, threshold)")
    print("=" * 105)
    for col, lbl in [("mfe_at_30s", "30s"), ("mfe_at_60s", "60s"),
                     ("mfe_at_90s", "90s"), ("mfe_at_120s", "120s"),
                     ("mfe_at_180s", "180s"), ("mfe_at_300s", "300s")]:
        print(f"\n  {lbl}:")
        print(f"    {'Threshold':>10} {'Winners kept':>14} "
              f"{'Losers kept':>13} {'W/L ratio':>10}")
        for thr in [0.25, 0.50, 0.75, 1.00, 1.25]:
            w_vals = win[col].values
            l_vals = lose[col].values
            w_valid = w_vals[~np.isnan(w_vals)]
            l_valid = l_vals[~np.isnan(l_vals)]
            if len(w_valid) == 0 or len(l_valid) == 0:
                continue
            w_pct = (w_valid >= thr).mean() * 100
            l_pct = (l_valid >= thr).mean() * 100
            w_n = (w_valid >= thr).sum()
            l_n = (l_valid >= thr).sum()
            ratio = w_pct / l_pct if l_pct > 0 else float("inf")
            print(f"    {thr:>9.2f}  {w_n:>6,} ({w_pct:>5.1f}%)  "
                  f"{l_n:>6,} ({l_pct:>5.1f}%)  {ratio:>9.2f}x")

    print("\n" + "=" * 105)


if __name__ == "__main__":
    main()
