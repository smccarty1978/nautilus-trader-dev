"""MFE @ 60s/90s/120s for losing trades.

mfe_at_60s and mfe_at_120s are pre-computed in the collector.
mfe_at_90s requires a walk.
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
    """Compute peak MFE up to target_offset_s after entry."""
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
    return (f"  {label:<25}  N={len(vals):>6,}  "
            f"P10={np.percentile(vals, 10):>5.3f}  "
            f"P25={np.percentile(vals, 25):>5.3f}  "
            f"P50={np.percentile(vals, 50):>5.3f}  "
            f"P75={np.percentile(vals, 75):>5.3f}  "
            f"P90={np.percentile(vals, 90):>5.3f}  "
            f"P95={np.percentile(vals, 95):>5.3f}  "
            f"mean={vals.mean():>5.3f}")


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

    print("Extracting...")
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

    # Compute MFE@90s (60s and 120s already in trades)
    print("Computing mfe_at_90s...")
    n_t = len(trades)
    mfe_90s = np.empty(n_t)
    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        mfe_90s[k] = peak_mfe_at_t(
            entry_px[k], entry_ts[k], direction[k], atr[k],
            90, ts_arr, h_arr, l_arr, i_start, i_end)
    print(f"  Done")

    trades["mfe_at_90s"] = mfe_90s

    print("\n" + "=" * 105)
    print("PEAK MFE (ATR) FOR LOSING TRADES — by bracket")
    print("=" * 105)

    for tag, pt, sl in [("050_050", 0.50, 0.50),
                         ("075_075", 0.75, 0.75),
                         ("100_100", 1.00, 1.00),
                         ("100_050", 1.00, 0.50),
                         ("150_075", 1.50, 0.75)]:
        result = trades[f"bracket_{tag}_result"].values
        sl_mask = result == "SL"
        nei_mask = result == "neither"
        loser_mask = sl_mask | nei_mask

        print(f"\n--- Bracket {tag} (PT={pt}/SL={sl})  "
              f"SL-first N={sl_mask.sum():,}  "
              f"Neither N={nei_mask.sum():,} ---")
        for snap_col, label in [("mfe_at_60s", " 60s peak MFE"),
                                  ("mfe_at_90s", " 90s peak MFE"),
                                  ("mfe_at_120s", "120s peak MFE")]:
            print(f"  SL-first @ {label}:")
            print(percentiles(label, trades.loc[sl_mask, snap_col].values))
            if nei_mask.sum() > 100:
                print(f"  Neither @ {label}:")
                print(percentiles(label,
                                    trades.loc[nei_mask, snap_col].values))
        # Combined losers
        for snap_col, label in [("mfe_at_60s", " 60s peak MFE"),
                                  ("mfe_at_90s", " 90s peak MFE"),
                                  ("mfe_at_120s", "120s peak MFE")]:
            print(f"  ALL losers (SL+nei) @ {label}:")
            print(percentiles(label,
                                trades.loc[loser_mask, snap_col].values))
        # PT for reference
        pt_mask = result == "PT"
        for snap_col, label in [("mfe_at_60s", " 60s peak MFE"),
                                  ("mfe_at_90s", " 90s peak MFE"),
                                  ("mfe_at_120s", "120s peak MFE")]:
            print(f"  [ref] PT-first @ {label}:")
            print(percentiles(label,
                                trades.loc[pt_mask, snap_col].values))

    print("\n" + "=" * 105)


if __name__ == "__main__":
    main()
