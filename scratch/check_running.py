import psutil
import os

print(f"Current Process ID: {os.getpid()}")

# Find python processes
for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
    try:
        cmd = proc.info['cmdline']
        if cmd and any('run_paired_bootstrap.py' in part for part in cmd):
            print(f"\nFound target process:")
            print(f"  PID: {proc.info['pid']}")
            print(f"  Cmdline: {proc.info['cmdline']}")
            print(f"  CPU%: {proc.cpu_percent(interval=1.0)}")
            print(f"  Memory: {proc.info['memory_info'].rss / 1024 / 1024:.1f} MB")
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
