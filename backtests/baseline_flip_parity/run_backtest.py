"""Runner for the baseline flip-parity test. Adapted from
compression_vwap_launchpad/run_backtest.py — same engine config,
different strategy (no filters, both directions, 1-lot bracket).
Now supports loading both 1s and 1m bars to align with the collector.
"""
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
from strategy import BaselineFlipParityConfig, BaselineFlipParityStrategy


PRODUCT_CFG = {
    "NQ": dict(symbol="NQ", multiplier="20", price_increment="0.25",
                bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
                bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
                instrument_id="NQ.XCME",
                catalog="data/catalog/NQ_v0_2020_2026"),
    "ES": dict(symbol="ES", multiplier="50", price_increment="0.25",
                bar_type_1s="ES.XCME-1-SECOND-LAST-EXTERNAL",
                bar_type_1m="ES.XCME-1-MINUTE-LAST-EXTERNAL",
                instrument_id="ES.XCME",
                catalog="data/catalog/ES_v0_2020_2026"),
}


def create_instrument(product: str):
    cfg = PRODUCT_CFG[product]
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
    ap.add_argument("--product", choices=["NQ", "ES"], default="NQ")
    ap.add_argument("--catalog", default=None,
                    help="override product default catalog path")
    ap.add_argument("--lead-in-days", type=int, default=5)
    # Added stall protection arguments
    ap.add_argument("--use-stall-protection", action="store_true", default=False)
    ap.add_argument("--gate-atr", type=float, default=0.5)
    ap.add_argument("--stall-thresh", type=int, default=3)
    ap.add_argument("--ma-period", type=int, default=9)
    ap.add_argument("--ma-type", choices=["SMA", "EMA"], default="SMA")
    ap.add_argument("--trade-side", choices=["both", "long", "short"], default="both")
    ap.add_argument("--entry-type", choices=["flip", "random"], default="flip")
    ap.add_argument("--entry-prob", type=float, default=0.040)
    ap.add_argument("--sl-atr", type=float, default=1.0)
    ap.add_argument("--tp-atr", type=float, default=1.0)
    ap.add_argument("--use-trailing-stop", action="store_true", default=False)
    ap.add_argument("--trail-distance-atr", type=float, default=0.25)
    ap.add_argument("--be-trigger-atr", type=float, default=0.25)
    ap.add_argument("--be-level-atr", type=float, default=0.25)
    ap.add_argument("--suffix", default=None, help="override default results folder suffix")
    args = ap.parse_args()


    product = args.product
    cfg = PRODUCT_CFG[product]
    catalog_path = args.catalog or cfg["catalog"]

    year = args.year
    if args.suffix is not None:
        suffix = args.suffix
    else:
        if args.use_trailing_stop:
            suffix = f"_trail_tp{args.tp_atr}_sl{args.sl_atr}"
        else:
            suffix = "_stall" if args.use_stall_protection else "_base"
        if args.trade_side != "both":
            suffix += f"_{args.trade_side}"
    out_dir = Path(f"backtests/baseline_flip_parity/results/"
                   f"{product.lower()}_live_{year}{suffix}")
    out_dir.mkdir(parents=True, exist_ok=True)


    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=args.lead_in_days)
    load_end   = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"Year {year}: bar load range {load_start} .. {load_end}")

    catalog = ParquetDataCatalog(catalog_path)
    
    t0 = time.time()
    bars_1s = catalog.bars(
        bar_types=[cfg["bar_type_1s"]],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s bars  ({time.time()-t0:.0f}s)")
    
    t1 = time.time()
    bars_1m = catalog.bars(
        bar_types=[cfg["bar_type_1m"]],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1m):,} 1m bars  ({time.time()-t1:.0f}s)")

    if not bars_1s or not bars_1m:
        print("Data missing — aborting")
        return

    inst = create_instrument(product)
    engine_cfg = BacktestEngineConfig(
        trader_id="BASELINE-PARITY",
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

    strat = BaselineFlipParityStrategy(
        BaselineFlipParityConfig(
            instrument_id=cfg["instrument_id"],
            bar_type_1s=cfg["bar_type_1s"],
            bar_type_1m=cfg["bar_type_1m"],
            year=args.year,
            use_stall_protection=args.use_stall_protection,
            gate_atr=args.gate_atr,
            stall_thresh=args.stall_thresh,
            ma_period=args.ma_period,
            ma_type=args.ma_type,
            trade_side=args.trade_side,
            entry_type=args.entry_type,
            entry_prob=args.entry_prob,
            sl_atr=args.sl_atr,
            tp_atr=args.tp_atr,
            use_trailing_stop=args.use_trailing_stop,
            trail_distance_atr=args.trail_distance_atr,
            be_trigger_atr=args.be_trigger_atr,
            be_level_atr=args.be_level_atr,
        )
    )

    engine.add_strategy(strat)

    print("\nRunning backtest...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time()-t0:.0f}s")

    trades = pd.DataFrame(strat.all_trades)
    print(f"\nTotal trades: {len(trades)}")
    if len(trades) > 0:
        yr_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
        yr_end_ns   = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
        in_year = trades[
            (trades["entry_ts"] >= yr_start_ns) &
            (trades["entry_ts"] <= yr_end_ns)].copy()
        print(f"In-year trades: {len(in_year)}")
        if "exit_reason" in in_year.columns:
            print(f"\nExit reasons:\n{in_year['exit_reason'].value_counts().to_string()}")
        if "signal_direction" in in_year.columns:
            print(f"\nBy direction:\n{in_year['signal_direction'].value_counts().to_string()}")
        out_path = out_dir / "trades.parquet"
        in_year.to_parquet(out_path, index=False)
        print(f"\nWrote {len(in_year)} trade records → {out_path}")

    print("\n--- Signal Gate Diagnostics ---")
    for k, v in strat._diag.items():
        print(f"  {k}: {v}")

    engine.dispose()


if __name__ == "__main__":
    main()
