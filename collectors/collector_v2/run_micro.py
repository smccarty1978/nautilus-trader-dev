"""Micro-smoke test: 2 RTH days (Jan 8-9, 2024) for fast iteration."""

from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from collectors.collector_v2.run_smoke import run_one, compare_snapshots, provenance_check


def main():
    out_root = Path("collectors/collector_v2/results/micro")
    out_root.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    load_start = pd.Timestamp("2024-01-05", tz="UTC")
    load_end = pd.Timestamp("2024-01-09 23:59:59", tz="UTC")
    print(f"Loading {load_start} -> {load_end}...")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars")

    print("\n[Mode 1]")
    e1, d1 = run_one("research", bars_1s, bars_1m,
                       out_root / "mode1")
    print(f"  done in {e1:.0f}s, diag={d1}")

    print("\n[Mode 2]")
    e2, d2 = run_one("trading", bars_1s, bars_1m,
                       out_root / "mode2")
    print(f"  done in {e2:.0f}s, diag={d2}")

    df1 = pd.read_parquet(out_root / "mode1/snapshots.parquet")
    df2 = pd.read_parquet(out_root / "mode2/snapshots.parquet")
    print(f"\nMode 1 snapshots: {len(df1):,}")
    print(f"Mode 2 snapshots: {len(df2):,}")
    if (out_root / "mode2/trades.parquet").exists():
        trades = pd.read_parquet(out_root / "mode2/trades.parquet")
        print(f"Mode 2 trades:    {len(trades):,}")
        if len(trades):
            print(f"  Total $: {trades['net_pnl'].sum():,.0f}, "
                   f"WR: {(trades['net_pnl']>0).mean()*100:.1f}%")

    print("\n=== Provenance ===")
    print(f"Mode 1: {provenance_check(df1, 'm1')}")
    print(f"Mode 2: {provenance_check(df2, 'm2')}")

    print("\n=== Parity ===")
    parity = compare_snapshots(df1, df2)
    print(f"Matched: {parity.get('n_matched')}, "
           f"only_m1: {parity.get('n_only_mode1')}, "
           f"only_m2: {parity.get('n_only_mode2')}, "
           f"mismatched_cols: {len(parity.get('mismatches', {}))}")
    if parity.get("mismatches"):
        for c, info in parity["mismatches"].items():
            print(f"  {c}: {info['n_mismatch']} mismatches")
            for s in info["sample"][:2]:
                print(f"    {s}")


if __name__ == "__main__":
    main()
