"""Download mbp-1 (tick-level L1) for NQ.v.0, ES.v.0, YM.v.0 — 2026 YTD.

Splits into monthly chunks for resumability:
  4 months (Jan/Feb/Mar/Apr 2026) × 3 symbols = 12 files

Saves to data/raw/<INST>_v0_mbp1_2026_<MM>.parquet alongside existing
.c.0 mbp-1 files. Existing files are NOT modified.

Cost confirmed via Databento metadata.get_cost(): $0.00 under current
account (free under subscription / credit). Total bytes: ~164 GB.

Resumability:
  - Skips files that already exist on disk.
  - On per-file download error, logs and continues to next file.
    Re-running picks up where the failure left off.

Usage:
    python scripts/download_v0_mbp1_2026.py --dry-run    # preview only
    python scripts/download_v0_mbp1_2026.py              # real download
    python scripts/download_v0_mbp1_2026.py --instruments NQ
    python scripts/download_v0_mbp1_2026.py --months 03,04
"""
from __future__ import annotations

import argparse
import calendar
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from download_data import download_mbp1  # triggers load_dotenv()

RAW_DIR = Path("data/raw")
DATASET = "GLBX.MDP3"

INSTRUMENTS_DEFAULT = ("NQ", "ES", "YM")
YEAR = 2026
MONTHS = (1, 2, 3, 4)  # Jan-Apr 2026 (YTD as of 2026-04-30)
END_DAY_LIMIT = 30  # April only has 30 days; cap the last partial month


def month_window(year: int, month: int) -> tuple[str, str]:
    """Return (start_date, end_date) inclusive in YYYY-MM-DD."""
    start = f"{year:04d}-{month:02d}-01"
    last_day_of_month = calendar.monthrange(year, month)[1]
    if month == max(MONTHS) and END_DAY_LIMIT is not None:
        last_day = min(last_day_of_month, END_DAY_LIMIT)
    else:
        last_day = last_day_of_month
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                              help="Print plan without downloading.")
    parser.add_argument("--instruments",
                              default=",".join(INSTRUMENTS_DEFAULT))
    parser.add_argument("--months", default=None,
                              help="Comma-separated month numbers "
                                    "(e.g. 03,04).")
    args = parser.parse_args()

    instruments = [s.strip() for s in args.instruments.split(",")
                       if s.strip()]
    if args.months:
        months = tuple(int(m.strip())
                          for m in args.months.split(",")
                          if m.strip())
    else:
        months = MONTHS

    if not args.dry_run and os.environ.get(
            "DATABENTO_API_KEY") is None:
        print("ERROR: DATABENTO_API_KEY not set.")
        return 2

    jobs = []
    for inst in instruments:
        symbol = f"{inst}.v.0"
        for m in months:
            start, end = month_window(YEAR, m)
            out_name = (
                f"{inst}_v0_mbp1_{YEAR:04d}_{m:02d}.parquet")
            out_path = RAW_DIR / out_name
            jobs.append({
                "inst": inst, "symbol": symbol, "month": m,
                "start": start, "end": end,
                "out_name": out_name, "out_path": out_path,
            })

    print(f"Planned downloads: {len(jobs)}")
    for j in jobs:
        exists = " [EXISTS]" if j["out_path"].exists() else ""
        print(f"  {j['symbol']:>10}  {j['start']} -> "
              f"{j['end']}  -> {j['out_name']}{exists}")

    if args.dry_run:
        print("\n(dry run — no data downloaded)")
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    n_done = 0
    n_skipped = 0
    n_failed = 0
    failures = []
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
            download_mbp1(
                symbol=j["symbol"], dataset=DATASET,
                start=j["start"], end=j["end"],
                output_name=j["out_name"])
            elapsed = time.time() - t0
            size_gb = j["out_path"].stat().st_size / 1e9
            mins = elapsed / 60
            print(f"   done in {mins:.1f} min  "
                  f"({size_gb:.2f} GB)")
            n_done += 1
        except Exception as e:
            n_failed += 1
            failures.append((j["out_name"], str(e)))
            print(f"   FAILED: {e}")

    total_min = (time.time() - t_start) / 60
    print(f"\nSummary: {n_done} downloaded, "
          f"{n_skipped} skipped, {n_failed} failed.  "
          f"Total {total_min:.1f} min.")
    if failures:
        print("\nFailures (re-run to retry):")
        for name, err in failures:
            print(f"  {name}: {err}")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
