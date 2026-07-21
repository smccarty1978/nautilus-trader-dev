"""Overnight runner: 6-year collection + per-year parity gate.

For each year 2020..2025:
  1. Run the v2 collector (writes features/labels/event-summary parquet
     plus QA log to results/).
  2. Run the parity harness against that year's output (4-gate check
     at 1000-sample stratified RTH/ETH coverage). Determinism is NOT
     re-checked per year — we proved it on the smoke run, and each
     year's collector pass is the same deterministic code path.
  3. If parity FAILS, halt the chain and exit non-zero so the morning
     review surfaces the regression instead of compounding it.

Per-year wall-clock: ~12 min collection + ~10s parity = ~12 min.
Full chain: ~70-75 min. Output to console plus per-year log files
under results/logs/ so the morning recap is one ls + cat away.

Usage:
    python studies/1m_regime_collector_v2/run_6year_overnight.py

    # Subset of years for testing the script itself:
    python studies/1m_regime_collector_v2/run_6year_overnight.py \\
        --years 2024 2025
"""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS_DIR = Path("studies/1m_regime_collector_v2/results")
PARITY_DIR = Path("studies/1m_regime_collector_v2/parity")
LOG_DIR = RESULTS_DIR / "logs"
SUMMARY_PATH = RESULTS_DIR / "6year_run_summary.md"


def log_both(line: str, fh) -> None:
    """Write to console and the run-summary file handle."""
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def run_step(cmd: list[str], log_path: Path) -> int:
    """Run subprocess, tee output to log file + console."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            f.write(line)
        proc.wait()
        return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int,
                     default=[2020, 2021, 2022, 2023, 2024, 2025],
                     help="Years to process (default: 2020..2025)")
    ap.add_argument("--catalog", default="data/catalog/NQ_2020_2025")
    ap.add_argument("--sample-size", type=int, default=1000,
                     help="Parity-harness sample size per year")
    ap.add_argument("--halt-on-parity-fail", action="store_true",
                     default=True,
                     help="Stop the chain on first parity failure (default)")
    ap.add_argument("--continue-on-parity-fail",
                     dest="halt_on_parity_fail",
                     action="store_false",
                     help="Continue all years even if parity fails — "
                           "useful for batch diagnostic runs")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PARITY_DIR.mkdir(parents=True, exist_ok=True)

    chain_start = time.time()
    chain_started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    summary_rows: list[dict] = []
    halt_year: int | None = None

    with open(SUMMARY_PATH, "w", encoding="utf-8") as sumf:
        log_both("=" * 72, sumf)
        log_both(f"v2 COLLECTOR — 6-YEAR OVERNIGHT RUN", sumf)
        log_both(f"  Started:  {chain_started_at}", sumf)
        log_both(f"  Years:    {args.years}", sumf)
        log_both(f"  Catalog:  {args.catalog}", sumf)
        log_both(f"  Halt on parity fail: {args.halt_on_parity_fail}",
                  sumf)
        log_both("=" * 72, sumf)

        for year in args.years:
            year_start = time.time()
            log_both("", sumf)
            log_both("-" * 72, sumf)
            log_both(
                f"YEAR {year} | start "
                f"{datetime.now().strftime('%H:%M:%S')}", sumf)
            log_both("-" * 72, sumf)

            # === Step 1: Collection ===
            collect_log = LOG_DIR / f"collect_{year}.log"
            log_both(f"  [1/2] Collecting year {year}...", sumf)
            log_both(f"        Output → {collect_log}", sumf)
            t0 = time.time()
            rc = run_step(
                [sys.executable,
                 "studies/1m_regime_collector_v2/run_collection.py",
                 "--year", str(year),
                 "--catalog", args.catalog],
                collect_log,
            )
            collect_elapsed = time.time() - t0
            if rc != 0:
                log_both(
                    f"  [1/2] COLLECTOR FAILED (exit={rc}) after "
                    f"{collect_elapsed:.0f}s — halting chain.", sumf)
                summary_rows.append({
                    "year": year, "status": "FAIL",
                    "stage": "collector", "exit_code": rc,
                    "elapsed_s": collect_elapsed,
                })
                halt_year = year
                break
            log_both(
                f"  [1/2] Collection done in "
                f"{collect_elapsed/60:.1f} min", sumf)

            # === Step 2: Parity ===
            features_path = (
                RESULTS_DIR / f"v2_feature_snapshots_{year}.parquet")
            labels_path = (
                RESULTS_DIR / f"v2_outcome_labels_{year}.parquet")
            if not features_path.exists() or not labels_path.exists():
                log_both(
                    f"  [2/2] Parity SKIPPED — outputs missing "
                    f"({features_path}). Likely empty year.", sumf)
                summary_rows.append({
                    "year": year, "status": "PARTIAL",
                    "stage": "parity_skipped",
                    "elapsed_s": time.time() - year_start,
                })
                continue

            parity_log = LOG_DIR / f"parity_{year}.log"
            parity_report = PARITY_DIR / f"parity_report_{year}.md"
            log_both(f"  [2/2] Parity check (n={args.sample_size})...",
                      sumf)
            log_both(f"        Output → {parity_log}", sumf)
            log_both(f"        Report → {parity_report}", sumf)
            t0 = time.time()
            rc = run_step(
                [sys.executable,
                 "studies/1m_regime_collector_v2/parity/run_parity.py",
                 "--features-path", str(features_path),
                 "--labels-path", str(labels_path),
                 "--catalog", args.catalog,
                 "--sample-size", str(args.sample_size),
                 "--out-report", str(parity_report)],
                parity_log,
            )
            parity_elapsed = time.time() - t0
            year_elapsed = time.time() - year_start

            if rc != 0:
                log_both(
                    f"  [2/2] PARITY FAILED (exit={rc}) after "
                    f"{parity_elapsed:.0f}s.", sumf)
                summary_rows.append({
                    "year": year, "status": "FAIL",
                    "stage": "parity", "exit_code": rc,
                    "elapsed_s": year_elapsed,
                    "report": str(parity_report),
                })
                if args.halt_on_parity_fail:
                    log_both(
                        "        Halting chain (use "
                        "--continue-on-parity-fail to override).",
                        sumf)
                    halt_year = year
                    break
                log_both("        Continuing per --continue-on-parity-fail",
                          sumf)
                continue

            log_both(
                f"  [2/2] Parity PASS in {parity_elapsed:.0f}s", sumf)
            log_both(
                f"  YEAR {year} TOTAL: {year_elapsed/60:.1f} min",
                sumf)
            summary_rows.append({
                "year": year, "status": "PASS",
                "stage": "complete",
                "collect_s": collect_elapsed,
                "parity_s": parity_elapsed,
                "elapsed_s": year_elapsed,
                "report": str(parity_report),
            })

        # === Final summary ===
        chain_elapsed = time.time() - chain_start
        log_both("", sumf)
        log_both("=" * 72, sumf)
        log_both(
            f"CHAIN COMPLETE in {chain_elapsed/60:.1f} min", sumf)
        log_both(
            f"  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            sumf)
        log_both("=" * 72, sumf)
        log_both(
            f"  {'Year':<6} {'Status':<8} {'Stage':<20} {'Time':<10}",
            sumf)
        log_both("  " + "-" * 50, sumf)
        for row in summary_rows:
            t = (f"{row.get('elapsed_s', 0)/60:.1f} min"
                  if row.get('elapsed_s') else "")
            log_both(
                f"  {row['year']:<6} {row['status']:<8} "
                f"{row['stage']:<20} {t:<10}", sumf)

        all_pass = all(r["status"] == "PASS" for r in summary_rows)
        if all_pass and len(summary_rows) == len(args.years):
            log_both("", sumf)
            log_both(
                "  OVERALL: ALL YEARS PASS — outputs in "
                "studies/1m_regime_collector_v2/results/", sumf)
            log_both(
                "  Per-year parity reports in "
                "studies/1m_regime_collector_v2/parity/", sumf)
            return 0
        else:
            log_both("", sumf)
            failed = [r["year"] for r in summary_rows
                       if r["status"] == "FAIL"]
            log_both(
                f"  OVERALL: FAIL — {len(failed)} year(s) failed: "
                f"{failed}",
                sumf)
            if halt_year is not None:
                log_both(
                    f"  Chain halted at year {halt_year}. "
                    f"Years not attempted: "
                    f"{[y for y in args.years if y > halt_year]}",
                    sumf)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
