import argparse
import os
import sys
from pathlib import Path

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
from utils.runner.checkpoint import DailyStateCheckpointer


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", type=str, default="2025-03-01")
    ap.add_argument("--end-date", type=str, default="2025-03-31")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--checkpoint-dir", type=str, default="backtests/results/checkpoints")
    args = ap.parse_args()

    cfg = PRODUCT_CFG["NQ"]
    checkpoint_path = Path(args.checkpoint_dir)
    
    start_dt = pd.Timestamp(args.start_date, tz="UTC")
    end_dt = pd.Timestamp(args.end_date + " 23:59:59", tz="UTC")
    
    # Configure fanning strategy config dict
    strat_cfg_dict = {
        "instrument_id": cfg["instrument_id"],
        "bar_type_1s": cfg["bar_type_1s"],
        "bar_type_1m": cfg["bar_type_1m"],
        "checkpoint_dir": str(checkpoint_path),
        "policies": [
            {"name": "R5", "threshold": 0.62, "sl_atr_mult": 1.5, "pt_atr_mult": 2.0},
            {"name": "R2.5", "threshold": 0.50, "sl_atr_mult": 1.5, "pt_atr_mult": 2.0}
        ]
    }

    # Verify if we should resume from a daily checkpoint
    resume_date_str = None
    if args.resume:
        checkpointer = DailyStateCheckpointer(checkpoint_path)
        resume_date_str = checkpointer.verify_manifest(strat_cfg_dict, {})
        if resume_date_str:
            print(f"Manifest verified. Resuming backtest from state on: {resume_date_str}")
            # Adjust start date to the day after the checkpoint
            start_dt = pd.Timestamp(resume_date_str, tz="UTC") + pd.Timedelta(days=1)
        else:
            print("No valid manifest found matching current configuration. Starting from beginning.")

    if start_dt > end_dt:
        print(f"Start date {start_dt} is past end date {end_dt}. Nothing to run.")
        return

    # Load data using CausalDataLoader (process-local caching)
    data_loader = CausalDataLoader(Path(cfg["catalog"]))
    
    # Pre-load lead-in window for indicators
    lead_start = start_dt - pd.Timedelta(days=5)
    print(f"Loading bars ({lead_start} .. {end_dt})...")
    
    bars_1s = data_loader.load_bars(cfg["bar_type_1s"], lead_start, end_dt)
    bars_1m = data_loader.load_bars(cfg["bar_type_1m"], lead_start, end_dt)
    
    print(f"Loaded {len(bars_1s):,} 1s bars and {len(bars_1m):,} 1m bars.")

    engine_cfg = BacktestEngineConfig(
        trader_id="STAGED-BACKTESTER",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="INFO",
            log_directory=str(checkpoint_path / "logs"),
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

    strat_cfg = ScoreFanningConfig(**strat_cfg_dict)
    strategy = ScoreFanningStrategy(config=strat_cfg)
    
    # Restore checkpoint state in strategy if resuming
    if resume_date_str:
        strategy.load_daily_checkpoint(resume_date_str)
        
    engine.add_strategy(strategy)

    print(f"Running backtest from {start_dt} to {end_dt}...")
    engine.run(start=start_dt, end=end_dt)
    print("Backtest run finished.")

    # Save final evaluator results
    for evalr in strategy.evaluators:
        trades_list = evalr.trade_history + evalr.active_trades
        if trades_list:
            df = pd.DataFrame([
                {
                    "trade_id": t.trade_id,
                    "entry_time": t.entry_time,
                    "entry_px": t.entry_px,
                    "direction": t.direction,
                    "qty": t.qty,
                    "atr": t.atr_at_entry,
                    "exit_time": t.exit_time,
                    "exit_px": t.exit_px,
                    "exit_reason": t.exit_reason,
                    "pnl": t.pnl,
                    "is_open": t.is_open
                }
                for t in trades_list
            ])
            out_file = checkpoint_path / f"results_{evalr.name}.parquet"
            df.to_parquet(out_file, index=False)
            print(f"Saved {len(trades_list)} trades for policy {evalr.name} to {out_file}")

    engine.dispose()


if __name__ == "__main__":
    main()
