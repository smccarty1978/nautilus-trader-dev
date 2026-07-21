"""Asymmetric bracket race on high-variance subsets.

If magnitude is predictable, a 2:1 or 2.67:1 bracket might clear its
lower breakeven threshold on Q5 trades even if direction is 50/50.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time as _time
import pandas as pd
import numpy as np
from numba import njit

from nautilus_trader.persistence.catalog import ParquetDataCatalog


@njit(cache=True)
def race_bracket(entry_px, direction, atr,
                 h_arr, l_arr,
                 pt_atr, sl_atr):
    n = len(h_arr)
    if n == 0 or atr <= 0:
        return 3
    pt_px = entry_px + direction * pt_atr * atr
    sl_px = entry_px - direction * sl_atr * atr
    for i in range(n):
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            pt_hit = h >= pt_px
            sl_hit = l <= sl_px
        else:
            pt_hit = l <= pt_px
            sl_hit = h >= sl_px
        if pt_hit and sl_hit:
            return 0  # both → optimistic PT
        if pt_hit:
            return 0
        if sl_hit:
            return 1
    return 3


NQ_MULT = 20.0
COMMISSION = 5.0


def race_and_report(label, mask, trades, h_list, l_list,
                    atr_arr, entry_px, direction, configs):
    idx = np.where(mask)[0]
    n = len(idx)
    if n < 50:
        return
    print(f"\n{'='*92}")
    print(f"  {label}  (N={n:,})")
    print(f"{'='*92}")
    print(f"  {'PT/SL':>10} {'PT%':>7} {'SL%':>7} {'Neither%':>9} "
          f"{'BE_WR':>7} {'Avg$':>8} {'Total$':>11} {'PF':>5}")
    print("-" * 92)
    reg_pnl = trades["regime_pnl_dollars"].values
    for pt, sl in configs:
        outs = np.empty(n, dtype=np.int32)
        for j, k in enumerate(idx):
            if atr_arr[k] <= 0 or len(h_list[k]) == 0:
                outs[j] = 3
                continue
            outs[j] = race_bracket(
                entry_px[k], direction[k], atr_arr[k],
                h_list[k], l_list[k], pt, sl)

        n_pt = (outs == 0).sum()
        n_sl = (outs == 1).sum()
        n_nei = (outs == 3).sum()

        # PnL
        pnl = np.zeros(n)
        atr_sub = atr_arr[idx]
        reg_sub = reg_pnl[idx]
        pnl[outs == 0] = pt * atr_sub[outs == 0] * NQ_MULT - COMMISSION
        pnl[outs == 1] = -sl * atr_sub[outs == 1] * NQ_MULT - COMMISSION
        pnl[outs == 3] = reg_sub[outs == 3]

        avg = pnl.mean()
        total = pnl.sum()
        gw = pnl[pnl > 0].sum()
        gl = abs(pnl[pnl <= 0].sum())
        pf = gw / gl if gl > 0 else 999
        be_wr = sl / (pt + sl) * 100
        pt_pct = n_pt / n * 100
        flag = " ★" if pt_pct > be_wr + 0.5 else ""
        print(f"  {pt:.2f}/{sl:.2f}  {pt_pct:>6.1f}% "
              f"{n_sl/n*100:>6.1f}% {n_nei/n*100:>8.1f}% "
              f"{be_wr:>6.1f}% ${avg:>+7.1f} ${total:>+10,.0f} "
              f"{pf:>4.2f}{flag}")


def main():
    print("=" * 92)
    print("ASYMMETRIC BRACKET RACE — Q5 variance subsets (6 years)")
    print("  Does magnitude predictability = asymmetric edge?")
    print("  ★ = PT-first% exceeds breakeven threshold")
    print("=" * 92)

    print("\nLoading trades...")
    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    print(f"  {len(trades):,} trades")

    print("\nLoading 1s bars (6 years)...")
    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")

    print("Extracting...")
    t0 = _time.time()
    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    high_arr = np.empty(n)
    low_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        high_arr[i] = float(b.high)
        low_arr[i] = float(b.low)
    del bars_1s
    print(f"  Done ({_time.time()-t0:.0f}s)")

    entry_walk = trades["entry_ts"].astype("int64").values + 60_000_000_000
    exit_walk = (pd.to_datetime(trades["exit_time"]).astype("int64").values
                 + 60_000_000_000)
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr_arr = trades["atr_at_flip"].values

    h_list = [None] * len(trades)
    l_list = [None] * len(trades)
    for k in range(len(trades)):
        i_start = np.searchsorted(ts_arr, entry_walk[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_walk[k], side="right")
        h_list[k] = high_arr[i_start:i_end]
        l_list[k] = low_arr[i_start:i_end]

    # JIT warmup
    race_bracket(100.0, 1, 1.0,
                  np.array([100.0]), np.array([100.0]), 1.0, 1.0)

    # ---- Compute Q5 masks ----
    ema_spread = trades["ema_spread"].values
    flip_range = trades["flip_bar_range_atr"].values
    vol_vs_avg = trades["flip_bar_vol_vs_20avg"].values

    ema_q5 = ema_spread >= np.percentile(ema_spread, 80)
    range_q5 = flip_range >= np.percentile(flip_range, 80)
    vol_q5 = vol_vs_avg >= np.percentile(vol_vs_avg, 80)
    both_q5 = ema_q5 & range_q5
    triple_q5 = ema_q5 & range_q5 & vol_q5

    print(f"\nSegment sizes:")
    print(f"  All trades:               {len(trades):,}")
    print(f"  Q5 ema_spread:            {ema_q5.sum():,}")
    print(f"  Q5 flip_bar_range_atr:    {range_q5.sum():,}")
    print(f"  Q5 vol_vs_20avg:          {vol_q5.sum():,}")
    print(f"  ema_q5 × range_q5:        {both_q5.sum():,}")
    print(f"  ema_q5 × range_q5 × vol_q5: {triple_q5.sum():,}")

    configs = [
        (0.75, 0.75),   # reference: symmetric
        (1.00, 1.00),   # reference
        (1.50, 0.75),   # 2:1
        (2.00, 1.00),   # 2:1
        (1.50, 1.00),   # 1.5:1
        (2.00, 0.75),   # 2.67:1
        (2.00, 0.50),   # 4:1 bonus — can we clear 20% PT-first?
    ]

    race_and_report("ALL trades (baseline)",
                     np.ones(len(trades), bool),
                     trades, h_list, l_list, atr_arr, entry_px, direction,
                     configs)
    race_and_report("Q5 ema_spread (top 20% band width)", ema_q5,
                     trades, h_list, l_list, atr_arr, entry_px, direction,
                     configs)
    race_and_report("Q5 flip_bar_range_atr (top 20% flip size)", range_q5,
                     trades, h_list, l_list, atr_arr, entry_px, direction,
                     configs)
    race_and_report("Q5 ema × Q5 range (intersection)", both_q5,
                     trades, h_list, l_list, atr_arr, entry_px, direction,
                     configs)
    race_and_report("Q5 ema × Q5 range × Q5 volume (triple intersection)",
                     triple_q5,
                     trades, h_list, l_list, atr_arr, entry_px, direction,
                     configs)

    # Year-by-year for best subset × best bracket
    print(f"\n{'='*92}")
    print(f"YEAR STABILITY — ema_q5 × range_q5 at PT 2.00/SL 1.00")
    print(f"{'='*92}")
    print(f"  {'Year':>6} {'N':>7} {'PT%':>7} {'SL%':>7} {'Avg$':>8} "
          f"{'Total$':>11}")
    idx = np.where(both_q5)[0]
    outs = np.empty(len(idx), dtype=np.int32)
    for j, k in enumerate(idx):
        if atr_arr[k] <= 0 or len(h_list[k]) == 0:
            outs[j] = 3
            continue
        outs[j] = race_bracket(
            entry_px[k], direction[k], atr_arr[k],
            h_list[k], l_list[k], 2.00, 1.00)
    atr_sub = atr_arr[idx]
    reg_sub = trades["regime_pnl_dollars"].values[idx]
    years = trades["year"].values[idx]
    pnl = np.zeros(len(idx))
    pnl[outs == 0] = 2.00 * atr_sub[outs == 0] * NQ_MULT - COMMISSION
    pnl[outs == 1] = -1.00 * atr_sub[outs == 1] * NQ_MULT - COMMISSION
    pnl[outs == 3] = reg_sub[outs == 3]
    for year in sorted(np.unique(years)):
        ym = years == year
        if ym.sum() < 20:
            continue
        yo = outs[ym]
        yp = pnl[ym]
        print(f"  {year:>6} {ym.sum():>7,} "
              f"{(yo == 0).mean()*100:>6.1f}% "
              f"{(yo == 1).mean()*100:>6.1f}% "
              f"${yp.mean():>+7.1f} ${yp.sum():>+10,.0f}")

    print(f"\n{'='*92}")


if __name__ == "__main__":
    main()
