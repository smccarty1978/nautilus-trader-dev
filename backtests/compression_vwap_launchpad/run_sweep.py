"""EXCURSION_CAP robustness sweep driver.

Runs (year, cap) combinations in parallel processes (max N concurrent),
each calling run_backtest.py with --excursion-cap and --out-tag so
results don't clobber the baseline.  Window fixed at 30 1m bars for
this sweep.

Output:
  backtests/compression_vwap_launchpad/results/sweep/cap_<X>/live_<year>/
    trades.parquet

After all runs complete, aggregate_sweep() reads every parquet,
computes the same PnL math the user verified ($5 RT comm, 1-tick
stop slip), and prints a 5x7 grid plus totals.
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
RUNNER = "backtests/compression_vwap_launchpad/run_backtest.py"

# Default sweep grid: ±20% and ±10% around baseline 22.0
CAPS = [17.6, 19.8, 22.0, 24.2, 26.4]
YEARS = list(range(2020, 2027))


def _tag(cap: float) -> str:
    return f"cap_{cap:.1f}".replace(".", "p")


def run_one(year: int, cap: float, log_dir: Path):
    """Spawn one backtest subprocess.  Returns (year, cap, ok, sec)."""
    t0 = time.time()
    tag = _tag(cap)
    log_path = log_dir / f"{tag}_{year}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, RUNNER,
        "--year", str(year),
        "--excursion-cap", str(cap),
        "--out-tag", tag,
    ]
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        r = subprocess.run(cmd, cwd=str(PROJECT_ROOT),
                           stdout=f, stderr=subprocess.STDOUT)
    return year, cap, (r.returncode == 0), time.time() - t0


def aggregate(out_root: Path):
    """Read every sweep trades.parquet and report a grid."""
    NQ_MULT = 20.0
    COMM = 5.0
    TICK = 0.25
    rows = []
    for cap in CAPS:
        tag = _tag(cap)
        for y in YEARS:
            p = out_root / "sweep" / tag / f"live_{y}" / "trades.parquet"
            if not p.exists():
                rows.append({"cap": cap, "year": y, "n": 0,
                             "pnl": 0.0, "t1": float("nan"),
                             "t2": float("nan")})
                continue
            df = pd.read_parquet(p)
            if len(df) == 0:
                rows.append({"cap": cap, "year": y, "n": 0,
                             "pnl": 0.0, "t1": float("nan"),
                             "t2": float("nan")})
                continue
            def pnl_row(r):
                a = r.entry_atr
                if r.exit_reason == "T2":
                    return (3 * a) * NQ_MULT - 2 * COMM
                if r.exit_reason == "SL_after_T1":
                    return (a - TICK) * NQ_MULT - 2 * COMM
                if r.exit_reason == "SL":
                    return (-2 * (a + TICK)) * NQ_MULT - 2 * COMM
                return -2 * COMM
            df["pnl"] = df.apply(pnl_row, axis=1)
            rows.append({
                "cap": cap, "year": y, "n": len(df),
                "pnl": df["pnl"].sum(),
                "t1": df["t1_filled"].mean(),
                "t2": (df["exit_reason"] == "T2").mean(),
            })
    agg = pd.DataFrame(rows)
    print(f"\n{'='*78}\nEXCURSION_CAP SWEEP — PnL grid (year x cap)"
          f"\n{'='*78}")
    # n trades grid
    print(f"\nTrades (n):")
    print(agg.pivot(index="year", columns="cap", values="n")
              .to_string(float_format=lambda x: f"{x:.0f}"))
    print(f"\nPnL ($):")
    print(agg.pivot(index="year", columns="cap", values="pnl")
              .to_string(float_format=lambda x: f"{x:,.0f}"))
    # totals per cap
    tot = agg.groupby("cap").agg(
        n=("n", "sum"), pnl=("pnl", "sum"),
        years_pos=("pnl", lambda s: (s > 0).sum()))
    tot["ev"] = tot["pnl"] / tot["n"].replace(0, 1)
    print(f"\nTotals per cap (7-year sum):")
    print(tot.to_string(float_format=lambda x: f"{x:,.2f}"))
    out_csv = out_root / "sweep" / "summary.csv"
    agg.to_csv(out_csv, index=False)
    print(f"\nsaved {out_csv}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--aggregate-only", action="store_true",
                    help="skip runs, just aggregate existing results")
    args = ap.parse_args()
    out_root = PROJECT_ROOT / "backtests" / "compression_vwap_launchpad" / "results"
    log_dir = out_root / "sweep" / "logs"

    if not args.aggregate_only:
        tasks = [(y, c) for c in CAPS for y in YEARS]
        print(f"Sweep: {len(tasks)} runs, max {args.parallel} parallel")
        print(f"  caps:  {CAPS}")
        print(f"  years: {YEARS}")
        t0 = time.time()
        completed = 0
        with ProcessPoolExecutor(max_workers=args.parallel) as ex:
            futs = {ex.submit(run_one, y, c, log_dir): (y, c)
                    for (y, c) in tasks}
            for fut in as_completed(futs):
                y, c, ok, sec = fut.result()
                completed += 1
                tag = "OK" if ok else "FAIL"
                print(f"  [{completed:>2}/{len(tasks)}] {tag} "
                      f"cap={c:.1f} year={y}  ({sec:.0f}s)")
        print(f"\nAll runs done in {(time.time()-t0)/60:.1f} min")

    aggregate(out_root)


if __name__ == "__main__":
    main()
