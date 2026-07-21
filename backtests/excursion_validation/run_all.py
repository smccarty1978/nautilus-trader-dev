import subprocess
import sys

for yr in range(2020, 2027):
    print(f"Running year {yr}...")
    subprocess.run([sys.executable, "backtests/excursion_validation/run_backtest.py", "--year", str(yr)], check=True)
