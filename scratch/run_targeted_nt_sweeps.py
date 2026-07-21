import sys
import time
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
RUNNER = PROJECT_ROOT / "backtests/baseline_flip_parity/run_backtest.py"
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

# Define the targeted sweeps to run
SWEEPS = [
    # Candidate 1: Long-only, G = 0.0, S = 3, ma_rule = SMA13
    {
        "name": "stall_sma13_s3_g0_long",
        "args": [
            "--use-stall-protection",
            "--gate-atr", "0.0",
            "--stall-thresh", "3",
            "--ma-period", "13",
            "--ma-type", "SMA",
            "--trade-side", "long",
            "--suffix", "_stall_sma13_s3_g0_long"
        ]
    },
    # Candidate 2: Long-only, G = 0.5, S = 4, ma_rule = EMA21
    {
        "name": "stall_ema21_s4_g0.5_long",
        "args": [
            "--use-stall-protection",
            "--gate-atr", "0.5",
            "--stall-thresh", "4",
            "--ma-period", "21",
            "--ma-type", "EMA",
            "--trade-side", "long",
            "--suffix", "_stall_ema21_s4_g0.5_long"
        ]
    },
    # Candidate 3: Both, G = 0.0, S = 2, ma_rule = SMA21
    {
        "name": "stall_sma21_s2_g0_both",
        "args": [
            "--use-stall-protection",
            "--gate-atr", "0.0",
            "--stall-thresh", "2",
            "--ma-period", "21",
            "--ma-type", "SMA",
            "--trade-side", "both",
            "--suffix", "_stall_sma21_s2_g0"
        ]
    },
    # Baseline Long-only (for comparative lift)
    {
        "name": "base_long",
        "args": [
            "--trade-side", "long",
            "--suffix", "_base_long"
        ]
    }
]

def run_task(year, sweep_name, sweep_args):
    t0 = time.time()
    out_dir = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{year}{sweep_args[-1]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    
    cmd = [sys.executable, str(RUNNER), "--year", str(year), "--product", "NQ"] + sweep_args[:-2] + ["--suffix", sweep_args[-1]]
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        r = subprocess.run(cmd, cwd=str(PROJECT_ROOT), stdout=f, stderr=subprocess.STDOUT)
    return year, sweep_name, r.returncode == 0, time.time() - t0

def main():
    print("Starting targeted Nautilus Trader validation sweeps...")
    tasks = []
    for s in SWEEPS:
        for y in YEARS:
            tasks.append((y, s["name"], s["args"]))
            
    print(f"Total runs scheduled: {len(tasks)}")
    
    t0 = time.time()
    # Run in parallel with a max of 3 workers to prevent CPU starvation
    with ProcessPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(run_task, y, name, args): (y, name) for y, name, args in tasks}
        for fut in as_completed(futures):
            y, name = futures[fut]
            try:
                year, s_name, ok, sec = fut.result()
                tag = "OK" if ok else "FAIL"
                print(f"  [{tag}] {s_name} - NQ {year} ({sec:.1f}s)")
            except Exception as e:
                print(f"  [EXC] {name} - NQ {y}: {e}")
                
    print(f"All sweeps completed in {(time.time() - t0) / 60:.2f} minutes.")

if __name__ == "__main__":
    main()
