"""Build v0 2025 NT catalog with FIXED 1m resample (closed='left').

The original build_v0_2025_catalog.py used resample(closed='right'), which
includes the FIRST second of the next minute in each 1m bar — a 1-second
look-ahead. This version uses closed='left' which produces a true
[T-60s, T) window.

Output: data/catalog/NQ_v0_2025_fixed/
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.data import BarType


def create_nq_v0():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2025-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2025-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2025-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def main():
    t0 = time.time()
    out_dir = Path("data/catalog/NQ_v0_2025_fixed")
    if out_dir.exists():
        print(f"WARNING: {out_dir} exists. Reusing.")
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(out_dir))
    nq = create_nq_v0()
    catalog.write_data([nq])

    raw_path = Path("data/raw/NQ_v0_1s_2025.parquet")
    print(f"Loading {raw_path}...")
    df = pd.read_parquet(raw_path)
    print(f"  {len(df):,} rows, range {df.index.min()} -> {df.index.max()}")

    df_in = df[["open", "high", "low", "close", "volume"]].copy()
    if df_in.index.tz is None:
        df_in.index = df_in.index.tz_localize("UTC")

    print(f"\nWrangling 1s bars...")
    bt_1s = BarType.from_str("NQ.XCME-1-SECOND-LAST-EXTERNAL")
    w_1s = BarDataWrangler(bar_type=bt_1s, instrument=nq)
    bars_1s = w_1s.process(df_in, ts_init_delta=1_000_000_000)
    print(f"  {len(bars_1s):,} 1s bars")
    catalog.write_data(bars_1s)

    print(f"\nResampling to 1m (closed='left' — FIXED)...")
    df_1m = df_in.resample("1min", label="right",
                              closed="left").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["open", "high", "low", "close"])
    print(f"  {len(df_1m):,} 1m bars")

    df_1m_aligned = df_1m.copy()
    df_1m_aligned.index = df_1m_aligned.index - pd.Timedelta(seconds=60)

    bt_1m = BarType.from_str("NQ.XCME-1-MINUTE-LAST-EXTERNAL")
    w_1m = BarDataWrangler(bar_type=bt_1m, instrument=nq)
    bars_1m = w_1m.process(df_1m_aligned, ts_init_delta=60_000_000_000)
    print(f"  {len(bars_1m):,} bars after wrangle")
    catalog.write_data(bars_1m)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
