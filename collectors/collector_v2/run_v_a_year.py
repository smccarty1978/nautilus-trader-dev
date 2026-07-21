"""Run V_A reference (Mode 2) through Collector V2 for one year.

Outputs:
  collectors/collector_v2/results/v_a_<year>/
    snapshots.parquet
    trades.parquet
    diag.json

V_A rule (matches prior NT-validated baseline):
  - 1m raw regime flip
  - bar+1 HH/LL confirmation
  - bar+1 momentum confirmation
  - enter at bar+1 close + 30s
  - hold to opposing 1m regime flip close
  - NO 5m alignment filter (baseline reproduction)
"""

from __future__ import annotations
import argparse, os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from nautilus_trader.persistence.catalog import ParquetDataCatalog

from collectors.collector_v2.run_smoke import run_one


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    out_dir = Path(
        f"collectors/collector_v2/results/v_a_{args.year}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 5-day warmup
    load_start = pd.Timestamp(
        f"{args.year}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(
        f"{args.year}-12-31 23:59:59", tz="UTC")
    print(f"Loading {load_start} -> {load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
           f"({time.time()-t0:.0f}s)")

    print(f"\nRunning V_A Mode 2 for {args.year}...", flush=True)
    t0 = time.time()
    elapsed, diag = run_one("trading", bars_1s, bars_1m, out_dir,
                                require_5m_aligned=False)
    print(f"  Done in {elapsed:.0f}s")
    print(f"  Diag: {diag}")

    # Quick perf summary
    snaps_p = out_dir / "snapshots.parquet"
    trades_p = out_dir / "trades.parquet"
    if snaps_p.exists():
        df_s = pd.read_parquet(snaps_p)
        print(f"\n  Snapshots: {len(df_s):,}")
    if trades_p.exists():
        df_t = pd.read_parquet(trades_p)
        n = len(df_t)
        if n:
            wr = (df_t["net_pnl"] > 0).mean() * 100
            mean_ = df_t["net_pnl"].mean()
            total = df_t["net_pnl"].sum()
            wins = df_t[df_t["net_pnl"] > 0]["net_pnl"].sum()
            losses = abs(df_t[df_t["net_pnl"] < 0]["net_pnl"].sum())
            pf = wins / losses if losses else float("inf")
            print(f"  Trades: {n:,}")
            print(f"  WR: {wr:.1f}%, mean ${mean_:.2f}, "
                   f"PF {pf:.2f}, total ${total:,.0f}")


if __name__ == "__main__":
    main()
