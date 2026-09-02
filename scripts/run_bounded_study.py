import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Try importing psutil for memory monitoring, fall back if not present
try:
    import psutil
except ImportError:
    psutil = None


def progress_signature(path: Path) -> tuple[int, int]:
    """Return a heartbeat signature that changes on rewrites, growth, or truncation."""
    stat_info = path.stat()
    return stat_info.st_mtime_ns, stat_info.st_size


def monitor_process(
    cmd_args: list,
    timeout_sec: float,
    stale_timeout_sec: float,
    progress_file_path: Optional[Path],
    out_status_path: Path,
    rss_limit_mb: Optional[float] = None,
) -> None:
    print(f"[RUNNER] Launching: {' '.join(cmd_args)}")
    start_time = time.time()
    
    # Ensure parents directories for status output exist
    out_status_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Run subprocess.  Do not leave a PIPE undrained while the supervisor
    # monitors progress: verbose, long-running children can fill that pipe and
    # deadlock even though their work is otherwise healthy.  A temporary spool
    # preserves the combined diagnostic log without imposing back-pressure.
    run_output = ""
    output_spool = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    proc = subprocess.Popen(
        cmd_args,
        stdout=output_spool,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    peak_memory_mb = 0.0
    status = "running"
    exit_code = None
    last_progress_time = time.time()
    last_progress_signature = None

    if progress_file_path and progress_file_path.exists():
        last_progress_signature = progress_signature(progress_file_path)

    try:
        while proc.poll() is None:
            # Check absolute timeout
            elapsed = time.time() - start_time
            if elapsed > timeout_sec:
                status = "timeout"
                proc.terminate()
                print(f"[RUNNER] Terminated process due to absolute timeout (> {timeout_sec}s)")
                break

            # Treat every rewrite as progress, even when the file's size is unchanged.
            if progress_file_path and progress_file_path.exists():
                current_signature = progress_signature(progress_file_path)
                if current_signature != last_progress_signature:
                    last_progress_time = time.time()
                    last_progress_signature = current_signature
                elif time.time() - last_progress_time > stale_timeout_sec:
                    status = "stale_stall"
                    proc.terminate()
                    print(
                        "[RUNNER] Terminated process due to stale progress "
                        f"(> {stale_timeout_sec}s without progress-file modification)"
                    )
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
                    if rss_limit_mb is not None and peak_memory_mb > rss_limit_mb:
                        status = "rss_limit"
                        proc.terminate()
                        print(f"[RUNNER] Terminated process due to RSS limit (> {rss_limit_mb} MB)")
                        break
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
    proc.communicate()
    output_spool.seek(0)
    run_output = output_spool.read()
    output_spool.close()

    # Capture logs to run output log
    log_dir = out_status_path.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_log_path = log_dir / f"run_{int(start_time)}.log"
    with open(run_log_path, "w", encoding="utf-8") as f:
        f.write("=== COMBINED OUTPUT ===\n")
        f.write(run_output)

    # Compile final execution card
    status_card = {
        "status": status,
        "exit_code": exit_code,
        "elapsed_seconds": int(elapsed_seconds),
        "peak_memory_mb": int(peak_memory_mb),
        "pid": proc.pid,
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
    ap.add_argument("--rss-limit-mb", type=float, default=None, help="Maximum aggregate process RSS in MB")
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
        out_status_path=Path(args.out_status),
        rss_limit_mb=args.rss_limit_mb,
    )


if __name__ == "__main__":
    main()
