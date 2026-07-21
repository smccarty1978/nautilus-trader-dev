"""Run Pullback Scalp v1 on NQ for one year. Writes to
collectors/collector_v2/results/scalp_v1/<run_label>_<year>/."""

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

from collectors.collector_v2.scalp_strategy import (
    ScalpV1Strategy, ScalpV1Config,
)
from collectors.collector_v2.run_portfolio import (
    PRODUCT_CFG, create_instrument,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="NQ",
                     choices=list(PRODUCT_CFG.keys()))
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--label", default="base")
    ap.add_argument("--pt_atr", type=float, default=0.35)
    ap.add_argument("--sl_atr", type=float, default=0.35)
    ap.add_argument("--max_hold_s", type=int, default=60)
    ap.add_argument("--impulse_body_atr", type=float, default=0.40)
    ap.add_argument("--pullback_min_atr", type=float, default=0.15)
    ap.add_argument("--pullback_max_atr", type=float, default=0.55)
    ap.add_argument("--reaccel_atr", type=float, default=0.10)
    ap.add_argument("--cooldown_s", type=int, default=0)
    args = ap.parse_args()

    pcfg = PRODUCT_CFG[args.product]
    out_dir = Path(
        f"collectors/collector_v2/results/scalp_v1/"
        f"{args.label}_{args.product}_{args.year}")
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(
        f"{args.year}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(
        f"{args.year}-12-31 23:59:59", tz="UTC")
    print(f"[{args.label} {args.product} {args.year}] Loading "
           f"{load_start} -> {load_end}...", flush=True)
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
        print("  NO DATA — skipping"); return

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"SCALP-{args.product[:2]}{str(args.year)[-2:]}-001",
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

    cfg = ScalpV1Config(
        instrument_id=pcfg["instrument_id"],
        bar_type_1m=pcfg["bar_type_1m"],
        bar_type_1s=pcfg["bar_type_1s"],
        rth_only=True,
        position_size=1,
        output_dir=str(out_dir),
        multiplier=pcfg["multiplier"],
        tick_dollar=pcfg["tick_dollar"],
        commission_per_rt=5.0,
        impulse_body_atr=args.impulse_body_atr,
        pullback_min_atr=args.pullback_min_atr,
        pullback_max_atr=args.pullback_max_atr,
        reaccel_atr=args.reaccel_atr,
        pullback_window_s=30,
        reaccel_window_s=30,
        cooldown_s=args.cooldown_s,
        pt_atr=args.pt_atr,
        sl_atr=args.sl_atr,
        max_hold_s=args.max_hold_s,
    )
    strat = ScalpV1Strategy(cfg)
    engine.add_strategy(strat)
    print(f"  Running...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")
    print(f"  Diag: {strat._diag}")
    engine.dispose()


if __name__ == "__main__":
    main()
