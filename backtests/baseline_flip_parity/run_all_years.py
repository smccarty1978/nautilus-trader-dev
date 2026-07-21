"""Run baseline flip-parity NT backtest for all years 2020-2026.
Supports NQ or ES, with custom stall protection parameters.
3 parallel processes.
"""
from __future__ import annotations
import argparse, os, sys, time, subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).parent.parent.parent
RUNNER = "backtests/baseline_flip_parity/run_backtest.py"
PARALLEL = 3


def run_one(year, product, extra_args):
    t0 = time.time()
    suffix = None
    if "--suffix" in extra_args:
        idx = extra_args.index("--suffix")
        suffix = extra_args[idx + 1]
        
    if suffix is None:
        if "--use-trailing-stop" in extra_args:
            tp = 1.0
            sl = 1.0
            if "--tp-atr" in extra_args:
                tp = extra_args[extra_args.index("--tp-atr") + 1]
            if "--sl-atr" in extra_args:
                sl = extra_args[extra_args.index("--sl-atr") + 1]
            suffix = f"_trail_tp{tp}_sl{sl}"
        else:
            suffix = "_stall" if "--use-stall-protection" in extra_args else "_base"
        if "--trade-side" in extra_args:
            idx = extra_args.index("--trade-side")
            side = extra_args[idx + 1]
            if side != "both":
                suffix += f"_{side}"
    out_dir = (PROJECT_ROOT / "backtests/baseline_flip_parity/results"
               / f"{product.lower()}_live_{year}{suffix}")
    out_dir.mkdir(parents=True, exist_ok=True)

    log_path = out_dir / "run.log"
    
    cmd = [sys.executable, RUNNER, "--year", str(year), "--product", product] + extra_args
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        r = subprocess.run(cmd, cwd=str(PROJECT_ROOT),
                           stdout=f, stderr=subprocess.STDOUT)
    return year, r.returncode == 0, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", choices=["NQ", "ES"], default="NQ")
    ap.add_argument("--years", default="2020,2021,2022,2023,2024,2025,2026")
    
    # Stall protection and trailing stop arguments
    ap.add_argument("--use-stall-protection", action="store_true", default=False)
    ap.add_argument("--gate-atr", type=float, default=0.5)
    ap.add_argument("--stall-thresh", type=int, default=3)
    ap.add_argument("--ma-period", type=int, default=9)
    ap.add_argument("--ma-type", choices=["SMA", "EMA"], default="SMA")
    ap.add_argument("--trade-side", choices=["both", "long", "short"], default="both")
    ap.add_argument("--entry-type", choices=["flip", "random"], default="flip")
    ap.add_argument("--entry-prob", type=float, default=0.040)
    ap.add_argument("--sl-atr", type=float, default=1.0)
    ap.add_argument("--tp-atr", type=float, default=1.0)
    ap.add_argument("--use-trailing-stop", action="store_true", default=False)
    ap.add_argument("--trail-distance-atr", type=float, default=0.25)
    ap.add_argument("--be-trigger-atr", type=float, default=0.25)
    ap.add_argument("--be-level-atr", type=float, default=0.25)
    ap.add_argument("--suffix", default=None, help="override default results folder suffix")
    
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(",")]
    
    extra_args = []
    if args.use_stall_protection:
        extra_args.append("--use-stall-protection")
    extra_args.extend(["--gate-atr", str(args.gate_atr)])
    extra_args.extend(["--stall-thresh", str(args.stall_thresh)])
    extra_args.extend(["--ma-period", str(args.ma_period)])
    extra_args.extend(["--ma-type", args.ma_type])
    extra_args.extend(["--trade-side", args.trade_side])
    extra_args.extend(["--entry-type", args.entry_type])
    extra_args.extend(["--entry-prob", str(args.entry_prob)])
    extra_args.extend(["--sl-atr", str(args.sl_atr)])
    extra_args.extend(["--tp-atr", str(args.tp_atr)])
    if args.use_trailing_stop:
        extra_args.append("--use-trailing-stop")
    extra_args.extend(["--trail-distance-atr", str(args.trail_distance_atr)])
    extra_args.extend(["--be-trigger-atr", str(args.be_trigger_atr)])
    extra_args.extend(["--be-level-atr", str(args.be_level_atr)])

    if args.suffix is not None:
        extra_args.extend(["--suffix", args.suffix])
    
    print(f"Running {len(years)} NT baseline parity sweeps for {args.product}, "
          f"{PARALLEL} parallel")
    print(f"Extra args: {extra_args}")
    
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=PARALLEL) as ex:
        futs = {ex.submit(run_one, y, args.product, extra_args): y for y in years}
        for fut in as_completed(futs):
            y, ok, sec = fut.result()
            tag = "OK" if ok else "FAIL"
            print(f"  {tag}  {args.product} year {y}  ({sec:.0f}s)")
    print(f"All done in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
