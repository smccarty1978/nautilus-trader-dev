"""Build combined 2020-2025 catalog for ORB study."""

from pathlib import Path
import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.model.data import BarType
from nautilus_trader.test_kit.providers import TestInstrumentProvider

RAW_DATA_DIR = Path("data/raw")
CATALOG_DIR = Path("data/catalog")

TS_INIT_DELTAS = {
    "1-SECOND": 1_000_000_000,
    "1-MINUTE": 60_000_000_000,
}


def get_instrument(symbol: str):
    if symbol == "NQ":
        return TestInstrumentProvider.future(
            symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME",
        )
    elif symbol == "ES":
        return TestInstrumentProvider.future(
            symbol="ES", underlying="ES", venue="XCME", exchange="XCME",
        )
    else:
        raise ValueError(f"Unknown symbol: {symbol}")


def aggregate_bars(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    df_clean = df[['open', 'high', 'low', 'close', 'volume']].copy()
    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }
    df_agg = df_clean.resample(rule, label='left').agg(agg_dict)
    df_agg = df_agg.dropna()
    return df_agg


def build_catalog(symbol: str):
    """Build combined 2020-2025 catalog."""

    catalog_name = f"{symbol}_2020_2025"
    catalog_path = CATALOG_DIR / catalog_name

    print("=" * 60)
    print(f"BUILDING {symbol} 2020-2025 CATALOG")
    print("=" * 60)

    # Load and combine data
    print("\nLoading 2020-2024 data...")
    df_2020_2024 = pd.read_parquet(RAW_DATA_DIR / f"{symbol}_1s_2020_2024.parquet")
    print(f"  Loaded {len(df_2020_2024):,} rows")

    print("Loading 2025 data...")
    df_2025 = pd.read_parquet(RAW_DATA_DIR / f"{symbol}_1s_2025.parquet")
    print(f"  Loaded {len(df_2025):,} rows")

    # Combine
    print("\nCombining datasets...")
    df_raw = pd.concat([df_2020_2024, df_2025])
    df_raw = df_raw.sort_index()
    df_raw = df_raw[~df_raw.index.duplicated(keep='first')]
    print(f"Combined: {len(df_raw):,} rows")
    print(f"Date range: {df_raw.index[0]} to {df_raw.index[-1]}")

    # Select OHLCV
    df = df_raw[['open', 'high', 'low', 'close', 'volume']].copy()

    # Get instrument
    instrument = get_instrument(symbol)
    print(f"\nInstrument: {instrument.id}")

    # Create catalog
    catalog_path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(catalog_path))

    # Write instrument
    catalog.write_data([instrument])
    print("Wrote instrument to catalog")

    # Build 1-SECOND bars
    print("\n" + "-" * 40)
    print("Building 1-SECOND bars...")
    bar_type_1s = BarType.from_str(f"{instrument.id}-1-SECOND-LAST-EXTERNAL")
    wrangler_1s = BarDataWrangler(instrument=instrument, bar_type=bar_type_1s)

    ts_delta_1s = TS_INIT_DELTAS["1-SECOND"]
    bars_1s = wrangler_1s.process(data=df, ts_init_delta=ts_delta_1s)
    print(f"Wrangled {len(bars_1s):,} bars")

    catalog.write_data(bars_1s)
    print(f"Wrote 1s bars to catalog")

    # Build 1-MINUTE bars
    print("\n" + "-" * 40)
    print("Building 1-MINUTE bars...")

    df_1m = aggregate_bars(df, '1min')
    print(f"Aggregated to {len(df_1m):,} 1m bars")

    bar_type_1m = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
    wrangler_1m = BarDataWrangler(instrument=instrument, bar_type=bar_type_1m)

    ts_delta_1m = TS_INIT_DELTAS["1-MINUTE"]
    bars_1m = wrangler_1m.process(data=df_1m, ts_init_delta=ts_delta_1m)
    print(f"Wrangled {len(bars_1m):,} bars")

    catalog.write_data(bars_1m)
    print(f"Wrote 1m bars to catalog")

    print("\n" + "=" * 60)
    print(f"CATALOG BUILD COMPLETE: {catalog_path}")
    print("=" * 60)

    return catalog_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True, choices=["NQ", "ES"])
    args = parser.parse_args()

    build_catalog(args.symbol)
