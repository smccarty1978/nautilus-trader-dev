"""Run V_A + 5m-aligned NT strategy."""

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
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

sys.path.insert(0, str(Path(__file__).parent))
from nt_strategy import (  # noqa
    MomentumConfirm5mStrategy, MomentumConfirm5mConfig)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-5m-gate", action="store_true",
                     help="Disable 5m alignment (for parity sanity)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir or
                     f"studies/momentum_confirm_5m_v1/results/"
                     f"nt_{args.year}")
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(f"{args.year}-01-01", tz="UTC") \
                    - pd.Timedelta(days=10)
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
           f"({time.time() - t0:.0f}s)")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"M5-{args.year}",
        logging=LoggingConfig(
            log_level="WARNING",
            log_directory=str(out_dir / "logs"),
        ),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True)
    engine.add_instrument(create_nq())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = MomentumConfirm5mConfig(
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        rth_only=True,
        position_size=1,
        require_5m_aligned=not args.no_5m_gate,
        output_dir=str(out_dir),
    )
    strat = MomentumConfirm5mStrategy(cfg)
    engine.add_strategy(strat)

    print("Running...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")

    positions = engine.trader.generate_positions_report()
    print(f"\nDiag: {strat._diag}")
    print(f"Trade log: {len(strat._trade_log)} trades")
    print(f"NT positions: {len(positions):,}")

    engine.dispose()
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
