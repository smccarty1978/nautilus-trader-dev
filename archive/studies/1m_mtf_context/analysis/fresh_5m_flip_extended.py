"""Fresh 5m flip — extended grid every 30s up to 600s.

For each delay D in {30, 60, 90, ..., 600}:
  Filter to: regime_5m_aligned=0 at bar+1 close AND 5m aligned at D.
  (i.e., a fresh 5m flip into support by delay D)
  Report: N, WR, Avg$, forward MFE/MAE from delayed entry.

Also reports: of ever-flipped trades, what delay had the FIRST flip?
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
DELAYS_S = list(range(30, 601, 30))  # 30..600 step 30


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
def walk_forward_one(entry_ts, exit_ts, direction, atr, exit_price,
                      delay_s, ts_1s, h_1s, l_1s, c_1s, i_start, i_end):
    """Returns (survived, new_pnl_atr, peak_mfe, peak_mae)"""
    if atr <= 0 or i_end <= i_start:
        return (0, 0.0, 0.0, 0.0)
    delay_ts = entry_ts + delay_s * 1_000_000_000
    if exit_ts <= delay_ts:
        return (0, 0.0, 0.0, 0.0)
    i_delay = i_start
    while i_delay < i_end and ts_1s[i_delay] < delay_ts:
        i_delay += 1
    if i_delay >= i_end:
        return (0, 0.0, 0.0, 0.0)
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
    return (1, new_pnl_atr, peak_mfe, peak_mae)


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
    ts_5m_arr, regime_5m_arr = build_5m_regime(ts_1m, h_1m, l_1m, c_1m)
    print(f"  {len(ts_5m_arr):,} 5m bars")

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    exit_px = trades["exit_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values
    bar1_aligned = trades["regime_5m_aligned"].values
    not_aligned_bar1 = (bar1_aligned == 0)

    # JIT warmup
    walk_forward_one(0, 60_000_000_000, 1, 1.0, 100.0, 60,
                      np.array([0, 1], dtype=np.int64),
                      np.array([100.0, 100.0]),
                      np.array([100.0, 100.0]),
                      np.array([100.0, 100.0]), 0, 2)

    n_t = len(trades)

    print(f"\n{'='*120}")
    print(f"FRESH 5m FLIP — EXTENDED GRID (delay every 30s, up to 600s)")
    print(f"  Filter: regime_5m_aligned=0 at bar+1 close AND 5m aligned at delay")
    print(f"{'='*120}")

    print(f"\n  {'Delay':>6} {'Surv':>7} | {'Fresh N':>8} "
          f"{'%fresh':>7} {'WR':>6} {'Avg$':>8} "
          f"{'Total$':>11} {'fMFE':>6} {'fMAE':>6}")
    print("  " + "-" * 110)

    results = []
    for delay_s in DELAYS_S:
        survived = np.zeros(n_t, dtype=np.int32)
        new_pnl_atr = np.zeros(n_t)
        peak_mfe = np.zeros(n_t)
        peak_mae = np.zeros(n_t)

        for k in range(n_t):
            i_start = np.searchsorted(ts_1s, entry_ts[k], side="left")
            i_end = np.searchsorted(ts_1s, exit_ts[k], side="right")
            s, np_atr, pm, pa = walk_forward_one(
                entry_ts[k], exit_ts[k], direction[k], atr[k], exit_px[k],
                delay_s, ts_1s, h_1s, l_1s, c_1s, i_start, i_end)
            survived[k] = s
            new_pnl_atr[k] = np_atr
            peak_mfe[k] = pm
            peak_mae[k] = pa

        surv_mask = survived == 1

        # Compute regime_5m at delay for each trade
        reg5m_delay = np.empty(n_t, dtype=np.int32)
        for k in range(n_t):
            if surv_mask[k]:
                delay_ts = entry_ts[k] + delay_s * 1_000_000_000
                reg5m_delay[k] = regime_at_ts(
                    ts_5m_arr, regime_5m_arr, delay_ts)
            else:
                reg5m_delay[k] = 0
        delay_aligned = (reg5m_delay == direction)

        fresh_flip = surv_mask & not_aligned_bar1 & delay_aligned

        n_f = fresh_flip.sum()
        if n_f == 0:
            continue

        pnl = new_pnl_atr[fresh_flip] * atr[fresh_flip] * NQ_MULT - COMMISSION
        wr = (pnl > 0).mean() * 100
        avg = pnl.mean()
        total = pnl.sum()
        mfe = peak_mfe[fresh_flip].mean()
        mae = peak_mae[fresh_flip].mean()
        flag = " ★" if avg > 0 else ""
        print(f"  {delay_s:>5}s {surv_mask.sum():>7,} | "
              f"{n_f:>8,} {n_f/surv_mask.sum()*100:>6.2f}% "
              f"{wr:>5.1f}% ${avg:>+7.1f} "
              f"${total:>+10,.0f} {mfe:>6.3f} {mae:>6.3f}{flag}")
        results.append({
            "delay_s": delay_s, "n_fresh": n_f, "wr": wr,
            "avg": avg, "total": total, "mfe": mfe, "mae": mae,
        })

    # Year stability for the best delay
    print(f"\n{'='*120}")
    print(f"YEAR STABILITY — top 3 delays by total$")
    print(f"{'='*120}")
    top3 = sorted(results, key=lambda r: -r["total"])[:3]
    years = trades["year"].values
    for r in top3:
        delay_s = r["delay_s"]
        print(f"\n  Delay {delay_s}s (N={r['n_fresh']:,}, "
              f"Avg ${r['avg']:+.1f}, Total ${r['total']:+,.0f}):")

        # Re-run for this delay to get year stats
        survived = np.zeros(n_t, dtype=np.int32)
        new_pnl_atr = np.zeros(n_t)
        for k in range(n_t):
            i_start = np.searchsorted(ts_1s, entry_ts[k], side="left")
            i_end = np.searchsorted(ts_1s, exit_ts[k], side="right")
            s, np_atr, _, _ = walk_forward_one(
                entry_ts[k], exit_ts[k], direction[k], atr[k], exit_px[k],
                delay_s, ts_1s, h_1s, l_1s, c_1s, i_start, i_end)
            survived[k] = s
            new_pnl_atr[k] = np_atr

        surv_mask = survived == 1
        reg5m_delay = np.empty(n_t, dtype=np.int32)
        for k in range(n_t):
            if surv_mask[k]:
                delay_ts = entry_ts[k] + delay_s * 1_000_000_000
                reg5m_delay[k] = regime_at_ts(
                    ts_5m_arr, regime_5m_arr, delay_ts)
            else:
                reg5m_delay[k] = 0
        delay_aligned = (reg5m_delay == direction)
        fresh_flip = surv_mask & not_aligned_bar1 & delay_aligned

        print(f"    {'Year':>6} {'N':>5} {'WR':>6} "
              f"{'Avg$':>8} {'Total$':>10}")
        for y in sorted(np.unique(years)):
            mask = fresh_flip & (years == y)
            n_y = mask.sum()
            if n_y < 20:
                continue
            pnl_y = new_pnl_atr[mask] * atr[mask] * NQ_MULT - COMMISSION
            wr_y = (pnl_y > 0).mean() * 100
            print(f"    {y:>6} {n_y:>5,} {wr_y:>5.1f}% "
                  f"${pnl_y.mean():>+7.1f} ${pnl_y.sum():>+9,.0f}")

    print(f"\n{'='*120}")


if __name__ == "__main__":
    main()
