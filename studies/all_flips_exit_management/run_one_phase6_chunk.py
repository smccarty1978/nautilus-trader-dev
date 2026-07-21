"""Process exactly ONE outstanding (policy, year, chunk) combo, then
exit. Meant to be invoked repeatedly as a FRESH short-lived process
(e.g. from a bash `until` loop) -- unlike run_phase6_policies.py,
which runs the entire remaining grid within a single long-lived Python
process and was observed to keep getting killed on later chunks
(a standalone re-run of the exact same chunk that kept failing
in-process completed in 297s without issue, pointing at cumulative
process age/lifetime as the kill trigger, not per-chunk cost).

Exit codes: 0 = one chunk processed (or nothing was pending -- all
done), 1 = error.
"""
from __future__ import annotations
import pickle, sys, time
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd

from studies._shared_exit_mgmt.nt_runner import run_period
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
CHUNK_MONTHS = 1
WARMUP_DAYS = 5

POLICIES = ["S6_checkpoint", "S6_mfe", "S7_checkpoint", "S7_mfe"]
YEARS = [2025, 2026]


def load_engine() -> StopPolicyEngine:
    with open(RESULTS_ROOT / "w0_model.pkl", "rb") as f:
        bundle = pickle.load(f)
    cond_table = pd.read_parquet(
        RESULTS_ROOT / "conditional_recovery_mae_tables.parquet")
    return StopPolicyEngine(
        model=bundle["model"], feature_cols=W0_FEATURES,
        decile_edges=bundle["decile_edges"], cond_table=cond_table)


def chunk_bounds(year: int) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]:
    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    load_end = (YEAR_2026_END if year == 2026
                   else pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bounds = []
    cur = load_start
    i = 0
    while cur < load_end:
        chunk_end = min(cur + pd.DateOffset(months=CHUNK_MONTHS), load_end)
        bounds.append((i, cur, chunk_end))
        cur = chunk_end
        i += 1
    return bounds


def find_next_pending():
    """Returns (policy_name, year, chunk_i, chunk_start, chunk_end,
    chunk_dir, out_dir, all_bounds) for the first incomplete combo, or
    None if the whole reduced grid is done."""
    for name in POLICIES:
        for year in YEARS:
            out_dir = WORK_ROOT / name / str(year)
            if (out_dir / "trades.parquet").exists():
                continue
            bounds = chunk_bounds(year)
            for i, chunk_start, chunk_end in bounds:
                chunk_dir = out_dir / "_chunks" / str(i)
                if ((chunk_dir / "trades.parquet").exists()
                        or (chunk_dir / "_empty.marker").exists()):
                    continue
                return (name, year, i, chunk_start, chunk_end,
                            chunk_dir, out_dir, bounds)
            # All chunks for this policy/year are done -- concatenate.
            _concatenate(out_dir, bounds)
    return None


def _concatenate(out_dir: Path, bounds):
    frames = []
    for i, _, _ in bounds:
        p = out_dir / "_chunks" / str(i) / "trades.parquet"
        if p.exists():
            frames.append(pd.read_parquet(p))
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined):
        combined = combined.sort_values("entry_ts").reset_index(drop=True)
        combined["trade_id"] = range(1, len(combined) + 1)
    combined.to_parquet(out_dir / "trades.parquet", index=False)
    print(f"  CONCATENATED {out_dir} -- {len(combined)} trades from "
             f"{len(frames)} chunks", flush=True)


def main():
    pending = find_next_pending()
    if pending is None:
        print("ALL DONE -- nothing pending.", flush=True)
        return 0

    name, year, i, chunk_start, chunk_end, chunk_dir, out_dir, bounds = pending
    print(f"[{name}][{year}] chunk {i}/{len(bounds)-1} "
             f"[{chunk_start} -> {chunk_end}]", flush=True)

    engine = load_engine()
    cfg = POLICY_GRID[name]

    def post_init(strat):
        strat.policy_engine = engine
        strat.policy_cfg = cfg

    warmup_start = chunk_start - pd.Timedelta(days=WARMUP_DAYS)
    t0 = time.time()
    res = run_period(
        AllFlipsPolicyStrategy, AllFlipsPolicyConfig, {},
        warmup_start, chunk_end - pd.Timedelta(seconds=1), chunk_dir,
        strategy_post_init=post_init)
    elapsed = time.time() - t0
    print(f"  done in {elapsed:.0f}s, diag: {res['diag']}", flush=True)

    # Filter to this chunk's true (non-warmup) date range -- same fix
    # as run_period_chunked, required to avoid duplicate entries at
    # chunk boundaries (a chunk's own warmup causally re-generates
    # entries from the tail of the PREVIOUS chunk's true window).
    trades_p = chunk_dir / "trades.parquet"
    if trades_p.exists():
        df = pd.read_parquet(trades_p)
        mask = ((df["entry_ts"] >= chunk_start.value)
                    & (df["entry_ts"] < chunk_end.value))
        df = df[mask]
        if len(df):
            df.to_parquet(trades_p, index=False)
        else:
            trades_p.unlink()
    if not (chunk_dir / "trades.parquet").exists():
        (chunk_dir / "_empty.marker").write_text("no trades this chunk")

    return 0


if __name__ == "__main__":
    sys.exit(main())
