"""Study C: Combined strategy simulation.

Four variants (using delay=90s and 5s-micro-aligned filter):
  V1: delay + skip(fast-fail) + 5s micro filter + regime exit (no trail, no SL)
  V2: V1 + catastrophic SL at 2.0 ATR
  V3: V1 + trail (arm 0.50, dist 0.25)
  V4: V1 + catastrophic SL + trail (the full spec)

For each variant, report:
  - Skipped (died) count
  - Skipped (filter) count
  - Entered count, exit reason breakdown
  - Total PnL
  - Year-by-year
  - RTH/ETH
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

# Config
DELAY_S = 90
MICRO_THR = 0.583     # ≥7/12 up
TRAIL_ARM = 0.50
TRAIL_DIST = 0.25
SL_ATR = 2.00


@njit(cache=True)
def simulate(
    entry_ts, exit_ts, direction, atr,
    exit_price,
    delay_s,
    micro_thr, trail_arm, trail_dist, sl_atr,
    apply_sl, apply_trail,
    ts_1s, h_1s, l_1s, c_1s, i_start, i_end,
):
    """Run full simulation for one trade.

    Returns (outcome_code, pnl_atr)
      outcome_code:
        0 = skipped (died before delay)
        1 = skipped (5s filter)
        2 = SL hit
        3 = trail hit
        4 = regime exit
    """
    if atr <= 0 or i_end <= i_start:
        return (0, 0.0)

    delay_ts = entry_ts + delay_s * 1_000_000_000
    if exit_ts <= delay_ts:
        return (0, 0.0)

    i_delay = i_start
    while i_delay < i_end and ts_1s[i_delay] < delay_ts:
        i_delay += 1
    if i_delay >= i_end:
        return (0, 0.0)

    # Check 5s micro filter: last 12 1s closes at i_delay
    window_start = max(i_start, i_delay - 12)
    prev_c = c_1s[window_start]
    up = 0
    down = 0
    for i in range(window_start + 1, i_delay + 1):
        if c_1s[i] > prev_c:
            up += 1
        elif c_1s[i] < prev_c:
            down += 1
        prev_c = c_1s[i]
    total = up + down
    if total == 0:
        return (1, 0.0)
    if direction == 1:
        micro_ratio = up / total
    else:
        micro_ratio = down / total
    if micro_ratio < micro_thr:
        return (1, 0.0)

    new_entry = c_1s[i_delay]
    sl_px = new_entry - direction * sl_atr * atr
    peak_mfe = 0.0
    trail_armed = False
    trail_px = 0.0

    for i in range(i_delay + 1, i_end):
        h = h_1s[i]
        l = l_1s[i]
        # Check SL first (intra-bar)
        if apply_sl:
            if direction == 1 and l <= sl_px:
                return (2, -sl_atr)
            elif direction == -1 and h >= sl_px:
                return (2, -sl_atr)
        # MFE for trail
        if apply_trail:
            if direction == 1:
                cur_mfe = (h - new_entry) / atr
            else:
                cur_mfe = (new_entry - l) / atr
            if cur_mfe > peak_mfe:
                peak_mfe = cur_mfe
                if peak_mfe >= trail_arm:
                    trail_armed = True
                if trail_armed:
                    trail_px = (new_entry
                                 + direction * (peak_mfe - trail_dist) * atr)
            if trail_armed:
                if direction == 1 and l <= trail_px:
                    return (3, peak_mfe - trail_dist)
                elif direction == -1 and h >= trail_px:
                    return (3, peak_mfe - trail_dist)

    # Regime exit
    new_pnl_atr = (exit_price - new_entry) * direction / atr
    return (4, new_pnl_atr)


def run_variant(name, trades_data, delay_s, apply_sl, apply_trail):
    (entry_ts, exit_ts, direction, atr, exit_px,
     ts_1s, h_1s, l_1s, c_1s, year_arr, is_rth_arr) = trades_data

    n_t = len(entry_ts)
    outcome = np.empty(n_t, dtype=np.int32)
    pnl_atr = np.empty(n_t)
    for k in range(n_t):
        i_start = np.searchsorted(ts_1s, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_1s, exit_ts[k], side="right")
        o, p = simulate(
            entry_ts[k], exit_ts[k], direction[k], atr[k], exit_px[k],
            delay_s,
            MICRO_THR, TRAIL_ARM, TRAIL_DIST, SL_ATR,
            apply_sl, apply_trail,
            ts_1s, h_1s, l_1s, c_1s, i_start, i_end)
        outcome[k] = o
        pnl_atr[k] = p

    # Dollar PnL (only for entered trades)
    pnl_dollars = np.where(
        outcome >= 2,
        pnl_atr * atr * NQ_MULT - COMMISSION,
        0.0)  # skipped → $0

    # Report
    n_died = (outcome == 0).sum()
    n_filtered = (outcome == 1).sum()
    n_sl = (outcome == 2).sum()
    n_trail = (outcome == 3).sum()
    n_regime = (outcome == 4).sum()
    n_entered = n_sl + n_trail + n_regime
    total = pnl_dollars.sum()
    entered_avg = (pnl_dollars[outcome >= 2].mean()
                    if n_entered > 0 else 0)
    per_opp = total / n_t

    print(f"\n--- Variant: {name} ---")
    print(f"  Total opps: {n_t:,}")
    print(f"  Skipped (died before delay): {n_died:,} "
          f"({n_died/n_t*100:.1f}%)")
    print(f"  Skipped (5s filter): {n_filtered:,} "
          f"({n_filtered/n_t*100:.1f}%)")
    print(f"  ENTERED: {n_entered:,} "
          f"({n_entered/n_t*100:.1f}%)")
    if n_entered > 0:
        if n_sl > 0:
            avg_sl = pnl_dollars[outcome == 2].mean()
            print(f"    SL hit:      {n_sl:>6,} ({n_sl/n_entered*100:>4.1f}%)  avg ${avg_sl:+.1f}")
        if n_trail > 0:
            avg_trail = pnl_dollars[outcome == 3].mean()
            wr_trail = (pnl_dollars[outcome == 3] > 0).mean() * 100
            print(f"    Trail hit:   {n_trail:>6,} ({n_trail/n_entered*100:>4.1f}%)  avg ${avg_trail:+.1f}  WR {wr_trail:.1f}%")
        if n_regime > 0:
            avg_reg = pnl_dollars[outcome == 4].mean()
            wr_reg = (pnl_dollars[outcome == 4] > 0).mean() * 100
            print(f"    Regime exit: {n_regime:>6,} ({n_regime/n_entered*100:>4.1f}%)  avg ${avg_reg:+.1f}  WR {wr_reg:.1f}%")

    print(f"  Entered avg: ${entered_avg:+.2f}")
    print(f"  Strategy total: ${total:+,.0f}")
    print(f"  Per-opportunity avg: ${per_opp:+.2f}")

    # Year-by-year
    print(f"\n  Year-by-year (entered trades):")
    print(f"    {'Year':>6} {'N ent':>7} {'WR%':>6} {'Avg$':>8} {'Total$':>11}")
    for y in sorted(np.unique(year_arr)):
        ym = (year_arr == y) & (outcome >= 2)
        n = ym.sum()
        if n == 0:
            continue
        sub_pnl = pnl_dollars[ym]
        wr = (sub_pnl > 0).mean() * 100
        print(f"    {y:>6} {n:>7,} {wr:>5.1f}% "
              f"${sub_pnl.mean():>+7.1f} "
              f"${sub_pnl.sum():>+10,.0f}")

    # RTH / ETH
    for val, lbl in [(1, "RTH"), (0, "ETH")]:
        sub_mask = (is_rth_arr == val) & (outcome >= 2)
        n = sub_mask.sum()
        if n == 0:
            continue
        sub_pnl = pnl_dollars[sub_mask]
        wr = (sub_pnl > 0).mean() * 100
        print(f"  {lbl}: N={n:,}  WR={wr:.1f}%  "
              f"Avg ${sub_pnl.mean():+.2f}  "
              f"Total ${sub_pnl.sum():+,.0f}")

    return total


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

    trades_data = (
        trades["entry_ts"].astype("int64").values,
        pd.to_datetime(trades["exit_time"]).astype("int64").values,
        trades["direction"].values.astype(np.int64),
        trades["atr_at_entry"].values,
        trades["exit_price"].values,
        ts_1s, h_1s, l_1s, c_1s,
        trades["year"].values,
        trades["is_rth"].values,
    )

    # JIT warmup
    simulate(0, 60_000_000_000, 1, 1.0, 100.0, 60,
              0.5, 0.5, 0.25, 2.0, True, True,
              np.array([0, 1], dtype=np.int64),
              np.array([100.0, 100.0]), np.array([100.0, 100.0]),
              np.array([100.0, 100.0]), 0, 2)

    baseline_total = trades["regime_pnl_dollars"].sum()

    print(f"\n{'='*105}")
    print(f"STUDY C — Combined Strategy Simulations (delay={DELAY_S}s, "
          f"5s micro thr={MICRO_THR:.3f})")
    print(f"{'='*105}")
    print(f"Baseline (no delay, no filter, no SL, no trail): "
          f"${baseline_total:+,.0f}")

    v1 = run_variant("V1: delay + skip-died + 5s filter + regime exit",
                      trades_data, DELAY_S, False, False)
    v2 = run_variant("V2: V1 + catastrophic SL @ 2.0 ATR",
                      trades_data, DELAY_S, True, False)
    v3 = run_variant("V3: V1 + trail (arm 0.5, dist 0.25)",
                      trades_data, DELAY_S, False, True)
    v4 = run_variant("V4: V1 + SL + trail (full spec)",
                      trades_data, DELAY_S, True, True)

    print(f"\n{'='*105}")
    print(f"SUMMARY (baseline ${baseline_total:+,.0f})")
    print(f"{'='*105}")
    for name, total in [("V1 (filter only)", v1),
                         ("V2 (+ SL)", v2),
                         ("V3 (+ trail)", v3),
                         ("V4 (full spec)", v4)]:
        delta = total - baseline_total
        print(f"  {name:<25} Total ${total:>+12,.0f}  "
              f"Δ baseline ${delta:>+12,.0f}")

    print(f"\n{'='*105}")


if __name__ == "__main__":
    main()
