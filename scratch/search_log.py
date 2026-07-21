import re
import glob
from pathlib import Path

log_dir = "backtests/baseline_flip_parity/results/nq_live_2025/logs"
log_files = glob.glob(f"{log_dir}/BASELINE-PARITY_*.log")
if not log_files:
    print("No log files found.")
    sys.exit(0)

# Sort by modification time to get the latest run's log
log_files.sort(key=lambda x: Path(x).stat().st_mtime, reverse=True)
log_path = log_files[0]
print(f"Reading log file: {log_path}")

order_id = "O-20250528-064805-PARITY-000-22098"

with open(log_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if order_id in line:
        print(f"--- Line {idx} ---")
        # Print 8 lines before and after
        start = max(0, idx - 8)
        end = min(len(lines), idx + 8)
        for i in range(start, end):
            print(f"{i}: {lines[i]}", end="")
