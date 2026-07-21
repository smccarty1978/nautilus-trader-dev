"""Study A: MTF filter at delayed entry.

At each delayed entry (60s/90s/120s), check:
  - 5m regime state (computed from precomputed 5m bars)
  - 5s micro direction (count up/down closes in last 12 1s bars)
Filter trades and report WR/Avg/FwdMFE/FwdMAE per filter.
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


# ---- 5m regime precomputation ----

@njit(cache=True)
def build_5m_regime(ts_1m, h_1m, l_1m, c_1m):
    """Build 5m bars from 1m bars (assume clock-aligned on 5-min boundaries).

    Returns: ts_5m_close (close time = ts_1m + 60s of last bar in window),
             regime_5m (-1/0/+1) for each 5m bar
    """
    n = len(ts_1m)
    # Worst case n 5m bars
    ts_5m = np.empty(n // 5 + 2, dtype=np.int64)
    h_5m = np.empty(n // 5 + 2)
    l_5m = np.empty(n // 5 + 2)
    c_5m = np.empty(n // 5 + 2)
    regime_5m = np.empty(n // 5 + 2, dtype=np.int32)

    # EMA 3/9 state for H, L, C
    alpha3 = 2.0 / 4.0
    alpha9 = 2.0 / 10.0
    emaH_3 = emaH_9 = emaL_3 = emaL_9 = 0.0
    count = 0
    regime = 0

    out_idx = 0
    i = 0
    while i < n:
        # Determine the 5m window for 1m bar i
        # Clock-aligned: minute_of_hour % 5 == 4 closes the window
        minute_of_hour = (ts_1m[i] // 60_000_000_000) % 60
        # Accumulate up to end of current 5m window
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
        # Emit 5m bar: close time = ts_1m of last bar in window + 60s
        close_ts_5m = ts_1m[j - 1] + 60_000_000_000
        ts_5m[out_idx] = close_ts_5m
        h_5m[out_idx] = agg_h
        l_5m[out_idx] = agg_l
        c_5m[out_idx] = agg_c

        # Update EMAs
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

        # Detect regime (after 9 bars for EMA warmup)
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
def compute_trade_filters(
    entry_ts, exit_ts, direction, atr,
    delay_s,
    ts_1s, h_1s, l_1s, c_1s, i_start, i_end,
    ts_5m, regime_5m,
):
    """At delayed entry, compute 5m regime state and 5s micro direction.

    Returns (survived, new_entry_px, fwd_peak_mfe, fwd_peak_mae,
             regime_5m_at_delay, micro_up_pct)
    """
    if atr <= 0 or i_end <= i_start:
        return (0, 0.0, 0.0, 0.0, 0, 0.0)
    delay_ts = entry_ts + delay_s * 1_000_000_000
    if exit_ts <= delay_ts:
        return (0, 0.0, 0.0, 0.0, 0, 0.0)
    i_delay = i_start
    while i_delay < i_end and ts_1s[i_delay] < delay_ts:
        i_delay += 1
    if i_delay >= i_end:
        return (0, 0.0, 0.0, 0.0, 0, 0.0)

    new_entry = c_1s[i_delay]

    # Walk forward for MFE/MAE
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

    # Find 5m regime state: most recent 5m bar close <= delay_ts
    # Binary search ts_5m
    lo = 0
    hi = len(ts_5m) - 1
    idx = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if ts_5m[mid] <= delay_ts:
            idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    regime_at_delay = regime_5m[idx] if idx >= 0 else 0

    # 5s micro: last 12 1s bars before delay_ts, count up closes
    # Up close = c > prev close (approximate direction)
    start_window = max(i_start, i_delay - 12)
    up_count = 0
    down_count = 0
    prev_c = c_1s[start_window]
    for i in range(start_window + 1, i_delay + 1):
        if c_1s[i] > prev_c:
            up_count += 1
        elif c_1s[i] < prev_c:
            down_count += 1
        prev_c = c_1s[i]
    total = up_count + down_count
    micro_up_pct = up_count / total if total > 0 else 0.5

    return (1, new_entry, peak_mfe, peak_mae,
             regime_at_delay, micro_up_pct)


def summarize(label, mask, trades, pnl, mfe, mae):
    n = mask.sum()
    if n == 0:
        return (label, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    sub_pnl = pnl[mask]
    sub_mfe = mfe[mask]
    sub_mae = mae[mask]
    wr = (sub_pnl > 0).mean() * 100
    avg = sub_pnl.mean()
    mfe_mean = sub_mfe.mean()
    mae_mean = sub_mae.mean()
    mfe_p50 = np.median(sub_mfe)
    mae_p50 = np.median(sub_mae)
    return (label, n, wr, avg, mfe_mean, mae_mean, mfe_p50, mae_p50)


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

    print("Building 5m regime sequence from 1m bars...")
    t0 = _time.time()
    ts_5m, regime_5m_arr = build_5m_regime(ts_1m, h_1m, l_1m, c_1m)
    print(f"  {len(ts_5m):,} 5m bars ({_time.time()-t0:.0f}s)")

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values
    regime_pnl = trades["regime_pnl_dollars"].values

    # JIT warmup
    compute_trade_filters(
        0, 60_000_000_000, 1, 1.0, 60,
        np.array([0, 1], dtype=np.int64),
        np.array([100.0, 100.0]), np.array([100.0, 100.0]),
        np.array([100.0, 100.0]), 0, 2,
        np.array([60_000_000_000], dtype=np.int64),
        np.array([1], dtype=np.int32))

    n_t = len(trades)
    print(f"\n{'='*105}")
    print(f"STUDY A — MTF Filter at Delayed Entry")
    print(f"{'='*105}")

    for delay_s in DELAYS_S:
        survived = np.empty(n_t, dtype=np.int32)
        peak_mfe = np.empty(n_t)
        peak_mae = np.empty(n_t)
        reg5m = np.empty(n_t, dtype=np.int32)
        micro_up = np.empty(n_t)

        for k in range(n_t):
            i_start = np.searchsorted(ts_1s, entry_ts[k], side="left")
            i_end = np.searchsorted(ts_1s, exit_ts[k], side="right")
            s, _, pm, pa, r5m, mu = compute_trade_filters(
                entry_ts[k], exit_ts[k], direction[k], atr[k],
                delay_s, ts_1s, h_1s, l_1s, c_1s, i_start, i_end,
                ts_5m, regime_5m_arr)
            survived[k] = s
            peak_mfe[k] = pm
            peak_mae[k] = pa
            reg5m[k] = r5m
            micro_up[k] = mu

        surv_mask = survived == 1
        # Direction-aware:
        reg5m_aligned = ((reg5m == direction) & surv_mask)
        micro_aligned = (
            ((direction == 1) & (micro_up >= 0.583) & surv_mask) |
            ((direction == -1) & ((1 - micro_up) >= 0.583) & surv_mask))
        micro_opposing = (
            ((direction == 1) & ((1 - micro_up) >= 0.583) & surv_mask) |
            ((direction == -1) & (micro_up >= 0.583) & surv_mask))

        # Filters
        filters = [
            ("no filter (survived)", surv_mask),
            ("5m aligned", surv_mask & reg5m_aligned),
            ("5m NOT aligned", surv_mask & ~reg5m_aligned),
            ("5s micro aligned", surv_mask & micro_aligned),
            ("5s micro opposing", surv_mask & micro_opposing),
            ("5m aligned & 5s not opposing",
             surv_mask & reg5m_aligned & ~micro_opposing),
            ("5m aligned & 5s aligned",
             surv_mask & reg5m_aligned & micro_aligned),
        ]

        print(f"\n--- Delay +{delay_s}s ---")
        print(f"  Alive at delay: {surv_mask.sum():,} / {n_t:,}")
        print(f"\n  {'Filter':<32} {'N':>7} {'N%':>6} "
              f"{'WR':>6} {'Avg$':>8} "
              f"{'fMFE':>6} {'fMAE':>6} "
              f"{'fMFE_P50':>9} {'fMAE_P50':>9}")
        print("  " + "-" * 98)
        for label, mask in filters:
            s = summarize(label, mask, trades, regime_pnl,
                            peak_mfe, peak_mae)
            _, n_f, wr, avg, mm, ma, m_p50, ma_p50 = s
            flag = " ★" if wr > 33.3 and avg > 0 else ""
            print(f"  {label:<32} {n_f:>7,} "
                  f"{n_f/surv_mask.sum()*100:>5.1f}% "
                  f"{wr:>5.1f}% ${avg:>+7.1f} "
                  f"{mm:>6.3f} {ma:>6.3f} "
                  f"{m_p50:>9.3f} {ma_p50:>9.3f}{flag}")

    print(f"\n{'='*105}")


if __name__ == "__main__":
    main()
