"""Run V_A baseline with trade-tape emission for one (product, year).

Output: collectors/collector_v2/results/with_tape/<product>_<year>/
  - trades.parquet
  - snapshots.parquet
  - micro_pre.parquet
  - micro_post.parquet
  - trade_tape.parquet  ← per-1s-bar tape during open trades
"""

from __future__ import annotations
import argparse, os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from collectors.collector_v2.strategy import (
    CollectorV2Strategy, CollectorV2Config,
)
from collectors.collector_v2.run_portfolio import (
    PRODUCT_CFG, create_instrument,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="NQ",
                     choices=list(PRODUCT_CFG.keys()))
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    pcfg = PRODUCT_CFG[args.product]
    out_dir = Path(
        f"collectors/collector_v2/results/with_tape/"
        f"{args.product}_{args.year}")
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(
        f"{args.year}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(
        f"{args.year}-12-31 23:59:59", tz="UTC")
    print(f"[{args.product} {args.year}] Loading {load_start} -> "
           f"{load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(pcfg["catalog"])
    bars_1s = catalog.bars(
        bar_types=[pcfg["bar_type_1s"]],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=[pcfg["bar_type_1m"]],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
           f"({time.time()-t0:.0f}s)")
    if not bars_1s or not bars_1m:
        print("  NO DATA"); return

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"TAPE-{args.product[:2]}{str(args.year)[-2:]}-001",
        logging=LoggingConfig(
            log_level="WARNING",
            log_directory=str(out_dir / "logs")),
    ))
    engine.add_venue(
        venue=Venue(pcfg["venue"]), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True)
    engine.add_instrument(create_instrument(args.product, pcfg))
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = CollectorV2Config(
        instrument_id=pcfg["instrument_id"],
        bar_type_1m=pcfg["bar_type_1m"],
        bar_type_1s=pcfg["bar_type_1s"],
        mode="trading",
        rth_only=False,
        position_size=1,
        require_5m_aligned=False,
        output_dir=str(out_dir),
        multiplier=pcfg["multiplier"],
        tick_dollar=pcfg["tick_dollar"],
        commission_per_rt=5.0,
        emit_trade_tape=True,
    )
    strat = CollectorV2Strategy(cfg)
    engine.add_strategy(strat)

    print("  Running with trade tape enabled...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")
    print(f"  Diag: {strat._diag}")
    engine.dispose()


if __name__ == "__main__":
    main()
