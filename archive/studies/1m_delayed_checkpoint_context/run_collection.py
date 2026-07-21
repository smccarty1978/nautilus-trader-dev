"""Runner for v3 delayed checkpoint collector.

Usage:
    python studies/1m_delayed_checkpoint_context/run_collection.py --smoke
    python studies/1m_delayed_checkpoint_context/run_collection.py --year 2025
    python studies/1m_delayed_checkpoint_context/run_collection.py    # full 6yr
"""

import argparse
import os
import sys
import time as _time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.enums import OmsType, AccountType
from nautilus_trader.model.objects import Money
from nautilus_trader.model.currencies import USD
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract

sys.path.insert(0, str(Path(__file__).parent))
from collector import DelayedCheckpointCollector, DCContextConfig  # noqa


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp(
        "2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp(
        "2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def run_period(start, end, label, out_file, catalog_path):
    print("=" * 70)
    print(f"v3 DELAYED CHECKPOINT COLLECTOR — {label}")
    print(f"  Output: {out_file}")
    print("=" * 70)

    warmup_start = start - pd.Timedelta(days=1)

    print(f"\nLoading 1s bars {warmup_start.date()} → {end.date()}...",
          flush=True)
    t0 = _time.time()
    catalog = ParquetDataCatalog(catalog_path)
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=warmup_start, end=end)
    print(f"  {len(bars_1s):,} 1s bars ({_time.time()-t0:.0f}s)")

    print("Loading 1m bars...", flush=True)
    t0 = _time.time()
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=warmup_start, end=end)
    print(f"  {len(bars_1m):,} 1m bars ({_time.time()-t0:.0f}s)")

    nq = create_nq()
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)

    safe_label = "".join(c if c.isalnum() or c in "-_" else ""
                          for c in label)[:30]
    config = DCContextConfig(
        strategy_id=f"DC-{safe_label}",
        output_file=str(out_file),
    )

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"DC-{safe_label[:5]}",
        logging=LoggingConfig(log_level="ERROR"),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(10_000_000, USD)],
        bar_execution=True,
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    strat = DelayedCheckpointCollector(config)
    engine.add_strategy(strat)

    print("\nRunning...", flush=True)
    t0 = _time.time()
    engine.run()
    elapsed = _time.time() - t0
    engine.dispose()

    print(f"\n  Done in {elapsed:.0f}s")
    print(f"  Trades: {len(strat._trades):,}")
    print(f"  Diag: {strat._diag}")
    return len(strat._trades)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true",
                    help="1-week smoke test (2025-04-07 → 2025-04-11)")
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--catalog",
                    default="data/catalog/NQ_2020_2025")
    args = p.parse_args()

    out_dir = Path("studies/1m_delayed_checkpoint_context/results")

    if args.smoke:
        start = pd.Timestamp("2025-04-07", tz="UTC")
        end = pd.Timestamp("2025-04-12 23:59:59", tz="UTC")
        out_file = out_dir / "trades_smoke.parquet"
        run_period(start, end, "SMOKE_20250407_20250411",
                    out_file, args.catalog)
    elif args.year:
        start = pd.Timestamp(f"{args.year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{args.year}-12-31 23:59:59", tz="UTC")
        out_file = out_dir / f"trades_{args.year}.parquet"
        run_period(start, end, f"{args.year}", out_file, args.catalog)
    else:
        years = list(range(2020, 2026))
        for y in years:
            start = pd.Timestamp(f"{y}-01-01", tz="UTC")
            end = pd.Timestamp(f"{y}-12-31 23:59:59", tz="UTC")
            out_file = out_dir / f"trades_{y}.parquet"
            run_period(start, end, f"{y}", out_file, args.catalog)
        # Combine
        dfs = []
        for y in years:
            f = out_dir / f"trades_{y}.parquet"
            if f.exists():
                dfs.append(pd.read_parquet(f))
        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            combined.to_parquet(out_dir / "trades_all.parquet", index=False)
            print(f"\nCombined: {len(combined):,} trades → trades_all.parquet")


if __name__ == "__main__":
    main()
