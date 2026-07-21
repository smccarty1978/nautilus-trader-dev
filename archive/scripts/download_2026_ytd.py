"""Download 2026 YTD 1s OHLCV for NQ, ES, YM.

Runs in parallel with the main multi-year download. These files don't
overlap with the main job so no conflicts.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import databento as db

API_KEY = os.environ.get("DATABENTO_API_KEY")
RAW_DATA_DIR = Path("data/raw")

JOBS = [
    ("NQ.c.0", "2026-01-01", "2026-04-16", "NQ_1s_2026_ytd.parquet", "NQ 2026 YTD"),
    ("ES.c.0", "2026-01-01", "2026-04-16", "ES_1s_2026_ytd.parquet", "ES 2026 YTD"),
    ("YM.c.0", "2026-01-01", "2026-04-16", "YM_1s_2026_ytd.parquet", "YM 2026 YTD"),
]


def main():
    if API_KEY is None:
        raise ValueError("DATABENTO_API_KEY not set")

    client = db.Historical(key=API_KEY)

    for i, (symbol, start, end, fname, desc) in enumerate(JOBS, 1):
        out_path = RAW_DATA_DIR / fname
        if out_path.exists():
            print(f"SKIP {desc}: {fname} exists")
            continue

        print(f"\n[{i}/{len(JOBS)}] {desc} {start} to {end}...")
        try:
            data = client.timeseries.get_range(
                dataset="GLBX.MDP3",
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
            print(f"  ERROR: {e}")

    print("\n2026 YTD downloads complete.")


if __name__ == "__main__":
    main()
