"""Bracket race segmented by RTH/ETH and flip-bar size.

Tests the same 5 PT/SL configs on the full 6-year confirmed flip
population, segmented to find subsets where PT-first beats breakeven.
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
        return 3, -1, 0.0, 0.0
    pt_px = entry_px + direction * pt_atr * atr
    sl_px = entry_px - direction * sl_atr * atr
    peak_mfe = 0.0
    peak_mae = 0.0
    for i in range(n):
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            cur_mfe = (h - entry_px) / atr
            cur_mae = (entry_px - l) / atr
            pt_hit = h >= pt_px
            sl_hit = l <= sl_px
        else:
            cur_mfe = (entry_px - l) / atr
            cur_mae = (h - entry_px) / atr
            pt_hit = l <= pt_px
            sl_hit = h >= sl_px
        if cur_mfe > peak_mfe:
            peak_mfe = cur_mfe
        if cur_mae > peak_mae:
            peak_mae = cur_mae
        if pt_hit and sl_hit:
            return 2, i, peak_mfe, peak_mae
        if pt_hit:
            return 0, i, peak_mfe, peak_mae
        if sl_hit:
            return 1, i, peak_mfe, peak_mae
    return 3, -1, peak_mfe, peak_mae


def race_segment(label, mask, trades, h_list, l_list,
                  atr_arr, entry_px, direction, configs,
                  pt_lookup, sl_lookup, ts_arr_dummy=None):
    """Race all configs on a subset of trades."""
    idx = np.where(mask)[0]
    n = len(idx)
    if n == 0:
        return None
    print(f"\n{'='*88}")
    print(f"  SEGMENT: {label}  (N={n:,})")
    print(f"{'='*88}")
    print(f"  {'PT/SL':>10} {'PT%':>7} {'SL%':>7} {'Both%':>7} "
          f"{'Neither%':>9} {'Avg$':>8} {'Total$':>11} {'WR':>6} {'PF':>5} "
          f"{'BE_WR':>6}")
    print("-" * 88)
    nq_mult = 20.0
    comm = 5.0
    reg_pnl = trades["regime_pnl_dollars"].values
    for pt, sl in configs:
        outs = np.empty(n, dtype=np.int32)
        for j, k in enumerate(idx):
            if atr_arr[k] <= 0 or len(h_list[k]) == 0:
                outs[j] = 3
                continue
            o, _, _, _ = race_bracket(
                entry_px[k], direction[k], atr_arr[k],
                h_list[k], l_list[k], pt, sl)
            outs[j] = o
        n_pt = (outs == 0).sum() + (outs == 2).sum()  # both → optimistic PT
        n_sl = (outs == 1).sum()
        n_both = (outs == 2).sum()
        n_neither = (outs == 3).sum()

        # PnL
        pnl = np.zeros(n)
        atr_sub = atr_arr[idx]
        pnl[outs == 0] = pt * atr_sub[outs == 0] * nq_mult - comm
        pnl[outs == 2] = pt * atr_sub[outs == 2] * nq_mult - comm
        pnl[outs == 1] = -sl * atr_sub[outs == 1] * nq_mult - comm
        reg_sub = reg_pnl[idx]
        pnl[outs == 3] = reg_sub[outs == 3]

        avg = pnl.mean()
        total = pnl.sum()
        wr = (pnl > 0).mean() * 100
        gw = pnl[pnl > 0].sum()
        gl = abs(pnl[pnl <= 0].sum())
        pf = gw / gl if gl > 0 else 999
        # Breakeven WR ignoring commission: SL/(PT+SL)
        be_wr = sl / (pt + sl) * 100
        marker = " ★" if wr > be_wr else ""
        print(f"  {pt:.2f}/{sl:.2f}   {n_pt/n*100:>6.1f}% "
              f"{n_sl/n*100:>6.1f}% {n_both/n*100:>6.1f}% "
              f"{n_neither/n*100:>8.1f}% "
              f"${avg:>+7.1f} ${total:>+10,.0f} "
              f"{wr:>5.1f}% {pf:>4.2f} {be_wr:>5.1f}%{marker}")
    return None


def main():
    print("=" * 88)
    print("BRACKET RACE — segmented (6 years, 2020-2025)")
    print("  ★ = WR exceeds breakeven threshold")
    print("=" * 88)

    print("\nLoading trades (6 years)...")
    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    trades["entry_dt"] = pd.to_datetime(
        trades["entry_ts"], unit="ns", utc=True)
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

    print("Pre-slicing...")
    t0 = _time.time()
    h_list = [None] * len(trades)
    l_list = [None] * len(trades)
    for k in range(len(trades)):
        i_start = np.searchsorted(ts_arr, entry_walk[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_walk[k], side="right")
        h_list[k] = high_arr[i_start:i_end]
        l_list[k] = low_arr[i_start:i_end]
    print(f"  Done ({_time.time()-t0:.0f}s)")

    # JIT warmup
    race_bracket(100.0, 1, 1.0,
                  np.array([100.0]), np.array([100.0]), 1.0, 1.0)

    configs = [
        (0.50, 0.50),
        (0.75, 0.75),
        (1.00, 1.00),
        (0.50, 0.25),
        (1.00, 0.50),
    ]

    pt_lookup = sl_lookup = None  # not needed

    is_rth = trades["is_rth"].values == 1
    is_eth = ~is_rth

    # Flip bar range — find column name
    if "flip_bar_range_atr" in trades.columns:
        flip_size = trades["flip_bar_range_atr"].values
    else:
        flip_size = (trades["flip_bar_high"] - trades["flip_bar_low"]).values \
                    / atr_arr

    big_flip_15 = flip_size > 1.5
    big_flip_20 = flip_size > 2.0
    big_flip_30 = flip_size > 3.0

    # Run segments
    race_segment("ALL trades", np.ones(len(trades), bool),
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)
    race_segment("RTH only", is_rth,
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)
    race_segment("ETH only", is_eth,
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)
    race_segment("Flip bar range > 1.5 ATR", big_flip_15,
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)
    race_segment("Flip bar range > 2.0 ATR", big_flip_20,
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)
    race_segment("Flip bar range > 3.0 ATR", big_flip_30,
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)

    # RTH × big flip combos
    race_segment("RTH × Flip > 1.5 ATR", is_rth & big_flip_15,
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)
    race_segment("RTH × Flip > 2.0 ATR", is_rth & big_flip_20,
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)
    race_segment("ETH × Flip > 2.0 ATR", is_eth & big_flip_20,
                  trades, h_list, l_list, atr_arr, entry_px, direction,
                  configs, pt_lookup, sl_lookup)

    print(f"\n{'='*88}")


if __name__ == "__main__":
    main()
