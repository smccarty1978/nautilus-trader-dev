"""Phase 1 orchestrator for the good-entry study.

Pipeline:
  1. Load v2 corpus + feature contract
  2. Build cohort with good_entry_300s label
  3. Compute Phase 1 descriptive table
  4. Write markdown report with verdict

Usage:
    python studies/good_entry_v2/run_phase1.py
    python studies/good_entry_v2/run_phase1.py --years 2024 2025
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
from collect import collect_all_years  # noqa
from analyze_phase1 import build_phase1_table, write_phase1_report  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int,
                     default=[2020, 2021, 2022, 2023, 2024, 2025])
    ap.add_argument("--results-dir",
                     default="studies/1m_regime_collector_v2/results")
    ap.add_argument("--contract",
                     default="models/ml_5m_flip/feature_contract_v2.json")
    ap.add_argument("--out-dir",
                     default="studies/good_entry_v2/results")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("GOOD ENTRY v2 — PHASE 1 (descriptive)")
    print("=" * 72)
    print(f"  Years:       {args.years}")
    print(f"  Contract:    {args.contract}")
    print(f"  V2 results:  {args.results_dir}")
    print(f"  Output:      {out_dir}")
    print()

    t0 = time.time()
    print("Loading v2 corpus + computing label...")
    cohort = collect_all_years(
        Path(args.results_dir), Path(args.contract), args.years)
    print(f"  {len(cohort):,} cohort rows "
           f"({time.time() - t0:.1f}s)")

    cohort_path = out_dir / "cohort_long.parquet"
    cohort.to_parquet(cohort_path, index=False)
    print(f"  Saved: {cohort_path}")

    print("\nBuilding Phase 1 descriptive table...")
    t1 = time.time()
    desc = build_phase1_table(cohort)
    print(f"  {len(desc):,} (T × stratum) rows "
           f"({time.time() - t1:.1f}s)")

    desc_path = out_dir / "phase1_descriptive.parquet"
    desc.to_parquet(desc_path, index=False)
    print(f"  Saved: {desc_path}")

    report_path = out_dir / "PHASE1_REPORT.md"
    write_phase1_report(desc, cohort, report_path)
    print(f"  Saved: {report_path}")

    print(f"\nDone in {time.time() - t0:.1f}s")
    print(f"\n  Report: {report_path}")


if __name__ == "__main__":
    main()
