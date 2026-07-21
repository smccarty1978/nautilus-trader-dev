"""Trigger C structural test: pullback depth × initial stop width matrix.

Architecture (fixed):
  Trigger C + lock@+1.00A -> +0.25A floor + regime-flip exit
  hc_floor=0.50, bar_filter="none"

Matrix (5 variants):
  V1  baseline       min_pb_depth=0.00  initial_stop=0.50A  (baseline)
  V2  base_075sl     min_pb_depth=0.00  initial_stop=0.75A
  V3  depth075_050sl min_pb_depth=0.75  initial_stop=0.50A
  V4  depth075_075sl min_pb_depth=0.75  initial_stop=0.75A
  V5  depth100_075sl min_pb_depth=1.00  initial_stop=0.75A

Date range: 2024-07-01 to 2025-06-30 (12-month primary)
Lead-in:    7 days for regime warmup

Outputs: studies/pullback_dna/results/depth_sl_study/
  depth_sl_baseline.parquet
  depth_sl_base_075sl.parquet
  depth_sl_depth075_050sl.parquet
  depth_sl_depth075_075sl.parquet
  depth_sl_depth100_075sl.parquet
"""
from __future__ import annotations
import os, sys, time
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

from studies.pullback_dna.strategy_c_lock import CLockConfig, CLockStrategy

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
OUT_DIR      = Path("studies/pullback_dna/results/depth_sl_study")

LEAD_IN = pd.Timedelta(days=7)
START   = pd.Timestamp("2024-07-01", tz="UTC")
END     = pd.Timestamp("2025-06-30 23:59:59", tz="UTC")

# (name, min_pb_depth_atr, initial_stop_atr)
VARIANTS = [
    ("baseline",        0.00, 0.50),
    ("base_075sl",      0.00, 0.75),
    ("depth075_050sl",  0.75, 0.50),
    ("depth075_075sl",  0.75, 0.75),
    ("depth100_075sl",  1.00, 0.75),
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


def run_one(name: str, min_pb_depth: float, initial_stop: float,
            bars_1s: list, nq: FuturesContract) -> list[dict]:
    engine_cfg = BacktestEngineConfig(
        trader_id=f"DSS-{name.upper()[:8]}",
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

    cfg = CLockConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        initial_stop_atr=initial_stop,
        lock_at_atr=1.00,
        lock_floor_atr=0.25,
        hc_floor=0.50,
        trade_size=1,
        bar_filter="none",
        min_pb_depth_atr=min_pb_depth,
    )
    strat = CLockStrategy(cfg)
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

    for name, min_pb_depth, initial_stop in VARIANTS:
        label = f"depth>={min_pb_depth:.2f} / SL={initial_stop:.2f}A"
        print(f"\nRunning {name}: {label} ...", flush=True)
        t0  = time.time()
        obs = run_one(name, min_pb_depth, initial_stop, bars_1s, nq)
        elapsed = time.time() - t0

        if obs:
            df = pd.DataFrame(obs)
            df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
            df = df[df["entry_dt"] >= START].copy()
            df.drop(columns=["entry_dt"], inplace=True)
            path = OUT_DIR / f"depth_sl_{name}.parquet"
            df.to_parquet(path, index=False)
            n_regimes = df["regime_start_ts"].nunique()
            print(f"  {len(obs):,} total | {len(df):,} in window | "
                  f"{n_regimes:,} regimes | {elapsed:.0f}s -> {path.name}")
        else:
            print(f"  0 observations in {elapsed:.0f}s")

    print("\nDone.")


if __name__ == "__main__":
    main()
