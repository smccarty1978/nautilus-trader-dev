"""1m Confirmed Flip — Run 2020-2025 Collection."""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import time as _time
import yaml
from datetime import datetime

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.enums import OmsType, AccountType
from nautilus_trader.model.objects import Money
from nautilus_trader.model.currencies import USD
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "collector",
    str(project_root / "studies" / "1m_confirmed_flip" / "collector.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ConfirmedFlipCollector = _mod.ConfirmedFlipCollector
ConfirmedFlipConfig = _mod.ConfirmedFlipConfig


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2025-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def main():
    print("=" * 70)
    print("1m CONFIRMED FLIP COLLECTOR — NQ 2020-2025")
    print("  Entry: bar+1 close after HH/LL confirmation")
    print("  Track HH/HL/LH/LL on all bars, record all exit triggers")
    print("=" * 70)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    start = pd.Timestamp("2020-01-01", tz="UTC")
    end = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")

    print("\nLoading data...", flush=True)
    t0 = _time.time()
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start, end=end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=start, end=end)
    print(f"  1s bars: {len(bars_1s):,}")
    print(f"  1m bars: {len(bars_1m):,}")
    print(f"  Load: {_time.time()-t0:.0f}s")

    config = ConfirmedFlipConfig(strategy_id="CONFIRMED-FLIP-01")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="CONFIRMED-FLIP-001",
        logging=LoggingConfig(log_level="ERROR"),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(create_nq())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    strat = ConfirmedFlipCollector(config)
    engine.add_strategy(strat)

    print("\nRunning collector...", flush=True)
    t0 = _time.time()
    engine.run()
    elapsed = _time.time() - t0
    engine.dispose()
    print(f"Done in {elapsed:.0f}s.")

    results = strat._results
    skipped = strat._skipped

    if not results:
        print("NO TRADES")
        return

    df = pd.DataFrame(results)
    sf = pd.DataFrame(skipped) if skipped else pd.DataFrame()
    n = len(df)

    # Save
    out_dir = Path("studies/1m_confirmed_flip/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "trades_all.parquet", index=False)
    if len(sf) > 0:
        sf.to_parquet(out_dir / "skipped_flips.parquet", index=False)

    if "year" in df.columns:
        for year in sorted(df["year"].unique()):
            ydf = df[df["year"] == year]
            ydf.to_parquet(out_dir / f"trades_{year}.parquet", index=False)

    print(f"\nSaved {n:,} trades x {len(df.columns)} cols")
    if len(sf) > 0:
        print(f"Saved {len(sf):,} skipped flips")

    # Checkpoint
    checkpoint = {
        "run_time": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "bars_1s": len(bars_1s),
        "bars_1m": len(bars_1m),
        "trades": n,
        "skipped_flips": len(sf) if len(sf) > 0 else 0,
    }
    with open(out_dir.parent / "checkpoint.yaml", "w") as f:
        yaml.dump(checkpoint, f, default_flow_style=False)

    # ---- Summary ----
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"  Trades (confirmed entries): {n:,}")
    if len(sf) > 0:
        print(f"  Skipped (no bar+1 HH): {len(sf):,}")
        total_flips = n + len(sf)
        print(f"  Total flips: {total_flips:,}")
        print(f"  Confirm rate: {n/total_flips*100:.1f}%")

    # Regime exit baseline
    print(f"\n  Regime exit baseline:")
    print(f"    Avg: ${df['regime_pnl_dollars'].mean():+.1f}")
    print(f"    Total: ${df['regime_pnl_dollars'].sum():+,.0f}")

    # Exit triggers — compute weighted PnL (use trigger when triggered, else regime)
    print(f"\n  Exit trigger comparison (fallback = regime exit):")
    print(f"  {'Exit':<18} {'Trig%':>6} {'Avg$':>8} {'Total$':>11}")
    print(f"  {'-'*48}")

    for name in ["hh1_stall", "hh2_stall", "hh3_stall",
                 "first_ll", "second_ll", "first_lh",
                 "first_lh_ll", "hl_break"]:
        col = f"{name}_pnl_dollars"
        if col not in df.columns:
            continue
        trig = df[col].notna().sum()
        combined = df[col].fillna(df["regime_pnl_dollars"])
        avg = combined.mean()
        total = combined.sum()
        print(f"  {name:<18} {trig/n*100:>5.1f}% "
              f"{avg:>+7.1f} {total:>+10,.0f}")

    # Per year for regime baseline
    print(f"\n  Regime exit by year:")
    print(f"  {'Year':>6} {'N':>7} {'Avg$':>8} {'Total$':>10} {'WR':>6}")
    print(f"  {'-'*42}")
    for year in sorted(df["year"].unique()):
        ydf = df[df["year"] == year]
        wr = (ydf["regime_pnl_dollars"] > 0).mean() * 100
        print(f"  {year:>6} {len(ydf):>7,} "
              f"{ydf['regime_pnl_dollars'].mean():>+7.1f} "
              f"{ydf['regime_pnl_dollars'].sum():>+9,.0f} {wr:>5.1f}%")

    # RTH/ETH
    for val, lbl in [(1, "RTH"), (0, "ETH")]:
        s = df[df["is_rth"] == val]
        if len(s):
            print(f"  {lbl}: {len(s):,} avg "
                  f"${s['regime_pnl_dollars'].mean():+.1f}")

    # Skipped flips counterfactual
    if len(sf) > 0:
        print(f"\n  Skipped flips analysis:")
        print(f"    Count: {len(sf):,}")
        print(f"    These would have lost money at -$99/trade avg in prior study")
        print(f"    By skipping them, we avoid the bar+1 close exit losses")

    print(f"\n{'='*70}")
    print("COLLECTION COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
