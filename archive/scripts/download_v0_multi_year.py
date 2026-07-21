"""Download NQ/ES/YM ohlcv-1s with VOLUME-roll continuation (`.v.0`).

Saves to data/raw/<INST>_v0_1s_<year>.parquet. Matches the year coverage
of existing .c.0 files (2016-2026 YTD). Existing .c.0 raw files are NOT
modified — these are saved alongside under _v0_ names.

Year-by-year files (not multi-year combined) so a partial failure only
costs one year of bytes. Skips files that already exist on disk.

IMPORTANT — `.v.0` is still raw / unadjusted. Roll dates shift ±1-2 days
vs `.c.0`, but the price gap at each roll is still present in the series.
This download exists for the volume-tracking property, not for gap removal.

Usage:
    # Dry run first to confirm scope
    python scripts/download_v0_multi_year.py --dry-run

    # Real download (requires DATABENTO_API_KEY env var)
    python scripts/download_v0_multi_year.py

    # Restrict scope
    python scripts/download_v0_multi_year.py --instruments NQ
    python scripts/download_v0_multi_year.py --years 2024,2025
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Reuse the proven downloader from scripts/download_data.py
sys.path.insert(0, str(Path(__file__).parent))
from download_data import download_ohlcv_1s  # noqa: E402

RAW_DIR = Path("data/raw")
DATASET = "GLBX.MDP3"

INSTRUMENTS_DEFAULT = ("NQ", "ES", "YM")

YEAR_RANGES = [
    (2016, "2016-01-01", "2016-12-31"),
    (2017, "2017-01-01", "2017-12-31"),
    (2018, "2018-01-01", "2018-12-31"),
    (2019, "2019-01-01", "2019-12-31"),
    (2020, "2020-01-01", "2020-12-31"),
    (2021, "2021-01-01", "2021-12-31"),
    (2022, "2022-01-01", "2022-12-31"),
    (2023, "2023-01-01", "2023-12-31"),
    (2024, "2024-01-01", "2024-12-31"),
    (2025, "2025-01-01", "2025-12-31"),
    ("2026_ytd", "2026-01-01", "2026-04-30"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                              help="Print what would be downloaded; "
                                    "do not call Databento API.")
    parser.add_argument("--instruments", default=",".join(
        INSTRUMENTS_DEFAULT),
                              help="Comma-separated, e.g. NQ,ES,YM")
    parser.add_argument("--years", default=None,
                              help="Comma-separated years to limit "
                                    "download (e.g. 2024,2025).")
    args = parser.parse_args()

    instruments = [s.strip() for s in args.instruments.split(",")
                       if s.strip()]
    year_filter = None
    if args.years:
        year_filter = {s.strip() for s in args.years.split(",")
                          if s.strip()}

    if not args.dry_run and os.environ.get(
            "DATABENTO_API_KEY") is None:
        print("ERROR: DATABENTO_API_KEY env var not set. Either "
              "export it and re-run, or use --dry-run.")
        sys.exit(2)

    jobs = []
    for inst in instruments:
        symbol = f"{inst}.v.0"
        for tag, start, end in YEAR_RANGES:
            if year_filter is not None and str(tag) not in year_filter:
                continue
            out_name = f"{inst}_v0_1s_{tag}.parquet"
            out_path = RAW_DIR / out_name
            jobs.append({
                "inst": inst, "symbol": symbol, "tag": tag,
                "start": start, "end": end,
                "out_name": out_name, "out_path": out_path,
            })

    print(f"Planned downloads: {len(jobs)}")
    for j in jobs:
        exists = " [EXISTS]" if j["out_path"].exists() else ""
        print(f"  {j['symbol']:>10}  {j['tag']:>10}  "
              f"{j['start']} -> {j['end']}  {j['out_name']}{exists}")

    if args.dry_run:
        print("\n(dry run — no data downloaded)")
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    n_done = 0
    n_skipped = 0
    n_failed = 0
    t_start = time.time()

    for i, j in enumerate(jobs, 1):
        if j["out_path"].exists():
            print(f"[{i:2d}/{len(jobs)}] SKIP {j['out_name']} "
                  "(exists)")
            n_skipped += 1
            continue
        print(f"[{i:2d}/{len(jobs)}] downloading {j['symbol']} "
              f"{j['start']} -> {j['end']}")
        t0 = time.time()
        try:
            download_ohlcv_1s(
                symbol=j["symbol"], dataset=DATASET,
                start=j["start"], end=j["end"],
                output_name=j["out_name"])
            elapsed = time.time() - t0
            size_mb = j["out_path"].stat().st_size / 1e6
            print(f"   done in {elapsed:.1f}s  ({size_mb:.0f} MB)")
            n_done += 1
        except Exception as e:
            print(f"   FAILED: {e}")
            n_failed += 1

    total_elapsed = (time.time() - t_start) / 60
    print(f"\nSummary: {n_done} downloaded, {n_skipped} skipped, "
          f"{n_failed} failed.  Total {total_elapsed:.1f} min.")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
