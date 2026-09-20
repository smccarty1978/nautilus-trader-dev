import sys
import os
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

REPO_ROOT = Path(r"c:/Users/Scott McCarty/Projects/Nautilus Trader")
WORK_DIR = REPO_ROOT / "studies/nq_leaf4_execution_robustness/_work"
WORK_DIR.mkdir(parents=True, exist_ok=True)

df_ref = pd.read_parquet(REPO_ROOT / 'studies/nq_leaf4_runtime_validation_and_distribution_diagnostic/runtime_trade_ledger.parquet')
df_ref['dt'] = pd.to_datetime(df_ref['checkpoint_ts'], unit='ns')

def get_expected_count(year, month):
    sub = df_ref[(df_ref['dt'].dt.year == year) & (df_ref['dt'].dt.month == month)]
    return len(sub)

def run_month(year, month):
    expected_count = get_expected_count(year, month)
    out_file = WORK_DIR / f"nt_trades_{year}_{month:02d}.parquet"
    if out_file.exists():
        try:
            df = pd.read_parquet(out_file)
            if len(df) == expected_count:
                return year, month, True, 0.0, f"Already cached ({len(df)}/{expected_count} trades)"
        except Exception:
            pass

    t0 = time.time()
    cmd = [sys.executable, str(REPO_ROOT / "scripts/run_nt_worker_month.py"), "--year", str(year), "--month", str(month)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0
    if p.returncode != 0:
        return year, month, False, elapsed, p.stderr
    return year, month, True, elapsed, p.stdout.strip()

def main():
    tasks = []
    for y in [2023, 2024]:
        for m in range(1, 13):
            tasks.append((y, m))
    for m in [1, 2, 3]:
        tasks.append((2025, m))

    print(f"Starting parallel execution of {len(tasks)} monthly NT backtest subprocesses with max_workers=6...")
    sys.stdout.flush()
    t_start = time.time()

    completed_count = 0
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(run_month, y, m): (y, m) for y, m in tasks}
        for future in as_completed(futures):
            y, m, success, elapsed, msg = future.result()
            completed_count += 1
            if success:
                print(f"[{completed_count:02d}/{len(tasks)}] Done {y}-{m:02d} in {elapsed:.1f}s: {msg}")
            else:
                print(f"[{completed_count:02d}/{len(tasks)}] FAILED {y}-{m:02d} in {elapsed:.1f}s: {msg}", file=sys.stderr)
            sys.stdout.flush()

    total_elapsed = time.time() - t_start
    print(f"\nAll monthly subprocesses finished in {total_elapsed/60:.2f} minutes.")

    # Validate and concatenate results
    dfs = []
    total_expected = len(df_ref)
    for y, m in tasks:
        pfile = WORK_DIR / f"nt_trades_{y}_{m:02d}.parquet"
        if not pfile.exists():
            raise FileNotFoundError(f"Missing expected output: {pfile}")
        df_m = pd.read_parquet(pfile)
        exp = get_expected_count(y, m)
        if len(df_m) != exp:
            raise ValueError(f"Month {y}-{m:02d} trade count mismatch: {len(df_m)} vs expected {exp}")
        if len(df_m) > 0:
            dfs.append(df_m)

    df_all = pd.concat(dfs, ignore_index=True)
    print(f"\nTotal live NT trades executed across all months: {len(df_all)} (Expected: {total_expected})")
    assert len(df_all) == total_expected, f"Total count mismatch: {len(df_all)} != {total_expected}"
    
    out_all = WORK_DIR / "nt_live_trades_ledger.parquet"
    df_all.to_parquet(out_all, index=False)
    print(f"Saved complete live NT ledger to {out_all}")

if __name__ == "__main__":
    main()
