"""ATR-normalized PnL on regime-flip exits.

Two views:
  1. ALL confirmed trades, exited at regime flip (collector baseline)
  2. Subset of trades that fell to regime under Trail 1.0/1.0
     (the trades nothing else caught)
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


@njit(cache=True)
def did_trail_hit(entry_px, direction, atr,
                   h_arr, l_arr, ts_arr,
                   trail_dist_atr, trail_activ_atr):
    """Return True if trail would have fired during the window."""
    n = len(h_arr)
    if n == 0 or atr <= 0:
        return False
    peak_px = entry_px
    trail_active = False
    for i in range(n):
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            if h > peak_px:
                peak_px = h
        else:
            if l < peak_px:
                peak_px = l
        mfe = (peak_px - entry_px) / atr if direction == 1 \
            else (entry_px - peak_px) / atr
        if not trail_active and mfe >= trail_activ_atr:
            trail_active = True
        if trail_active:
            ts_px = peak_px - direction * trail_dist_atr * atr
            if direction == 1 and l <= ts_px:
                return True
            elif direction == -1 and h >= ts_px:
                return True
    return False


def main():
    print("=" * 72)
    print("ATR-NORMALIZED PnL on regime-flip exits — 2025")
    print("=" * 72)

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

    # ---- View 1: ALL confirmed trades, regime baseline ----
    pnl_pts = trades["regime_pnl_pts"].values
    atr = trades["atr_at_flip"].values
    valid = atr > 0
    pnl_atr_all = pnl_pts[valid] / atr[valid]

    print(f"\nVIEW 1: ALL {valid.sum():,} confirmed trades, regime exit")
    print(f"  PnL in points:")
    print(f"    mean={pnl_pts[valid].mean():+.3f}  "
          f"median={np.median(pnl_pts[valid]):+.3f}")
    print(f"  PnL in ATR units:")
    print(f"    mean={pnl_atr_all.mean():+.4f}  "
          f"median={np.median(pnl_atr_all):+.4f}  "
          f"std={pnl_atr_all.std():.4f}")
    print(f"    P10={np.percentile(pnl_atr_all,10):+.3f}  "
          f"P25={np.percentile(pnl_atr_all,25):+.3f}  "
          f"P50={np.percentile(pnl_atr_all,50):+.3f}  "
          f"P75={np.percentile(pnl_atr_all,75):+.3f}  "
          f"P90={np.percentile(pnl_atr_all,90):+.3f}")
    wr_all = (pnl_atr_all > 0).mean() * 100
    print(f"  WR: {wr_all:.1f}%")

    # Losers only
    losers = pnl_atr_all[pnl_atr_all <= 0]
    print(f"\n  LOSERS only ({len(losers):,}):")
    print(f"    mean={losers.mean():+.4f} ATR  "
          f"median={np.median(losers):+.4f}")
    print(f"    P10={np.percentile(losers,10):+.3f}  "
          f"P25={np.percentile(losers,25):+.3f}  "
          f"P50={np.percentile(losers,50):+.3f}")

    # ---- View 2: trades that survived Trail 1.0/1.0 ----
    print("\n\nLoading 1s bars for Trail 1.0/1.0 subset analysis...")
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

    # JIT warmup
    did_trail_hit(100.0, 1, 1.0,
                   np.array([100.0]), np.array([100.0]),
                   np.array([0], dtype=np.int64), 1.0, 1.0)

    print(f"\n  Walking {len(trades):,} trades for Trail 1.0/1.0...")
    t0 = _time.time()
    fell_to_regime = np.zeros(len(trades), dtype=bool)
    for k in range(len(trades)):
        if atr[k] <= 0:
            continue
        i_start = np.searchsorted(ts_arr, entry_walk[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_walk[k], side="right")
        if i_end <= i_start:
            fell_to_regime[k] = True
            continue
        hit = did_trail_hit(
            entry_px[k], direction[k], atr[k],
            high_arr[i_start:i_end], low_arr[i_start:i_end],
            ts_arr[i_start:i_end], 1.0, 1.0)
        fell_to_regime[k] = not hit
    print(f"  Done ({_time.time()-t0:.0f}s)")

    sub_pnl_pts = pnl_pts[fell_to_regime & valid]
    sub_atr = atr[fell_to_regime & valid]
    sub_pnl_atr = sub_pnl_pts / sub_atr

    print(f"\nVIEW 2: trades that fell to regime under Trail 1.0/1.0")
    print(f"  Subset size: {len(sub_pnl_atr):,} "
          f"({len(sub_pnl_atr)/len(trades)*100:.1f}% of all)")
    print(f"  PnL in points:")
    print(f"    mean={sub_pnl_pts.mean():+.3f}  "
          f"median={np.median(sub_pnl_pts):+.3f}")
    print(f"  PnL in ATR units:")
    print(f"    mean={sub_pnl_atr.mean():+.4f}  "
          f"median={np.median(sub_pnl_atr):+.4f}  "
          f"std={sub_pnl_atr.std():.4f}")
    print(f"    P10={np.percentile(sub_pnl_atr,10):+.3f}  "
          f"P25={np.percentile(sub_pnl_atr,25):+.3f}  "
          f"P50={np.percentile(sub_pnl_atr,50):+.3f}  "
          f"P75={np.percentile(sub_pnl_atr,75):+.3f}  "
          f"P90={np.percentile(sub_pnl_atr,90):+.3f}")
    wr_sub = (sub_pnl_atr > 0).mean() * 100
    print(f"  WR: {wr_sub:.1f}%")

    # Losers in subset
    sub_losers = sub_pnl_atr[sub_pnl_atr <= 0]
    print(f"\n  LOSERS in subset ({len(sub_losers):,}):")
    print(f"    mean={sub_losers.mean():+.4f} ATR  "
          f"median={np.median(sub_losers):+.4f}")
    print(f"    P10={np.percentile(sub_losers,10):+.3f}  "
          f"P50={np.percentile(sub_losers,50):+.3f}")

    # Compare distributions in $ terms (NQ $20/pt)
    print(f"\n  In dollars (NQ $20/pt, no commission):")
    print(f"    All regime exits:  mean ${pnl_pts[valid].mean()*20:+.1f}")
    print(f"    Survivors only:    mean ${sub_pnl_pts.mean()*20:+.1f}")

    print(f"\n{'=' * 72}")


if __name__ == "__main__":
    main()
