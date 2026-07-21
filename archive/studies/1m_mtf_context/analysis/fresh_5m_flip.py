"""Fresh 5m flip into support during delay.

Filter: 5m regime was NOT aligned at bar+1 close but FLIPPED to aligned
during the delay period. That's a genuine fresh HTF confirmation that
wasn't available at original entry.

For each delay (60s, 90s, 120s):
  1. Check regime_5m_aligned at bar+1 close (from collector, 0 = not aligned)
  2. Compute regime_5m at delayed entry
  3. Filter: bar1_aligned == 0 AND delay_aligned == 1
  4. Report N, WR, Avg$, Forward MFE/MAE from DELAYED entry
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
DELAYS_S = [60, 90, 120]


@njit(cache=True)
def build_5m_regime(ts_1m, h_1m, l_1m, c_1m):
    n = len(ts_1m)
    ts_5m = np.empty(n // 5 + 2, dtype=np.int64)
    regime_5m = np.empty(n // 5 + 2, dtype=np.int32)
    alpha3 = 2.0 / 4.0
    alpha9 = 2.0 / 10.0
    emaH_3 = emaH_9 = emaL_3 = emaL_9 = 0.0
    count = 0
    regime = 0
    out_idx = 0
    i = 0
    while i < n:
        agg_h = h_1m[i]
        agg_l = l_1m[i]
        agg_c = c_1m[i]
        j = i + 1
        while j < n and (ts_1m[j] // 60_000_000_000) % 5 != 0:
            if h_1m[j] > agg_h:
                agg_h = h_1m[j]
            if l_1m[j] < agg_l:
                agg_l = l_1m[j]
            agg_c = c_1m[j]
            j += 1
        close_ts_5m = ts_1m[j - 1] + 60_000_000_000
        ts_5m[out_idx] = close_ts_5m
        count += 1
        if count == 1:
            emaH_3 = agg_h
            emaH_9 = agg_h
            emaL_3 = agg_l
            emaL_9 = agg_l
        else:
            emaH_3 = alpha3 * agg_h + (1 - alpha3) * emaH_3
            emaH_9 = alpha9 * agg_h + (1 - alpha9) * emaH_9
            emaL_3 = alpha3 * agg_l + (1 - alpha3) * emaL_3
            emaL_9 = alpha9 * agg_l + (1 - alpha9) * emaL_9
        if count >= 9:
            if agg_c > emaH_3 and agg_c > emaH_9:
                regime = 1
            elif agg_c < emaL_3 and agg_c < emaL_9:
                regime = -1
        regime_5m[out_idx] = regime
        out_idx += 1
        i = j
    return ts_5m[:out_idx], regime_5m[:out_idx]


@njit(cache=True)
def regime_at_ts(ts_5m, regime_5m, query_ts):
    """Most recent 5m regime state <= query_ts via binary search."""
    lo = 0
    hi = len(ts_5m) - 1
    idx = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if ts_5m[mid] <= query_ts:
            idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return regime_5m[idx] if idx >= 0 else 0


@njit(cache=True)
def walk_forward(entry_ts, exit_ts, direction, atr, exit_price,
                  delay_s,
                  ts_1s, h_1s, l_1s, c_1s, i_start, i_end,
                  ts_5m, regime_5m):
    """Return (survived, new_entry, new_pnl_atr, peak_mfe, peak_mae,
             reg5m_at_delay)"""
    if atr <= 0 or i_end <= i_start:
        return (0, 0.0, 0.0, 0.0, 0.0, 0)
    delay_ts = entry_ts + delay_s * 1_000_000_000
    if exit_ts <= delay_ts:
        return (0, 0.0, 0.0, 0.0, 0.0, 0)
    i_delay = i_start
    while i_delay < i_end and ts_1s[i_delay] < delay_ts:
        i_delay += 1
    if i_delay >= i_end:
        return (0, 0.0, 0.0, 0.0, 0.0, 0)

    new_entry = c_1s[i_delay]
    new_pnl_atr = (exit_price - new_entry) * direction / atr

    peak_mfe = 0.0
    peak_mae = 0.0
    for i in range(i_delay + 1, i_end):
        h = h_1s[i]
        l = l_1s[i]
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

    reg5m_at_delay = regime_at_ts(ts_5m, regime_5m, delay_ts)
    return (1, new_entry, new_pnl_atr, peak_mfe, peak_mae,
             reg5m_at_delay)


def report_segment(label, mask, data_atr, data_regime_pnl_new,
                     data_peak_mfe, data_peak_mae, total_n):
    n = mask.sum()
    if n == 0:
        return
    pnl_dollars = data_regime_pnl_new[mask] * data_atr[mask] * NQ_MULT - COMMISSION
    wr = (pnl_dollars > 0).mean() * 100
    avg = pnl_dollars.mean()
    total = pnl_dollars.sum()
    mfe_mean = data_peak_mfe[mask].mean()
    mfe_p50 = np.median(data_peak_mfe[mask])
    mae_mean = data_peak_mae[mask].mean()
    mae_p50 = np.median(data_peak_mae[mask])
    flag = " ★" if wr > 33.3 and avg > 0 else ""
    print(f"  {label:<42} {n:>6,} "
          f"{n/total_n*100:>5.1f}% {wr:>5.1f}% ${avg:>+7.1f} "
          f"${total:>+10,.0f}   {mfe_mean:>5.2f}({mfe_p50:>4.2f})   "
          f"{mae_mean:>5.2f}({mae_p50:>4.2f}){flag}")


def main():
    print("Loading trades + 1s + 1m bars...")
    trades = pd.read_parquet(
        "studies/1m_mtf_context/results/trades_all.parquet").copy()
    print(f"  {len(trades):,} trades")

    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  1s: {len(bars_1s):,}, 1m: {len(bars_1m):,} "
          f"({_time.time()-t0:.0f}s)")

    n = len(bars_1s)
    ts_1s = np.empty(n, dtype=np.int64)
    h_1s = np.empty(n)
    l_1s = np.empty(n)
    c_1s = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_1s[i] = b.ts_event
        h_1s[i] = float(b.high)
        l_1s[i] = float(b.low)
        c_1s[i] = float(b.close)
    del bars_1s

    nm = len(bars_1m)
    ts_1m = np.empty(nm, dtype=np.int64)
    h_1m = np.empty(nm)
    l_1m = np.empty(nm)
    c_1m = np.empty(nm)
    for i, b in enumerate(bars_1m):
        ts_1m[i] = b.ts_event
        h_1m[i] = float(b.high)
        l_1m[i] = float(b.low)
        c_1m[i] = float(b.close)
    del bars_1m

    print("Building 5m regime sequence...")
    t0 = _time.time()
    ts_5m_arr, regime_5m_arr = build_5m_regime(ts_1m, h_1m, l_1m, c_1m)
    print(f"  {len(ts_5m_arr):,} 5m bars ({_time.time()-t0:.0f}s)")

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    exit_px = trades["exit_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values

    # JIT warmup
    walk_forward(0, 60_000_000_000, 1, 1.0, 100.0, 60,
                  np.array([0, 1], dtype=np.int64),
                  np.array([100.0, 100.0]), np.array([100.0, 100.0]),
                  np.array([100.0, 100.0]), 0, 2,
                  np.array([60_000_000_000], dtype=np.int64),
                  np.array([1], dtype=np.int32))

    n_t = len(trades)
    bar1_aligned = trades["regime_5m_aligned"].values  # 0 or 1 at bar+1 close

    print(f"\n{'='*110}")
    print(f"FRESH 5m FLIP DURING DELAY — specific HTF confirmation")
    print(f"  Filter: regime_5m_aligned=0 at bar+1 close AND 5m flipped"
          f" to aligned during delay")
    print(f"{'='*110}")

    for delay_s in DELAYS_S:
        survived = np.zeros(n_t, dtype=np.int32)
        new_pnl_atr = np.zeros(n_t)
        peak_mfe = np.zeros(n_t)
        peak_mae = np.zeros(n_t)
        reg5m_delay = np.zeros(n_t, dtype=np.int32)

        for k in range(n_t):
            i_start = np.searchsorted(ts_1s, entry_ts[k], side="left")
            i_end = np.searchsorted(ts_1s, exit_ts[k], side="right")
            s, _, np_atr, pm, pa, r5m = walk_forward(
                entry_ts[k], exit_ts[k], direction[k], atr[k], exit_px[k],
                delay_s, ts_1s, h_1s, l_1s, c_1s, i_start, i_end,
                ts_5m_arr, regime_5m_arr)
            survived[k] = s
            new_pnl_atr[k] = np_atr
            peak_mfe[k] = pm
            peak_mae[k] = pa
            reg5m_delay[k] = r5m

        # Alignment at delay (direction-aware)
        delay_aligned = (reg5m_delay == direction)

        surv_mask = survived == 1

        # Filter: NOT aligned at bar1 close, aligned at delay
        not_aligned_bar1 = (bar1_aligned == 0)
        fresh_flip = surv_mask & not_aligned_bar1 & delay_aligned

        # Other comparable filters
        always_aligned = surv_mask & (bar1_aligned == 1) & delay_aligned
        stayed_not_aligned = surv_mask & (bar1_aligned == 0) & ~delay_aligned
        became_misaligned = surv_mask & (bar1_aligned == 1) & ~delay_aligned

        print(f"\n--- Delay +{delay_s}s ---")
        print(f"  Surviving: {surv_mask.sum():,}")
        print(f"\n  {'Segment':<42} {'N':>6} {'%surv':>6} "
              f"{'WR':>6} {'Avg$':>8} {'Total$':>11}   "
              f"{'fMFE mean(P50)':>14}   {'fMAE mean(P50)':>14}")
        print("  " + "-" * 115)
        total_n = surv_mask.sum()

        report_segment("surv baseline (no filter)", surv_mask,
                         atr, new_pnl_atr, peak_mfe, peak_mae, total_n)
        report_segment("FRESH 5m flip (0 at bar1 → aligned at delay)",
                         fresh_flip,
                         atr, new_pnl_atr, peak_mfe, peak_mae, total_n)
        report_segment("always aligned (1 at bar1 AND at delay)",
                         always_aligned,
                         atr, new_pnl_atr, peak_mfe, peak_mae, total_n)
        report_segment("stayed not aligned",
                         stayed_not_aligned,
                         atr, new_pnl_atr, peak_mfe, peak_mae, total_n)
        report_segment("became misaligned (1→0 during delay)",
                         became_misaligned,
                         atr, new_pnl_atr, peak_mfe, peak_mae, total_n)

        # Year stability for FRESH flip
        if fresh_flip.sum() > 100:
            print(f"\n  Year stability — FRESH 5m flip during {delay_s}s delay:")
            print(f"    {'Year':>6} {'N':>6} {'WR%':>6} "
                  f"{'Avg$':>8} {'Total$':>11}")
            years = trades["year"].values
            for y in sorted(np.unique(years)):
                ymask = fresh_flip & (years == y)
                n_y = ymask.sum()
                if n_y < 30:
                    continue
                pnl_y = new_pnl_atr[ymask] * atr[ymask] * NQ_MULT - COMMISSION
                wr_y = (pnl_y > 0).mean() * 100
                print(f"    {y:>6} {n_y:>6,} {wr_y:>5.1f}% "
                      f"${pnl_y.mean():>+7.1f} ${pnl_y.sum():>+10,.0f}")

    print(f"\n{'='*110}")


if __name__ == "__main__":
    main()
