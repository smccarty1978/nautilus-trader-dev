"""Winners vs losers classified purely by regime flip PnL.

No brackets. Just: regime_pnl > 0 = winner, else loser.
Report MFE @ 60s/90s/120s, MAE, duration, regime_pnl_atr distribution.
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


@njit(cache=True)
def peak_mfe_at_t(entry_px, entry_ts, direction, atr,
                   target_offset_s,
                   ts_arr, h_arr, l_arr, i_start, i_end):
    if atr <= 0 or i_end <= i_start:
        return np.nan
    target_ts = entry_ts + target_offset_s * 1_000_000_000
    peak = 0.0
    for i in range(i_start, i_end):
        if ts_arr[i] >= target_ts:
            return peak
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            mfe = (h - entry_px) / atr
        else:
            mfe = (entry_px - l) / atr
        if mfe > peak:
            peak = mfe
    return peak


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
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        h_arr[i] = float(b.high)
        l_arr[i] = float(b.low)
    del bars_1s

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values

    # JIT warmup
    peak_mfe_at_t(100.0, 0, 1, 1.0, 60,
                   np.array([0, 1], dtype=np.int64),
                   np.array([100.0, 100.0]), np.array([100.0, 100.0]),
                   0, 2)

    # Compute MFE at 90s (60s and 120s pre-computed)
    print("Computing mfe_at_90s...")
    n_t = len(trades)
    mfe_90s = np.empty(n_t)
    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        mfe_90s[k] = peak_mfe_at_t(
            entry_px[k], entry_ts[k], direction[k], atr[k],
            90, ts_arr, h_arr, l_arr, i_start, i_end)
    trades["mfe_at_90s"] = mfe_90s

    # Classify by regime_pnl
    trades["regime_pnl_atr"] = (
        trades["regime_pnl_pts"] / trades["atr_at_entry"])
    trades["is_winner_regime"] = trades["regime_pnl_dollars"] > 0

    win_mask = trades["is_winner_regime"].values
    lose_mask = ~win_mask

    n_win = win_mask.sum()
    n_lose = lose_mask.sum()

    print("\n" + "=" * 110)
    print(f"TRADES CLASSIFIED BY REGIME EXIT PnL (no brackets)")
    print("=" * 110)
    print(f"\n  Total: {n_t:,}")
    print(f"  Winners (regime_pnl > 0): {n_win:,} "
          f"({n_win/n_t*100:.1f}%)")
    print(f"  Losers  (regime_pnl ≤ 0): {n_lose:,} "
          f"({n_lose/n_t*100:.1f}%)")
    print(f"\n  Overall avg regime PnL: "
          f"${trades['regime_pnl_dollars'].mean():+.2f}  "
          f"total ${trades['regime_pnl_dollars'].sum():+,.0f}")
    print(f"  Overall avg regime PnL (ATR): "
          f"{trades['regime_pnl_atr'].mean():+.4f}")

    print(f"\n--- Regime PnL distribution ---")
    print(percentiles("ALL trades PnL$",
                        trades["regime_pnl_dollars"].values))
    print(percentiles("Winners PnL$",
                        trades.loc[win_mask, "regime_pnl_dollars"].values))
    print(percentiles("Losers PnL$",
                        trades.loc[lose_mask, "regime_pnl_dollars"].values))
    print(percentiles("ALL trades PnL(ATR)",
                        trades["regime_pnl_atr"].values))
    print(percentiles("Winners PnL(ATR)",
                        trades.loc[win_mask, "regime_pnl_atr"].values))
    print(percentiles("Losers PnL(ATR)",
                        trades.loc[lose_mask, "regime_pnl_atr"].values))

    print(f"\n--- Peak MFE (ATR) distribution ---")
    for col, lbl in [("mfe_at_60s", "60s"), ("mfe_at_90s", "90s"),
                     ("mfe_at_120s", "120s")]:
        print(f"\n  {lbl}:")
        print(percentiles(f"Winners MFE@{lbl}",
                            trades.loc[win_mask, col].values))
        print(percentiles(f"Losers MFE@{lbl}",
                            trades.loc[lose_mask, col].values))

    print(f"\n--- Peak MAE (ATR) distribution ---")
    for col, lbl in [("mae_at_60s", "60s"),
                     ("mae_at_120s", "120s")]:
        if col in trades.columns:
            print(f"\n  {lbl}:")
            print(percentiles(f"Winners MAE@{lbl}",
                                trades.loc[win_mask, col].values))
            print(percentiles(f"Losers MAE@{lbl}",
                                trades.loc[lose_mask, col].values))

    print(f"\n--- Full-trade peak MFE / MAE (ATR) ---")
    if "peak_mfe_atr" in trades.columns:
        print(percentiles("Winners peak MFE",
                            trades.loc[win_mask, "peak_mfe_atr"].values))
        print(percentiles("Losers peak MFE",
                            trades.loc[lose_mask, "peak_mfe_atr"].values))
    if "peak_mae_atr" in trades.columns:
        print(percentiles("Winners peak MAE",
                            trades.loc[win_mask, "peak_mae_atr"].values))
        print(percentiles("Losers peak MAE",
                            trades.loc[lose_mask, "peak_mae_atr"].values))

    print(f"\n--- Duration (bars_processed_1s = seconds from entry to exit) ---")
    if "bars_processed_1s" in trades.columns:
        print(percentiles("Winners duration(s)",
                            trades.loc[win_mask,
                                        "bars_processed_1s"].values))
        print(percentiles("Losers duration(s)",
                            trades.loc[lose_mask,
                                        "bars_processed_1s"].values))

    # WR by year
    print(f"\n--- Year-by-year ---")
    print(f"  {'Year':>6} {'N':>7} {'Win%':>7} {'Avg$':>8} {'Tot$':>11}")
    for y in sorted(trades["year"].unique()):
        sub = trades[trades["year"] == y]
        wr = sub["is_winner_regime"].mean() * 100
        avg = sub["regime_pnl_dollars"].mean()
        tot = sub["regime_pnl_dollars"].sum()
        print(f"  {y:>6} {len(sub):>7,} {wr:>6.1f}% "
              f"${avg:>+7.1f} ${tot:>+10,.0f}")

    # RTH/ETH
    print(f"\n--- RTH vs ETH ---")
    for val, lbl in [(1, "RTH"), (0, "ETH")]:
        sub = trades[trades["is_rth"] == val]
        wr = sub["is_winner_regime"].mean() * 100
        avg = sub["regime_pnl_dollars"].mean()
        print(f"  {lbl}: N={len(sub):,}  WR={wr:.1f}%  "
              f"Avg ${avg:+.2f}  Total ${sub['regime_pnl_dollars'].sum():+,.0f}")

    print("\n" + "=" * 110)


if __name__ == "__main__":
    main()
