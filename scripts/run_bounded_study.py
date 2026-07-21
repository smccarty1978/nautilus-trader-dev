import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Try importing psutil for memory monitoring, fall back if not present
try:
    import psutil
except ImportError:
    psutil = None



def monitor_process(
    cmd_args: list,
    timeout_sec: float,
    stale_timeout_sec: float,
    progress_file_path: Optional[Path],
    out_status_path: Path
) -> None:
    print(f"[RUNNER] Launching: {' '.join(cmd_args)}")
    start_time = time.time()
    
    # Ensure parents directories for status output exist
    out_status_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Run subprocess
    proc = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    peak_memory_mb = 0.0
    status = "running"
    exit_code = None
    last_progress_time = time.time()
    last_progress_size = 0

    if progress_file_path and progress_file_path.exists():
        last_progress_size = progress_file_path.stat().st_size

    try:
        while proc.poll() is None:
            # Check absolute timeout
            elapsed = time.time() - start_time
            if elapsed > timeout_sec:
                status = "timeout"
                proc.terminate()
                print(f"[RUNNER] Terminated process due to absolute timeout (> {timeout_sec}s)")
                break

            # Check stale progress (log file updates)
            if progress_file_path and progress_file_path.exists():
                stat_info = progress_file_path.stat()
                curr_size = stat_info.st_size
                curr_mtime = stat_info.st_mtime
                
                # If file size increased or mod time changed, reset stale check
                if curr_size > last_progress_size:
                    last_progress_time = time.time()
                    last_progress_size = curr_size
                elif time.time() - last_progress_time > stale_timeout_sec:
                    status = "stale_stall"
                    proc.terminate()
                    print(f"[RUNNER] Terminated process due to stale progress (> {stale_timeout_sec}s without log updates)")
                    break

            # Memory tracking
            if psutil:
                try:
                    p = psutil.Process(proc.pid)
                    # Include child processes if any
                    mem = p.memory_info().rss
                    for child in p.children(recursive=True):
                        mem += child.memory_info().rss
                    peak_memory_mb = max(peak_memory_mb, mem / (1024 * 1024))
                except Exception:
                    pass

            time.sleep(1.0)
        
        # Collect final exit code
        if status == "running":
            exit_code = proc.wait()
            status = "completed" if exit_code == 0 else "failed"
        else:
            proc.wait() # Ensure process fully disposes

    except KeyboardInterrupt:
        status = "interrupted"
        proc.terminate()
        proc.wait()
        print("[RUNNER] Interrupted by user.")

    elapsed_seconds = time.time() - start_time
    stdout_data, stderr_data = proc.communicate()

    # Capture logs to run output log
    log_dir = out_status_path.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_log_path = log_dir / f"run_{int(start_time)}.log"
    with open(run_log_path, "w", encoding="utf-8") as f:
        f.write("=== STDOUT ===\n")
        f.write(stdout_data)
        f.write("\n=== STDERR ===\n")
        f.write(stderr_data)

    # Compile final execution card
    status_card = {
        "status": status,
        "exit_code": exit_code,
        "elapsed_seconds": int(elapsed_seconds),
        "peak_memory_mb": int(peak_memory_mb),
        "log_file": str(run_log_path)
    }

    # Write status JSON card atomically
    tmp_path = out_status_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(status_card, f, indent=4)
    os.replace(tmp_path, out_status_path)

    print(f"[RUNNER] Run finished with status: {status}. Status card saved to {out_status_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", type=str, required=True, help="Command string to execute (e.g. 'python backtests/run_staged_backtest.py')")
    ap.add_argument("--timeout", type=float, default=600.0, help="Absolute timeout in seconds")
    ap.add_argument("--stale-timeout", type=float, default=120.0, help="Maximum seconds without progress updates")
    ap.add_argument("--progress-file", type=str, default=None, help="Log or output file to watch for modification updates")
    ap.add_argument("--out-status", type=str, default="backtests/results/status.json", help="Output path for the status JSON record")
    args = ap.parse_args()

    # Parse command arguments split by whitespace
    import shlex
    cmd_args = shlex.split(args.cmd)

    progress_path = Path(args.progress_file) if args.progress_file else None
    monitor_process(
        cmd_args=cmd_args,
        timeout_sec=args.timeout,
        stale_timeout_sec=args.stale_timeout,
        progress_file_path=progress_path,
        out_status_path=Path(args.out_status)
    )


if __name__ == "__main__":
    main()
