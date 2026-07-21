"""Validate data integrity for raw files and catalogs."""

from pathlib import Path
from datetime import datetime

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog

RAW_DATA_DIR = Path("data/raw")
CATALOG_DIR = Path("data/catalog")


def validate_raw_ohlcv(file_path: Path) -> dict:
    """
    Validate a raw OHLCV parquet file.

    Parameters
    ----------
    file_path : Path
        Path to the parquet file.

    Returns
    -------
    dict
        Validation results.
    """
    print(f"\n{'='*60}")
    print(f"Validating: {file_path}")
    print(f"{'='*60}")

    df = pd.read_parquet(file_path)

    results = {
        "file": str(file_path),
        "rows": len(df),
        "columns": list(df.columns),
        "issues": [],
    }

    # Check required columns
    required_cols = {"open", "high", "low", "close", "volume"}
    missing_cols = required_cols - set(c.lower() for c in df.columns)
    if missing_cols:
        results["issues"].append(f"Missing columns: {missing_cols}")

    print(f"Rows: {results['rows']}")
    print(f"Columns: {results['columns']}")

    # Check for timestamp column
    ts_cols = [c for c in df.columns if "time" in c.lower() or "ts" in c.lower()]
    if ts_cols:
        ts_col = ts_cols[0]
        results["first_timestamp"] = str(df[ts_col].iloc[0])
        results["last_timestamp"] = str(df[ts_col].iloc[-1])
        print(f"First timestamp: {results['first_timestamp']}")
        print(f"Last timestamp: {results['last_timestamp']}")

    # OHLC validation
    if all(c in df.columns for c in ["open", "high", "low", "close"]):
        # High should be >= Low
        invalid_hl = (df["high"] < df["low"]).sum()
        if invalid_hl > 0:
            results["issues"].append(f"High < Low in {invalid_hl} rows")

        # Open/Close should be within High/Low
        invalid_open = ((df["open"] > df["high"]) | (df["open"] < df["low"])).sum()
        if invalid_open > 0:
            results["issues"].append(f"Open outside H/L range in {invalid_open} rows")

        invalid_close = ((df["close"] > df["high"]) | (df["close"] < df["low"])).sum()
        if invalid_close > 0:
            results["issues"].append(f"Close outside H/L range in {invalid_close} rows")

        print(f"OHLC validation: {'PASS' if invalid_hl == 0 and invalid_open == 0 and invalid_close == 0 else 'ISSUES FOUND'}")

    # Check for nulls
    null_counts = df.isnull().sum()
    if null_counts.any():
        null_cols = null_counts[null_counts > 0].to_dict()
        results["issues"].append(f"Null values: {null_cols}")
        print(f"Null values found: {null_cols}")
    else:
        print("Null values: None")

    # Summary
    if results["issues"]:
        print(f"\nISSUES FOUND:")
        for issue in results["issues"]:
            print(f"  - {issue}")
    else:
        print("\nVALIDATION PASSED")

    return results


def validate_catalog(catalog_path: Path) -> dict:
    """
    Validate a NautilusTrader catalog.

    Parameters
    ----------
    catalog_path : Path
        Path to the catalog directory.

    Returns
    -------
    dict
        Validation results.
    """
    print(f"\n{'='*60}")
    print(f"Validating catalog: {catalog_path}")
    print(f"{'='*60}")

    catalog = ParquetDataCatalog(str(catalog_path))

    results = {
        "catalog_path": str(catalog_path),
        "instruments": [],
        "bar_types": [],
        "issues": [],
    }

    # Check instruments
    instruments = catalog.instruments()
    results["instruments"] = [str(i.id) for i in instruments]
    print(f"Instruments: {results['instruments']}")

    if not instruments:
        results["issues"].append("No instruments found in catalog")

    # Check bar types
    bar_types = catalog.bar_types()
    results["bar_types"] = [str(bt) for bt in bar_types]
    print(f"Bar types: {results['bar_types']}")

    if not bar_types:
        results["issues"].append("No bar types found in catalog")

    # Validate each bar type
    for bt in bar_types:
        bars = catalog.bars(bar_types=[str(bt)])
        bt_results = {
            "bar_type": str(bt),
            "count": len(bars),
            "first": str(bars[0].ts_event) if bars else None,
            "last": str(bars[-1].ts_event) if bars else None,
        }
        results[f"bars_{bt}"] = bt_results

        print(f"\n{bt}:")
        print(f"  Count: {bt_results['count']}")
        print(f"  First: {bt_results['first']}")
        print(f"  Last: {bt_results['last']}")

        # Spot check OHLC
        if bars:
            issues_found = 0
            for bar in bars[:1000]:  # Check first 1000
                if bar.high.as_double() < bar.low.as_double():
                    issues_found += 1
            if issues_found > 0:
                results["issues"].append(f"{bt}: {issues_found} bars with High < Low")

    # Summary
    if results["issues"]:
        print(f"\nISSUES FOUND:")
        for issue in results["issues"]:
            print(f"  - {issue}")
    else:
        print("\nVALIDATION PASSED")

    return results


def validate_all_raw() -> list:
    """Validate all raw parquet files."""
    results = []
    for file in RAW_DATA_DIR.glob("*.parquet"):
        results.append(validate_raw_ohlcv(file))
    return results


def validate_all_catalogs() -> list:
    """Validate all catalogs."""
    results = []
    for catalog_dir in CATALOG_DIR.iterdir():
        if catalog_dir.is_dir():
            results.append(validate_catalog(catalog_dir))
    return results


if __name__ == "__main__":
    print("Data Validation Script")
    print("=" * 60)

    # Validate raw files
    print("\n\nVALIDATING RAW FILES")
    print("=" * 60)
    raw_results = validate_all_raw()

    # Validate catalogs
    if any(CATALOG_DIR.iterdir()):
        print("\n\nVALIDATING CATALOGS")
        print("=" * 60)
        catalog_results = validate_all_catalogs()
    else:
        print("\n\nNo catalogs found to validate.")

    # Summary
    print("\n\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    total_issues = sum(len(r.get("issues", [])) for r in raw_results)
    print(f"Raw files validated: {len(raw_results)}")
    print(f"Total issues in raw files: {total_issues}")
