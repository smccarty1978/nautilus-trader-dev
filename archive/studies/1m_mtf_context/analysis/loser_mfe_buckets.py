"""Study B: Loser MFE bucketing + trail simulation.

For losers (regime_pnl <= 0), bucket by forward peak MFE:
  Bucket 1 "DOA":     MFE < 0.25
  Bucket 2 "Brief":   0.25 <= MFE < 0.50
  Bucket 3 "Failed":  0.50 <= MFE < 1.00
  Bucket 4 "Big-rev": MFE >= 1.00

For each bucket report:
  N, Avg regime PnL, Fwd MFE mean, Fwd MAE mean,
  Time to peak MFE (sec), Trail PnL

Trail simulation (for all losers):
  Walk 1s bars from delayed entry.
  Arm trail when MFE reaches 0.50.
  Once armed, trail stop at (peak_mfe - 0.25) * ATR below current price.
  Exit on retrace to trail, else use regime_pnl.
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
TRAIL_ARM = 0.50
TRAIL_DIST = 0.25


@njit(cache=True)
def walk_and_track(
    entry_ts, exit_ts, direction, atr,
    delay_s,
    trail_arm_atr, trail_dist_atr,
    ts_arr, h_arr, l_arr, c_arr, i_start, i_end,
):
    """Walk from delayed entry. Return (survived, peak_mfe, peak_mae,
    time_to_peak_mfe_s, trail_pnl_atr)
    trail_pnl_atr = trail exit PnL (or NaN if trail never fired)
    """
    if atr <= 0 or i_end <= i_start:
        return (0, 0.0, 0.0, 0.0, np.nan, 0.0)
    delay_ts = entry_ts + delay_s * 1_000_000_000
    if exit_ts <= delay_ts:
        return (0, 0.0, 0.0, 0.0, np.nan, 0.0)
    i_delay = i_start
    while i_delay < i_end and ts_arr[i_delay] < delay_ts:
        i_delay += 1
    if i_delay >= i_end:
        return (0, 0.0, 0.0, 0.0, np.nan, 0.0)

    new_entry = c_arr[i_delay]
    new_entry_ts = ts_arr[i_delay]

    peak_mfe = 0.0
    peak_mae = 0.0
    peak_mfe_ts = new_entry_ts
    trail_armed = False
    trail_px = 0.0
    trail_fired_px = np.nan
    trail_fired = False

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
            peak_mfe_ts = ts_arr[i]
            if peak_mfe >= trail_arm_atr:
                trail_armed = True
            if trail_armed:
                trail_px = (new_entry
                             + direction * (peak_mfe - trail_dist_atr) * atr)

        if mae > peak_mae:
            peak_mae = mae

        # Check trail hit
        if trail_armed and not trail_fired:
            if direction == 1 and l <= trail_px:
                trail_fired_px = trail_px
                trail_fired = True
                break
            elif direction == -1 and h >= trail_px:
                trail_fired_px = trail_px
                trail_fired = True
                break

    time_to_peak = (peak_mfe_ts - new_entry_ts) / 1_000_000_000.0

    if trail_fired:
        trail_pnl_atr = (trail_fired_px - new_entry) * direction / atr
    else:
        trail_pnl_atr = np.nan

    return (1, peak_mfe, peak_mae, time_to_peak, trail_pnl_atr, new_entry)


def pctile(v, p):
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return 0.0
    return np.percentile(v, p)


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
    regime_pnl = trades["regime_pnl_dollars"].values
    is_loser = regime_pnl <= 0

    # JIT warmup
    walk_and_track(0, 60_000_000_000, 1, 1.0, 60, 0.5, 0.25,
                    np.array([0, 1], dtype=np.int64),
                    np.array([100.0, 100.0]),
                    np.array([100.0, 100.0]),
                    np.array([100.0, 100.0]), 0, 2)

    print(f"\n{'='*105}")
    print(f"STUDY B — Loser MFE Buckets + Trail Simulation")
    print(f"  Trail: arm at {TRAIL_ARM} ATR MFE, trail {TRAIL_DIST} "
          f"behind peak")
    print(f"{'='*105}")

    n_t = len(trades)
    for delay_s in DELAYS_S:
        survived = np.zeros(n_t, dtype=np.int32)
        peak_mfe = np.zeros(n_t)
        peak_mae = np.zeros(n_t)
        time_to_peak = np.zeros(n_t)
        trail_pnl_atr = np.full(n_t, np.nan)
        new_entry_px = np.zeros(n_t)

        for k in range(n_t):
            i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
            i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
            s, pm, pa, t_peak, t_pnl, ne = walk_and_track(
                entry_ts[k], exit_ts[k], direction[k], atr[k],
                delay_s, TRAIL_ARM, TRAIL_DIST,
                ts_arr, h_arr, l_arr, c_arr, i_start, i_end)
            survived[k] = s
            peak_mfe[k] = pm
            peak_mae[k] = pa
            time_to_peak[k] = t_peak
            trail_pnl_atr[k] = t_pnl
            new_entry_px[k] = ne

        # For losers who survived delay
        loser_surv = is_loser & (survived == 1)
        n_loser_surv = loser_surv.sum()

        print(f"\n--- Delay +{delay_s}s ---")
        print(f"  Losers surviving delay: {n_loser_surv:,}")

        # Bucket by forward peak MFE
        buckets = [
            ("<0.25 (DOA)", peak_mfe < 0.25),
            ("0.25-0.50 (Brief)", (peak_mfe >= 0.25) & (peak_mfe < 0.50)),
            ("0.50-1.00 (Failed)", (peak_mfe >= 0.50) & (peak_mfe < 1.00)),
            (">=1.00 (Big-rev)", peak_mfe >= 1.00),
        ]

        print(f"\n  {'Bucket':<22} {'N':>6} {'%':>5} "
              f"{'Avg rgm$':>9} {'fMFE':>6} {'fMAE':>6} "
              f"{'t_peak(s)':>9}")
        print("  " + "-" * 85)
        for label, mask in buckets:
            m = mask & loser_surv
            n_b = m.sum()
            if n_b == 0:
                continue
            avg_pnl = regime_pnl[m].mean()
            mfe_mean = peak_mfe[m].mean()
            mae_mean = peak_mae[m].mean()
            t_peak_med = np.median(time_to_peak[m])
            t_peak_p75 = np.percentile(time_to_peak[m], 75)
            print(f"  {label:<22} {n_b:>6,} "
                  f"{n_b/n_loser_surv*100:>4.1f}% "
                  f"${avg_pnl:>+8.1f} "
                  f"{mfe_mean:>6.3f} {mae_mean:>6.3f} "
                  f"{t_peak_med:>7.0f}s (P75={t_peak_p75:.0f}s)")

        # Trail sim on losers
        print(f"\n  TRAIL SIMULATION (losers only, arm {TRAIL_ARM}, "
              f"dist {TRAIL_DIST}):")
        loser_mfe = peak_mfe[loser_surv]
        loser_trail_pnl_atr = trail_pnl_atr[loser_surv]
        loser_regime_pnl = regime_pnl[loser_surv]
        loser_atr = atr[loser_surv]

        # Trail dollar PnL
        trail_pnl_dollars = np.where(
            np.isnan(loser_trail_pnl_atr),
            loser_regime_pnl,  # trail never fired → regime exit
            loser_trail_pnl_atr * loser_atr * NQ_MULT - COMMISSION)

        n_trail_fired = (~np.isnan(loser_trail_pnl_atr)).sum()
        trail_wins = ((trail_pnl_dollars > 0) & ~np.isnan(loser_trail_pnl_atr)).sum()

        print(f"    Losers with MFE >= {TRAIL_ARM}: "
              f"{(loser_mfe >= TRAIL_ARM).sum():,}")
        print(f"    Trail fired: {n_trail_fired:,} "
              f"({n_trail_fired/n_loser_surv*100:.1f}% of losers)")
        print(f"    Trail wins (PnL > 0): {trail_wins:,} "
              f"({trail_wins/n_loser_surv*100:.1f}% of losers)")

        print(f"\n    Regime baseline (losers only):")
        print(f"      Avg: ${loser_regime_pnl.mean():+.2f}  "
              f"Total: ${loser_regime_pnl.sum():+,.0f}")
        print(f"    Trail strategy (losers only):")
        print(f"      Avg: ${trail_pnl_dollars.mean():+.2f}  "
              f"Total: ${trail_pnl_dollars.sum():+,.0f}")
        delta = trail_pnl_dollars.sum() - loser_regime_pnl.sum()
        print(f"      Δ: ${delta:+,.0f}  "
              f"per-loser ${delta/n_loser_surv:+.2f}")

        # Winners check: does trail hurt winners?
        winner_surv = ~is_loser & (survived == 1)
        n_winner_surv = winner_surv.sum()
        winner_mfe = peak_mfe[winner_surv]
        winner_trail_pnl_atr = trail_pnl_atr[winner_surv]
        winner_regime_pnl = regime_pnl[winner_surv]
        winner_atr = atr[winner_surv]

        winner_trail_pnl_dollars = np.where(
            np.isnan(winner_trail_pnl_atr),
            winner_regime_pnl,
            winner_trail_pnl_atr * winner_atr * NQ_MULT - COMMISSION)

        print(f"\n    Winner impact (trail vs regime on winners):")
        print(f"      Regime avg: ${winner_regime_pnl.mean():+.2f}  "
              f"Total: ${winner_regime_pnl.sum():+,.0f}")
        print(f"      Trail avg:  ${winner_trail_pnl_dollars.mean():+.2f}  "
              f"Total: ${winner_trail_pnl_dollars.sum():+,.0f}")
        w_delta = winner_trail_pnl_dollars.sum() - winner_regime_pnl.sum()
        print(f"      Δ (winners give up): ${w_delta:+,.0f}  "
              f"per-winner ${w_delta/n_winner_surv:+.2f}")

        # Net
        total_delta = delta + w_delta
        print(f"\n    NET strategy effect (losers + winners):")
        print(f"      Δ total: ${total_delta:+,.0f}")

    print(f"\n{'='*105}")


if __name__ == "__main__":
    main()
