"""Orchestrate live NT runs for the failure-filter sweep.

For each OOS year × each filter level:
  - Compute threshold (val percentile)
  - Run LiveBracketStrategy in `exclude` mode (skip when score >= threshold)
  - Save positions + strategy_trades

Filter levels:
  baseline   — trade everything (threshold = 1.0, always under)
  excl_top5  — skip top-5%-by-failure-score   (threshold = val p95)
  excl_top10 — skip top-10%                    (threshold = val p90)
  excl_top20 — skip top-20%                    (threshold = val p80)
  excl_top30 — skip top-30%                    (threshold = val p70)

Total: 5 levels × 2 years = 10 NT runs ≈ ~80 min.
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path("studies/failure_filter_v1/results")
NT_ROOT = ROOT / "nt_runs"
NT_ROOT.mkdir(parents=True, exist_ok=True)
THR_DIR = ROOT / "thresholds"
THR_DIR.mkdir(parents=True, exist_ok=True)

YEARS = [2024, 2026]
LEVELS = [
    ("baseline",   None),   # trade everything
    ("excl_top10", "p90"),
]
# Reduced scope per user direction (2026-04-24): 2 levels × 2 years = 4 runs.
# If excl_top10 beats baseline materially in both years, expand to top5/20/30.


def make_threshold_file(year: int, level: str,
                          pct_key: str | None) -> Path:
    """Write a threshold.json for the live runner."""
    if pct_key is None:
        # Baseline: trade everything — threshold higher than any score
        thr = 1.0
    else:
        with open(ROOT / f"models_oos_{year}" / "val_percentiles.json") as f:
            pcts = json.load(f)
        thr = float(pcts[pct_key])
    path = THR_DIR / f"thr_{year}_{level}.json"
    with open(path, "w") as f:
        json.dump({"threshold_top10": thr,
                    "level": level,
                    "from_val_percentile": pct_key,
                    "year": year}, f, indent=2)
    return path


def run_one(year: int, level: str, pct_key: str | None) -> bool:
    out_dir = NT_ROOT / f"{year}_{level}"
    if (out_dir / "positions.parquet").exists():
        print(f"  [skip] {year}/{level} — exists")
        return True
    out_dir.mkdir(parents=True, exist_ok=True)

    model_dir = ROOT / f"models_oos_{year}"
    thr_file = make_threshold_file(year, level, pct_key)

    if year == 2024:
        start, end = "2024-01-01", "2024-12-31 23:59:59"
    else:
        start, end = "2026-01-01", "2026-04-15 23:59:59"

    cmd = [
        sys.executable,
        "studies/bracket_entry_v2/validation_2026/run_2026_live.py",
        "--model", str(model_dir / "model_full.txt"),
        "--features", str(model_dir / "feature_list.json"),
        "--threshold-file", str(thr_file),
        "--mode", "exclude",
        "--out-dir", str(out_dir),
        "--start", start,
        "--end", end,
    ]
    print(f"  Running {year}/{level} (thr from {pct_key})...")
    t0 = time.time()
    rc = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    if rc.returncode != 0:
        print(f"    FAILED in {elapsed:.0f}s")
        print(f"    stderr (last 500): {rc.stderr[-500:]}")
        return False
    for line in rc.stdout.strip().splitlines()[-6:]:
        print(f"    {line}")
    print(f"    OK in {elapsed:.0f}s")
    return True


def main():
    t_total = time.time()
    print(f"FAILURE-FILTER SWEEP — "
           f"{len(YEARS)} years × {len(LEVELS)} levels = "
           f"{len(YEARS)*len(LEVELS)} runs")
    for year in YEARS:
        for level, pct_key in LEVELS:
            print(f"\n===== {year} / {level} =====")
            run_one(year, level, pct_key)
    print(f"\nTotal: {(time.time()-t_total)/60:.1f} min")


if __name__ == "__main__":
    main()
