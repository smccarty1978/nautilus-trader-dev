"""For trades that reach MFE thresholds, what MAE was seen first?

Walks each trade's 1s bars from bar+1 close to flip bar close.
For each MFE threshold (0.25, 0.5, 1.0, etc), records the MAE
that had occurred BY THAT MOMENT (not the eventual full-window MAE).

This answers: if SL was at -X ATR, how often would price have
stopped us out BEFORE reaching the profit threshold?
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time as _time
import pandas as pd
import numpy as np
from numba import njit

from nautilus_trader.persistence.catalog import ParquetDataCatalog


MFE_THRESHOLDS = np.array([0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00])


@njit(cache=True)
def walk_path(entry_px, direction, atr,
              h_arr, l_arr,
              thresholds):
    """Walk bars, record max-MAE-so-far at the moment max-MFE first hits
    each threshold. Returns:
      max_mfe, max_mae, mae_at_thresholds (one per threshold; NaN if never reached)
    """
    n = len(h_arr)
    n_thr = len(thresholds)
    out_mae_at = np.full(n_thr, np.nan)
    if n == 0 or atr <= 0:
        return 0.0, 0.0, out_mae_at

    max_mfe = 0.0
    max_mae = 0.0
    next_thr_idx = 0

    for i in range(n):
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            cur_mfe = (h - entry_px) / atr
            cur_mae = (entry_px - l) / atr
        else:
            cur_mfe = (entry_px - l) / atr
            cur_mae = (h - entry_px) / atr
        if cur_mfe > max_mfe:
            max_mfe = cur_mfe
        if cur_mae > max_mae:
            max_mae = cur_mae

        # Check if any new MFE threshold crossed this bar
        while (next_thr_idx < n_thr
               and max_mfe >= thresholds[next_thr_idx]):
            out_mae_at[next_thr_idx] = max_mae
            next_thr_idx += 1
        if next_thr_idx >= n_thr:
            # All thresholds hit — keep walking only to update max_mae
            # but we don't need the full max_mae here; can break early
            # We DO want full window max_mae though
            pass

    return max_mfe, max_mae, out_mae_at


def main():
    print("=" * 80)
    print("PATH ANALYSIS — MAE at moment MFE first hits threshold (2025)")
    print("=" * 80)

    print("\nLoading trades (2025)...")
    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    trades["entry_dt"] = pd.to_datetime(
        trades["entry_ts"], unit="ns", utc=True)
    trades = trades[
        (trades["entry_dt"] >= "2025-01-01") &
        (trades["entry_dt"] < "2026-01-01")
    ].reset_index(drop=True)
    print(f"  {len(trades):,} trades")

    print("\nLoading 1s bars...")
    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")

    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    high_arr = np.empty(n)
    low_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        high_arr[i] = float(b.high)
        low_arr[i] = float(b.low)
    del bars_1s

    entry_walk = trades["entry_ts"].astype("int64").values + 60_000_000_000
    exit_walk = (pd.to_datetime(trades["exit_time"]).astype("int64").values
                 + 60_000_000_000)
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_flip"].values

    # JIT warmup
    walk_path(100.0, 1, 1.0, np.array([100.0]), np.array([100.0]),
              MFE_THRESHOLDS)

    print(f"\nWalking {len(trades):,} trades...")
    t0 = _time.time()
    n_t = len(trades)
    n_thr = len(MFE_THRESHOLDS)
    max_mfes = np.empty(n_t)
    max_maes = np.empty(n_t)
    mae_at_thr = np.full((n_t, n_thr), np.nan)

    for k in range(n_t):
        if atr[k] <= 0:
            max_mfes[k] = 0.0
            max_maes[k] = 0.0
            continue
        i_start = np.searchsorted(ts_arr, entry_walk[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_walk[k], side="right")
        if i_end <= i_start:
            max_mfes[k] = 0.0
            max_maes[k] = 0.0
            continue
        mfe, mae, mae_thr = walk_path(
            entry_px[k], direction[k], atr[k],
            high_arr[i_start:i_end], low_arr[i_start:i_end],
            MFE_THRESHOLDS)
        max_mfes[k] = mfe
        max_maes[k] = mae
        mae_at_thr[k] = mae_thr

    print(f"  Done ({_time.time()-t0:.0f}s)")

    # ---- Summary stats ----
    print(f"\n{'='*80}")
    print(f"FULL-WINDOW MFE/MAE distribution ({n_t:,} trades)")
    print(f"{'='*80}")
    print(f"  MFE  mean={max_mfes.mean():.3f}  "
          f"P25={np.percentile(max_mfes,25):.3f}  "
          f"P50={np.percentile(max_mfes,50):.3f}  "
          f"P75={np.percentile(max_mfes,75):.3f}  "
          f"P90={np.percentile(max_mfes,90):.3f}")
    print(f"  MAE  mean={max_maes.mean():.3f}  "
          f"P25={np.percentile(max_maes,25):.3f}  "
          f"P50={np.percentile(max_maes,50):.3f}  "
          f"P75={np.percentile(max_maes,75):.3f}  "
          f"P90={np.percentile(max_maes,90):.3f}")

    print(f"\n  MFE achievement:")
    for thr in MFE_THRESHOLDS:
        pct = (max_mfes >= thr).mean() * 100
        print(f"    >= {thr:.2f} ATR: {pct:>5.1f}%")

    # ---- Path analysis ----
    print(f"\n{'='*80}")
    print(f"MAE seen BEFORE MFE first reached threshold")
    print(f"  (For trades that DID reach the MFE threshold)")
    print(f"{'='*80}")
    print(f"  {'Thr':>5} {'Reach%':>8} {'N':>6}  "
          f"{'MAE_mean':>9} {'MAE_med':>9} {'MAE_P75':>9} "
          f"{'MAE_P90':>9} {'MAE>=thr%':>10}")
    print("-" * 88)
    for tidx, thr in enumerate(MFE_THRESHOLDS):
        col = mae_at_thr[:, tidx]
        valid = ~np.isnan(col)
        n_reach = valid.sum()
        if n_reach == 0:
            continue
        sub = col[valid]
        # How often did MAE >= thr happen BEFORE MFE reached thr
        # (i.e., would a SL at -thr have fired first?)
        pct_sl_first = (sub >= thr).mean() * 100
        print(f"  {thr:>5.2f} {n_reach/n_t*100:>7.1f}% {n_reach:>6,}  "
              f"{sub.mean():>9.3f} {np.median(sub):>9.3f} "
              f"{np.percentile(sub,75):>9.3f} "
              f"{np.percentile(sub,90):>9.3f} "
              f"{pct_sl_first:>9.1f}%")

    # ---- Path classifications ----
    print(f"\n{'='*80}")
    print(f"PATH PATTERN at 1.0 ATR MFE threshold")
    print(f"{'='*80}")
    col = mae_at_thr[:, 3]  # 1.0 ATR threshold
    reached = ~np.isnan(col)
    n_reach = reached.sum()
    if n_reach > 0:
        sub = col[reached]
        print(f"  Of {n_reach:,} trades that reached 1.0 ATR MFE:")
        for sl_thr in [0.25, 0.50, 0.75, 1.00]:
            pct = (sub >= sl_thr).mean() * 100
            print(f"    SL @ -{sl_thr:.2f} ATR would have fired first: "
                  f"{pct:>5.1f}%")
        # Distribution of MAE at +1 ATR MFE
        print(f"  MAE distribution at moment MFE first hit 1.0 ATR:")
        print(f"    P10={np.percentile(sub,10):.3f}  "
              f"P25={np.percentile(sub,25):.3f}  "
              f"P50={np.percentile(sub,50):.3f}  "
              f"P75={np.percentile(sub,75):.3f}  "
              f"P90={np.percentile(sub,90):.3f}  "
              f"P99={np.percentile(sub,99):.3f}")

    print(f"\n  At +0.5 ATR MFE (lower threshold):")
    col = mae_at_thr[:, 1]  # 0.5 ATR
    reached = ~np.isnan(col)
    if reached.sum() > 0:
        sub = col[reached]
        print(f"  Of {reached.sum():,} trades that reached 0.5 ATR MFE:")
        for sl_thr in [0.25, 0.50, 0.75, 1.00]:
            pct = (sub >= sl_thr).mean() * 100
            print(f"    SL @ -{sl_thr:.2f} ATR would have fired first: "
                  f"{pct:>5.1f}%")

    # Save
    trades["max_mfe_atr"] = max_mfes
    trades["max_mae_atr"] = max_maes
    for tidx, thr in enumerate(MFE_THRESHOLDS):
        trades[f"mae_at_mfe_{thr:.2f}"] = mae_at_thr[:, tidx]
    out = Path(
        "studies/1m_confirmed_flip/results/path_mae_at_mfe_2025.parquet")
    trades.to_parquet(out, index=False)
    print(f"\n  Saved: {out}")

    print(f"\n{'='*80}")


if __name__ == "__main__":
    main()
