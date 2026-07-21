"""Download raw data from Databento."""

import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import databento as db

# Get API key from environment
API_KEY = os.environ.get("DATABENTO_API_KEY")

# Data directory
RAW_DATA_DIR = Path("data/raw")


def download_ohlcv_1s(
    symbol: str,
    dataset: str,
    start: str,
    end: str,
    output_name: str = None,
) -> Path:
    """
    Download 1-second OHLCV bars from Databento.

    Parameters
    ----------
    symbol : str
        Symbol to download (e.g., "NQ.c.0" for NQ continuous front month).
    dataset : str
        Databento dataset (e.g., "GLBX.MDP3" for CME Globex).
    start : str
        Start date in YYYY-MM-DD format.
    end : str
        End date in YYYY-MM-DD format.
    output_name : str, optional
        Output filename. If None, auto-generated.

    Returns
    -------
    Path
        Path to the saved parquet file.
    """
    if API_KEY is None:
        raise ValueError("DATABENTO_API_KEY environment variable not set")

    client = db.Historical(key=API_KEY)

    # Generate output filename
    if output_name is None:
        symbol_clean = symbol.replace(".", "_").replace("/", "_")
        output_name = f"{symbol_clean}_1s_{start}_{end}.parquet"

    output_path = RAW_DATA_DIR / output_name

    print(f"Downloading {symbol} from {start} to {end}...")

    data = client.timeseries.get_range(
        dataset=dataset,
        symbols=[symbol],
        stype_in="continuous",
        schema="ohlcv-1s",
        start=start,
        end=end,
    )

    # Save to parquet
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    data.to_parquet(str(output_path))

    print(f"Saved to {output_path}")
    return output_path


def download_trades(
    symbol: str,
    dataset: str,
    start: str,
    end: str,
    output_name: str = None,
) -> Path:
    """
    Download trade data from Databento.

    Parameters
    ----------
    symbol : str
        Symbol to download.
    dataset : str
        Databento dataset.
    start : str
        Start date in YYYY-MM-DD format.
    end : str
        End date in YYYY-MM-DD format.
    output_name : str, optional
        Output filename.

    Returns
    -------
    Path
        Path to the saved parquet file.
    """
    if API_KEY is None:
        raise ValueError("DATABENTO_API_KEY environment variable not set")

    client = db.Historical(key=API_KEY)

    if output_name is None:
        symbol_clean = symbol.replace(".", "_").replace("/", "_")
        output_name = f"{symbol_clean}_trades_{start}_{end}.parquet"

    output_path = RAW_DATA_DIR / output_name

    print(f"Downloading trades for {symbol} from {start} to {end}...")

    data = client.timeseries.get_range(
        dataset=dataset,
        symbols=[symbol],
        stype_in="continuous",
        schema="trades",
        start=start,
        end=end,
    )

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    data.to_parquet(str(output_path))

    print(f"Saved to {output_path}")
    return output_path


def download_bbo(
    symbol: str,
    dataset: str,
    start: str,
    end: str,
    output_name: str = None,
) -> Path:
    """
    Download BBO (best bid/offer) data from Databento.

    Parameters
    ----------
    symbol : str
        Symbol to download.
    dataset : str
        Databento dataset.
    start : str
        Start date in YYYY-MM-DD format.
    end : str
        End date in YYYY-MM-DD format.
    output_name : str, optional
        Output filename.

    Returns
    -------
    Path
        Path to the saved parquet file.
    """
    if API_KEY is None:
        raise ValueError("DATABENTO_API_KEY environment variable not set")

    client = db.Historical(key=API_KEY)

    if output_name is None:
        symbol_clean = symbol.replace(".", "_").replace("/", "_")
        output_name = f"{symbol_clean}_bbo_{start}_{end}.parquet"

    output_path = RAW_DATA_DIR / output_name

    print(f"Downloading BBO for {symbol} from {start} to {end}...")

    data = client.timeseries.get_range(
        dataset=dataset,
        symbols=[symbol],
        stype_in="continuous",
        schema="bbo-1s",
        start=start,
        end=end,
    )

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    data.to_parquet(str(output_path))

    print(f"Saved to {output_path}")
    return output_path


def download_mbp1(
    symbol: str,
    dataset: str,
    start: str,
    end: str,
    output_name: str = None,
) -> Path:
    """Download tick-level BBO (MBP-1) data from Databento."""
    if API_KEY is None:
        raise ValueError("DATABENTO_API_KEY environment variable not set")

    client = db.Historical(key=API_KEY)

    if output_name is None:
        symbol_clean = symbol.replace(".", "_").replace("/", "_")
        output_name = f"{symbol_clean}_mbp1_{start}_{end}.parquet"

    output_path = RAW_DATA_DIR / output_name

    print(f"Downloading MBP-1 for {symbol} from {start} to {end}...")

    data = client.timeseries.get_range(
        dataset=dataset,
        symbols=[symbol],
        stype_in="continuous",
        schema="mbp-1",
        start=start,
        end=end,
    )

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    data.to_parquet(str(output_path))

    print(f"Saved to {output_path}")
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download NQ data from Databento")
    parser.add_argument("--schema", choices=["trades", "bbo", "mbp-1", "ohlcv-1s", "all"],
                        default="all", help="Data type to download")
    parser.add_argument("--start", default="2025-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2025-12-31", help="End date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded")
    args = parser.parse_args()

    SYMBOL = "NQ.c.0"
    DATASET = "GLBX.MDP3"

    jobs = []
    if args.schema in ("trades", "all"):
        jobs.append(("trades", download_trades,
                      f"NQ_trades_{args.start.replace('-','')}_{args.end.replace('-','')}.parquet"))
    if args.schema in ("mbp-1", "all"):
        jobs.append(("mbp-1", download_mbp1,
                      f"NQ_mbp1_{args.start.replace('-','')}_{args.end.replace('-','')}.parquet"))
    if args.schema in ("bbo", "all"):
        jobs.append(("bbo", download_bbo,
                      f"NQ_bbo_{args.start.replace('-','')}_{args.end.replace('-','')}.parquet"))
    if args.schema in ("ohlcv-1s", "all"):
        jobs.append(("ohlcv-1s", download_ohlcv_1s,
                      f"NQ_1s_{args.start.replace('-','')}_{args.end.replace('-','')}.parquet"))

    for schema_name, fn, out_name in jobs:
        out_path = RAW_DATA_DIR / out_name
        if out_path.exists():
            print(f"SKIP {schema_name}: {out_path} already exists")
            continue
        if args.dry_run:
            print(f"WOULD download {schema_name}: {SYMBOL} {args.start} to {args.end} -> {out_name}")
        else:
            fn(SYMBOL, DATASET, args.start, args.end, output_name=out_name)

    if args.dry_run:
        print("\n(dry run — no data downloaded)")
    else:
        print("\nDone.")
