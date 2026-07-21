"""Aggregate NQ.c.0 trades into 1s OHLC bars for summer 2025.

Reads `data/raw/legacy_c0/NQ_trades_20250101_20251231.parquet`,
filters to the target month, aggregates price/size to 1s OHLC.
Saves one parquet per month for use by the NT MBP-1 runner.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd


TRADES_PATH = "data/raw/legacy_c0/NQ_trades_20250101_20251231.parquet"
OUT_DIR = Path("data/raw/c0_1s_2025")


def build_month(year, month):
    out_path = OUT_DIR / f"NQ_c0_1s_{year}_{month:02d}.parquet"
    if out_path.exists():
        print(f"  Already exists: {out_path}")
        return
    t0 = time.time()
    print(f"  Loading trades...", flush=True)
    df = pd.read_parquet(TRADES_PATH,
                              columns=["ts_event", "price", "size"])
    # Filter to month (UTC)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df = df[(df["ts_event"].dt.year == year)
              & (df["ts_event"].dt.month == month)].copy()
    print(f"  {len(df):,} trades in {year}-{month:02d}  "
          f"({time.time()-t0:.0f}s)")
    if len(df) == 0:
        print(f"  no trades — skipping")
        return
    df = df.set_index("ts_event").sort_index()

    # Aggregate to 1s OHLC
    print(f"  Resampling to 1s OHLC...", flush=True)
    ohlc = df["price"].resample("1s").ohlc()
    volume = df["size"].resample("1s").sum()
    ohlc["volume"] = volume
    ohlc = ohlc.dropna(subset=["open", "high", "low", "close"])
    ohlc["volume"] = ohlc["volume"].fillna(0).astype("uint64")
    ohlc.index.name = "ts_event"
    print(f"  {len(ohlc):,} 1s bars  ({time.time()-t0:.0f}s)")
    print(f"    first: {ohlc.index.min()}")
    print(f"    last:  {ohlc.index.max()}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ohlc.to_parquet(out_path)
    print(f"  Saved {out_path}  ({time.time()-t0:.0f}s)")
    del df, ohlc, volume


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    months = [(2025, m) for m in [6, 7, 8, 9]]
    for year, month in months:
        print(f"\n=== {year}-{month:02d} ===")
        build_month(year, month)
