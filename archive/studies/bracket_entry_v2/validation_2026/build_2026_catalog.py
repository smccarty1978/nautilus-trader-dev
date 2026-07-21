"""Extend NQ_2020_2025 catalog with 2026 YTD data.

Appends 2026 1s + 1m + 5m bars to the existing catalog so that:
  - run_collection.py --year 2026 can use it seamlessly
  - 2-day warmup lead-in reaches into 2025-12-30 (already in catalog)

Source: data/raw/NQ_1s_2026_ytd.parquet (through 2026-04-15)
Target: data/catalog/NQ_2020_2025 (existing, will now span 2020-04-15)
"""

from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
import os
os.chdir(project_root)

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.model.data import BarType
from nautilus_trader.test_kit.providers import TestInstrumentProvider

TS_DELTA_1S = 1_000_000_000
TS_DELTA_1M = 60_000_000_000

RAW_PATH = Path("data/raw/NQ_1s_2026_ytd.parquet")
CATALOG_PATH = Path("data/catalog/NQ_2020_2025")


def aggregate(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    return df[list(agg)].resample(rule, label="left").agg(agg).dropna()


def main():
    print(f"Loading {RAW_PATH}...")
    df = pd.read_parquet(RAW_PATH)
    print(f"  {len(df):,} 1s rows, "
           f"{df.index[0]} to {df.index[-1]}")

    df = df[["open", "high", "low", "close", "volume"]].copy()

    instrument = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    # Match existing catalog's instrument definition
    d = instrument.to_dict(instrument)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp(
        "2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp(
        "2020-01-01", tz="UTC").value
    d["multiplier"] = "20"
    d["price_increment"] = "0.25"
    from nautilus_trader.model.instruments import FuturesContract
    instrument = FuturesContract.from_dict(d)

    catalog = ParquetDataCatalog(str(CATALOG_PATH))

    # 1s bars
    print("\nWrangling 1s bars...")
    bt_1s = BarType.from_str(f"{instrument.id}-1-SECOND-LAST-EXTERNAL")
    w1s = BarDataWrangler(instrument=instrument, bar_type=bt_1s)
    bars_1s = w1s.process(data=df, ts_init_delta=TS_DELTA_1S)
    print(f"  {len(bars_1s):,} 1s bars")
    catalog.write_data(bars_1s)
    print("  Wrote to catalog")

    # 1m bars (aggregated)
    print("\nAggregating + wrangling 1m bars...")
    df_1m = aggregate(df, "1min")
    print(f"  {len(df_1m):,} 1m rows")
    bt_1m = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
    w1m = BarDataWrangler(instrument=instrument, bar_type=bt_1m)
    bars_1m = w1m.process(data=df_1m, ts_init_delta=TS_DELTA_1M)
    print(f"  {len(bars_1m):,} 1m bars")
    catalog.write_data(bars_1m)
    print("  Wrote to catalog")

    print("\nDone.")

    # Verify by re-reading
    start = pd.Timestamp("2026-01-01", tz="UTC")
    end = pd.Timestamp("2026-04-30", tz="UTC")
    bars = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=start, end=end)
    print(f"\nVerify: catalog now has {len(bars):,} 1m bars in 2026")
    if bars:
        print(f"  First: {pd.Timestamp(bars[0].ts_event, unit='ns')}")
        print(f"  Last:  {pd.Timestamp(bars[-1].ts_event, unit='ns')}")


if __name__ == "__main__":
    main()
