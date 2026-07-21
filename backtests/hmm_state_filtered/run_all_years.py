"""Run HMM-state-filtered NT validation across all 7 years, 3 parallel."""
from __future__ import annotations
import argparse, os, sys, time, subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).parent.parent.parent
RUNNER = "backtests/hmm_state_filtered/run_backtest.py"
PARALLEL = 3


def run_one(year, product, state_col, target_state, min_state_dur, pt_atr, sl_atr,
            entry_anchor, state_path, state_tag,
            state_col_5m, target_state_5m, anchor_5m,
            be_trig_atr=0.0, be_level_atr=0.0, min_atr=0.0, max_hold_s=60,
            vwap_exit_active=False, qty=1, pt_runner_atr=2.0, pt_c1_atr=0.50,
            vwap_z_threshold=1.0, features_path="",
            post_entry_gates_active=False, speed_gate_threshold_s=30.0, gate_60s_pnl_atr=0.30,
            wide_sl_atr=0.0):
    t0 = time.time()
    dur_suffix = f"_dur{min_state_dur}" if min_state_dur > 0 else ""
    pt_suffix  = f"_pt{pt_atr}".replace(".", "p") if pt_atr > 0 else ""
    sl_suffix  = f"_sl{sl_atr}".replace(".", "p") if sl_atr > 0 else ""
    anchor_suffix = f"_anc{entry_anchor}" if entry_anchor != "bar1_confirm" else ""
    tag_suffix = f"_{state_tag}" if state_tag else ""
    m5_suffix = f"_m5_{state_col_5m}_s{target_state_5m}_{anchor_5m}" if state_col_5m else ""
    be_suffix = f"_be{be_trig_atr}_lvl{be_level_atr}".replace(".", "p").replace("-", "m") if be_trig_atr > 0 else ""
    atr_suffix = f"_minatr{min_atr}".replace(".", "p") if min_atr > 0 else ""
    vwap_suffix = f"_vwapF_qty{qty}_ptr{pt_runner_atr}".replace(".", "p") if vwap_exit_active else ""
    gates_suffix = f"_gates_qty{qty}_ptr{pt_runner_atr}".replace(".", "p") if post_entry_gates_active else ""
    if post_entry_gates_active and wide_sl_atr > 0:
        gates_suffix += f"_wsl{wide_sl_atr}".replace(".", "p")
    out_dir = (PROJECT_ROOT / "backtests/hmm_state_filtered/results"
               / f"{product.lower()}_{state_col}_s{target_state}{dur_suffix}{pt_suffix}{sl_suffix}{anchor_suffix}{tag_suffix}{m5_suffix}{be_suffix}{atr_suffix}{vwap_suffix}{gates_suffix}_{year}")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    cmd = [sys.executable, RUNNER, "--year", str(year),
           "--product", product,
           "--state-col", state_col,
           "--target-state", str(target_state),
           "--min-state-dur", str(min_state_dur),
           "--pt-atr", str(pt_atr),
           "--sl-atr", str(sl_atr),
           "--entry-anchor", entry_anchor,
           "--be-trig-atr", str(be_trig_atr),
           "--be-level-atr", str(be_level_atr),
           "--min-atr", str(min_atr),
           "--max-hold-s", str(max_hold_s),
           "--qty", str(qty),
           "--pt-runner-atr", str(pt_runner_atr),
           "--pt-c1-atr", str(pt_c1_atr),
           "--vwap-z-threshold", str(vwap_z_threshold),
           "--wide-sl-atr", str(wide_sl_atr)]
    if vwap_exit_active:
        cmd += ["--vwap-exit-active"]
    if post_entry_gates_active:
        cmd += ["--post-entry-gates-active",
                "--speed-gate-threshold-s", str(speed_gate_threshold_s),
                "--gate-60s-pnl-atr", str(gate_60s_pnl_atr)]
    if features_path:
        cmd += ["--features-path", features_path]
    if state_path:
        cmd += ["--state-path", state_path]
    if state_tag:
        cmd += ["--state-tag", state_tag]
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
    ap.add_argument("--pt-atr", type=float, default=2.0)
    ap.add_argument("--sl-atr", type=float, default=0.0)
    ap.add_argument("--entry-anchor", default="bar1_confirm",
                    choices=["bar1_confirm", "bar1", "flip"])
    ap.add_argument("--state-path", default="",
                    help="Override state parquet path")
    ap.add_argument("--state-tag", default="",
                    help="Suffix tag for output dir")
    ap.add_argument("--years", default="2020,2021,2022,2023,2024,2025,2026")
    ap.add_argument("--state-col-5m", default="")
    ap.add_argument("--target-state-5m", type=int, default=-1)
    ap.add_argument("--anchor-5m", default="bar1", choices=["flip", "bar1"])
    ap.add_argument("--be-trig-atr", type=float, default=0.0)
    ap.add_argument("--be-level-atr", type=float, default=0.0)
    ap.add_argument("--min-atr", type=float, default=0.0)
    ap.add_argument("--max-hold-s", type=int, default=60)
    ap.add_argument("--vwap-exit-active", action="store_true")
    ap.add_argument("--qty", type=int, default=1)
    ap.add_argument("--pt-runner-atr", type=float, default=2.0)
    ap.add_argument("--pt-c1-atr", type=float, default=0.50)
    ap.add_argument("--vwap-z-threshold", type=float, default=1.0)
    ap.add_argument("--features-path", default="")
    ap.add_argument("--post-entry-gates-active", action="store_true")
    ap.add_argument("--speed-gate-threshold-s", type=float, default=30.0)
    ap.add_argument("--gate-60s-pnl-atr", type=float, default=0.30)
    ap.add_argument("--wide-sl-atr", type=float, default=0.0)
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(",")]
 
    m5_str = f" m5={args.state_col_5m}=={args.target_state_5m} ({args.anchor_5m})" if args.state_col_5m else ""
    print(f"Running {len(years)} {args.product} backtests, "
          f"state={args.state_col}=={args.target_state} "
          f"dur>={args.min_state_dur} pt={args.pt_atr} sl={args.sl_atr} "
          f"be_trig={args.be_trig_atr} be_lvl={args.be_level_atr} min_atr={args.min_atr} max_hold={args.max_hold_s}s "
          f"anchor={args.entry_anchor}{m5_str}, "
          f"{PARALLEL} parallel")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=PARALLEL) as ex:
        futs = {ex.submit(run_one, y, args.product, args.state_col,
                            args.target_state, args.min_state_dur,
                            args.pt_atr, args.sl_atr, args.entry_anchor,
                            args.state_path, args.state_tag,
                            args.state_col_5m,
                            args.target_state_5m, args.anchor_5m,
                            args.be_trig_atr, args.be_level_atr, args.min_atr,
                            args.max_hold_s,
                            args.vwap_exit_active, args.qty, args.pt_runner_atr, args.pt_c1_atr,
                            args.vwap_z_threshold, args.features_path,
                            args.post_entry_gates_active, args.speed_gate_threshold_s, args.gate_60s_pnl_atr,
                            args.wide_sl_atr): y for y in years}
        for fut in as_completed(futs):
            y, ok, sec = fut.result()
            tag = "OK" if ok else "FAIL"
            print(f"  {tag}  {args.product} {args.state_col}=={args.target_state} "
                  f"year {y}  ({sec:.0f}s)")
    print(f"All done in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
