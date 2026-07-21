"""Runner for the Regime Flip Truth Collector.

Loads 1s bars from the SAFE catalog (NQ_v0_2020_2026, closed='left' build),
runs the research-mode collector (NO ORDERS), and writes two datasets per year:

    flip_truth_dataset_{year}.parquet        (one row per event)
    flip_checkpoint_dataset_{year}.parquet   (one row per event per checkpoint)

24h collection with an rth_flag tag on each event. A lead-in window warms the
streaming indicators / regime engine; events whose entry falls before Jan 1 of
the target year are dropped.

Usage:
    python studies/regime_flip_truth/run_collector.py --year 2021
    python studies/regime_flip_truth/run_collector.py --year 2021 --smoke 7
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
from collector import RegimeFlipTruthCollector, RegimeFlipTruthConfig  # noqa: E402

CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
INSTRUMENT_ID = "NQ.XCME"
OUT_DIR = Path("studies/regime_flip_truth/results")


def create_instrument():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"] = "20"
    d["price_increment"] = "0.25"
    return FuturesContract.from_dict(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--lead-in-days", type=int, default=3)
    ap.add_argument("--smoke", type=int, default=0,
                    help="If >0, collect only the first N days of the year "
                         "(causality smoke test).")
    args = ap.parse_args()
    year = args.year

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    load_start = (pd.Timestamp(f"{year}-01-01", tz="UTC")
                  - pd.Timedelta(days=args.lead_in_days))
    if args.smoke > 0:
        load_end = pd.Timestamp(f"{year}-01-01", tz="UTC") + pd.Timedelta(days=args.smoke)
    else:
        load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"Year {year}: bar load range {load_start} .. {load_end}"
          f"{'  [SMOKE]' if args.smoke else ''}")

    catalog = ParquetDataCatalog(CATALOG)
    t0 = time.time()
    bars_1s = catalog.bars(bar_types=[BAR_TYPE], start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s bars  ({time.time()-t0:.0f}s)")
    if not bars_1s:
        print("  No bars; aborting.")
        return

    inst = create_instrument()
    engine_cfg = BacktestEngineConfig(
        trader_id="FLIP-TRUTH",
        logging=LoggingConfig(log_level="ERROR", log_level_file="WARNING",
                              log_directory=str(OUT_DIR / "logs")),
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

    strat = RegimeFlipTruthCollector(
        RegimeFlipTruthConfig(instrument_id=INSTRUMENT_ID, bar_type_1s=BAR_TYPE))
    engine.add_strategy(strat)

    print("\nRunning collector (research mode, no orders)...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time()-t0:.0f}s")

    print("\n--- Collector Diagnostics ---")
    for k, v in strat._diag.items():
        print(f"  {k}: {v}")

    engine.dispose()

    events = pd.DataFrame(strat.events)
    checks = pd.DataFrame(strat.checkpoints)
    print(f"\nRaw events: {len(events):,}   checkpoints: {len(checks):,}")
    if len(events) == 0:
        print("  No events; aborting save.")
        return

    # Drop lead-in events (entry before Jan 1 of target year).
    yr_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr_end_ns = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    in_year = events[(events["entry_ts"] >= yr_start_ns)
                     & (events["entry_ts"] <= yr_end_ns)].copy()
    keep_ids = set(in_year["event_id"])
    in_year_ck = checks[checks["event_id"].isin(keep_ids)].copy()
    print(f"In-year events: {len(in_year):,}   checkpoints: {len(in_year_ck):,}")

    suffix = f"_smoke{args.smoke}" if args.smoke else ""
    ev_path = OUT_DIR / f"flip_truth_dataset_{year}{suffix}.parquet"
    ck_path = OUT_DIR / f"flip_checkpoint_dataset_{year}{suffix}.parquet"
    in_year.to_parquet(ev_path, index=False)
    in_year_ck.to_parquet(ck_path, index=False)
    print(f"\nWrote {ev_path}")
    print(f"Wrote {ck_path}")

    # quick orientation print
    print("\n--- Quick orientation (in-year) ---")
    for pop in ("A", "B"):
        sub = in_year[in_year["population"] == pop]
        if len(sub) == 0:
            continue
        warm = sub[sub["warmed_up"]]
        print(f"  Population {pop}: n={len(sub):,} (warmed={len(warm):,})  "
              f"rth={sub['rth_flag'].mean():.0%}  "
              f"clean_A={warm['clean_trend_a'].mean():.1%}  "
              f"elite={warm['elite_trend'].mean():.1%}  "
              f"reach2ATR={warm['reached_2_0_atr'].mean():.1%}")


if __name__ == "__main__":
    main()
