"""Phase 6 driver for ALL_FLIPS: run every non-E0 policy in the grid
(E1, S1-S7 x {checkpoint, mfe} = 15 configs) over 2025 (full year,
sliced to dev_test = Mar-Dec at analysis time) and 2026 (through the
catalog's last available date, = the reserved_eval period in full).

E0 needs NO new run: it is identical to the already-collected Phase 1
baseline (entries + hold-to-opposite-flip exits), just filtered to the
dev_test/reserved_eval splits at analysis time.

Same year-boundary convention (5-day warmup) as Phase 1's
collect_entries.py, so entries in the warmup window are naturally
excluded when Phase 7 filters by split (entry_ts) exactly as Phase 3
did -- consistent with how the baseline data was collected.
"""
from __future__ import annotations
import argparse, pickle, sys, time
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd

from studies._shared_exit_mgmt.nt_runner import run_period_chunked
from studies._shared_exit_mgmt.stop_policy import StopPolicyEngine
from studies._shared_exit_mgmt.policy_grid import POLICY_GRID
from studies._shared_exit_mgmt.w0_features import W0_FEATURES
from studies.all_flips_exit_management.policy_strategy import (
    AllFlipsPolicyStrategy, AllFlipsPolicyConfig,
)

STUDY_ROOT = Path(__file__).parent
RESULTS_ROOT = STUDY_ROOT / "results"
WORK_ROOT = STUDY_ROOT / "_work" / "phase6_raw"
YEAR_2026_END = pd.Timestamp("2026-04-30 23:59:59", tz="UTC")


def load_engine() -> StopPolicyEngine:
    with open(RESULTS_ROOT / "w0_model.pkl", "rb") as f:
        bundle = pickle.load(f)
    cond_table = pd.read_parquet(
        RESULTS_ROOT / "conditional_recovery_mae_tables.parquet")
    return StopPolicyEngine(
        model=bundle["model"], feature_cols=W0_FEATURES,
        decile_edges=bundle["decile_edges"], cond_table=cond_table)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policies", nargs="*", default=None,
                        help="Subset of policy names (default: all)")
    ap.add_argument("--years", type=int, nargs="*", default=[2025, 2026])
    args = ap.parse_args()

    engine = load_engine()
    policy_names = args.policies if args.policies else list(POLICY_GRID.keys())
    WORK_ROOT.mkdir(parents=True, exist_ok=True)

    for name in policy_names:
        cfg = POLICY_GRID[name]

        def post_init(strat, _cfg=cfg):
            strat.policy_engine = engine
            strat.policy_cfg = _cfg

        for year in args.years:
            out_dir = WORK_ROOT / name / str(year)
            if (out_dir / "trades.parquet").exists():
                print(f"\n[{name}][{year}] SKIP -- already completed "
                         f"({out_dir})", flush=True)
                continue
            print(f"\n[{name}][{year}] -> {out_dir}", flush=True)
            t0 = time.time()
            if year == 2026:
                load_start = pd.Timestamp("2026-01-01", tz="UTC")
                load_end = YEAR_2026_END
            else:
                load_start = pd.Timestamp(f"{year}-01-01", tz="UTC")
                load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
            res = run_period_chunked(
                AllFlipsPolicyStrategy, AllFlipsPolicyConfig, {},
                load_start, load_end, out_dir,
                strategy_post_init=post_init, chunk_months=1)
            elapsed = time.time() - t0
            print(f"  done in {elapsed:.0f}s ({res['n_chunks']} chunks), "
                     f"diag: {res['diag']}", flush=True)


if __name__ == "__main__":
    main()
