"""Build NQ, ES, YM catalogs from all year files (2016 - 2026 YTD).

Combines all yearly 1s parquet files per symbol, applies ts_init_delta
for OPEN->CLOSE timestamp correction (Databento → NT), aggregates to
1m and 5m bars, writes to catalog.

Usage:
    python scripts/build_multi_index_catalog.py --symbol NQ
    python scripts/build_multi_index_catalog.py --symbol ES
    python scripts/build_multi_index_catalog.py --symbol YM
    python scripts/build_multi_index_catalog.py --all
"""

import sys
import os
import argparse
import time as _time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import pandas as pd

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.model.data import BarType
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract

RAW_DIR = Path("data/raw")
CATALOG_DIR = Path("data/catalog")

TS_INIT_DELTAS = {
    "1-SECOND": 1_000_000_000,
    "1-MINUTE": 60_000_000_000,
    "5-MINUTE": 300_000_000_000,
}

# Per-symbol config
SYMBOLS = {
    "NQ": {
        "catalog_name": "NQ_multi_year",
        "venue": "XCME",
        "multiplier": "20",
        "tick": "0.25",
        "files": [
            "NQ_1s_2016.parquet",
            "NQ_1s_2017.parquet",
            "NQ_1s_2018.parquet",
            "NQ_1s_2019.parquet",
            "NQ_1s_2020_2024.parquet",
            "NQ_1s_2025.parquet",
            "NQ_1s_2026_ytd.parquet",
        ],
    },
    "ES": {
        "catalog_name": "ES_multi_year",
        "venue": "XCME",
        "multiplier": "50",
        "tick": "0.25",
        "files": [
            "ES_1s_2016.parquet",
            "ES_1s_2017.parquet",
            "ES_1s_2018.parquet",
            "ES_1s_2019.parquet",
            "ES_1s_2020_2024.parquet",
            "ES_1s_2025.parquet",
            "ES_1s_2026_ytd.parquet",
        ],
    },
    "YM": {
        "catalog_name": "YM_multi_year",
        "venue": "XCBT",  # CBOT
        "multiplier": "5",
        "tick": "1",
        "price_precision": 0,
        "files": [
            "YM_1s_2016.parquet",
            "YM_1s_2017.parquet",
            "YM_1s_2018.parquet",
            "YM_1s_2019.parquet",
            "YM_1s_2020.parquet",
            "YM_1s_2021.parquet",
            "YM_1s_2022.parquet",
            "YM_1s_2023.parquet",
            "YM_1s_2024.parquet",
            "YM_1s_2025.parquet",
            "YM_1s_2026_ytd.parquet",
        ],
    },
}


def create_instrument(symbol: str, config: dict):
    """Create a FuturesContract for the symbol with proper activation range."""
    t = TestInstrumentProvider.future(
        symbol=symbol,
        underlying=symbol,
        venue=config["venue"],
        exchange=config["venue"],
    )
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2016-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2016-01-01", tz="UTC").value
    d["multiplier"] = config["multiplier"]
    d["price_increment"] = config["tick"]
    if "price_precision" in config:
        d["price_precision"] = config["price_precision"]
    return FuturesContract.from_dict(d)


def load_and_combine(symbol: str, files: list) -> pd.DataFrame:
    """Load all yearly files and combine into one DataFrame."""
    dfs = []
    for fname in files:
        path = RAW_DIR / fname
        if not path.exists():
            print(f"  WARN: {fname} not found, skipping")
            continue
        df = pd.read_parquet(path)
        dfs.append(df)
        print(f"  Loaded {fname}: {len(df):,} rows "
              f"[{df.index[0]} to {df.index[-1]}]")
    if not dfs:
        raise ValueError(f"No files found for {symbol}")
    combined = pd.concat(dfs)
    combined = combined[~combined.index.duplicated(keep="first")]
    combined = combined.sort_index()
    return combined[["open", "high", "low", "close", "volume"]]


def aggregate_bars(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate OHLCV to higher timeframe."""
    agg_dict = {
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }
    df_agg = df.resample(rule, label="left").agg(agg_dict)
    return df_agg.dropna()


def build_catalog_for_symbol(symbol: str):
    config = SYMBOLS[symbol]
    catalog_path = CATALOG_DIR / config["catalog_name"]

    print("=" * 70)
    print(f"BUILDING {symbol} CATALOG ({config['catalog_name']})")
    print("=" * 70)

    # Load and combine
    print("\nLoading yearly files...", flush=True)
    t0 = _time.time()
    df = load_and_combine(symbol, config["files"])
    print(f"\nCombined: {len(df):,} rows ({_time.time()-t0:.0f}s)")
    print(f"  Range: {df.index[0]} to {df.index[-1]}")

    # Create instrument
    instrument = create_instrument(symbol, config)
    print(f"\nInstrument: {instrument.id}")
    print(f"  Multiplier: {config['multiplier']}")
    print(f"  Tick: {config['tick']}")

    # Create catalog
    catalog_path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(catalog_path))
    catalog.write_data([instrument])

    # ---- 1s bars ----
    print("\n" + "-" * 50)
    print("Building 1-SECOND bars...")
    t0 = _time.time()
    bar_type_1s = BarType.from_str(
        f"{instrument.id}-1-SECOND-LAST-EXTERNAL")
    wrangler_1s = BarDataWrangler(
        instrument=instrument, bar_type=bar_type_1s)
    bars_1s = wrangler_1s.process(
        data=df, ts_init_delta=TS_INIT_DELTAS["1-SECOND"])
    print(f"  Wrangled {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")
    t0 = _time.time()
    catalog.write_data(bars_1s)
    print(f"  Wrote to catalog ({_time.time()-t0:.0f}s)")

    # ---- 1m bars (aggregated from 1s) ----
    print("\n" + "-" * 50)
    print("Building 1-MINUTE bars...")
    t0 = _time.time()
    df_1m = aggregate_bars(df, "1min")
    print(f"  Aggregated to {len(df_1m):,} 1m bars ({_time.time()-t0:.0f}s)")
    bar_type_1m = BarType.from_str(
        f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
    wrangler_1m = BarDataWrangler(
        instrument=instrument, bar_type=bar_type_1m)
    t0 = _time.time()
    bars_1m = wrangler_1m.process(
        data=df_1m, ts_init_delta=TS_INIT_DELTAS["1-MINUTE"])
    print(f"  Wrangled ({_time.time()-t0:.0f}s)")
    t0 = _time.time()
    catalog.write_data(bars_1m)
    print(f"  Wrote to catalog ({_time.time()-t0:.0f}s)")

    # ---- 5m bars ----
    print("\n" + "-" * 50)
    print("Building 5-MINUTE bars...")
    t0 = _time.time()
    df_5m = aggregate_bars(df, "5min")
    print(f"  Aggregated to {len(df_5m):,} 5m bars ({_time.time()-t0:.0f}s)")
    bar_type_5m = BarType.from_str(
        f"{instrument.id}-5-MINUTE-LAST-EXTERNAL")
    wrangler_5m = BarDataWrangler(
        instrument=instrument, bar_type=bar_type_5m)
    t0 = _time.time()
    bars_5m = wrangler_5m.process(
        data=df_5m, ts_init_delta=TS_INIT_DELTAS["5-MINUTE"])
    print(f"  Wrangled ({_time.time()-t0:.0f}s)")
    t0 = _time.time()
    catalog.write_data(bars_5m)
    print(f"  Wrote to catalog ({_time.time()-t0:.0f}s)")

    # ---- Validate ----
    print("\n" + "=" * 70)
    print(f"CATALOG BUILD COMPLETE: {symbol}")
    print("=" * 70)
    for bt_str in [
        f"{instrument.id}-1-SECOND-LAST-EXTERNAL",
        f"{instrument.id}-1-MINUTE-LAST-EXTERNAL",
        f"{instrument.id}-5-MINUTE-LAST-EXTERNAL",
    ]:
        bars = catalog.bars(bar_types=[bt_str])
        if bars:
            print(f"  {bt_str}")
            print(f"    {len(bars):,} bars")
            print(f"    First: {pd.Timestamp(bars[0].ts_event, unit='ns', tz='UTC')}")
            print(f"    Last:  {pd.Timestamp(bars[-1].ts_event, unit='ns', tz='UTC')}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=["NQ", "ES", "YM"])
    parser.add_argument("--all", action="store_true",
                        help="Build all three symbol catalogs")
    args = parser.parse_args()

    if args.all:
        for sym in ["NQ", "ES", "YM"]:
            build_catalog_for_symbol(sym)
    elif args.symbol:
        build_catalog_for_symbol(args.symbol)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
