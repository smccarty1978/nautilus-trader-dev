"""Build NautilusTrader data catalog from raw parquet files.

This script processes raw Databento OHLCV data and creates a NautilusTrader
catalog with multiple bar timeframes (1s, 1m, 5m).

IMPORTANT: Databento timestamps bars at OPEN time. We apply ts_init_delta
to shift timestamps to CLOSE time for proper event ordering.
"""

from pathlib import Path

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.model.data import BarType
from nautilus_trader.test_kit.providers import TestInstrumentProvider

# Directories
RAW_DATA_DIR = Path("data/raw")
CATALOG_DIR = Path("data/catalog")


# Timestamp deltas for bar aggregation (in nanoseconds)
# Databento timestamps at OPEN, NT needs CLOSE time
TS_INIT_DELTAS = {
    "1-SECOND": 1_000_000_000,       # 1 second
    "1-MINUTE": 60_000_000_000,      # 60 seconds
    "5-MINUTE": 300_000_000_000,     # 5 minutes
    "15-MINUTE": 900_000_000_000,    # 15 minutes
    "1-HOUR": 3_600_000_000_000,     # 1 hour
}


def get_instrument(symbol: str):
    """Get instrument definition for a symbol."""
    if "NQ" in symbol.upper():
        # NQ E-mini NASDAQ-100 futures
        return TestInstrumentProvider.future(
            symbol="NQ",
            underlying="NQ",
            venue="XCME",
            exchange="XCME",
        )
    elif "ES" in symbol.upper():
        # ES E-mini S&P 500 futures
        return TestInstrumentProvider.future(
            symbol="ES",
            underlying="ES",
            venue="XCME",
            exchange="XCME",
        )
    else:
        raise ValueError(f"Unknown symbol: {symbol}. Add instrument definition.")


def aggregate_bars(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Aggregate OHLCV data to a higher timeframe.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with DatetimeIndex and OHLCV columns.
    rule : str
        Pandas resample rule (e.g., '1min', '5min').

    Returns
    -------
    pd.DataFrame
        Aggregated OHLCV data.
    """
    # Ensure we have the right columns (lowercase)
    df_clean = df[['open', 'high', 'low', 'close', 'volume']].copy()

    # Resample using standard OHLCV aggregation
    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }

    # Use label='left' to timestamp at bar open (Databento convention)
    # ts_init_delta will shift to close time
    df_agg = df_clean.resample(rule, label='left').agg(agg_dict)

    # Drop rows with NaN (incomplete bars)
    df_agg = df_agg.dropna()

    return df_agg


def build_catalog(
    raw_file: Path = None,
    catalog_name: str = "NQ_2025",
    symbol: str = "NQ",
):
    """
    Build a complete catalog with 1s, 1m, and 5m bars.

    Parameters
    ----------
    raw_file : Path, optional
        Path to raw 1s parquet file. Defaults to {symbol}_1s_2025.parquet.
    catalog_name : str
        Name for the catalog subdirectory.
    symbol : str
        Instrument symbol (NQ, ES, etc.).
    """
    if raw_file is None:
        raw_file = RAW_DATA_DIR / f"{symbol}_1s_2025.parquet"

    catalog_path = CATALOG_DIR / catalog_name

    print("=" * 60)
    print(f"BUILDING {symbol} CATALOG")
    print("=" * 60)
    print(f"Raw file: {raw_file}")
    print(f"Catalog path: {catalog_path}")
    print()

    # Load raw 1s data
    print("Loading raw data...")
    df_raw = pd.read_parquet(raw_file)
    print(f"Loaded {len(df_raw):,} rows")
    print(f"Date range: {df_raw.index[0]} to {df_raw.index[-1]}")

    # Select only OHLCV columns (wrangler expects these)
    df = df_raw[['open', 'high', 'low', 'close', 'volume']].copy()
    print()

    # Get instrument
    instrument = get_instrument(symbol)
    print(f"Instrument: {instrument.id}")
    print()

    # Create catalog directory
    catalog_path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(catalog_path))

    # Write instrument
    catalog.write_data([instrument])
    print("Wrote instrument to catalog")

    # --- Build 1-SECOND bars ---
    print("\n" + "-" * 40)
    print("Building 1-SECOND bars...")
    bar_type_1s = BarType.from_str(f"{instrument.id}-1-SECOND-LAST-EXTERNAL")
    wrangler_1s = BarDataWrangler(instrument=instrument, bar_type=bar_type_1s)

    ts_delta_1s = TS_INIT_DELTAS["1-SECOND"]
    print(f"Applying ts_init_delta: {ts_delta_1s:,} ns ({ts_delta_1s / 1e9:.0f}s)")

    bars_1s = wrangler_1s.process(data=df, ts_init_delta=ts_delta_1s)
    print(f"Wrangled {len(bars_1s):,} bars")

    catalog.write_data(bars_1s)
    print(f"Wrote 1s bars to catalog")
    print(f"First: {bars_1s[0].ts_event}")
    print(f"Last: {bars_1s[-1].ts_event}")

    # --- Build 1-MINUTE bars ---
    print("\n" + "-" * 40)
    print("Building 1-MINUTE bars...")

    # Aggregate 1s to 1m
    df_1m = aggregate_bars(df, '1min')
    print(f"Aggregated to {len(df_1m):,} 1m bars")

    bar_type_1m = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
    wrangler_1m = BarDataWrangler(instrument=instrument, bar_type=bar_type_1m)

    ts_delta_1m = TS_INIT_DELTAS["1-MINUTE"]
    print(f"Applying ts_init_delta: {ts_delta_1m:,} ns ({ts_delta_1m / 1e9:.0f}s)")

    bars_1m = wrangler_1m.process(data=df_1m, ts_init_delta=ts_delta_1m)
    print(f"Wrangled {len(bars_1m):,} bars")

    catalog.write_data(bars_1m)
    print(f"Wrote 1m bars to catalog")
    print(f"First: {bars_1m[0].ts_event}")
    print(f"Last: {bars_1m[-1].ts_event}")

    # --- Build 5-MINUTE bars ---
    print("\n" + "-" * 40)
    print("Building 5-MINUTE bars...")

    # Aggregate 1s to 5m
    df_5m = aggregate_bars(df, '5min')
    print(f"Aggregated to {len(df_5m):,} 5m bars")

    bar_type_5m = BarType.from_str(f"{instrument.id}-5-MINUTE-LAST-EXTERNAL")
    wrangler_5m = BarDataWrangler(instrument=instrument, bar_type=bar_type_5m)

    ts_delta_5m = TS_INIT_DELTAS["5-MINUTE"]
    print(f"Applying ts_init_delta: {ts_delta_5m:,} ns ({ts_delta_5m / 1e9:.0f}s)")

    bars_5m = wrangler_5m.process(data=df_5m, ts_init_delta=ts_delta_5m)
    print(f"Wrangled {len(bars_5m):,} bars")

    catalog.write_data(bars_5m)
    print(f"Wrote 5m bars to catalog")
    print(f"First: {bars_5m[0].ts_event}")
    print(f"Last: {bars_5m[-1].ts_event}")

    # --- Validate ---
    print("\n" + "=" * 60)
    print("CATALOG BUILD COMPLETE")
    print("=" * 60)
    validate_catalog(str(catalog_path), bar_types=[
        f"{instrument.id}-1-SECOND-LAST-EXTERNAL",
        f"{instrument.id}-1-MINUTE-LAST-EXTERNAL",
        f"{instrument.id}-5-MINUTE-LAST-EXTERNAL",
    ])

    return catalog


def validate_catalog(catalog_path: str, bar_types: list = None) -> None:
    """Validate a catalog by printing summary information."""
    catalog = ParquetDataCatalog(catalog_path)

    print(f"\nCatalog: {catalog_path}")
    print("-" * 40)

    # Check instruments
    instruments = catalog.instruments()
    print(f"Instruments: {len(instruments)}")
    for inst in instruments:
        print(f"  - {inst.id}")

    # Check bar types (use provided list or default NQ types)
    if bar_types is None:
        bar_types = [
            "NQ.XCME-1-SECOND-LAST-EXTERNAL",
            "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
            "NQ.XCME-5-MINUTE-LAST-EXTERNAL",
        ]

    print(f"\nBar Types:")
    for bt in bar_types:
        try:
            bars = catalog.bars(bar_types=[bt])
            if bars:
                print(f"  - {bt}: {len(bars):,} bars")
                print(f"      First: {bars[0].ts_event}")
                print(f"      Last: {bars[-1].ts_event}")
        except Exception as e:
            print(f"  - {bt}: Error - {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build NautilusTrader data catalog")
    parser.add_argument(
        "--raw-file",
        type=str,
        default=None,
        help="Path to raw parquet file (default: data/raw/NQ_1s_2025.parquet)",
    )
    parser.add_argument(
        "--catalog-name",
        type=str,
        default="NQ_2025",
        help="Name for catalog subdirectory (default: NQ_2025)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="NQ",
        help="Instrument symbol (default: NQ)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate existing catalog, don't build",
    )

    args = parser.parse_args()

    if args.validate_only:
        catalog_path = CATALOG_DIR / args.catalog_name
        validate_catalog(str(catalog_path))
    else:
        raw_file = Path(args.raw_file) if args.raw_file else None
        build_catalog(raw_file=raw_file, catalog_name=args.catalog_name, symbol=args.symbol)
