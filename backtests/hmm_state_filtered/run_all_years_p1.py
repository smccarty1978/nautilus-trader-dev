"""Run P1 (partial+BE) NT validation across all 7 years, 3 parallel."""
from __future__ import annotations
import argparse, os, sys, time, subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).parent.parent.parent
RUNNER = "backtests/hmm_state_filtered/run_backtest_p1.py"
PARALLEL = 3


def run_one(year, product, state_col, target_state, min_state_dur,
            entry_size, partial_atr, partial_size, be_after_partial,
            entry_anchor, state_col_5m, target_state_5m, anchor_5m):
    t0 = time.time()
    dur_suffix = f"_dur{min_state_dur}" if min_state_dur > 0 else ""
    p1_suffix = (f"_p1_e{entry_size}p{partial_size}@"
                  f"{partial_atr}".replace(".", "p")
                  + ("_BE" if be_after_partial else "_noBE"))
    anchor_suffix = f"_anc{entry_anchor}" if entry_anchor != "bar1_confirm" else ""
    m5_suffix = f"_m5_{state_col_5m}_s{target_state_5m}_{anchor_5m}" if state_col_5m else ""
    out_dir = (PROJECT_ROOT / "backtests/hmm_state_filtered/results"
               / f"{product.lower()}_{state_col}_s{target_state}"
                  f"{dur_suffix}{p1_suffix}{anchor_suffix}{m5_suffix}_{year}")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    cmd = [sys.executable, RUNNER, "--year", str(year),
           "--product", product,
           "--state-col", state_col,
           "--target-state", str(target_state),
           "--min-state-dur", str(min_state_dur),
           "--entry-size", str(entry_size),
           "--partial-atr", str(partial_atr),
           "--partial-size", str(partial_size),
           "--be-after-partial", str(int(be_after_partial)),
           "--entry-anchor", entry_anchor]
    if state_col_5m:
        cmd += ["--state-col-5m", state_col_5m,
                "--target-state-5m", str(target_state_5m),
                "--anchor-5m", anchor_5m]
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        r = subprocess.run(cmd, cwd=str(PROJECT_ROOT),
                           stdout=f, stderr=subprocess.STDOUT)
    return year, r.returncode == 0, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", choices=["NQ", "ES"], default="NQ")
    ap.add_argument("--state-col", default="hmm_4")
    ap.add_argument("--target-state", type=int, default=3)
    ap.add_argument("--min-state-dur", type=int, default=0)
    ap.add_argument("--entry-size", type=int, default=2)
    ap.add_argument("--partial-atr", type=float, default=1.0)
    ap.add_argument("--partial-size", type=int, default=1)
    ap.add_argument("--be-after-partial", type=int, default=1)
    ap.add_argument("--entry-anchor", default="bar1_confirm",
                    choices=["bar1_confirm", "bar1", "flip"])
    ap.add_argument("--years", default="2020,2021,2022,2023,2024,2025,2026")
    ap.add_argument("--state-col-5m", default="")
    ap.add_argument("--target-state-5m", type=int, default=-1)
    ap.add_argument("--anchor-5m", default="bar1", choices=["flip", "bar1"])
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(",")]

    m5_str = f" m5={args.state_col_5m}=={args.target_state_5m} ({args.anchor_5m})" if args.state_col_5m else ""
    print(f"P1 ({args.product}): {len(years)} years; "
          f"state={args.state_col}=={args.target_state} dur>={args.min_state_dur} "
          f"P1 e{args.entry_size}p{args.partial_size}@{args.partial_atr}ATR "
          f"BE={args.be_after_partial} anchor={args.entry_anchor}{m5_str}, "
          f"{PARALLEL} parallel")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=PARALLEL) as ex:
        futs = {ex.submit(run_one, y, args.product, args.state_col,
                          args.target_state, args.min_state_dur,
                          args.entry_size, args.partial_atr, args.partial_size,
                          bool(args.be_after_partial), args.entry_anchor,
                          args.state_col_5m,
                          args.target_state_5m, args.anchor_5m): y for y in years}
        for fut in as_completed(futs):
            y, ok, sec = fut.result()
            tag = "OK" if ok else "FAIL"
            print(f"  {tag}  {args.product} P1 year {y}  ({sec:.0f}s)")
    print(f"All done in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
