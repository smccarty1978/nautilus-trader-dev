"""Prove-it gate with REALISTIC cut PnL.

Cut trades exit AT the gate time (not held to regime exit).
Cut PnL = (price_at_T - entry) × direction × NQ_MULT - commission.

Kept trades hold to regime exit, use regime_pnl_dollars.
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

NQ_MULT = 20.0
COMMISSION = 5.0

TIMES = [30, 60, 90, 120, 180, 300]
THRESHOLDS = [0.25, 0.50, 0.75, 1.00, 1.25]


@njit(cache=True)
def mfe_and_price_at_t(entry_px, entry_ts, direction, atr,
                        target_offset_s,
                        ts_arr, h_arr, l_arr, c_arr, i_start, i_end):
    """Return (peak_mfe_up_to_T, close_at_T_ATR_from_entry).

    close_at_T_ATR = (close_price_at_first_bar_past_T - entry_px) *
                     direction / atr

    Returns (nan, nan) if trade ended before T.
    """
    if atr <= 0 or i_end <= i_start:
        return (np.nan, np.nan)
    target_ts = entry_ts + target_offset_s * 1_000_000_000
    peak = 0.0
    for i in range(i_start, i_end):
        if ts_arr[i] >= target_ts:
            close_atr = (c_arr[i] - entry_px) * direction / atr
            return (peak, close_atr)
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            mfe = (h - entry_px) / atr
        else:
            mfe = (entry_px - l) / atr
        if mfe > peak:
            peak = mfe
    return (np.nan, np.nan)


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
    c_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        h_arr[i] = float(b.high)
        l_arr[i] = float(b.low)
        c_arr[i] = float(b.close)
    del bars_1s

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values
    regime_pnl = trades["regime_pnl_dollars"].values

    # JIT warmup
    mfe_and_price_at_t(100.0, 0, 1, 1.0, 60,
                        np.array([0, 1], dtype=np.int64),
                        np.array([100.0, 100.0]),
                        np.array([100.0, 100.0]),
                        np.array([100.0, 100.0]),
                        0, 2)

    print("Computing MFE and close-price at target times...")
    n_t = len(trades)
    mfe_at = {t: np.empty(n_t) for t in TIMES}
    close_at = {t: np.empty(n_t) for t in TIMES}
    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        for t in TIMES:
            mfe, cl = mfe_and_price_at_t(
                entry_px[k], entry_ts[k], direction[k], atr[k],
                t, ts_arr, h_arr, l_arr, c_arr, i_start, i_end)
            mfe_at[t][k] = mfe
            close_at[t][k] = cl
    print("  Done")

    is_winner = regime_pnl > 0

    print("\n" + "=" * 120)
    print("REALISTIC PROVE-IT GATE — cut trades exit AT gate time")
    print("  Kept PnL = regime_pnl (held to regime exit)")
    print("  Cut PnL  = (close_at_T - entry) × dir × ATR × 20 - $5 commission")
    print("=" * 120)

    for T in TIMES:
        mfe = mfe_at[T]
        close_atr = close_at[T]
        alive_mask = ~np.isnan(mfe)
        alive_n = alive_mask.sum()

        # Dead before T: use their actual regime_pnl (they already exited)
        dead_mask = np.isnan(mfe)
        dead_pnl = regime_pnl[dead_mask]
        dead_n = dead_mask.sum()

        print(f"\n--- Gate @ {T}s ---")
        print(f"  Alive at {T}s: {alive_n:,} ({alive_n/n_t*100:.1f}%)")
        print(f"  Dead before {T}s (already exited at regime): "
              f"{dead_n:,}  avg ${dead_pnl.mean():+.2f}")

        print(f"\n  {'Thr':>5} | "
              f"{'Kept N':>7} {'KeptW%':>6} {'W/L':>5} {'Kept Avg$':>10} | "
              f"{'Cut N':>6} {'CutW%':>6} {'Cut Avg$':>9} | "
              f"{'Gate Avg$':>10} {'vs base Δ':>10}")
        print("  " + "-" * 120)
        for thr in THRESHOLDS:
            keep_mask = alive_mask & (mfe >= thr)
            cut_mask = alive_mask & (mfe < thr)

            keep_n = keep_mask.sum()
            keep_w_n = (keep_mask & is_winner).sum()
            keep_l_n = (keep_mask & ~is_winner).sum()
            keep_w_pct = keep_w_n / keep_n * 100 if keep_n > 0 else 0
            w_l = keep_w_n / keep_l_n if keep_l_n > 0 else float("inf")

            # Kept → regime exit
            keep_pnl = regime_pnl[keep_mask]
            keep_avg = keep_pnl.mean() if keep_n > 0 else 0

            # Cut → exit at gate time at close price
            cut_n = cut_mask.sum()
            cut_w_pct = ((cut_mask & is_winner).sum() / cut_n * 100
                          if cut_n > 0 else 0)
            if cut_n > 0:
                cut_close_atr = close_atr[cut_mask]
                cut_atr_sub = atr[cut_mask]
                cut_pnl = (cut_close_atr * cut_atr_sub * NQ_MULT
                             - COMMISSION)
                cut_avg = cut_pnl.mean()
                cut_total = cut_pnl.sum()
            else:
                cut_avg = 0
                cut_total = 0
                cut_pnl = np.array([])

            # Dead-before-T trades: regime_pnl as-is
            gate_total = (keep_pnl.sum()
                          + cut_total
                          + dead_pnl.sum())
            gate_avg = gate_total / n_t
            # Baseline total
            baseline_total = regime_pnl.sum()
            delta = gate_total - baseline_total
            flag = " ★" if gate_avg > 0 else (
                " +" if delta > 0 else "")
            print(f"  {thr:>5.2f} | "
                  f"{keep_n:>7,} {keep_w_pct:>5.1f}% {w_l:>4.2f}x "
                  f"${keep_avg:>+9.2f} | "
                  f"{cut_n:>6,} {cut_w_pct:>5.1f}% ${cut_avg:>+8.2f} | "
                  f"${gate_avg:>+9.2f} ${delta:>+9,.0f}{flag}")

    # Baseline reference
    print("\n" + "=" * 120)
    print(f"Baseline (no gate): avg ${regime_pnl.mean():+.2f}  "
          f"total ${regime_pnl.sum():+,.0f}")
    print("=" * 120)


if __name__ == "__main__":
    main()
