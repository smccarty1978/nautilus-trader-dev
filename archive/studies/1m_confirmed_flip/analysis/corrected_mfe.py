"""Compute corrected post-entry MFE/MAE for confirmed flip trades.

Collector recorded MFE from entry_ts (bar+1 OPEN time) using
entry_price = bar+1 CLOSE. That captures bar+1's intra-minute action
(including the HH/LL spike that confirmed entry) as if it were
post-entry MFE — look-ahead.

This script re-walks 1s bars from bar+1 CLOSE (entry_ts + 60s) to
flip bar CLOSE (exit_ts + 60s) and recomputes MFE/MAE.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
import time as _time
from nautilus_trader.persistence.catalog import ParquetDataCatalog


def main():
    print("=" * 72)
    print("CORRECTED MFE/MAE — fix entry-timing look-ahead")
    print("=" * 72)

    print("\nLoading trades (Q4 2025)...")
    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    trades["entry_dt"] = pd.to_datetime(
        trades["entry_ts"], unit="ns", utc=True)
    trades = trades[
        (trades["entry_dt"] >= "2025-10-01") &
        (trades["entry_dt"] < "2026-01-01")
    ].copy()
    print(f"  {len(trades):,} trades")

    print("\nLoading 1s bars (Q4 2025)...")
    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-10-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")

    print("Extracting...")
    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    high_arr = np.empty(n)
    low_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        high_arr[i] = float(b.high)
        low_arr[i] = float(b.low)
    del bars_1s

    # Compute post-entry MFE/MAE for each trade
    print(f"\nWalking {len(trades):,} trades...")
    t0 = _time.time()
    new_mfe = np.empty(len(trades))
    new_mae = np.empty(len(trades))
    bars_held = np.empty(len(trades), dtype=np.int64)

    entry_ts = trades["entry_ts"].astype("int64").values + 60_000_000_000
    exit_ts = (pd.to_datetime(trades["exit_time"]).astype("int64").values
               + 60_000_000_000)
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values
    atr = trades["atr_at_flip"].values

    for k in range(len(trades)):
        if atr[k] <= 0:
            new_mfe[k] = 0.0
            new_mae[k] = 0.0
            bars_held[k] = 0
            continue

        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        if i_end <= i_start:
            new_mfe[k] = 0.0
            new_mae[k] = 0.0
            bars_held[k] = 0
            continue

        h_slice = high_arr[i_start:i_end]
        l_slice = low_arr[i_start:i_end]
        ep = entry_px[k]
        a = atr[k]
        if direction[k] == 1:
            mfe = max(0.0, (h_slice.max() - ep) / a)
            mae = max(0.0, (ep - l_slice.min()) / a)
        else:
            mfe = max(0.0, (ep - l_slice.min()) / a)
            mae = max(0.0, (h_slice.max() - ep) / a)
        new_mfe[k] = mfe
        new_mae[k] = mae
        bars_held[k] = i_end - i_start

    print(f"  Done in {_time.time()-t0:.0f}s")

    # Compare old vs new
    old_mfe = trades["mfe_atr"].values
    old_mae = trades["mae_atr"].values

    print(f"\n{'='*72}")
    print(f"OLD (collector, with look-ahead) MFE/MAE distribution:")
    print(f"  MFE: mean={old_mfe.mean():.3f}  P25={np.percentile(old_mfe,25):.3f}  "
          f"P50={np.percentile(old_mfe,50):.3f}  "
          f"P75={np.percentile(old_mfe,75):.3f}  "
          f"P90={np.percentile(old_mfe,90):.3f}")
    print(f"  MAE: mean={old_mae.mean():.3f}  P25={np.percentile(old_mae,25):.3f}  "
          f"P50={np.percentile(old_mae,50):.3f}  "
          f"P75={np.percentile(old_mae,75):.3f}  "
          f"P90={np.percentile(old_mae,90):.3f}")

    print(f"\nNEW (post-entry only, no look-ahead) MFE/MAE:")
    print(f"  MFE: mean={new_mfe.mean():.3f}  P25={np.percentile(new_mfe,25):.3f}  "
          f"P50={np.percentile(new_mfe,50):.3f}  "
          f"P75={np.percentile(new_mfe,75):.3f}  "
          f"P90={np.percentile(new_mfe,90):.3f}")
    print(f"  MAE: mean={new_mae.mean():.3f}  P25={np.percentile(new_mae,25):.3f}  "
          f"P50={np.percentile(new_mae,50):.3f}  "
          f"P75={np.percentile(new_mae,75):.3f}  "
          f"P90={np.percentile(new_mae,90):.3f}")

    delta_mfe = new_mfe - old_mfe
    delta_mae = new_mae - old_mae
    print(f"\nDelta (new - old):")
    print(f"  MFE: mean={delta_mfe.mean():+.3f}  "
          f"% reduced: {(delta_mfe < 0).mean()*100:.1f}%")
    print(f"  MAE: mean={delta_mae.mean():+.3f}  "
          f"% increased: {(delta_mae > 0).mean()*100:.1f}%")

    # MFE achievement rates (how often does MFE reach key thresholds)
    print(f"\nMFE threshold achievement rates (post-entry):")
    for thr in [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]:
        pct_old = (old_mfe >= thr).mean() * 100
        pct_new = (new_mfe >= thr).mean() * 100
        print(f"  >= {thr:.2f} ATR:  OLD {pct_old:>5.1f}%  →  "
              f"NEW {pct_new:>5.1f}%  (Δ {pct_new-pct_old:+.1f}pp)")

    # Save corrected MFE
    trades["mfe_atr_corrected"] = new_mfe
    trades["mae_atr_corrected"] = new_mae
    trades["bars_held_1s"] = bars_held
    out = Path(
        "studies/1m_confirmed_flip/results/trades_q4_2025_corrected_mfe.parquet")
    trades.to_parquet(out, index=False)
    print(f"\n  Saved: {out}")

    print(f"\n{'='*72}")


if __name__ == "__main__":
    main()
