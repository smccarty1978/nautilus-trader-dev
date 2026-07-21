"""Early exit gate — can we cut losers based on current PnL at time T?

For each combination of (gate_time, gate_threshold):
  - Cut trades where current PnL @ gate_time < threshold (in ATR)
  - Keep the rest, race to PT/SL/regime
  - Total PnL = (cut trades exit at current price) + (kept trades race normally)

Compare vs baseline (no gate) PnL.

Time points: 30s, 60s, 90s, 120s, 180s, 300s
Thresholds (ATR): -1.0, -0.75, -0.50, -0.25, -0.10, 0
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
GATE_TIMES_S = [30, 60, 90, 120, 180, 300]


@njit(cache=True)
def get_pnl_at_time(entry_px, entry_ts, direction, atr,
                     time_offset_s,
                     ts_arr, c_arr, i_start, i_end):
    """Find 1s bar at entry_ts + time_offset_s. Return (price, pnl_atr).

    If trade ended before that time, return NaN.
    """
    if atr <= 0 or i_end <= i_start:
        return (np.nan, np.nan)
    target_ts = entry_ts + time_offset_s * 1_000_000_000

    i = i_start
    while i < i_end and ts_arr[i] < target_ts:
        i += 1
    if i >= i_end:
        return (np.nan, np.nan)
    price = c_arr[i]
    return (price, (price - entry_px) * direction / atr)


def run_gate(trades, gate_time_s, gate_thr_atr,
              pnl_at_t, baseline_pnl, atr, bracket_pnl):
    """Compute total PnL with this gate.

    For trades cut (pnl_at_t < gate_thr): PnL = pnl_at_t × atr × NQ_MULT - COMMISSION
    For trades kept: PnL = bracket_pnl
    For trades with no gate data (NaN): use baseline (don't cut, hold)
    """
    n = len(trades)
    has_data = ~np.isnan(pnl_at_t)
    cut_mask = has_data & (pnl_at_t < gate_thr_atr)
    keep_mask = ~cut_mask

    pnl = np.empty(n)
    # Cut: exit at current price
    cut_pnl = pnl_at_t[cut_mask] * atr[cut_mask] * NQ_MULT - COMMISSION
    pnl[cut_mask] = cut_pnl
    # Kept: original bracket outcome
    pnl[keep_mask] = bracket_pnl[keep_mask]

    return pnl, cut_mask


def main():
    print("=" * 100)
    print("EARLY EXIT GATE — current PnL @ T < threshold → exit, else hold")
    print("=" * 100)

    print("\nLoading trades + 1s bars...")
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
    t0 = _time.time()
    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    c_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        c_arr[i] = float(b.close)
    del bars_1s
    print(f"  ({_time.time()-t0:.0f}s)")

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values

    # JIT warmup
    get_pnl_at_time(100.0, 0, 1, 1.0, 60,
                     np.array([0, 1], dtype=np.int64),
                     np.array([100.0, 100.0]), 0, 2)

    # Compute current PnL at each time point
    n_t = len(trades)
    print(f"\nWalking trades for current PnL at gate times...")
    pnl_at_t = {}
    for gate_s in GATE_TIMES_S:
        pnl_at_t[gate_s] = np.empty(n_t)

    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        for gate_s in GATE_TIMES_S:
            _, p_atr = get_pnl_at_time(
                entry_px[k], entry_ts[k], direction[k], atr[k],
                gate_s, ts_arr, c_arr, i_start, i_end)
            pnl_at_t[gate_s][k] = p_atr

    print(f"  Done")

    # Baseline bracket PnLs for two brackets
    for tag, pt_atr, sl_atr in [("075_075", 0.75, 0.75),
                                  ("100_100", 1.00, 1.00),
                                  ("050_050", 0.50, 0.50)]:
        result = trades[f"bracket_{tag}_result"].values
        reg_pnl = trades["regime_pnl_dollars"].values
        bracket_pnl = np.empty(n_t)
        bracket_pnl[result == "PT"] = (
            pt_atr * atr[result == "PT"] * NQ_MULT - COMMISSION)
        bracket_pnl[result == "SL"] = (
            -sl_atr * atr[result == "SL"] * NQ_MULT - COMMISSION)
        bracket_pnl[result == "neither"] = reg_pnl[result == "neither"]

        baseline_avg = bracket_pnl.mean()
        baseline_total = bracket_pnl.sum()

        print(f"\n{'='*100}")
        print(f"BRACKET {tag} (PT={pt_atr}/SL={sl_atr}) "
              f"BASELINE: avg ${baseline_avg:+.2f}, "
              f"total ${baseline_total:+,.0f}")
        print(f"{'='*100}")
        print(f"  {'Gate T':>7} {'Threshold':>10} {'Cut N':>8} {'Cut %':>7}  "
              f"{'Cut Avg':>8} {'Kept Avg':>9}  {'New Avg':>8} {'New Total':>13}  "
              f"{'Δ vs base':>10}")
        print("-" * 110)
        for gate_s in GATE_TIMES_S:
            for thr in [-1.0, -0.75, -0.50, -0.25, -0.10, 0.0]:
                pnl, cut_mask = run_gate(
                    trades, gate_s, thr, pnl_at_t[gate_s],
                    bracket_pnl, atr, bracket_pnl)
                cut_n = cut_mask.sum()
                cut_pct = cut_n / n_t * 100
                cut_avg = (pnl[cut_mask].mean() if cut_n > 0 else 0)
                kept_avg = pnl[~cut_mask].mean()
                new_avg = pnl.mean()
                new_total = pnl.sum()
                delta = new_total - baseline_total
                flag = " ★" if new_avg > 0 else (
                    " +" if delta > 0 else "")
                print(f"  {gate_s:>5}s {thr:>+10.2f} {cut_n:>7,} "
                      f"{cut_pct:>6.1f}% ${cut_avg:>+7.1f} "
                      f"${kept_avg:>+8.1f}  ${new_avg:>+7.2f} "
                      f"${new_total:>+12,.0f}  ${delta:>+9,.0f}{flag}")

    print(f"\n{'='*100}")


if __name__ == "__main__":
    main()
