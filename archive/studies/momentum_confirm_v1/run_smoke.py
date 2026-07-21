"""Smoke test: 2 weeks Jan 2024, both modes."""

from __future__ import annotations
import os, sys, time
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

sys.path.insert(0, str(Path(__file__).parent))
from nt_strategy import MomentumConfirmStrategy, MomentumConfirmConfig
from run_nt import create_nq


def run_one(mode: str, bars_1s, bars_1m):
    out_dir = Path(f"studies/momentum_confirm_v1/results/smoke_{mode}")
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"SMOKE-001",
        logging=LoggingConfig(log_level="WARNING",
                                log_directory=str(out_dir / "logs"))))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True)
    engine.add_instrument(create_nq())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)
    cfg = MomentumConfirmConfig(
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        mode=mode, rth_only=True, position_size=1,
        output_dir=str(out_dir))
    strat = MomentumConfirmStrategy(cfg)
    engine.add_strategy(strat)
    t0 = time.time()
    engine.run()
    print(f"\n{mode}: done in {time.time()-t0:.0f}s, "
           f"diag={strat._diag}, trades={len(strat._trade_log)}")
    if strat._trade_log:
        df = pd.DataFrame(strat._trade_log)
        print(f"  Total $: {df['net_pnl'].sum():,.0f}, "
               f"WR: {(df['net_pnl']>0).mean()*100:.1f}%, "
               f"mean: ${df['net_pnl'].mean():.2f}")
    engine.dispose()


def main():
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    load_start = pd.Timestamp("2023-12-25", tz="UTC")
    load_end = pd.Timestamp("2024-01-15 23:59:59", tz="UTC")
    print(f"Loading {load_start} -> {load_end}...")
    t0 = time.time()
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m "
           f"({time.time()-t0:.0f}s)")
    run_one("1m_momentum", bars_1s, bars_1m)
    run_one("30s_momentum", bars_1s, bars_1m)


if __name__ == "__main__":
    main()
