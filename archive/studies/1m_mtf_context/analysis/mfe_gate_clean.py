"""Prove-it gate analysis — clean, unbiased.

Two views:
  1. ALIVE-AT-T gate table: for each (T, threshold), filter to trades
     still open at T. Show W/L kept, ratio, PnL of kept vs cut subsets.
  2. FULL-POPULATION diagnostic table: NaN for died-before-T trades.

Walker returns NaN for trades that ended before T (so we can cleanly
identify the alive-at-T population).
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
def peak_mfe_up_to_t(entry_px, entry_ts, direction, atr,
                      target_offset_s,
                      ts_arr, h_arr, l_arr, i_start, i_end):
    """Peak MFE (ATR) up to target_offset_s after entry.

    Returns NaN if trade ended before target (can't gate at that point).
    Returns peak MFE observed from entry up to the first 1s bar
    whose ts_event >= target_ts.
    """
    if atr <= 0 or i_end <= i_start:
        return np.nan
    target_ts = entry_ts + target_offset_s * 1_000_000_000
    peak = 0.0
    reached_target = False
    for i in range(i_start, i_end):
        if ts_arr[i] >= target_ts:
            reached_target = True
            break
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            mfe = (h - entry_px) / atr
        else:
            mfe = (entry_px - l) / atr
        if mfe > peak:
            peak = mfe
    if not reached_target:
        return np.nan
    return peak


TIMES = [30, 60, 90, 120, 180, 300]
THRESHOLDS = [0.25, 0.50, 0.75, 1.00, 1.25]


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
    regime_pnl = trades["regime_pnl_dollars"].values

    # JIT warmup
    peak_mfe_up_to_t(100.0, 0, 1, 1.0, 60,
                       np.array([0, 1], dtype=np.int64),
                       np.array([100.0, 100.0]), np.array([100.0, 100.0]),
                       0, 2)

    # Compute MFE @ each target time (NaN for died-before-T)
    print("Computing MFE up to target times (NaN if trade ended first)...")
    n_t = len(trades)
    mfe_tables = {}
    for tgt in TIMES:
        mfe_tables[tgt] = np.empty(n_t)
    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        for tgt in TIMES:
            mfe_tables[tgt][k] = peak_mfe_up_to_t(
                entry_px[k], entry_ts[k], direction[k], atr[k],
                tgt, ts_arr, h_arr, l_arr, i_start, i_end)
    print("  Done")

    is_winner = regime_pnl > 0

    # ===== VIEW 1: ALIVE-AT-T GATE TABLE =====
    print("\n" + "=" * 115)
    print("VIEW 1 — ALIVE-AT-T GATE TABLE")
    print("  For each (T, threshold): among trades alive at T, split by")
    print("  MFE >= threshold (keep) vs MFE < threshold (cut).")
    print("  Kept PnL = actual regime_pnl (hold to regime exit)")
    print("  Cut PnL uses regime_pnl as proxy — ALL PnL totals reported at")
    print("  regime exit for BOTH kept and cut subsets.")
    print("=" * 115)

    for T in TIMES:
        mfe = mfe_tables[T]
        alive_mask = ~np.isnan(mfe)
        alive_n = alive_mask.sum()
        alive_w = (alive_mask & is_winner).sum()
        alive_l = (alive_mask & ~is_winner).sum()
        alive_w_pct = alive_w / alive_n * 100 if alive_n > 0 else 0
        alive_l_pct = alive_l / alive_n * 100 if alive_n > 0 else 0
        alive_avg = regime_pnl[alive_mask].mean() if alive_n > 0 else 0

        print(f"\n--- Gate time: {T}s ---")
        print(f"  Alive at {T}s: {alive_n:,}/{n_t:,} "
              f"({alive_n/n_t*100:.1f}%)  "
              f"W={alive_w:,}({alive_w_pct:.1f}%) "
              f"L={alive_l:,}({alive_l_pct:.1f}%)  "
              f"Regime-exit avg ${alive_avg:+.2f}")
        print(f"\n  {'Thr':>5} | {'Kept N':>7} {'Kept W':>7} {'Kept L':>7} "
              f"{'KeptW%':>7} {'W/L':>6} | "
              f"{'Cut N':>7} {'Cut W':>7} {'Cut L':>7} "
              f"{'CutW%':>6} | "
              f"{'Kept Avg$':>10} {'Cut Avg$':>9}")
        print("  " + "-" * 113)
        for thr in THRESHOLDS:
            keep_mask = alive_mask & (mfe >= thr)
            cut_mask = alive_mask & (mfe < thr)

            keep_n = keep_mask.sum()
            keep_w = (keep_mask & is_winner).sum()
            keep_l = (keep_mask & ~is_winner).sum()
            keep_w_pct = keep_w / keep_n * 100 if keep_n > 0 else 0
            w_l = keep_w / keep_l if keep_l > 0 else float("inf")
            keep_avg = (regime_pnl[keep_mask].mean()
                         if keep_n > 0 else 0)

            cut_n = cut_mask.sum()
            cut_w = (cut_mask & is_winner).sum()
            cut_l = (cut_mask & ~is_winner).sum()
            cut_w_pct = cut_w / cut_n * 100 if cut_n > 0 else 0
            cut_avg = regime_pnl[cut_mask].mean() if cut_n > 0 else 0

            print(f"  {thr:>5.2f} | {keep_n:>7,} {keep_w:>7,} {keep_l:>7,} "
                  f"{keep_w_pct:>6.1f}% {w_l:>5.2f}x | "
                  f"{cut_n:>7,} {cut_w:>7,} {cut_l:>7,} "
                  f"{cut_w_pct:>5.1f}% | "
                  f"${keep_avg:>+9.2f} ${cut_avg:>+8.2f}")

    # ===== VIEW 2: FULL-POPULATION DIAGNOSTIC =====
    print("\n" + "=" * 115)
    print("VIEW 2 — FULL-POPULATION DIAGNOSTIC (NaN for died-before-T)")
    print("  Descriptive only — shows what % of ALL trades (including died-early) reached MFE threshold by T")
    print("=" * 115)
    print(f"\n  % of trades with MFE >= threshold AT time T")
    print(f"  (trades that died before T are excluded from numerator)")
    print(f"  {'Thr':>5} | " +
          " | ".join([f"@{T}s " for T in TIMES]))
    print("  " + "-" * (10 + 10 * len(TIMES)))
    for thr in THRESHOLDS:
        cells = []
        for T in TIMES:
            mfe = mfe_tables[T]
            alive_mask = ~np.isnan(mfe)
            pass_mask = alive_mask & (mfe >= thr)
            pct = pass_mask.sum() / n_t * 100
            alive_pct = alive_mask.sum() / n_t * 100
            cond_pct = pass_mask.sum() / alive_mask.sum() * 100 \
                if alive_mask.sum() > 0 else 0
            cells.append(f"{cond_pct:>5.1f}%")
        print(f"  {thr:>5.2f} | " + " | ".join(cells))

    print("\n  ALIVE-AT-T %:")
    for T in TIMES:
        alive_pct = (~np.isnan(mfe_tables[T])).sum() / n_t * 100
        print(f"    @{T:>4}s  {alive_pct:>5.1f}%  "
              f"(N={(~np.isnan(mfe_tables[T])).sum():,})")

    print("\n" + "=" * 115)


if __name__ == "__main__":
    main()
