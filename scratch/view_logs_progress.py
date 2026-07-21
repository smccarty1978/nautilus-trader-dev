import os
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
results_dir = PROJECT_ROOT / "backtests/baseline_flip_parity/results"

for year in [2021, 2022, 2023, 2024]:
    run_log_path = results_dir / f"nq_live_{year}_trail_tp1.5_sl1.0/run.log"
    print(f"--- Year {year} ---")
    if run_log_path.exists():
        with open(run_log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        print(f"Total lines: {len(lines)}")
        if lines:
            print("Last 5 lines:")
            for line in lines[-5:]:
                print("  " + line.strip())
        else:
            print("File is empty.")
    else:
        print("Folder or run.log does not exist yet.")
