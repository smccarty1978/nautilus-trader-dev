"""Autonomous batch driver for V_A portfolio matrix.

Runs (product, year) cells using run_portfolio.py, maintaining
MAX_PARALLEL processes. Skips cells where path_checkpoint snapshots
exist AND have valid (non-NaN) cur_pnl_atr.

Logs progress to MATRIX_LOG. Writes a final manifest at exit.
"""

from __future__ import annotations
import os, sys, time, subprocess, json
from pathlib import Path
import pandas as pd

project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

OUT = Path("collectors/collector_v2/results/portfolio")
OUT.mkdir(parents=True, exist_ok=True)
MATRIX_LOG = OUT / "MATRIX_DRIVER.log"
MANIFEST = OUT / "MATRIX_MANIFEST.json"

MAX_PARALLEL = 4

# (product, year) cells to run. Skip 2022/2023 for ES/YM (data gap).
MATRIX = []
for yr in [2020, 2021, 2022, 2023, 2024, 2025, 2026]:
    MATRIX.append(("NQ", yr))
for yr in [2020, 2021, 2024, 2025, 2026]:
    MATRIX.append(("ES", yr))
for yr in [2020, 2021, 2024, 2025, 2026]:
    MATRIX.append(("YM", yr))


def cell_dir(product: str, year: int) -> Path:
    return OUT / f"{product}_{year}"


def cell_log(product: str, year: int) -> Path:
    return OUT / f"run_{product}_{year}.log"


def has_valid_path_checkpoints(d: Path) -> bool:
    """Returns True if dir has snapshots.parquet AND
    path_checkpoint rows have valid cur_pnl_atr (non-NaN)."""
    s_path = d / "snapshots.parquet"
    if not s_path.exists():
        return False
    try:
        df = pd.read_parquet(s_path, columns=["kind"])
    except Exception:
        return False
    if "path_checkpoint" not in df["kind"].values:
        # baseline-only output (no path emission); count as missing
        return False
    df = pd.read_parquet(
        s_path, columns=["kind", "cur_pnl_atr"])
    cp = df[df["kind"] == "path_checkpoint"]
    if not len(cp):
        return False
    if cp["cur_pnl_atr"].notna().all():
        return True
    return False


def cell_status(product: str, year: int) -> str:
    """One of: 'done_with_path', 'done_no_path', 'missing'."""
    d = cell_dir(product, year)
    if not (d / "trades.parquet").exists():
        return "missing"
    return ("done_with_path"
              if has_valid_path_checkpoints(d) else "done_no_path")


def log_msg(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(MATRIX_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def main(force_rerun_no_path: bool = True):
    # Determine which cells need running
    pending = []
    for product, year in MATRIX:
        st = cell_status(product, year)
        if st == "missing":
            pending.append((product, year))
        elif st == "done_no_path" and force_rerun_no_path:
            pending.append((product, year))
        else:
            log_msg(f"skip {product} {year}: {st}")
    log_msg(f"Pending: {len(pending)} cells")
    if not pending:
        log_msg("Nothing to run. Done.")
        return

    # Parallel queue
    procs: dict = {}  # (product, year) → subprocess.Popen
    completed: list = []
    failed: list = []

    def can_launch_more():
        return len(procs) < MAX_PARALLEL and len(pending) > 0

    def launch(product, year):
        log_p = cell_log(product, year)
        cmd = [
            sys.executable, "collectors/collector_v2/run_portfolio.py",
            "--product", product, "--year", str(year),
        ]
        with open(log_p, "w") as f:
            p = subprocess.Popen(
                cmd, stdout=f, stderr=subprocess.STDOUT)
        procs[(product, year)] = p
        log_msg(f"launched {product} {year} (pid={p.pid})")

    # Initial fill
    while can_launch_more():
        prod, yr = pending.pop(0)
        launch(prod, yr)

    # Loop: wait for any to finish, launch next
    while procs:
        done_keys = []
        for k, p in procs.items():
            if p.poll() is not None:
                rc = p.returncode
                if rc == 0:
                    completed.append(k)
                    log_msg(f"completed {k[0]} {k[1]}")
                else:
                    failed.append((k, rc))
                    log_msg(f"FAILED {k[0]} {k[1]} (rc={rc})")
                done_keys.append(k)
        for k in done_keys:
            del procs[k]
        # Launch next
        while can_launch_more():
            prod, yr = pending.pop(0)
            launch(prod, yr)
        if procs:
            time.sleep(15)

    # Final manifest
    manifest = {
        "completed": [list(c) for c in completed],
        "failed": [
            {"cell": list(c), "rc": rc} for (c, rc) in failed],
        "all_cells": [list(c) for c in MATRIX],
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    log_msg(f"Matrix complete. {len(completed)}/{len(MATRIX)} done. "
              f"{len(failed)} failed. Manifest: {MANIFEST}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rerun", action="store_true",
                     help="Skip cells with done_no_path status")
    args = ap.parse_args()
    main(force_rerun_no_path=not args.no_rerun)
