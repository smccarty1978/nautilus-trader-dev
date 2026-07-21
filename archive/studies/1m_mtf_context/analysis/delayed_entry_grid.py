"""Delayed entry grid: test multiple delay durations.

For each delay D in {30s, 60s, 90s, 120s, 180s, 240s, 300s}:
  - Filter: trade must survive to D after entry (regime still active)
  - New entry: close of 1s bar at entry+D
  - New regime PnL: (regime_exit - new_entry) × dir × ATR × 20 - $5
  - Strategy total = sum(survived new PnL) (skipped trades = NOT taken)

Compares vs baseline (no delay, all trades taken).
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
DELAYS_S = [30, 60, 90, 120, 180, 240, 300]


@njit(cache=True)
def get_close_at_delay(entry_px, entry_ts, exit_ts, direction, atr,
                        exit_price, delay_s,
                        ts_arr, c_arr, i_start, i_end):
    """Return (survived, new_entry_px, new_pnl_atr) at delay_s after entry.

    Returns (0, 0, 0) if trade ended before delay.
    """
    if atr <= 0 or i_end <= i_start:
        return (0, 0.0, 0.0)
    delay_ts = entry_ts + delay_s * 1_000_000_000

    # If exit happened at or before delay, can't gate
    if exit_ts <= delay_ts:
        return (0, 0.0, 0.0)

    # Find bar at delay
    i_delay = i_start
    while i_delay < i_end and ts_arr[i_delay] < delay_ts:
        i_delay += 1
    if i_delay >= i_end:
        return (0, 0.0, 0.0)

    new_entry = c_arr[i_delay]
    new_pnl_atr = (exit_price - new_entry) * direction / atr
    return (1, new_entry, new_pnl_atr)


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
    c_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        c_arr[i] = float(b.close)
    del bars_1s

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    entry_px = trades["entry_price"].values
    exit_px = trades["exit_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values
    regime_pnl = trades["regime_pnl_dollars"].values

    n_t = len(trades)
    baseline_total = regime_pnl.sum()
    baseline_avg = regime_pnl.mean()
    baseline_wr = (regime_pnl > 0).mean() * 100

    # JIT warmup
    get_close_at_delay(100.0, 0, 60_000_000_000, 1, 1.0, 100.0, 60,
                        np.array([0, 1], dtype=np.int64),
                        np.array([100.0, 100.0]), 0, 2)

    print(f"\nBaseline (no delay): N={n_t:,}, "
          f"WR={baseline_wr:.1f}%, "
          f"Avg=${baseline_avg:+.2f}, Total=${baseline_total:+,.0f}")

    print("\n" + "=" * 110)
    print("DELAYED ENTRY GRID")
    print("  Delay = seconds AFTER current entry (bar+1 close).")
    print("  Filter: skip trades where regime flipped before delay.")
    print("=" * 110)

    rows = []
    for delay_s in DELAYS_S:
        survived = np.empty(n_t, dtype=np.int32)
        new_entry_px = np.empty(n_t)
        new_pnl_atr = np.empty(n_t)
        for k in range(n_t):
            i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
            i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
            s, ne, np_atr = get_close_at_delay(
                entry_px[k], entry_ts[k], exit_ts[k], direction[k],
                atr[k], exit_px[k], delay_s,
                ts_arr, c_arr, i_start, i_end)
            survived[k] = s
            new_entry_px[k] = ne
            new_pnl_atr[k] = np_atr

        new_pnl_dollars = new_pnl_atr * atr * NQ_MULT - COMMISSION
        surv_mask = survived == 1
        n_surv = surv_mask.sum()
        n_skipped = n_t - n_surv

        # Take only surviving trades
        surv_pnl = new_pnl_dollars[surv_mask]
        skip_pnl_lost = regime_pnl[~surv_mask].sum()  # what we'd lose if held

        gate_total = surv_pnl.sum()
        gate_avg = gate_total / n_t  # per opportunity
        gate_avg_taken = gate_total / n_surv if n_surv > 0 else 0
        wr_taken = (surv_pnl > 0).mean() * 100 if n_surv > 0 else 0
        delta_total = gate_total - baseline_total

        # Same-subset comparison: original entry on the surviving subset
        orig_pnl_subset = regime_pnl[surv_mask]
        orig_wr_subset = (orig_pnl_subset > 0).mean() * 100
        orig_avg_subset = orig_pnl_subset.mean()
        slip_per_trade = surv_pnl.mean() - orig_avg_subset

        # Skipped trades' avg loss (we avoided)
        skip_avg = (regime_pnl[~surv_mask].mean()
                    if n_skipped > 0 else 0)

        rows.append({
            "delay_s": delay_s, "n_surv": n_surv, "n_skip": n_skipped,
            "gate_avg_taken": gate_avg_taken, "wr_taken": wr_taken,
            "gate_total": gate_total,
            "delta_total": delta_total,
            "orig_avg_subset": orig_avg_subset,
            "orig_wr_subset": orig_wr_subset,
            "slip_per_trade": slip_per_trade,
            "skip_avg": skip_avg,
        })

    print(f"\n  {'Delay':>5} | {'N surv':>7} {'N skip':>6} {'Skip Avg$':>10} "
          f"| {'WR taken':>9} {'Avg taken':>10} {'Total taken':>13} "
          f"{'Δ vs base':>11} | "
          f"{'Slip vs orig':>13}")
    print("  " + "-" * 109)
    for r in rows:
        print(f"  {r['delay_s']:>4}s | {r['n_surv']:>7,} {r['n_skip']:>6,} "
              f"${r['skip_avg']:>+9.2f} | {r['wr_taken']:>8.1f}% "
              f"${r['gate_avg_taken']:>+9.2f} ${r['gate_total']:>+12,.0f} "
              f"${r['delta_total']:>+10,.0f} | ${r['slip_per_trade']:>+11.2f}")

    # Detail on subset comparisons
    print(f"\n--- Same-subset comparison (surv trades, original vs delayed) ---")
    print(f"  {'Delay':>5} | {'Orig WR':>8} {'Delay WR':>9} {'Orig Avg':>9} "
          f"{'Delay Avg':>10} {'Δ Avg':>8} ")
    for r in rows:
        delta_wr = r["wr_taken"] - r["orig_wr_subset"]
        print(f"  {r['delay_s']:>4}s | {r['orig_wr_subset']:>7.1f}% "
              f"{r['wr_taken']:>8.1f}% ${r['orig_avg_subset']:>+8.2f} "
              f"${r['gate_avg_taken']:>+9.2f} ${r['slip_per_trade']:>+7.2f}")

    print("\n" + "=" * 110)


if __name__ == "__main__":
    main()
