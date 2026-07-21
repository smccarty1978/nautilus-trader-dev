"""Run V_A baseline through Collector V2 for one (product, year).

Outputs:
  collectors/collector_v2/results/portfolio/<product>_<year>/
    snapshots.parquet  (with `session` tag)
    trades.parquet     (with `session` tag)
    diag.json

Per-product config covers multiplier, tick$, and catalog selection.
RTH/ETH/ALL split is done in the analyzer using the snapshot/trade
session column — single run captures both sessions.
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
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from collectors.collector_v2.strategy import (
    CollectorV2Strategy, CollectorV2Config,
)


# Per-product configuration
PRODUCT_CFG = {
    "NQ": {
        "catalog": "data/catalog/NQ_2020_2025",
        "venue": "XCME",
        "instrument_id": "NQ.XCME",
        "bar_type_1m": "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        "bar_type_1s": "NQ.XCME-1-SECOND-LAST-EXTERNAL",
        "multiplier": 20.0,
        "tick_dollar": 5.0,    # 0.25 * 20
        "price_increment": "0.25",
    },
    "ES": {
        "catalog": "data/catalog/ES_multi_year",
        "venue": "XCME",
        "instrument_id": "ES.XCME",
        "bar_type_1m": "ES.XCME-1-MINUTE-LAST-EXTERNAL",
        "bar_type_1s": "ES.XCME-1-SECOND-LAST-EXTERNAL",
        "multiplier": 50.0,
        "tick_dollar": 12.50,  # 0.25 * 50
        "price_increment": "0.25",
    },
    "YM": {
        "catalog": "data/catalog/YM_multi_year",
        "venue": "XCBT",
        "instrument_id": "YM.XCBT",
        "bar_type_1m": "YM.XCBT-1-MINUTE-LAST-EXTERNAL",
        "bar_type_1s": "YM.XCBT-1-SECOND-LAST-EXTERNAL",
        "multiplier": 5.0,
        "tick_dollar": 5.0,    # 1 * 5
        "price_increment": "1",   # precision 0 (integer YM prices)
    },
}


def create_instrument(product: str, cfg: dict):
    t = TestInstrumentProvider.future(
        symbol=product, underlying=product,
        venue=cfg["venue"], exchange=cfg["venue"])
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp(
        "2030-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp(
        "2019-01-01", tz="UTC").value
    d["multiplier"] = str(int(cfg["multiplier"]))
    d["price_increment"] = cfg["price_increment"]
    # price_precision must match the increment's precision
    if "." in cfg["price_increment"]:
        d["price_precision"] = len(cfg["price_increment"].split(".")[1])
    else:
        d["price_precision"] = 0
    return FuturesContract.from_dict(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True,
                     choices=list(PRODUCT_CFG.keys()))
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    pcfg = PRODUCT_CFG[args.product]
    out_dir = Path(
        f"collectors/collector_v2/results/portfolio/"
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
        print(f"  NO DATA — skipping {args.product} {args.year}")
        return

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"PORT-{args.product[:2]}{str(args.year)[-2:]}-001",
        logging=LoggingConfig(
            log_level="WARNING",
            log_directory=str(out_dir / "logs"),
        ),
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
        rth_only=False,                # capture ALL flips
        position_size=1,
        require_5m_aligned=False,
        output_dir=str(out_dir),
        multiplier=pcfg["multiplier"],
        tick_dollar=pcfg["tick_dollar"],
        commission_per_rt=5.0,
    )
    strat = CollectorV2Strategy(cfg)
    engine.add_strategy(strat)

    print(f"  Running...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")
    print(f"  Diag: {strat._diag}")
    engine.dispose()


if __name__ == "__main__":
    main()
