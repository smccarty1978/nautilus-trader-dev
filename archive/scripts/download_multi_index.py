"""Download ES, NQ, YM 1s OHLCV from Databento for 10-year history.

- NQ: fill gap 2016-2019 (already have 2020-2025)
- ES: fill gap 2016-2019 (already have 2020-2025)
- YM: full 10 years 2016-2025 (nothing yet)

1m bars are NOT downloaded separately — they are aggregated from 1s
in the catalog build step (see scripts/build_catalog.py).

Usage:
    # Cost preview (no downloads, no charges)
    python scripts/download_multi_index.py --cost-only

    # Dry run (shows jobs, no downloads)
    python scripts/download_multi_index.py --dry-run

    # Actual download
    python scripts/download_multi_index.py
"""

import os
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import databento as db

API_KEY = os.environ.get("DATABENTO_API_KEY")
RAW_DATA_DIR = Path("data/raw")
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

DATASET = "GLBX.MDP3"

# (symbol, start, end, output_filename, description)
JOBS = [
    # NQ gap fill — 2016-2019
    ("NQ.c.0", "2016-01-01", "2016-12-31",
     "NQ_1s_2016.parquet", "NQ 2016"),
    ("NQ.c.0", "2017-01-01", "2017-12-31",
     "NQ_1s_2017.parquet", "NQ 2017"),
    ("NQ.c.0", "2018-01-01", "2018-12-31",
     "NQ_1s_2018.parquet", "NQ 2018"),
    ("NQ.c.0", "2019-01-01", "2019-12-31",
     "NQ_1s_2019.parquet", "NQ 2019"),

    # ES gap fill — 2016-2019
    ("ES.c.0", "2016-01-01", "2016-12-31",
     "ES_1s_2016.parquet", "ES 2016"),
    ("ES.c.0", "2017-01-01", "2017-12-31",
     "ES_1s_2017.parquet", "ES 2017"),
    ("ES.c.0", "2018-01-01", "2018-12-31",
     "ES_1s_2018.parquet", "ES 2018"),
    ("ES.c.0", "2019-01-01", "2019-12-31",
     "ES_1s_2019.parquet", "ES 2019"),

    # YM — full 10 years
    ("YM.c.0", "2016-01-01", "2016-12-31",
     "YM_1s_2016.parquet", "YM 2016"),
    ("YM.c.0", "2017-01-01", "2017-12-31",
     "YM_1s_2017.parquet", "YM 2017"),
    ("YM.c.0", "2018-01-01", "2018-12-31",
     "YM_1s_2018.parquet", "YM 2018"),
    ("YM.c.0", "2019-01-01", "2019-12-31",
     "YM_1s_2019.parquet", "YM 2019"),
    ("YM.c.0", "2020-01-01", "2020-12-31",
     "YM_1s_2020.parquet", "YM 2020"),
    ("YM.c.0", "2021-01-01", "2021-12-31",
     "YM_1s_2021.parquet", "YM 2021"),
    ("YM.c.0", "2022-01-01", "2022-12-31",
     "YM_1s_2022.parquet", "YM 2022"),
    ("YM.c.0", "2023-01-01", "2023-12-31",
     "YM_1s_2023.parquet", "YM 2023"),
    ("YM.c.0", "2024-01-01", "2024-12-31",
     "YM_1s_2024.parquet", "YM 2024"),
    ("YM.c.0", "2025-01-01", "2025-12-31",
     "YM_1s_2025.parquet", "YM 2025"),

    # 2026 YTD (through 2026-04-16)
    ("NQ.c.0", "2026-01-01", "2026-04-16",
     "NQ_1s_2026_ytd.parquet", "NQ 2026 YTD"),
    ("ES.c.0", "2026-01-01", "2026-04-16",
     "ES_1s_2026_ytd.parquet", "ES 2026 YTD"),
    ("YM.c.0", "2026-01-01", "2026-04-16",
     "YM_1s_2026_ytd.parquet", "YM 2026 YTD"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cost-only", action="store_true",
                        help="Get cost estimate via Databento API, no download")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show jobs, no API calls")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip jobs where output file exists")
    args = parser.parse_args()

    if API_KEY is None and not args.dry_run:
        print("ERROR: DATABENTO_API_KEY environment variable not set")
        sys.exit(1)

    # Filter to jobs that need running
    pending = []
    for symbol, start, end, fname, desc in JOBS:
        path = RAW_DATA_DIR / fname
        if path.exists() and args.skip_existing:
            print(f"SKIP {desc}: {fname} already exists "
                  f"({path.stat().st_size / 1e6:.0f} MB)")
            continue
        pending.append((symbol, start, end, fname, desc))

    if not pending:
        print("\nAll files already present. Nothing to download.")
        return

    print(f"\n{len(pending)} jobs to process:\n")

    if args.dry_run:
        for symbol, start, end, fname, desc in pending:
            print(f"  WOULD download {desc}: {symbol} "
                  f"{start} to {end} -> {fname}")
        print("\n(dry run — no downloads)")
        return

    client = db.Historical(key=API_KEY)

    if args.cost_only:
        total_cost = 0.0
        print(f"{'Job':<20} {'Cost (USD)':>12}")
        print("-" * 34)
        for symbol, start, end, fname, desc in pending:
            try:
                cost = client.metadata.get_cost(
                    dataset=DATASET,
                    symbols=[symbol],
                    stype_in="continuous",
                    schema="ohlcv-1s",
                    start=start,
                    end=end,
                )
                print(f"{desc:<20} ${cost:>10.4f}")
                total_cost += cost
            except Exception as e:
                print(f"{desc:<20} ERROR: {e}")

        print("-" * 34)
        print(f"{'TOTAL':<20} ${total_cost:>10.2f}")
        print(f"\nRun without --cost-only to download.")
        return

    # Actual download
    total = len(pending)
    for i, (symbol, start, end, fname, desc) in enumerate(pending, 1):
        out_path = RAW_DATA_DIR / fname
        print(f"\n[{i}/{total}] Downloading {desc}...")

        try:
            data = client.timeseries.get_range(
                dataset=DATASET,
                symbols=[symbol],
                stype_in="continuous",
                schema="ohlcv-1s",
                start=start,
                end=end,
            )
            data.to_parquet(str(out_path))
            size_mb = out_path.stat().st_size / 1e6
            print(f"  Saved {fname} ({size_mb:.0f} MB)")
        except Exception as e:
            print(f"  ERROR on {desc}: {e}")
            continue

    print(f"\nAll downloads complete. Files saved to {RAW_DATA_DIR}")


if __name__ == "__main__":
    main()
