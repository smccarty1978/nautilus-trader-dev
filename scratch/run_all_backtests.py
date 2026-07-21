import subprocess
import time
import sys

years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
processes = {}

print("Starting all backtests in parallel...")
for year in years:
    cmd = [sys.executable, "backtests/compression_vwap_launchpad/run_backtest.py", "--year", str(year)]
    log_file = f"backtests/compression_vwap_launchpad/results/log_{year}.txt"
    f = open(log_file, "w")
    print(f"  Starting backtest for {year}, logging to {log_file}...")
    p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    processes[year] = (p, f)

print("\nAll backtests started. Monitoring progress...")
active = list(years)
while active:
    time.sleep(10)
    for year in list(active):
        p, f = processes[year]
        status = p.poll()
        if status is not None:
            f.close()
            active.remove(year)
            print(f"  Backtest for {year} finished with exit code {status}")

print("\nAll backtests completed!")
