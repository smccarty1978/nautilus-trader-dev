import psutil
import os

print(f"Current PID: {os.getpid()}")
found = False
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmd = proc.info['cmdline']
        if cmd and any('run_all_years' in part or 'run_backtest' in part for part in cmd):
            print(f"PID {proc.info['pid']}: {cmd}")
            found = True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

if not found:
    print("No run_all_years or run_backtest processes found.")
