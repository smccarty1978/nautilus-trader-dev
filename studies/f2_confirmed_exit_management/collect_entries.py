"""Phase 1 (part 1): run F2_CONFIRMED through NT BacktestEngine for
every year needed by the study's chronological splits, writing raw
per-year NT output to _work/nt_raw/<year>/ (trades.parquet,
checkpoints.parquet, diag.json). This is CACHE, not a final
deliverable -- build_atlas.py reads from here to construct the labeled
checkpoint atlas in results/.

Years: 2021-2026 covers train(2021-2024) + val/dev-test(2025) +
reserved eval (2026, through the catalog's last available date).
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd

from studies._shared_exit_mgmt.nt_runner import run_year, run_period
from studies.f2_confirmed_exit_management.strategy import (
    F2ConfirmedStrategy, F2ConfirmedConfig,
)

STUDY_ROOT = Path(__file__).parent
WORK_ROOT = STUDY_ROOT / "_work" / "nt_raw"

YEARS = [2021, 2022, 2023, 2024, 2025]
YEAR_2026_END = pd.Timestamp("2026-04-30 23:59:59", tz="UTC")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=None,
                        help="Subset of years to run (default: all)")
    args = ap.parse_args()

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {}

    years_to_run = args.years if args.years else YEARS + [2026]
    for year in years_to_run:
        out_dir = WORK_ROOT / str(year)
        print(f"\n[{year}] F2_CONFIRMED collection -> {out_dir}", flush=True)
        t0 = time.time()
        if year == 2026:
            load_start = (pd.Timestamp("2026-01-01", tz="UTC")
                             - pd.Timedelta(days=5))
            res = run_period(F2ConfirmedStrategy, F2ConfirmedConfig, {},
                                 load_start, YEAR_2026_END, out_dir)
        else:
            res = run_year(F2ConfirmedStrategy, F2ConfirmedConfig, {},
                               year, out_dir)
        elapsed = time.time() - t0
        print(f"  bars: {res['n_bars_1s']:,} 1s / {res['n_bars_1m']:,} 1m, "
                 f"total {elapsed:.0f}s (load {res['load_elapsed_s']:.0f}s, "
                 f"run {res['run_elapsed_s']:.0f}s)")
        print(f"  diag: {res['diag']}")
        manifest[str(year)] = {
            "n_bars_1s": res["n_bars_1s"], "n_bars_1m": res["n_bars_1m"],
            "elapsed_s": elapsed, "diag": res["diag"],
        }
        with open(WORK_ROOT / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

    print("\nAll years complete. Manifest written to "
             f"{WORK_ROOT / 'manifest.json'}")


if __name__ == "__main__":
    main()
