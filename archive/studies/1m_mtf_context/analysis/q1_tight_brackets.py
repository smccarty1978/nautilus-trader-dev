"""Test tighter brackets on Q1 of two_bar_close_vs_open_pct.

Q1 (most counter-flip 2-bar body) showed PT 47.1% vs SL 38.0% at 1.00/1.00
bracket — a 9pp asymmetry, but 14.9% neither-rate killed the PnL. Tighter
brackets should force more resolution. Question: does asymmetry survive?

Tests:
  PT 0.50 / SL 0.50
  PT 0.75 / SL 0.75
  PT 0.75 / SL 0.50  (1.5:1)
  PT 1.00 / SL 0.75  (1.33:1)
  PT 1.00 / SL 1.00  (baseline, already known)

Plus year-by-year on the 1.00/1.00 baseline.
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
            return 0
        if pt_hit:
            return 0
        if sl_hit:
            return 1
    return 3


def report_bracket(name, pt, sl, outs, atr_arr, reg_pnl):
    n = len(outs)
    n_pt = (outs == 0).sum()
    n_sl = (outs == 1).sum()
    n_nei = (outs == 3).sum()
    pnl = np.zeros(n)
    pnl[outs == 0] = pt * atr_arr[outs == 0] * NQ_MULT - COMMISSION
    pnl[outs == 1] = -sl * atr_arr[outs == 1] * NQ_MULT - COMMISSION
    pnl[outs == 3] = reg_pnl[outs == 3]
    avg = pnl.mean()
    total = pnl.sum()
    wr = (pnl > 0).mean() * 100
    gw = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gw / gl if gl > 0 else 999
    be = sl / (pt + sl) * 100
    edge_pp = n_pt / n * 100 - be
    flag = " ★" if avg > 0 else ""
    print(f"  {name:<14}  PT={n_pt/n*100:>5.1f}% SL={n_sl/n*100:>5.1f}% "
          f"Nei={n_nei/n*100:>5.1f}%  BE={be:>5.1f}%  edge={edge_pp:>+5.1f}pp  "
          f"Avg=${avg:>+7.1f}  Tot=${total:>+10,.0f}  PF={pf:>4.2f}{flag}")
    return outs


def main():
    print("=" * 110)
    print("TIGHT BRACKETS ON Q1 OF two_bar_close_vs_open_pct")
    print("  (Q1 = most counter-flip 2-bar body)")
    print("=" * 110)

    print("\nLoading trades...")
    trades = pd.read_parquet(
        "studies/1m_mtf_context/results/trades_all.parquet").copy()
    print(f"  Total trades: {len(trades):,}")

    # Compute Q1 mask
    trades["_q"] = pd.qcut(trades["two_bar_close_vs_open_pct"], q=5,
                            labels=False, duplicates="drop")
    q1_mask = trades["_q"] == 0
    q1 = trades[q1_mask].reset_index(drop=True)
    print(f"  Q1 subset: {len(q1):,} trades "
          f"(range two_bar_close_vs_open_pct: "
          f"[{q1['two_bar_close_vs_open_pct'].min():.3f}, "
          f"{q1['two_bar_close_vs_open_pct'].max():.3f}])")

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
    print(f"  ({_time.time()-t0:.0f}s)")

    entry_walk = q1["entry_ts"].astype("int64").values
    exit_walk = (pd.to_datetime(q1["exit_time"]).astype("int64").values)
    entry_px = q1["entry_price"].values
    direction = q1["direction"].values.astype(np.int64)
    atr_arr = q1["atr_at_entry"].values
    reg_pnl = q1["regime_pnl_dollars"].values

    print("\nPre-slicing...")
    t0 = _time.time()
    h_list = [None] * len(q1)
    l_list = [None] * len(q1)
    for k in range(len(q1)):
        i_start = np.searchsorted(ts_arr, entry_walk[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_walk[k], side="right")
        h_list[k] = high_arr[i_start:i_end]
        l_list[k] = low_arr[i_start:i_end]
    print(f"  ({_time.time()-t0:.0f}s)")

    # JIT warmup
    race_bracket(100.0, 1, 1.0,
                  np.array([100.0]), np.array([100.0]), 1.0, 1.0)

    BRACKETS = [
        ("PT0.50/SL0.50", 0.50, 0.50),
        ("PT0.75/SL0.75", 0.75, 0.75),
        ("PT0.75/SL0.50", 0.75, 0.50),
        ("PT1.00/SL0.75", 1.00, 0.75),
        ("PT1.00/SL1.00", 1.00, 1.00),
        ("PT1.50/SL1.00", 1.50, 1.00),
    ]

    print(f"\n{'='*110}")
    print(f"BRACKET RESULTS (Q1 N={len(q1):,})")
    print(f"{'='*110}")
    bracket_outs = {}
    for name, pt, sl in BRACKETS:
        outs = np.empty(len(q1), dtype=np.int32)
        for k in range(len(q1)):
            if atr_arr[k] <= 0 or len(h_list[k]) == 0:
                outs[k] = 3
                continue
            outs[k] = race_bracket(
                entry_px[k], direction[k], atr_arr[k],
                h_list[k], l_list[k], pt, sl)
        bracket_outs[name] = outs
        report_bracket(name, pt, sl, outs, atr_arr, reg_pnl)

    # Year-by-year on 1.00/1.00 (and the best new bracket)
    print(f"\n{'='*110}")
    print(f"YEAR-BY-YEAR — Q1 subset")
    print(f"{'='*110}")
    years = q1["year"].values

    for name, pt, sl in [("PT0.75/SL0.75", 0.75, 0.75),
                         ("PT1.00/SL1.00", 1.00, 1.00),
                         ("PT0.75/SL0.50", 0.75, 0.50)]:
        outs = bracket_outs[name]
        print(f"\n  {name}:")
        print(f"    {'Year':>6} {'N':>6} {'PT%':>6} {'SL%':>6} {'Nei%':>6} "
              f"{'Edge':>6} {'Avg$':>8} {'Total$':>11}")
        for y in sorted(np.unique(years)):
            ym = years == y
            yo = outs[ym]
            ya = atr_arr[ym]
            yr = reg_pnl[ym]
            n = ym.sum()
            n_pt = (yo == 0).sum()
            n_sl = (yo == 1).sum()
            n_nei = (yo == 3).sum()
            be = sl / (pt + sl) * 100
            edge = n_pt / n * 100 - be
            pnl = np.zeros(n)
            pnl[yo == 0] = pt * ya[yo == 0] * NQ_MULT - COMMISSION
            pnl[yo == 1] = -sl * ya[yo == 1] * NQ_MULT - COMMISSION
            pnl[yo == 3] = yr[yo == 3]
            print(f"    {y:>6} {n:>6,} {n_pt/n*100:>5.1f}% "
                  f"{n_sl/n*100:>5.1f}% {n_nei/n*100:>5.1f}% "
                  f"{edge:>+5.1f}pp ${pnl.mean():>+7.1f} "
                  f"${pnl.sum():>+10,.0f}")

    # Resolved-only PT-vs-SL ratio (excluding "neither")
    print(f"\n{'='*110}")
    print(f"RESOLVED-ONLY PT% (excluding regime fallbacks)")
    print(f"{'='*110}")
    print(f"  {'Bracket':<14} {'Resolved N':>11} {'PT/(PT+SL)':>11}  "
          f"vs BE")
    for name, pt, sl in BRACKETS:
        outs = bracket_outs[name]
        n_pt = (outs == 0).sum()
        n_sl = (outs == 1).sum()
        n_resolved = n_pt + n_sl
        if n_resolved == 0:
            continue
        pt_resolved = n_pt / n_resolved * 100
        be = sl / (pt + sl) * 100
        edge = pt_resolved - be
        flag = " ★" if edge > 0 else ""
        print(f"  {name:<14} {n_resolved:>11,} {pt_resolved:>10.1f}%  "
              f"vs {be:.1f}% (edge {edge:+.1f}pp){flag}")

    print(f"\n{'='*110}")


if __name__ == "__main__":
    main()
