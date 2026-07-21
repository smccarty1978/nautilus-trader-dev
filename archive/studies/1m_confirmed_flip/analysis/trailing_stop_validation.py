"""Real trailing stop validation — walk 1s bars for each trade.

LOOK-AHEAD FIXES (v3):
  EXIT: Collector's exit_time was OPEN of regime-flip 1m bar. Walking
    only to that timestamp meant we exited BEFORE the flip-causing
    adverse move. Now walk to flip bar CLOSE (exit_time + 60s).
  ENTRY: Collector's entry_ts was OPEN of bar+1 (bar.ts_event), but
    entry_price was bar+1 CLOSE. Walking from entry_ts meant we saw
    bar+1's intra-minute action (the HH spike that confirmed entry)
    BEFORE the actual entry moment — capturing pre-entry MFE for trail
    activation. Now walk from bar+1 CLOSE (entry_ts + 60s).

For each confirmed flip trade:
  1. Load 1s bars from entry_ts + 60s (bar+1 close) to exit_ts + 60s
  2. Track running peak MFE on every 1s bar
  3. Exit first time price retraces trail_distance from peak
  4. If no trail hit, exit at flip bar close (collector regime_pnl)

Runs on Q4 2025 (Oct-Dec) for quick iteration.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
import time as _time

from nautilus_trader.persistence.catalog import ParquetDataCatalog

NQ_MULT = 20.0
COMMISSION = 5.0


def simulate_trailing_stop(
    entry_price, direction, atr, entry_ts, exit_ts_max,
    regime_close_price,
    ts_arr, high_arr, low_arr,
    trail_distance_atr, trail_activation_atr,
):
    """Walk 1s bars. Track peak MFE. Exit on first retrace of trail_distance.

    exit_ts_max should be the CLOSE of the regime-flip bar (so we walk
    through the entire flip bar — no look-ahead).
    If no trail hit, exit at regime_close_price (collector's flip-bar close).

    Returns (exit_price, exit_ts, exit_reason, peak_mfe_atr, bars_held)
    """
    if atr <= 0:
        return entry_price, entry_ts, "no_atr", 0.0, 0

    # Find window in 1s bars
    i_start = np.searchsorted(ts_arr, entry_ts, side="left")
    i_end = np.searchsorted(ts_arr, exit_ts_max, side="right")

    if i_end <= i_start:
        return regime_close_price, entry_ts, "no_bars", 0.0, 0

    peak_mfe = 0.0
    peak_price = entry_price
    trail_active = False

    for i in range(i_start, i_end):
        h = high_arr[i]
        l = low_arr[i]
        ts = ts_arr[i]

        if direction == 1:
            current_mfe = (h - entry_price) / atr
            if current_mfe > peak_mfe:
                peak_mfe = current_mfe
                peak_price = h
            if not trail_active and peak_mfe >= trail_activation_atr:
                trail_active = True
            if trail_active:
                stop_price = peak_price - trail_distance_atr * atr
                if l <= stop_price:
                    return stop_price, ts, "trail_hit", peak_mfe, i - i_start + 1
        else:
            current_mfe = (entry_price - l) / atr
            if current_mfe > peak_mfe:
                peak_mfe = current_mfe
                peak_price = l
            if not trail_active and peak_mfe >= trail_activation_atr:
                trail_active = True
            if trail_active:
                stop_price = peak_price + trail_distance_atr * atr
                if h >= stop_price:
                    return stop_price, ts, "trail_hit", peak_mfe, i - i_start + 1

    # No trail hit — exit at regime-flip bar close (matches collector PnL)
    return regime_close_price, ts_arr[i_end - 1], "regime_end", peak_mfe, i_end - i_start


def main():
    print("=" * 80)
    print("TRAILING STOP VALIDATION — Walk 1s bars")
    print("=" * 80)

    # Load Q4 2025 confirmed trades
    print("\nLoading trades (Q4 2025)...")
    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    trades["entry_ts_dt"] = pd.to_datetime(trades["entry_ts"], unit="ns",
                                            utc=True)
    trades = trades[
        (trades["entry_ts_dt"] >= "2025-10-01") &
        (trades["entry_ts_dt"] < "2026-01-01")
    ].copy()
    print(f"  {len(trades):,} trades")

    if len(trades) == 0:
        print("No trades in range")
        return

    # Load Q4 2025 1s catalog
    print("\nLoading 1s bars (Q4 2025)...")
    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    start = pd.Timestamp("2025-10-01", tz="UTC")
    end = pd.Timestamp("2026-01-01", tz="UTC")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start, end=end)
    print(f"  {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")

    # Extract to arrays for fast lookup
    print("Extracting to arrays...")
    t0 = _time.time()
    n_bars = len(bars_1s)
    ts_arr = np.empty(n_bars, dtype=np.int64)
    high_arr = np.empty(n_bars)
    low_arr = np.empty(n_bars)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        high_arr[i] = float(b.high)
        low_arr[i] = float(b.low)
    del bars_1s
    print(f"  Extracted ({_time.time()-t0:.0f}s)")

    # exit_time = OPEN of regime-flip 1m bar (collector convention).
    # We need the CLOSE = open + 60s for the walk window so we don't have
    # look-ahead. exit_price = close of flip bar (matches collector PnL).
    trades["exit_ts_ns"] = (
        pd.to_datetime(trades["exit_time"]).astype("int64")
        + 60_000_000_000
    )
    trades["regime_close_price"] = trades["exit_price"]

    # entry_ts = OPEN of bar+1 (collector convention), but entry_price =
    # bar+1 CLOSE. Walk must start from bar+1 CLOSE = entry_ts + 60s,
    # not from bar+1 OPEN (which sees the pre-entry HH spike).
    trades["entry_walk_ts_ns"] = trades["entry_ts"].astype("int64") \
        + 60_000_000_000

    # Test grid: trail_distance x trail_activation
    grid = [
        # (trail_dist, trail_activation)
        (0.25, 0.25),
        (0.25, 0.50),
        (0.50, 0.25),
        (0.50, 0.50),
        (0.50, 0.75),
        (0.75, 0.50),
        (0.75, 0.75),
        (1.00, 0.50),
        (1.00, 1.00),
    ]

    print(f"\n{'='*80}")
    print(f"TRAILING STOP GRID ({len(trades):,} trades, Q4 2025)")
    print(f"  Look-ahead FIX: walk through full flip bar")
    print(f"{'='*80}\n")

    # Regime baseline
    regime_avg = trades["regime_pnl_dollars"].mean()
    regime_total = trades["regime_pnl_dollars"].sum()
    regime_wr = (trades["regime_pnl_dollars"] > 0).mean() * 100
    print(f"Regime exit baseline: "
          f"avg ${regime_avg:+.1f}, total ${regime_total:+,.0f}, "
          f"WR {regime_wr:.1f}%\n")

    print(f"{'Dist':>5} {'Activ':>5} {'Avg$':>8} {'Total$':>10} "
          f"{'WR':>6} {'PF':>6} {'Trail%':>7} {'RegFlip%':>9}")
    print("-" * 65)

    best = None
    best_total = -1e18

    for trail_dist, trail_act in grid:
        results = []
        for _, t in trades.iterrows():
            exit_px, exit_ts, reason, peak_mfe, bars = simulate_trailing_stop(
                t["entry_price"], int(t["direction"]),
                t["atr_at_flip"], int(t["entry_walk_ts_ns"]),
                int(t["exit_ts_ns"]),
                t["regime_close_price"],
                ts_arr, high_arr, low_arr,
                trail_dist, trail_act,
            )
            pnl_pts = (exit_px - t["entry_price"]) * t["direction"]
            pnl_dollars = pnl_pts * NQ_MULT - COMMISSION
            results.append({
                "pnl_dollars": pnl_dollars,
                "exit_reason": reason,
                "peak_mfe": peak_mfe,
                "bars": bars,
            })

        rdf = pd.DataFrame(results)
        avg = rdf["pnl_dollars"].mean()
        total = rdf["pnl_dollars"].sum()
        wr = (rdf["pnl_dollars"] > 0).mean() * 100
        gw = rdf[rdf["pnl_dollars"] > 0]["pnl_dollars"].sum()
        gl = abs(rdf[rdf["pnl_dollars"] <= 0]["pnl_dollars"].sum())
        pf = gw / gl if gl > 0 else float("inf")
        trail_pct = (rdf["exit_reason"] == "trail_hit").mean() * 100
        regend_pct = (rdf["exit_reason"] == "regime_end").mean() * 100

        marker = ""
        if total > best_total:
            best_total = total
            best = (trail_dist, trail_act, rdf)
            marker = " <<<"

        print(f"{trail_dist:>5.2f} {trail_act:>5.2f} "
              f"${avg:>+7.1f} ${total:>+9,.0f} "
              f"{wr:>5.1f}% {pf:>5.2f} "
              f"{trail_pct:>6.1f}% {regend_pct:>8.1f}%{marker}")

    # Detail on best config
    if best:
        td, ta, bdf = best
        print(f"\n{'='*80}")
        print(f"BEST: Trail dist={td}, activation={ta}")
        print(f"{'='*80}")

        winners = bdf[bdf["pnl_dollars"] > 0]
        losers = bdf[bdf["pnl_dollars"] <= 0]
        print(f"\n  Trades: {len(bdf):,}")
        print(f"  Winners: {len(winners):,} ({len(winners)/len(bdf)*100:.1f}%) "
              f"avg ${winners['pnl_dollars'].mean():+.1f}")
        print(f"  Losers:  {len(losers):,} ({len(losers)/len(bdf)*100:.1f}%) "
              f"avg ${losers['pnl_dollars'].mean():+.1f}")
        print(f"  Avg PnL: ${bdf['pnl_dollars'].mean():+.1f}")
        print(f"  Total:   ${bdf['pnl_dollars'].sum():+,.0f}")

        # Exit reason breakdown
        print(f"\n  Exit reasons:")
        for reason in bdf["exit_reason"].unique():
            sub = bdf[bdf["exit_reason"] == reason]
            print(f"    {reason}: {len(sub):,} ({len(sub)/len(bdf)*100:.1f}%), "
                  f"avg ${sub['pnl_dollars'].mean():+.1f}")

        # Peak MFE distribution
        print(f"\n  Peak MFE (ATR):")
        mfe = bdf["peak_mfe"]
        print(f"    P25={mfe.quantile(0.25):.3f} P50={mfe.median():.3f} "
              f"P75={mfe.quantile(0.75):.3f} P90={mfe.quantile(0.90):.3f}")

        # Compare vs regime on same trades
        print(f"\n  vs Regime Exit:")
        print(f"    Regime avg: ${regime_avg:+.1f}, "
              f"total ${regime_total:+,.0f}")
        print(f"    Trail avg:  ${bdf['pnl_dollars'].mean():+.1f}, "
              f"total ${bdf['pnl_dollars'].sum():+,.0f}")
        delta = bdf["pnl_dollars"].sum() - regime_total
        print(f"    Improvement: ${delta:+,.0f} "
              f"(${delta/len(trades):+.1f}/trade)")

        # Attach year/date/session for breakdown
        bdf["year"] = trades["year"].values
        bdf["date"] = trades["date"].values
        bdf["is_rth"] = trades["is_rth"].values

        # Per year
        print(f"\n  BY YEAR:")
        print(f"  {'Year':>6} {'Trades':>7} {'Avg$':>8} {'Total$':>10} {'WR':>6} {'PF':>6}")
        print(f"  {'-'*48}")
        for year in sorted(bdf["year"].unique()):
            ydf = bdf[bdf["year"] == year]
            ya = ydf["pnl_dollars"].mean()
            yt = ydf["pnl_dollars"].sum()
            ywr = (ydf["pnl_dollars"] > 0).mean() * 100
            ygw = ydf[ydf["pnl_dollars"] > 0]["pnl_dollars"].sum()
            ygl = abs(ydf[ydf["pnl_dollars"] <= 0]["pnl_dollars"].sum())
            ypf = ygw / ygl if ygl > 0 else 999
            print(f"  {year:>6} {len(ydf):>7,} {ya:>+7.1f} {yt:>+9,.0f} "
                  f"{ywr:>5.1f}% {ypf:>5.2f}")

        # Monthly breakdown
        bdf["_ym"] = pd.to_datetime(bdf["date"]).dt.to_period("M")
        monthly = bdf.groupby("_ym")["pnl_dollars"].mean()
        neg = (monthly < 0).sum()
        print(f"\n  Monthly: {len(monthly)} months, {neg} negative "
              f"({neg/len(monthly)*100:.0f}%)")

        # RTH vs ETH
        for val, lbl in [(1, "RTH"), (0, "ETH")]:
            sub = bdf[bdf["is_rth"] == val]
            if len(sub):
                print(f"  {lbl}: {len(sub):,} trades, avg "
                      f"${sub['pnl_dollars'].mean():+.1f}, "
                      f"total ${sub['pnl_dollars'].sum():+,.0f}")

        # Save
        out = Path(
            "studies/1m_confirmed_flip/results/trail_results_q4_2025_v3.parquet")
        bdf.to_parquet(out, index=False)
        print(f"\n  Saved to {out}")

        # Also compare vs the idealized MFE-0.5 upper bound
        ideal_pnl = []
        for _, t in trades.iterrows():
            if t["mfe_atr"] >= 0.50:
                p = (t["mfe_atr"] - 0.50) * t["atr_at_flip"] * NQ_MULT - COMMISSION
            else:
                p = t["regime_pnl_dollars"]
            ideal_pnl.append(p)
        ideal_arr = np.array(ideal_pnl)
        print(f"\n  vs Idealized MFE-0.5 upper bound:")
        print(f"    Ideal avg: ${ideal_arr.mean():+.1f}, "
              f"total ${ideal_arr.sum():+,.0f}")
        print(f"    Real trail captures "
              f"{bdf['pnl_dollars'].sum() / ideal_arr.sum() * 100:.1f}% "
              f"of ideal")

    print(f"\n{'='*80}")


if __name__ == "__main__":
    main()
