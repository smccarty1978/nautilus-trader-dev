"""Delayed entry analysis: enter at bar+4 open (= bar+3 close).

Filter: only trades where regime is still active at bar+3 close
(i.e., trade duration > 120s — regime didn't flip back at bar+2 or bar+3).

For surviving trades:
  - New entry = close of 1s bar at +120s after current entry (= bar+4 open)
  - New regime PnL = (regime_exit_price - new_entry) × dir × ATR × 20 - $5
  - New MFE/MAE from new entry baseline
  - Compare WR and Avg$ vs original entry baseline
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


@njit(cache=True)
def walk_delayed(entry_px, entry_ts, exit_ts, direction, atr, exit_price,
                  delay_s,
                  ts_arr, h_arr, l_arr, c_arr, i_start, i_end):
    """Walk forward from delay_s, compute new entry and forward stats.

    Returns:
      survived (1 if regime still active at delay_s), new_entry_px,
      new_regime_pnl_atr, new_peak_mfe, new_peak_mae,
      new_mfe_at_30, new_mfe_at_60, new_mfe_at_120,
      new_mae_at_30, new_mae_at_60, new_mae_at_120
    """
    if atr <= 0 or i_end <= i_start:
        return (0, 0.0, 0.0, 0.0, 0.0,
                 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    delay_ts = entry_ts + delay_s * 1_000_000_000

    # Find the bar at delay_s
    i_delay = i_start
    while i_delay < i_end and ts_arr[i_delay] < delay_ts:
        i_delay += 1

    if i_delay >= i_end:
        # Trade ended before delay_s — didn't survive gate
        return (0, 0.0, 0.0, 0.0, 0.0,
                 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    # New entry price = close at delay
    new_entry = c_arr[i_delay]
    new_regime_pnl_atr = (exit_price - new_entry) * direction / atr

    # Walk forward from i_delay+1 to i_end, compute MFE/MAE
    peak_mfe = 0.0
    peak_mae = 0.0
    snap_mfe_30 = 0.0
    snap_mfe_60 = 0.0
    snap_mfe_120 = 0.0
    snap_mae_30 = 0.0
    snap_mae_60 = 0.0
    snap_mae_120 = 0.0
    snap_30_done = False
    snap_60_done = False
    snap_120_done = False
    new_entry_ts = ts_arr[i_delay]

    for i in range(i_delay + 1, i_end):
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            mfe = (h - new_entry) / atr
            mae = (new_entry - l) / atr
        else:
            mfe = (new_entry - l) / atr
            mae = (h - new_entry) / atr
        if mfe > peak_mfe:
            peak_mfe = mfe
        if mae > peak_mae:
            peak_mae = mae

        elapsed = (ts_arr[i] - new_entry_ts) / 1_000_000_000
        if not snap_30_done and elapsed >= 30:
            snap_mfe_30 = peak_mfe
            snap_mae_30 = peak_mae
            snap_30_done = True
        if not snap_60_done and elapsed >= 60:
            snap_mfe_60 = peak_mfe
            snap_mae_60 = peak_mae
            snap_60_done = True
        if not snap_120_done and elapsed >= 120:
            snap_mfe_120 = peak_mfe
            snap_mae_120 = peak_mae
            snap_120_done = True

    return (1, new_entry, new_regime_pnl_atr, peak_mfe, peak_mae,
             snap_mfe_30, snap_mfe_60, snap_mfe_120,
             snap_mae_30, snap_mae_60, snap_mae_120)


def percentiles(label, vals):
    vals = np.asarray(vals)
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return f"  {label}: no data"
    return (f"  {label:<28} N={len(vals):>6,}  "
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
    exit_px = trades["exit_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values
    regime_pnl = trades["regime_pnl_dollars"].values

    # JIT warmup
    walk_delayed(100.0, 0, 60_000_000_000, 1, 1.0, 100.0, 60,
                  np.array([0, 1], dtype=np.int64),
                  np.array([100.0, 100.0]), np.array([100.0, 100.0]),
                  np.array([100.0, 100.0]), 0, 2)

    print("\nWalking trades for delayed entry @ +120s (= bar+4 open)...")
    n_t = len(trades)
    survived = np.empty(n_t, dtype=np.int32)
    new_entry_px = np.empty(n_t)
    new_pnl_atr = np.empty(n_t)
    peak_mfe = np.empty(n_t)
    peak_mae = np.empty(n_t)
    sn_mfe_30 = np.empty(n_t)
    sn_mfe_60 = np.empty(n_t)
    sn_mfe_120 = np.empty(n_t)
    sn_mae_30 = np.empty(n_t)
    sn_mae_60 = np.empty(n_t)
    sn_mae_120 = np.empty(n_t)

    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        (s, ne, np_atr, pm, pa, sm30, sm60, sm120,
         sma30, sma60, sma120) = walk_delayed(
            entry_px[k], entry_ts[k], exit_ts[k], direction[k],
            atr[k], exit_px[k], 120,
            ts_arr, h_arr, l_arr, c_arr, i_start, i_end)
        survived[k] = s
        new_entry_px[k] = ne
        new_pnl_atr[k] = np_atr
        peak_mfe[k] = pm
        peak_mae[k] = pa
        sn_mfe_30[k] = sm30
        sn_mfe_60[k] = sm60
        sn_mfe_120[k] = sm120
        sn_mae_30[k] = sma30
        sn_mae_60[k] = sma60
        sn_mae_120[k] = sma120

    print("  Done")

    # Build results
    surv_mask = survived == 1
    n_surv = surv_mask.sum()
    print(f"\n  Trades surviving past bar+3 close (>120s): "
          f"{n_surv:,} ({n_surv/n_t*100:.1f}%)")
    print(f"  Trades that died before bar+3 close: "
          f"{n_t - n_surv:,} ({(n_t-n_surv)/n_t*100:.1f}%)")

    new_pnl_dollars = new_pnl_atr * atr * NQ_MULT - COMMISSION
    new_winner = new_pnl_dollars > 0

    surv_pnl = new_pnl_dollars[surv_mask]
    surv_win_n = (new_winner & surv_mask).sum()
    surv_wr = surv_win_n / n_surv * 100

    print("\n" + "=" * 100)
    print("DELAYED ENTRY @ bar+4 open (~120s after current entry)")
    print("  Only trades where regime still active at bar+3 close")
    print("=" * 100)

    print(f"\n  Surviving trades: {n_surv:,}")
    print(f"  New WR (regime exit > 0): {surv_wr:.1f}%")
    print(f"  New avg PnL: ${surv_pnl.mean():+.2f}")
    print(f"  New total PnL: ${surv_pnl.sum():+,.0f}")

    # Compare to original entry on SAME subset
    orig_pnl_subset = regime_pnl[surv_mask]
    orig_wr_subset = (orig_pnl_subset > 0).mean() * 100
    print(f"\n  --- For comparison (same trades, original entry):")
    print(f"  Original WR: {orig_wr_subset:.1f}%")
    print(f"  Original avg PnL: ${orig_pnl_subset.mean():+.2f}")
    print(f"  Original total PnL: ${orig_pnl_subset.sum():+,.0f}")
    delta_avg = surv_pnl.mean() - orig_pnl_subset.mean()
    print(f"  Δ avg per trade: ${delta_avg:+.2f}")
    print(f"  Δ total: ${surv_pnl.sum() - orig_pnl_subset.sum():+,.0f}")

    # Full-strategy comparison: skipped trades (died before bar+3) get $0
    # PnL since we never enter them — they were filtered out
    skipped_pnl_loss = regime_pnl[~surv_mask].sum()
    print(f"\n  --- Strategy-level (delay applied):")
    print(f"  Trades skipped (died before delay): {n_t - n_surv:,}, "
          f"avg ${regime_pnl[~surv_mask].mean():+.2f}, "
          f"total avoided ${-skipped_pnl_loss:+,.0f}")
    print(f"  Trades taken (delayed entry): {n_surv:,}, "
          f"total ${surv_pnl.sum():+,.0f}")
    print(f"  Strategy total: ${surv_pnl.sum():+,.0f} (vs baseline "
          f"${regime_pnl.sum():+,.0f})")
    print(f"  Strategy avg per opportunity: "
          f"${surv_pnl.sum() / n_t:+.2f}")
    print(f"  Strategy avg per trade taken: "
          f"${surv_pnl.sum() / n_surv:+.2f}")

    # PnL distribution comparison
    print("\n--- PnL distribution (surviving trades, $) ---")
    print(percentiles("Original entry PnL$", orig_pnl_subset))
    print(percentiles("Delayed entry PnL$", surv_pnl))

    print("\n--- New PnL ATR-normalized ---")
    print(percentiles("Delayed regime PnL(ATR)",
                        new_pnl_atr[surv_mask]))

    print("\n--- Forward MFE from delayed entry (ATR) ---")
    print(percentiles("Full peak MFE",
                        peak_mfe[surv_mask]))
    print(percentiles("MFE @ 30s",
                        sn_mfe_30[surv_mask]))
    print(percentiles("MFE @ 60s",
                        sn_mfe_60[surv_mask]))
    print(percentiles("MFE @ 120s",
                        sn_mfe_120[surv_mask]))

    print("\n--- Forward MAE from delayed entry (ATR) ---")
    print(percentiles("Full peak MAE",
                        peak_mae[surv_mask]))
    print(percentiles("MAE @ 30s",
                        sn_mae_30[surv_mask]))
    print(percentiles("MAE @ 60s",
                        sn_mae_60[surv_mask]))
    print(percentiles("MAE @ 120s",
                        sn_mae_120[surv_mask]))

    # Year-by-year on delayed strategy
    print("\n--- Year-by-year (delayed entry, surviving trades only) ---")
    print(f"  {'Year':>6} {'N surv':>8} {'WR%':>6} {'Avg$':>8} {'Total$':>11}")
    years = trades["year"].values
    for y in sorted(np.unique(years)):
        ymask = (years == y) & surv_mask
        n = ymask.sum()
        if n == 0:
            continue
        sub_pnl = new_pnl_dollars[ymask]
        wr = (sub_pnl > 0).mean() * 100
        print(f"  {y:>6} {n:>7,} {wr:>5.1f}% "
              f"${sub_pnl.mean():>+7.1f} ${sub_pnl.sum():>+10,.0f}")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
