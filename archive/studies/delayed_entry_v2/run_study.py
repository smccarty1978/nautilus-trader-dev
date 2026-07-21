"""Delayed-entry study orchestrator.

Pipeline:
  1. Load 6 years of v2 collector output (features + labels)
  2. Build matched-cohort table (event-paired T=0 vs T_d outcomes)
  3. Compute descriptive table (T_d × stratum × endpoint)
  4. Write markdown report

Usage:
    python studies/delayed_entry_v2/run_study.py
    python studies/delayed_entry_v2/run_study.py --years 2024 2025
"""

from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from collect import collect_all_years, build_matched_cohort  # noqa
from analyze import build_descriptive_table, write_markdown_report  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int,
                     default=[2020, 2021, 2022, 2023, 2024, 2025])
    ap.add_argument("--results-dir",
                     default="studies/1m_regime_collector_v2/results",
                     help="Directory containing v2 collector parquets")
    ap.add_argument("--out-dir",
                     default="studies/delayed_entry_v2/results")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("DELAYED-ENTRY STUDY v2")
    print("=" * 72)
    print(f"  Years:         {args.years}")
    print(f"  V2 results:    {args.results_dir}")
    print(f"  Output:        {out_dir}")
    print()

    t0 = time.time()
    print("Loading v2 corpus...")
    long_df = collect_all_years(Path(args.results_dir), args.years)
    print(f"  {len(long_df):,} total checkpoint rows "
           f"({time.time() - t0:.1f}s)")

    print("\nBuilding matched cohort...")
    t1 = time.time()
    matched = build_matched_cohort(long_df)
    print(f"  {len(matched):,} matched-cohort rows "
           f"({time.time() - t1:.1f}s)")
    matched_path = out_dir / "matched_cohort_long.parquet"
    matched.to_parquet(matched_path, index=False)
    print(f"  Saved: {matched_path}")

    print("\nBuilding descriptive table...")
    t1 = time.time()
    desc = build_descriptive_table(matched)
    print(f"  {len(desc):,} (T_d × stratum × endpoint) rows "
           f"({time.time() - t1:.1f}s)")
    desc_path = out_dir / "descriptive_table.parquet"
    desc.to_parquet(desc_path, index=False)
    print(f"  Saved: {desc_path}")

    print("\nWriting markdown report...")
    report_path = out_dir / "REPORT.md"
    write_markdown_report(desc, matched, report_path)
    print(f"  Saved: {report_path}")

    print(f"\nDone in {time.time() - t0:.1f}s")
    print(f"\n  Report: {report_path}")


if __name__ == "__main__":
    main()
