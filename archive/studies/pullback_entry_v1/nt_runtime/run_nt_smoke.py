"""Smoke test: 2 weeks Jan 2024 to validate strategy runs."""

from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
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
from pullback_strategy import (  # noqa
    PullbackStrategy, PullbackStrategyConfig)
from run_nt import create_nq  # noqa


def main():
    out_dir = Path("studies/pullback_entry_v1/results/nt_smoke")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 2 weeks
    load_start = pd.Timestamp("2023-12-25", tz="UTC")
    load_end = pd.Timestamp("2024-01-15 23:59:59", tz="UTC")
    print(f"Loading {load_start} -> {load_end}...", flush=True)
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="SMOKE-001",
        logging=LoggingConfig(log_level="WARNING",
                                log_directory=str(out_dir / "logs")),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)], bar_execution=True)
    engine.add_instrument(create_nq())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = PullbackStrategyConfig(
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        output_dir=str(out_dir),
    )
    strat = PullbackStrategy(cfg)
    engine.add_strategy(strat)

    t0 = time.time()
    print("Running...", flush=True)
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")

    positions = engine.trader.generate_positions_report()

    print(f"\nDiag: {strat._diag}")
    print(f"Trade log: {len(strat._trade_log)}")
    print(f"NT positions: {len(positions)}")
    if len(strat._trade_log):
        df = pd.DataFrame(strat._trade_log)
        print("\nFirst 5 trades:")
        print(df[["direction", "atr", "actual_fill_price",
                   "exit_reason", "expected_exit_price",
                   "actual_exit_price", "net_pnl_actual",
                   "net_pnl_ref"]].head().to_string(index=False))
        print(f"\nExit reason counts:")
        print(df["exit_reason"].value_counts())
        print(f"\nNT actual: total ${df['net_pnl_actual'].sum():,.0f}, "
               f"mean ${df['net_pnl_actual'].mean():.2f}")
        print(f"Reference (collector exit): total "
               f"${df['net_pnl_ref'].sum():,.0f}, "
               f"mean ${df['net_pnl_ref'].mean():.2f}")
        print(f"Exit slippage: mean "
               f"${df['exit_slippage_dollars'].mean():.2f}, "
               f"sum ${df['exit_slippage_dollars'].sum():,.0f}")

    engine.dispose()


if __name__ == "__main__":
    main()
