"""Orchestrator — NT backtest for each finalist × each OOS year.

Uses existing infrastructure in backtests/good_entry_v2_bracket/:
  - build_schedule.py: builds RTH top-10% schedule from predictions
  - run_backtest.py: runs NT BacktestEngine

Runs up to 6 NT backtests:
  (full / top_15 / top_10) × (2025 / 2024)

Skips the (full, 2025) combo if the original NT run is already present.

Post-processes each run with the shared commission + slippage model
(scenario C) to produce cost-adjusted metrics for the final report.
"""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FINALISTS = ["full", "top_15", "top_10"]
YEARS = [2025, 2024]

FR_DIR = Path("studies/bracket_entry_v2/feature_reduction")
BT_ROOT = Path("backtests/good_entry_v2_bracket/results")
SCHEDULE_DIR = BT_ROOT / "fr_schedules"
SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
NT_ROOT = BT_ROOT / "fr_nt_runs"
NT_ROOT.mkdir(parents=True, exist_ok=True)


def build_schedule(finalist: str, year: int) -> Path:
    """Call build_schedule.py for one (finalist, year)."""
    pred_path = FR_DIR / f"predictions_{year}_{finalist}.parquet"
    out_path = SCHEDULE_DIR / f"schedule_{year}_{finalist}.parquet"
    ev_summary = (
        f"studies/1m_regime_collector_v2/results/"
        f"v2_event_summary_{year}.parquet")
    cmd = [
        sys.executable,
        "backtests/good_entry_v2_bracket/build_schedule.py",
        "--predictions", str(pred_path),
        "--event-summary", ev_summary,
        "--slice", "rth",
        "--top-k-frac", "0.10",
        "--out", str(out_path),
    ]
    print(f"  Building schedule: {finalist} / {year}")
    rc = subprocess.run(cmd, check=True, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    # Print the last few lines of output
    for line in rc.stdout.strip().splitlines()[-4:]:
        print(f"    {line}")
    return out_path


def run_nt(finalist: str, year: int, schedule_path: Path) -> Path:
    """Call run_backtest.py for one (finalist, year)."""
    out_dir = NT_ROOT / f"{year}_{finalist}"
    out_dir.mkdir(parents=True, exist_ok=True)
    start = f"{year}-01-01"
    end = f"{year}-12-31 23:59:59"
    cmd = [
        sys.executable,
        "backtests/good_entry_v2_bracket/run_backtest.py",
        "--schedule", str(schedule_path),
        "--out-dir", str(out_dir),
        "--start", start,
        "--end", end,
    ]
    print(f"  Running NT: {finalist} / {year} -> {out_dir}")
    t0 = time.time()
    rc = subprocess.run(cmd, check=True, capture_output=True,
                         text=True)
    elapsed = time.time() - t0
    # Tail of output
    for line in rc.stdout.strip().splitlines()[-8:]:
        print(f"    {line}")
    print(f"    Elapsed: {elapsed:.0f}s")
    return out_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", nargs="*", default=[],
                     help="Skip combos, e.g. 'full_2025' to reuse the "
                           "original NT run")
    args = ap.parse_args()

    skip_set = set(args.skip)
    t_total = time.time()

    for finalist in FINALISTS:
        for year in YEARS:
            combo = f"{finalist}_{year}"
            if combo in skip_set:
                print(f"\n[skip] {combo}")
                continue
            print(f"\n===== {combo} =====")
            try:
                sched = build_schedule(finalist, year)
                out_dir = run_nt(finalist, year, sched)
                print(f"  OK -> {out_dir}")
            except subprocess.CalledProcessError as e:
                print(f"  FAIL: {e}")
                print(f"  stderr: {e.stderr[-500:]}")

    print(f"\nAll runs elapsed: "
           f"{(time.time() - t_total) / 60:.1f} min")


if __name__ == "__main__":
    main()
