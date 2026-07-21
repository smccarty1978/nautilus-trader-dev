import os
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
results_dir = PROJECT_ROOT / "backtests/baseline_flip_parity/results"

for year in [2021, 2022, 2023, 2024]:
    logs_dir = results_dir / f"nq_live_{year}_trail_tp1.5_sl1.0/logs"
    print(f"--- Year {year} ---")
    if logs_dir.exists():
        files = list(logs_dir.glob("*.log"))
        if files:
            log_file = files[0]
            size_mb = log_file.stat().st_size / (1024 * 1024)
            print(f"Active log file: {log_file.name} ({size_mb:.2f} MB)")
            
            # Read last few lines to find current simulation time
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                # Seek to end and read last few lines
                f.seek(0, 2)
                file_size = f.tell()
                # Seek back 2000 characters
                f.seek(max(0, file_size - 2000))
                tail = f.read()
            
            print("Tail info:")
            for line in tail.split("\n")[-6:]:
                if line.strip():
                    print("  " + line.strip())
        else:
            print("No log files in logs/ directory.")
    else:
        print("logs/ directory does not exist yet.")
