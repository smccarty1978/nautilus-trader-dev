import os

years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
for y in years:
    path = f"backtests/compression_vwap_launchpad/results/log_{y}.txt"
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"Year {y}: log size = {size} bytes")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            # print last 3 lines
            print(f"  Last lines of log_{y}.txt:")
            for line in lines[-3:]:
                print(f"    {line.strip()}")
    else:
        print(f"Year {y}: log file does not exist")
