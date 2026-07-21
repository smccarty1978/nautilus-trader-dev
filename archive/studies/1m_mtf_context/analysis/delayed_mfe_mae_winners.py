"""Forward MFE/MAE from delayed entry — WINNERS ONLY.

Winner = regime_pnl_dollars > 0 (classified by original regime exit).

For each delay D, filter to surviving winners and report forward
MFE/MAE distribution.
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

DELAYS_S = [30, 60, 90, 120, 180, 240, 300]


@njit(cache=True)
def forward_mfe_mae(entry_ts, exit_ts, direction, atr,
                     delay_s,
                     ts_arr, h_arr, l_arr, c_arr, i_start, i_end):
    if atr <= 0 or i_end <= i_start:
        return (0, 0.0, 0.0)
    delay_ts = entry_ts + delay_s * 1_000_000_000
    if exit_ts <= delay_ts:
        return (0, 0.0, 0.0)
    i_delay = i_start
    while i_delay < i_end and ts_arr[i_delay] < delay_ts:
        i_delay += 1
    if i_delay >= i_end:
        return (0, 0.0, 0.0)
    new_entry = c_arr[i_delay]
    peak_mfe = 0.0
    peak_mae = 0.0
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
    return (1, peak_mfe, peak_mae)


def percentiles(label, vals):
    vals = np.asarray(vals)
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return f"  {label}: no data"
    return (f"  {label:<22} N={len(vals):>6,}  "
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

    is_winner = (trades["regime_pnl_dollars"].values > 0)
    n_w = is_winner.sum()
    print(f"  Winners (regime_pnl > 0): {n_w:,}")

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
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values

    # JIT warmup
    forward_mfe_mae(0, 60_000_000_000, 1, 1.0, 60,
                     np.array([0, 1], dtype=np.int64),
                     np.array([100.0, 100.0]),
                     np.array([100.0, 100.0]),
                     np.array([100.0, 100.0]), 0, 2)

    n_t = len(trades)

    # Baseline winners
    print(f"\n{'='*100}")
    print(f"BASELINE WINNERS — full-trade MFE/MAE (no delay)")
    print(f"{'='*100}")
    print(percentiles("Peak MFE (ATR)",
                        trades.loc[is_winner, "peak_mfe_atr"].values))
    print(percentiles("Peak MAE (ATR)",
                        trades.loc[is_winner, "peak_mae_atr"].values))

    print(f"\n{'='*100}")
    print(f"WINNERS ONLY — Forward MFE/MAE from delayed entry")
    print(f"{'='*100}")

    summary = []
    for delay_s in DELAYS_S:
        survived = np.empty(n_t, dtype=np.int32)
        peak_mfe = np.empty(n_t)
        peak_mae = np.empty(n_t)
        for k in range(n_t):
            i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
            i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
            s, pm, pa = forward_mfe_mae(
                entry_ts[k], exit_ts[k], direction[k], atr[k],
                delay_s, ts_arr, h_arr, l_arr, c_arr, i_start, i_end)
            survived[k] = s
            peak_mfe[k] = pm
            peak_mae[k] = pa

        # Winners that survived delay
        win_surv = (survived == 1) & is_winner
        n_win_surv = win_surv.sum()
        n_win_skip = is_winner.sum() - n_win_surv

        sub_mfe = peak_mfe[win_surv]
        sub_mae = peak_mae[win_surv]

        print(f"\n--- Delay +{delay_s}s "
              f"(winners survived: {n_win_surv:,}, "
              f"skipped: {n_win_skip:,}) ---")
        print(percentiles("Forward peak MFE", sub_mfe))
        print(percentiles("Forward peak MAE", sub_mae))

        summary.append({
            "delay_s": delay_s,
            "n_surv": n_win_surv,
            "n_skip": n_win_skip,
            "mfe_mean": sub_mfe.mean(), "mfe_p50": np.median(sub_mfe),
            "mfe_p75": np.percentile(sub_mfe, 75),
            "mfe_p90": np.percentile(sub_mfe, 90),
            "mae_mean": sub_mae.mean(), "mae_p50": np.median(sub_mae),
            "mae_p75": np.percentile(sub_mae, 75),
            "mae_p90": np.percentile(sub_mae, 90),
            "ratio": sub_mfe.mean() / sub_mae.mean(),
        })

    # Compact summary
    print(f"\n{'='*100}")
    print(f"COMPACT SUMMARY — WINNERS ONLY, Forward MFE/MAE")
    print(f"{'='*100}")
    print(f"  {'Delay':>6} {'N surv':>8} {'N skip':>7} | "
          f"{'MFE mean':>9} {'MFE P50':>8} {'MFE P75':>8} {'MFE P90':>8} | "
          f"{'MAE mean':>9} {'MAE P50':>8} {'MAE P75':>8} {'MAE P90':>8} | "
          f"{'MFE/MAE':>8}")
    print("  " + "-" * 115)
    base_mfe = trades.loc[is_winner, "peak_mfe_atr"].values
    base_mae = trades.loc[is_winner, "peak_mae_atr"].values
    print(f"  {'NONE':>6} {n_w:>8,} {0:>7,} | "
          f"{base_mfe.mean():>8.3f} {np.median(base_mfe):>7.3f} "
          f"{np.percentile(base_mfe, 75):>7.3f} "
          f"{np.percentile(base_mfe, 90):>7.3f} | "
          f"{base_mae.mean():>8.3f} {np.median(base_mae):>7.3f} "
          f"{np.percentile(base_mae, 75):>7.3f} "
          f"{np.percentile(base_mae, 90):>7.3f} | "
          f"{base_mfe.mean()/base_mae.mean():>7.2f}x")
    for s in summary:
        print(f"  {s['delay_s']:>5}s {s['n_surv']:>8,} {s['n_skip']:>7,} | "
              f"{s['mfe_mean']:>8.3f} {s['mfe_p50']:>7.3f} "
              f"{s['mfe_p75']:>7.3f} {s['mfe_p90']:>7.3f} | "
              f"{s['mae_mean']:>8.3f} {s['mae_p50']:>7.3f} "
              f"{s['mae_p75']:>7.3f} {s['mae_p90']:>7.3f} | "
              f"{s['ratio']:>7.2f}x")

    print(f"\n{'='*100}")


if __name__ == "__main__":
    main()
