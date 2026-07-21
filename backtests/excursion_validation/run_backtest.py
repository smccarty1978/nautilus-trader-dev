import argparse
import os
import sys
import time
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
from config import ExcursionValidationConfig
from strategy import ExcursionValidationStrategy

def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--catalog", default="data/catalog/NQ_v0_2020_2026")
    ap.add_argument("--lead-in-days", type=int, default=5)
    args = ap.parse_args()

    year = args.year
    out_dir = Path(f"backtests/excursion_validation/results/live_{year}")
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=args.lead_in_days)
    load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"Year {year}: bar load range {load_start} .. {load_end}")

    catalog = ParquetDataCatalog(args.catalog)
    t0 = time.time()
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s bars  ({time.time()-t0:.0f}s)")
    if not bars_1s:
        print("No bars loaded; aborting.")
        return

    nq = create_nq()
    engine_cfg = BacktestEngineConfig(
        trader_id="EXC-VAL",
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
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)

    strat_cfg = ExcursionValidationConfig(
        instrument_id="NQ.XCME",
        position_size=1,
    )
    strat = ExcursionValidationStrategy(strat_cfg)
    engine.add_strategy(strat)

    print("\nRunning NT backtest...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time()-t0:.0f}s")

    trades = pd.DataFrame(strat.all_trades)
    
    if len(trades) == 0:
        print("No completed trades.")
        engine.dispose()
        return

    yr_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr_end_ns = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    in_year = trades[(trades["entry_ts"] >= yr_start_ns) & (trades["entry_ts"] <= yr_end_ns)].copy()
    
    out_path = out_dir / "trades.parquet"
    in_year.to_parquet(out_path, index=False)
    print(f"Wrote {len(in_year)} trades to {out_path}")

    engine.dispose()

if __name__ == "__main__":
    main()
