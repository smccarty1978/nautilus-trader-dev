"""Run V_A through Collector V2 against NQ.v.0 catalog WITHOUT the
30s entry delay (entry at OPEN of next 1s bar after bar+1 close).

Output: collectors/collector_v2/results/v_a_v0_nodelay_<year>/

Compare to v_a_v0_<year> (with 30s delay) by joining on direction +
flip_bar_event.
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
        f"collectors/collector_v2/results/v_a_v0_nodelay_{args.year}")
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(
        f"{args.year}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(
        f"{args.year}-12-31 23:59:59", tz="UTC")
    print(f"[{args.year}] Loading {load_start} -> {load_end}...",
            flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_v0_2020_2026")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
           f"({time.time()-t0:.0f}s)")

    print(f"\n[{args.year}] Running V_A NO-DELAY...", flush=True)
    t0 = time.time()
    elapsed, diag = run_one("trading", bars_1s, bars_1m, out_dir,
                                require_5m_aligned=False)
    print(f"  Done in {elapsed:.0f}s")
    print(f"  Diag: {diag}")

    trades_p = out_dir / "trades.parquet"
    if trades_p.exists():
        df_t = pd.read_parquet(trades_p)
        n = len(df_t)
        if n:
            wr = (df_t["net_pnl"] > 0).mean() * 100
            mean_ = df_t["net_pnl"].mean()
            total = df_t["net_pnl"].sum()
            print(f"  Trades: {n:,}, WR: {wr:.1f}%, mean ${mean_:.2f}, "
                   f"total ${total:,.0f}")


if __name__ == "__main__":
    main()
