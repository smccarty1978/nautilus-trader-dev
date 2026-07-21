import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from strategies.score_fanning_strategy import ScoreFanningConfig, ScoreFanningStrategy
from utils.runner.data import CausalDataLoader

PRODUCT_CFG = {
    "NQ": dict(
        symbol="NQ",
        multiplier="20",
        price_increment="0.25",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        instrument_id="NQ.XCME",
        catalog="data/catalog/NQ_v0_2020_2026"
    ),
}


def create_instrument():
    cfg = PRODUCT_CFG["NQ"]
    t = TestInstrumentProvider.future(
        symbol=cfg["symbol"], underlying=cfg["symbol"],
        venue="XCME", exchange="XCME"
    )
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"] = cfg["multiplier"]
    d["price_increment"] = cfg["price_increment"]
    return FuturesContract.from_dict(d)


# Worker execution function
def run_worker_backtest(params: Dict[str, Any]) -> Dict[str, Any]:
    """Runs a single process-isolated backtest variant."""
    # Enforce process-local loading from CausalDataLoader cache
    cfg = PRODUCT_CFG["NQ"]
    loader = CausalDataLoader(Path(cfg["catalog"]))
    
    start_dt = pd.Timestamp(params["start_date"], tz="UTC")
    end_dt = pd.Timestamp(params["end_date"] + " 23:59:59", tz="UTC")
    lead_start = start_dt - pd.Timedelta(days=5)

    # Loads from cache if already loaded by this worker process (Priority 4)
    bars_1s = loader.load_bars(cfg["bar_type_1s"], lead_start, end_dt)
    bars_1m = loader.load_bars(cfg["bar_type_1m"], lead_start, end_dt)

    checkpoint_path = Path(params["checkpoint_dir"])
    
    engine_cfg = BacktestEngineConfig(
        trader_id=f"SWEEP-{params['variant_name']}",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="INFO",
            log_directory=str(checkpoint_path / f"logs_{params['variant_name']}"),
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
    
    inst = create_instrument()
    engine.add_instrument(inst)
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    strat_cfg = ScoreFanningConfig(
        instrument_id=cfg["instrument_id"],
        bar_type_1s=cfg["bar_type_1s"],
        bar_type_1m=cfg["bar_type_1m"],
        checkpoint_dir=str(checkpoint_path / params["variant_name"]),
        policies=params["policies"]
    )
    strategy = ScoreFanningStrategy(config=strat_cfg)
    engine.add_strategy(strategy)

    print(f"[{params['variant_name']}] Running backtest from {start_dt} to {end_dt}...")
    engine.run(start=start_dt, end=end_dt)
    
    results = {}
    for evalr in strategy.evaluators:
        trades = evalr.trade_history + evalr.active_trades
        total_pnl = sum(t.pnl for t in trades)
        results[evalr.name] = {
            "trade_count": len(trades),
            "total_pnl": total_pnl
        }
        
    engine.dispose()
    return {"variant": params["variant_name"], "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    checkpoint_dir = Path("backtests/results/sweeps")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Declare parameter variants to run
    variants = [
        {
            "variant_name": "set_A",
            "start_date": "2025-03-01",
            "end_date": "2025-03-31",
            "checkpoint_dir": str(checkpoint_dir),
            "policies": [
                {"name": "R5_tight", "threshold": 0.62, "sl_atr_mult": 1.0, "pt_atr_mult": 1.5},
                {"name": "R2.5_tight", "threshold": 0.50, "sl_atr_mult": 1.0, "pt_atr_mult": 1.5}
            ]
        },
        {
            "variant_name": "set_B",
            "start_date": "2025-03-01",
            "end_date": "2025-03-31",
            "checkpoint_dir": str(checkpoint_dir),
            "policies": [
                {"name": "R5_wide", "threshold": 0.62, "sl_atr_mult": 2.0, "pt_atr_mult": 3.0},
                {"name": "R2.5_wide", "threshold": 0.50, "sl_atr_mult": 2.0, "pt_atr_mult": 3.0}
            ]
        }
    ]

    print(f"Starting parameter sweep with {args.workers} workers...")
    
    # Run isolated sweeps in parallel
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_worker_backtest, var) for var in variants]
        for fut in futures:
            res = fut.result()
            print(f"Completed Variant: {res['variant']}")
            for policy, metrics in res["results"].items():
                print(f"  Policy {policy} -> Trades: {metrics['trade_count']}, PnL: ${metrics['total_pnl']:.2f}")


if __name__ == "__main__":
    main()
