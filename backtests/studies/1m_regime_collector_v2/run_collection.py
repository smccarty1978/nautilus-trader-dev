"""Runner for collector v2.

Usage:
    python studies/1m_regime_collector_v2/run_collection.py --smoke
    python studies/1m_regime_collector_v2/run_collection.py --year 2025
    python studies/1m_regime_collector_v2/run_collection.py  # full 2020-2025

Smoke test window: 1 week in April 2025.
Year runs: full calendar year with 2-day warmup lead-in per §3.6.
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
from collector import CollectorV2, CollectorV2Config  # noqa


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


def run_period(start, end, label, out_dir, catalog_path,
                warmup_days: int = 2):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    features_path = out_dir / f"v2_feature_snapshots_{label}.parquet"
    labels_path = out_dir / f"v2_outcome_labels_{label}.parquet"
    events_path = out_dir / f"v2_event_summary_{label}.parquet"
    qa_path = out_dir / f"v2_collection_qa_{label}.log"

    print("=" * 72)
    print(f"v2 COLLECTOR — {label}")
    print(f"  Output dir: {out_dir}")
    print(f"  Warmup:     {warmup_days} days lead-in")
    print("=" * 72)

    warmup_start = start - pd.Timedelta(days=warmup_days)

    print(f"\nLoading 1s bars {warmup_start.date()} -> {end.date()}...",
          flush=True)
    t0 = _time.time()
    catalog = ParquetDataCatalog(catalog_path)
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=warmup_start, end=end)
    print(f"  {len(bars_1s):,} 1s bars ({_time.time() - t0:.0f}s)")

    print("Loading 1m bars...", flush=True)
    t0 = _time.time()
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=warmup_start, end=end)
    print(f"  {len(bars_1m):,} 1m bars ({_time.time() - t0:.0f}s)")

    if len(bars_1m) == 0:
        print("NO DATA — aborting")
        return 0

    nq = create_nq()
    safe_label = "".join(
        c if c.isalnum() or c in "-_" else "" for c in label)[:30]
    cfg = CollectorV2Config(
        strategy_id=f"V2-{safe_label}",
        features_output=str(features_path),
        labels_output=str(labels_path),
        events_summary_output=str(events_path),
        qa_log_output=str(qa_path),
    )

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"V2-{safe_label[:5]}",
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

    strat = CollectorV2(cfg)
    engine.add_strategy(strat)

    print("\nRunning...", flush=True)
    t0 = _time.time()
    engine.run()
    elapsed = _time.time() - t0
    engine.dispose()

    print(f"\n  Done in {elapsed:.0f}s")
    print(f"  Diag: {strat._diag}")
    print(f"  Feature rows: {len(strat._feature_records):,}")
    print(f"  Label rows:   {len(strat._label_records):,}")
    print(f"  Events:       {len(strat._event_summary_records):,}")
    return len(strat._event_summary_records)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                     help="1-week smoke test (2025-04-07..2025-04-11)")
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--catalog",
                     default="data/catalog/NQ_2020_2025")
    ap.add_argument("--out", default="studies/1m_regime_collector_v2/results")
    args = ap.parse_args()

    out_dir = Path(args.out)

    if args.smoke:
        start = pd.Timestamp("2025-04-07", tz="UTC")
        end = pd.Timestamp("2025-04-11 23:59:59", tz="UTC")
        run_period(start, end, "SMOKE_20250407_20250411",
                    out_dir, args.catalog)
    elif args.year:
        start = pd.Timestamp(f"{args.year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{args.year}-12-31 23:59:59", tz="UTC")
        run_period(start, end, f"{args.year}", out_dir, args.catalog)
    else:
        for y in range(2020, 2026):
            start = pd.Timestamp(f"{y}-01-01", tz="UTC")
            end = pd.Timestamp(f"{y}-12-31 23:59:59", tz="UTC")
            run_period(start, end, f"{y}", out_dir, args.catalog)


if __name__ == "__main__":
    main()
