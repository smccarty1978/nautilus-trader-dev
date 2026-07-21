"""Head-to-head bracket race for PT/SL combos.

For each trade, find the first 1s bar where MFE hits PT level (race A)
and the first 1s bar where MAE hits SL level (race B). Whichever comes
first wins.

Reports the full breakdown for PT 0.75 / SL 0.75 and a few others to
reconcile the path-MAE-at-MFE table with the actual bracket result.

Also for SL-first trades: what was their peak MFE before SL?
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
    """Race PT vs SL on 1s bars.

    Returns:
      outcome: 0=PT first, 1=SL first, 2=both same bar, 3=neither
      bar_idx: bar where outcome resolved (-1 if neither)
      peak_mfe: max MFE up to and including resolution bar
      peak_mae: max MAE up to and including resolution bar
    """
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


def race_one_config(pt_atr, sl_atr, trades, h_list, l_list, atr_arr,
                     entry_px, direction):
    n_t = len(trades)
    outcomes = np.empty(n_t, dtype=np.int32)
    bar_idx = np.empty(n_t, dtype=np.int64)
    peak_mfes = np.empty(n_t)
    peak_maes = np.empty(n_t)

    for k in range(n_t):
        if atr_arr[k] <= 0 or len(h_list[k]) == 0:
            outcomes[k] = 3
            bar_idx[k] = -1
            peak_mfes[k] = 0
            peak_maes[k] = 0
            continue
        o, b, pm, ma = race_bracket(
            entry_px[k], direction[k], atr_arr[k],
            h_list[k], l_list[k], pt_atr, sl_atr)
        outcomes[k] = o
        bar_idx[k] = b
        peak_mfes[k] = pm
        peak_maes[k] = ma

    return outcomes, bar_idx, peak_mfes, peak_maes


def main():
    print("=" * 80)
    print("HEAD-TO-HEAD BRACKET RACE (2025)")
    print("=" * 80)

    print("\nLoading trades + 1s bars...")
    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    trades["entry_dt"] = pd.to_datetime(
        trades["entry_ts"], unit="ns", utc=True)
    trades = trades[
        (trades["entry_dt"] >= "2025-01-01") &
        (trades["entry_dt"] < "2026-01-01")
    ].reset_index(drop=True)
    print(f"  {len(trades):,} trades")

    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  {len(bars_1s):,} 1s bars ({_time.time()-t0:.0f}s)")

    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    high_arr = np.empty(n)
    low_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        high_arr[i] = float(b.high)
        low_arr[i] = float(b.low)
    del bars_1s

    entry_walk = trades["entry_ts"].astype("int64").values + 60_000_000_000
    exit_walk = (pd.to_datetime(trades["exit_time"]).astype("int64").values
                 + 60_000_000_000)
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr_arr = trades["atr_at_flip"].values

    h_list = []
    l_list = []
    for k in range(len(trades)):
        i_start = np.searchsorted(ts_arr, entry_walk[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_walk[k], side="right")
        h_list.append(high_arr[i_start:i_end])
        l_list.append(low_arr[i_start:i_end])

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

    for pt, sl in configs:
        print(f"\n{'='*80}")
        print(f"BRACKET: PT {pt:.2f} ATR / SL {sl:.2f} ATR")
        print(f"{'='*80}")
        t0 = _time.time()
        outcomes, bar_idx, peak_mfes, peak_maes = race_one_config(
            pt, sl, trades, h_list, l_list, atr_arr, entry_px, direction)
        elapsed = _time.time() - t0

        n_pt = (outcomes == 0).sum()
        n_sl = (outcomes == 1).sum()
        n_both = (outcomes == 2).sum()
        n_neither = (outcomes == 3).sum()
        n_t = len(outcomes)

        print(f"  Walked in {elapsed:.1f}s")
        print(f"  PT first:    {n_pt:>6,} ({n_pt/n_t*100:>5.1f}%)")
        print(f"  SL first:    {n_sl:>6,} ({n_sl/n_t*100:>5.1f}%)")
        print(f"  Both same bar: {n_both:>4,} ({n_both/n_t*100:>5.1f}%)")
        print(f"  Neither:     {n_neither:>6,} "
              f"({n_neither/n_t*100:>5.1f}%) → regime fallback")

        # Theoretical PnL (no commission, just PT/SL/regime PnL from collector)
        nq_mult = 20.0
        comm = 5.0
        pnl = np.zeros(n_t)
        # PT win: + pt * atr * mult - comm
        pnl[outcomes == 0] = pt * atr_arr[outcomes == 0] * nq_mult - comm
        # SL loss: - sl * atr * mult - comm
        pnl[outcomes == 1] = -sl * atr_arr[outcomes == 1] * nq_mult - comm
        # Both: assume PT wins (intra-bar tie = optimistic)
        pnl[outcomes == 2] = pt * atr_arr[outcomes == 2] * nq_mult - comm
        # Neither: regime fallback (use collector regime_pnl_dollars)
        reg_pnl = trades["regime_pnl_dollars"].values
        pnl[outcomes == 3] = reg_pnl[outcomes == 3]

        avg = pnl.mean()
        total = pnl.sum()
        wr = (pnl > 0).mean() * 100
        gw = pnl[pnl > 0].sum()
        gl = abs(pnl[pnl <= 0].sum())
        pf = gw / gl if gl > 0 else 999
        print(f"\n  Avg PnL: ${avg:+.1f}  Total: ${total:+,.0f}  "
              f"WR: {wr:.1f}%  PF: {pf:.2f}")

        # Of SL-first trades: peak MFE BEFORE the SL bar
        sl_mfes = peak_mfes[outcomes == 1]
        if len(sl_mfes):
            print(f"\n  SL-first trades — peak MFE before SL fired:")
            print(f"    mean={sl_mfes.mean():.3f} ATR  "
                  f"P25={np.percentile(sl_mfes,25):.3f}  "
                  f"P50={np.percentile(sl_mfes,50):.3f}  "
                  f"P75={np.percentile(sl_mfes,75):.3f}  "
                  f"P90={np.percentile(sl_mfes,90):.3f}")
            for thr in [0.25, 0.50, 0.75]:
                pct = (sl_mfes >= thr).mean() * 100
                print(f"    Reached MFE >= {thr:.2f} before SL: "
                      f"{pct:>5.1f}%")

        # Neither: full window peak MFE/MAE
        n_mfes = peak_mfes[outcomes == 3]
        n_maes = peak_maes[outcomes == 3]
        if len(n_mfes):
            print(f"\n  Neither-trade peak MFE/MAE (full walk):")
            print(f"    MFE mean={n_mfes.mean():.3f} P50={np.median(n_mfes):.3f}")
            print(f"    MAE mean={n_maes.mean():.3f} P50={np.median(n_maes):.3f}")

    print(f"\n{'='*80}")


if __name__ == "__main__":
    main()
