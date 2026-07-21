"""Run all four entry trigger variants and save one parquet per trigger.

Triggers A/B/C/D defined in collector_triggers.py.
Trigger A replicates the collector.py baseline at depth=0.25.

Usage:
    python studies/pullback_dna/run_triggers.py

Outputs (studies/pullback_dna/results/):
    trigger_A.parquet
    trigger_B.parquet
    trigger_C.parquet
    trigger_D.parquet
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
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

from studies.pullback_dna.collector_triggers import (
    PullbackTriggersConfig,
    PullbackTriggersCollector,
)

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
HC_MAP_PATH  = "collectors/collector_v2/results/combined_arch/hc_perbar_mapping.parquet"
OUT_DIR      = Path("studies/pullback_dna/results")

LEAD_IN = pd.Timedelta(days=7)
START   = pd.Timestamp("2020-01-01", tz="UTC")
END     = pd.Timestamp("2026-12-31 23:59:59", tz="UTC")

TRIGGERS = [
    ("A", 0.25),   # depth used for trigger A; ignored for B/C/D
    ("B", 0.0),
    ("C", 0.0),
    ("D", 0.0),
]


def create_nq() -> FuturesContract:
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def run_one(trigger: str, depth: float, bars_1s: list, nq: FuturesContract) -> list[dict]:
    engine_cfg = BacktestEngineConfig(
        trader_id=f"TRG-{trigger}",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="WARNING",
            log_directory=str(OUT_DIR / "logs"),
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

    cfg   = PullbackTriggersConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        trigger=trigger,
        depth=depth,
        hc_floor=0.50,
        trade_size=1,
        hc_mapping_path=HC_MAP_PATH,
    )
    strat = PullbackTriggersCollector(cfg)
    engine.add_strategy(strat)

    engine.run()
    obs = list(strat.obs_log)
    engine.dispose()
    return obs


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading 1s bars from catalog ...")
    t0  = time.time()
    cat = ParquetDataCatalog(CATALOG_PATH)
    bars_1s = cat.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=START - LEAD_IN,
        end=END,
    )
    print(f"  {len(bars_1s):,} 1s bars loaded in {time.time()-t0:.0f}s")

    nq = create_nq()

    for trigger, depth in TRIGGERS:
        print(f"\nRunning trigger {trigger} ...", flush=True)
        t0  = time.time()
        obs = run_one(trigger, depth, bars_1s, nq)
        elapsed = time.time() - t0

        if obs:
            df   = pd.DataFrame(obs)
            path = OUT_DIR / f"trigger_{trigger}.parquet"
            df.to_parquet(path, index=False)
            n_regimes = df["regime_start_ts"].nunique()
            print(
                f"  {len(obs):,} observations | {n_regimes:,} regimes | "
                f"{elapsed:.0f}s -> {path.name}"
            )
        else:
            print(f"  0 observations in {elapsed:.0f}s")

    print("\nDone.")


if __name__ == "__main__":
    main()
