"""1m bar OHLC comparison: catalog (1s resample) vs trade-tick aggregation.

Tests the phantom-trigger hypothesis: do the 1m bars used by NT 1s-bar
runs differ from the 1m bars built internally from trade ticks?

Catalog 1m: built from raw NQ_v0_1s_2025 1s bars (which include all
  price updates incl. quote-only) via pandas resample(label='right',
  closed='right').

Tick 1m: built from NQ_trades_20250101_20251231 (trades only, action='T')
  by manual 1-minute time bucket aggregation. Mimics NT
  BarAggregator-INTERNAL.

For each minute boundary in 2025-Jan, compute both 1m bars and compare:
  - O/H/L/C value differences
  - Distribution of differences
  - Specifically at trigger candidates (1m bullish breakout)

If the catalog has systematically different OHLC than tick-aggregated:
  → Phantom trigger hypothesis CONFIRMED
  → Catalog backtests over-trigger vs real tick execution
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)


def main():
    # ---- Load both sources for January 2025 (limit scope) ----
    print("Loading NQ_v0_1s_2025 (1s catalog source)...", flush=True)
    df_1s = pd.read_parquet(
        "data/raw/NQ_v0_1s_2025.parquet",
        columns=["open", "high", "low", "close", "volume"])
    if df_1s.index.tz is None:
        df_1s.index = df_1s.index.tz_localize("UTC")
    # Limit to Jan 2025 for tractable comparison
    jan_start = pd.Timestamp("2025-01-01", tz="UTC")
    feb_start = pd.Timestamp("2025-02-01", tz="UTC")
    df_1s_jan = df_1s[(df_1s.index >= jan_start) & (df_1s.index < feb_start)].copy()
    print(f"  {len(df_1s_jan):,} 1s bars in Jan", flush=True)

    print("Resampling 1s -> 1m (label=right closed=right)...", flush=True)
    cat_1m = df_1s_jan.resample("1min", label="right",
                                  closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["open", "high", "low", "close"])
    print(f"  catalog 1m bars (Jan): {len(cat_1m):,}", flush=True)

    print("\nLoading NQ_trades_jan2025 (trade ticks only)...", flush=True)
    df_t = pd.read_parquet(
        "data/raw/NQ_trades_jan2025.parquet",
        columns=["action", "price", "size", "ts_event"])
    print(f"  raw rows: {len(df_t):,}", flush=True)
    df_t = df_t[df_t["action"] == "T"].copy()
    print(f"  trade events: {len(df_t):,}", flush=True)

    # Use ts_event as bar source (when the trade actually occurred)
    df_t["ts_event"] = pd.to_datetime(df_t["ts_event"], utc=True)
    df_t = df_t.set_index("ts_event").sort_index()

    print("Aggregating trades -> 1m (label=right closed=right)...", flush=True)
    trade_1m = df_t.resample("1min", label="right",
                                closed="right").agg({
        "price": ["first", "max", "min", "last"],
        "size": "sum",
    }).dropna()
    trade_1m.columns = ["open", "high", "low", "close", "volume"]
    print(f"  trade-aggregated 1m bars (Jan): {len(trade_1m):,}", flush=True)

    # ---- Align ----
    print("\nAligning bars...", flush=True)
    aligned = cat_1m.join(trade_1m, how="inner",
                              lsuffix="_cat", rsuffix="_trd")
    print(f"  bars in both: {len(aligned):,}", flush=True)
    print(f"  bars in cat only: {len(cat_1m) - len(aligned):,}")
    print(f"  bars in trd only: {len(trade_1m) - len(aligned):,}")

    # ---- OHLC differences ----
    for col in ("open", "high", "low", "close"):
        aligned[f"{col}_diff"] = aligned[f"{col}_cat"] - aligned[f"{col}_trd"]

    print(f"\n{'='*78}")
    print(f"OHLC DIFFERENCE DISTRIBUTION (catalog - trade-agg)")
    print(f"{'='*78}")
    for col in ("open", "high", "low", "close"):
        d = aligned[f"{col}_diff"].values
        nonzero = (d != 0).sum()
        print(f"\n  {col}:")
        print(f"    non-zero diff: {nonzero:,} of {len(d):,} "
              f"({100*nonzero/len(d):.2f}%)")
        if nonzero > 0:
            nz = d[d != 0]
            print(f"    of non-zero: mean={nz.mean():+.4f}  median={np.median(nz):+.4f}")
            print(f"    abs: mean={np.abs(nz).mean():.4f}  "
                  f"p50={np.percentile(np.abs(nz),50):.4f}  "
                  f"p75={np.percentile(np.abs(nz),75):.4f}  "
                  f"p90={np.percentile(np.abs(nz),90):.4f}  "
                  f"p99={np.percentile(np.abs(nz),99):.4f}  "
                  f"max={np.abs(nz).max():.4f}")

    # Magnitude buckets for CLOSE difference (most relevant for trigger)
    print(f"\n{'='*78}")
    print(f"|close_cat - close_trd| magnitude buckets")
    print(f"{'='*78}")
    abs_close = np.abs(aligned["close_diff"].values)
    for thr in [0.0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]:
        n = (abs_close > thr).sum()
        print(f"  |close diff| > {thr:>5.2f}: {n:>6,} "
              f"({100*n/len(abs_close):.2f}%)")

    # ---- For trigger-candidate bars (large directional moves), compare ----
    print(f"\n{'='*78}")
    print(f"TRIGGER-CANDIDATE BARS (potential breakouts)")
    print(f"  Filter: |close - prev_close| > 5 pts (likely cross level)")
    print(f"{'='*78}")
    aligned["prev_cat_close"] = aligned["close_cat"].shift(1)
    aligned["delta_cat"] = aligned["close_cat"] - aligned["prev_cat_close"]
    big_moves = aligned[aligned["delta_cat"].abs() > 5].copy()
    print(f"  bars with cat |close-prev_close| > 5: {len(big_moves):,}")
    if len(big_moves) > 0:
        for col in ("open", "high", "low", "close"):
            d = big_moves[f"{col}_diff"]
            nonzero = (d != 0).sum()
            print(f"    {col}: {nonzero}/{len(big_moves)} "
                  f"({100*nonzero/len(big_moves):.1f}%) bars differ between cat & trd")

    # ---- Show sample bars where close differs significantly ----
    print(f"\n{'='*78}")
    print(f"SAMPLE: bars where close differs by >= 0.5 pts")
    print(f"{'='*78}")
    big_diffs = aligned[aligned["close_diff"].abs() >= 0.5]
    print(f"  found: {len(big_diffs):,} bars\n")
    cols_to_show = ["open_cat", "high_cat", "low_cat", "close_cat",
                     "volume_cat",
                     "open_trd", "high_trd", "low_trd", "close_trd",
                     "volume_trd",
                     "open_diff", "high_diff", "low_diff", "close_diff"]
    if len(big_diffs) > 0:
        for ts, row in big_diffs.head(10).iterrows():
            print(f"\n  {ts}:")
            print(f"    cat: O={row['open_cat']:.2f} H={row['high_cat']:.2f} "
                  f"L={row['low_cat']:.2f} C={row['close_cat']:.2f}  "
                  f"vol={int(row['volume_cat'])}")
            print(f"    trd: O={row['open_trd']:.2f} H={row['high_trd']:.2f} "
                  f"L={row['low_trd']:.2f} C={row['close_trd']:.2f}  "
                  f"vol={int(row['volume_trd'])}")
            print(f"    diff: O={row['open_diff']:+.4f} H={row['high_diff']:+.4f} "
                  f"L={row['low_diff']:+.4f} C={row['close_diff']:+.4f}")

    # ---- Save aligned for further analysis ----
    out = Path("studies/level_momentum_continuation/results_breakout")
    aligned.to_parquet(out / "1m_bar_compare_jan2025.parquet")
    print(f"\nsaved: 1m_bar_compare_jan2025.parquet")


if __name__ == "__main__":
    main()
