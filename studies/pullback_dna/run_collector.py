"""Pullback DNA Atlas — BacktestEngine runner.

Runs PullbackDNACollector for three pullback depths (0.25 / 0.50 / 0.75 ATR)
across the full available history (2020–2026).  Saves one parquet per depth.

Usage:
    python studies/pullback_dna/run_collector.py

Outputs:
    studies/pullback_dna/results/obs_depth025.parquet
    studies/pullback_dna/results/obs_depth050.parquet
    studies/pullback_dna/results/obs_depth075.parquet
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

from studies.pullback_dna.collector import PullbackDNAConfig, PullbackDNACollector

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
HC_MAP_PATH  = "collectors/collector_v2/results/combined_arch/hc_perbar_mapping.parquet"
OUT_DIR      = Path("studies/pullback_dna/results")
DEPTHS       = [0.25, 0.50, 0.75]

# 7-day lead-in for indicator warmup
LEAD_IN = pd.Timedelta(days=7)
START   = pd.Timestamp("2020-01-01", tz="UTC")
END     = pd.Timestamp("2026-12-31 23:59:59", tz="UTC")


# ── Instrument ─────────────────────────────────────────────────────────────────

def create_nq() -> FuturesContract:
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


# ── Single depth run ───────────────────────────────────────────────────────────

def run_one(depth: float, bars_1s: list, nq: FuturesContract) -> list[dict]:
    engine_cfg = BacktestEngineConfig(
        trader_id=f"DNA-{depth:.2f}",
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

    cfg = PullbackDNAConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        depth=depth,
        hc_floor=0.50,
        trade_size=1,
        hc_mapping_path=HC_MAP_PATH,
    )
    strat = PullbackDNACollector(cfg)
    engine.add_strategy(strat)

    engine.run()
    obs = list(strat.obs_log)
    engine.dispose()
    return obs


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading 1s bars from catalog …")
    t0  = time.time()
    cat = ParquetDataCatalog(CATALOG_PATH)
    bars_1s = cat.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=START - LEAD_IN,
        end=END,
    )
    print(f"  {len(bars_1s):,} 1s bars loaded in {time.time()-t0:.0f}s")

    nq = create_nq()

    for depth in DEPTHS:
        print(f"\nRunning depth={depth} …", flush=True)
        t0  = time.time()
        obs = run_one(depth, bars_1s, nq)
        elapsed = time.time() - t0

        if obs:
            df    = pd.DataFrame(obs)
            label = str(depth).replace(".", "p")
            path  = OUT_DIR / f"obs_depth{label}.parquet"
            df.to_parquet(path, index=False)
            n_regimes = df["regime_start_ts"].nunique()
            print(
                f"  {len(obs):,} observations | {n_regimes:,} regimes | "
                f"{elapsed:.0f}s → {path.name}"
            )
        else:
            print(f"  0 observations in {elapsed:.0f}s")

    print("\nDone.")


if __name__ == "__main__":
    main()
