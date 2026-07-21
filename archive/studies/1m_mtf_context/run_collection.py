"""Runner for MTF Context Collector.

Usage:
    python studies/1m_mtf_context/run_collection.py          # full 6yr
    python studies/1m_mtf_context/run_collection.py --year 2025
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
from collector import MTFContextCollector, MTFContextConfig  # noqa: E402


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


def run_year(year: int, catalog_path: str, out_dir: Path):
    print("=" * 70)
    print(f"MTF CONTEXT COLLECTOR — {year}")
    print("=" * 70)

    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")

    # Warmup: include 2.5 hours before Jan 1 for indicators
    warmup_start = start - pd.Timedelta(days=1)

    print(f"\nLoading 1s bars {warmup_start.date()} → {end.date()}...",
          flush=True)
    t0 = _time.time()
    catalog = ParquetDataCatalog(catalog_path)
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=warmup_start, end=end)
    print(f"  {len(bars_1s):,} 1s bars ({_time.time()-t0:.0f}s)")

    print(f"Loading 1m bars...", flush=True)
    t0 = _time.time()
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=warmup_start, end=end)
    print(f"  {len(bars_1m):,} 1m bars ({_time.time()-t0:.0f}s)")

    nq = create_nq()

    out_file = out_dir / f"trades_{year}.parquet"
    skipped_file = out_dir / f"skipped_{year}.parquet"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = MTFContextConfig(
        strategy_id=f"MTF-COLLECT-{year}",
        output_file=str(out_file),
        skipped_file=str(skipped_file),
    )

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"MTF-{year}",
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

    strat = MTFContextCollector(config)
    engine.add_strategy(strat)

    print(f"\nRunning {year}...", flush=True)
    t0 = _time.time()
    engine.run()
    elapsed = _time.time() - t0
    engine.dispose()

    print(f"\n  Done in {elapsed:.0f}s")
    print(f"  Trades: {len(strat._trades):,}")
    print(f"  Skipped: {len(strat._skipped):,}")
    return len(strat._trades), len(strat._skipped)


def combine_years(years: list, out_dir: Path):
    print("\n" + "=" * 70)
    print("COMBINING YEARS")
    print("=" * 70)
    trade_dfs = []
    skip_dfs = []
    for y in years:
        f = out_dir / f"trades_{y}.parquet"
        if f.exists():
            trade_dfs.append(pd.read_parquet(f))
        sf = out_dir / f"skipped_{y}.parquet"
        if sf.exists():
            skip_dfs.append(pd.read_parquet(sf))
    if trade_dfs:
        combined = pd.concat(trade_dfs, ignore_index=True)
        out_file = out_dir / "trades_all.parquet"
        combined.to_parquet(out_file, index=False)
        print(f"  {len(combined):,} trades → {out_file}")
    if skip_dfs:
        combined = pd.concat(skip_dfs, ignore_index=True)
        out_file = out_dir / "skipped_all.parquet"
        combined.to_parquet(out_file, index=False)
        print(f"  {len(combined):,} skipped → {out_file}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=None,
                    help="single year (omit for all 2020-2025)")
    p.add_argument("--catalog",
                    default="data/catalog/NQ_2020_2025",
                    help="catalog path")
    args = p.parse_args()

    out_dir = Path("studies/1m_mtf_context/results")

    if args.year:
        run_year(args.year, args.catalog, out_dir)
    else:
        years = list(range(2020, 2026))
        for y in years:
            run_year(y, args.catalog, out_dir)
        combine_years(years, out_dir)


if __name__ == "__main__":
    main()
