"""Orchestrate 14 live NT runs: 7 candidates × 2 OOS years.

For each (year, candidate):
  - Use the saved model + feature_list + threshold
  - Run LiveBracketStrategy on the OOS year's bar data
  - Save positions + strategy_trades for post-processing

2024: full year NT backtest (~5 min each × 7 = 35 min)
2026: YTD (Jan-April 15) backtest (~3 min each × 7 = 21 min)
Total: ~55-60 min
"""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ITERATIONS = ["full", "top_50", "top_35", "top_25", "top_20",
              "top_15", "top_10"]
YEARS = [2024, 2026]

V3_ROOT = Path("studies/bracket_entry_v3_fullpop/results")
NT_ROOT = V3_ROOT / "nt_runs"
NT_ROOT.mkdir(parents=True, exist_ok=True)


def run_one(year: int, iteration: str) -> bool:
    model_dir = V3_ROOT / f"models_oos_{year}" / iteration
    out_dir = NT_ROOT / f"{year}_{iteration}"
    if (out_dir / "positions.parquet").exists():
        print(f"  [skip] {year}/{iteration} — already exists")
        return True
    out_dir.mkdir(parents=True, exist_ok=True)

    if year == 2024:
        start, end = "2024-01-01", "2024-12-31 23:59:59"
    elif year == 2026:
        start, end = "2026-01-01", "2026-04-15 23:59:59"
    else:
        raise ValueError(year)

    cmd = [
        sys.executable,
        "studies/bracket_entry_v2/validation_2026/run_2026_live.py",
        "--model", str(model_dir / "model.txt"),
        "--features", str(model_dir / "feature_list.json"),
        "--threshold-file", str(model_dir / "threshold.json"),
        "--out-dir", str(out_dir),
        "--start", start,
        "--end", end,
    ]
    print(f"  Running {year}/{iteration}...")
    t0 = time.time()
    rc = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    if rc.returncode != 0:
        print(f"    FAILED after {elapsed:.0f}s")
        print(f"    stderr (last 500): {rc.stderr[-500:]}")
        return False
    # Show diag line
    for line in rc.stdout.strip().splitlines()[-6:]:
        print(f"    {line}")
    print(f"    OK in {elapsed:.0f}s")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=YEARS)
    ap.add_argument("--iterations", nargs="+", default=ITERATIONS)
    args = ap.parse_args()

    t_total = time.time()
    print(f"V3 LIVE SWEEP — {len(args.years)} years × "
           f"{len(args.iterations)} iterations = "
           f"{len(args.years)*len(args.iterations)} runs")
    print()

    for year in args.years:
        for iteration in args.iterations:
            print(f"\n===== {year} / {iteration} =====")
            run_one(year, iteration)

    print(f"\nTotal elapsed: {(time.time()-t_total)/60:.1f} min")


if __name__ == "__main__":
    main()
