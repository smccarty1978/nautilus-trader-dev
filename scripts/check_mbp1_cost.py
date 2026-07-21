"""Pre-flight cost check for MBP-1 download via Databento.

Calls metadata.get_cost() and metadata.get_record_count() for each of:
  NQ.v.0, ES.v.0, YM.v.0 — 2026-01-01 to 2026-04-30 — schema mbp-1

Does NOT download data; only queries cost/size estimates.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load DATABENTO_API_KEY from .env via download_data side-effect import
sys.path.insert(0, str(Path(__file__).parent))
from download_data import API_KEY  # triggers load_dotenv()

import databento as db


SYMBOLS = ["NQ.v.0", "ES.v.0", "YM.v.0"]
DATASET = "GLBX.MDP3"
START = "2026-01-01"
END = "2026-04-30"
SCHEMA = "mbp-1"
STYPE_IN = "continuous"


def main() -> int:
    if API_KEY is None:
        print("ERROR: DATABENTO_API_KEY not loaded.")
        return 2

    client = db.Historical(key=API_KEY)
    print(f"Cost estimate for {SCHEMA} on {DATASET}, "
          f"{START} -> {END}, stype_in={STYPE_IN}")
    print(f"{'symbol':<10} {'cost (USD)':>12} "
          f"{'records':>15} {'bytes':>15}")
    print("-" * 55)

    total_cost = 0.0
    total_records = 0
    total_bytes = 0
    failed = []

    for sym in SYMBOLS:
        kwargs = dict(
            dataset=DATASET, symbols=[sym], schema=SCHEMA,
            stype_in=STYPE_IN, start=START, end=END,
        )
        try:
            cost = client.metadata.get_cost(**kwargs)
            try:
                rec_count = client.metadata.get_record_count(
                    **kwargs)
            except Exception:
                rec_count = None
            try:
                size_bytes = client.metadata.get_billable_size(
                    **kwargs)
            except Exception:
                size_bytes = None
        except Exception as e:
            failed.append((sym, str(e)))
            print(f"{sym:<10} {'FAILED':>12}  {e}")
            continue

        cost_str = f"${float(cost):.2f}"
        rec_str = (f"{int(rec_count):,}"
                       if rec_count is not None else "—")
        size_str = (f"{int(size_bytes)/1e9:.2f} GB"
                       if size_bytes is not None else "—")
        print(f"{sym:<10} {cost_str:>12} {rec_str:>15} {size_str:>15}")
        total_cost += float(cost)
        if rec_count is not None:
            total_records += int(rec_count)
        if size_bytes is not None:
            total_bytes += int(size_bytes)

    print("-" * 55)
    if total_records or total_bytes:
        rec_str = f"{total_records:,}" if total_records else "—"
        sz_str = (f"{total_bytes/1e9:.2f} GB"
                    if total_bytes else "—")
    else:
        rec_str = "—"; sz_str = "—"
    print(f"{'TOTAL':<10} ${total_cost:>11.2f} {rec_str:>15} "
          f"{sz_str:>15}")

    if failed:
        print("\nFailures:")
        for s, e in failed:
            print(f"  {s}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
