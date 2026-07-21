import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = "backtests/compression_vwap_launchpad/results/log_2026.txt"
if os.path.exists(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        print(f.read())
else:
    print(f"{path} does not exist")
