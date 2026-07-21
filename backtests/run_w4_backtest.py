import argparse
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
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
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from strategies.w4_exit_strategy import W4ExitConfig, W4ExitStrategy

PRODUCT_CFG = {
    "NQ": dict(symbol="NQ", multiplier="20", price_increment="0.25",
                bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
                bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
                instrument_id="NQ.XCME",
                catalog="data/catalog/NQ_v0_2020_2026"),
}

def create_instrument():
    cfg = PRODUCT_CFG["NQ"]
    t = TestInstrumentProvider.future(
        symbol=cfg["symbol"], underlying=cfg["symbol"],
        venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"] = cfg["multiplier"]
    d["price_increment"] = cfg["price_increment"]
    return FuturesContract.from_dict(d)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--policy", choices=["B0", "B1", "B2", "B3", "B4", "B5"], required=True)
    ap.add_argument("--theta", type=float, default=0.62)
    ap.add_argument("--N", type=int, default=10)
    args = ap.parse_args()

    cfg = PRODUCT_CFG["NQ"]
    catalog_path = cfg["catalog"]
    year = args.year

    out_dir = Path(f"backtests/results/w4_exit_backtests/NQ_{year}_{args.policy}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Lead-in and range
    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"Loading data for year {year} ({load_start} .. {load_end})...")

    catalog = ParquetDataCatalog(catalog_path)
    
    t0 = time.time()
    bars_1s = catalog.bars(
        bar_types=[cfg["bar_type_1s"]],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s bars ({time.time()-t0:.1f}s)")
    
    bars_1m = catalog.bars(
        bar_types=[cfg["bar_type_1m"]],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1m):,} 1m bars ({time.time()-t0:.1f}s)")

    if not bars_1s or not bars_1m:
        print("Data missing — aborting")
        return

    inst = create_instrument()
    
    engine_cfg = BacktestEngineConfig(
        trader_id="W4-BACKTESTER",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="INFO",
            log_directory=str(out_dir / "logs"),
        ),
    )
    
    engine = BacktestEngine(config=engine_cfg)
    engine.add_venue(
        venue=Venue("XCME"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True,
        bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(inst)
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    # Configure Strategy
    # B4 (partial exit) scales out half the position on warning and needs a
    # 2-lot entry; every other policy trades the project standard 1 lot.
    entry_qty = 2 if args.policy == "B4" else 1
    strat_cfg = W4ExitConfig(
        instrument_id=cfg["instrument_id"],
        bar_type_1s=cfg["bar_type_1s"],
        bar_type_1m=cfg["bar_type_1m"],
        year=year,
        entry_qty=entry_qty,
        policy=args.policy,
        theta=args.theta,
        N=args.N
    )
    
    strategy = W4ExitStrategy(config=strat_cfg)
    engine.add_strategy(strategy)

    # Run
    print(f"Running backtest for NQ {year} with policy {args.policy} (theta={args.theta}, N={args.N})...")
    engine.run(start=pd.Timestamp(f"{year}-01-01", tz="UTC"))
    print("Backtest finished.")

    # Save trade reports (generate_trades_report does not exist on NT's Trader —
    # generate_positions_report gives one row per position, but includes still-OPEN
    # positions (ts_closed is NA) alongside closed ones, so filter to closed only)
    trades = engine.trader.generate_positions_report()
    if len(trades) > 0:
        trades = trades[trades["ts_closed"].notna()].copy()
    out_trades = out_dir / "trades.parquet"
    trades.to_parquet(out_trades, index=False)
    print(f"Saved {len(trades)} closed positions to {out_trades}")

    # Also save the strategy's own trade log (entry/exit price, blended PnL for
    # partial exits) since it captures the exact economics used by the W4 policies
    if strategy.all_trades:
        pd.DataFrame(strategy.all_trades).to_parquet(out_dir / "strategy_trades.parquet", index=False)
        print(f"Saved strategy trade log to {out_dir / 'strategy_trades.parquet'}")

    engine.dispose()

if __name__ == "__main__":
    main()
