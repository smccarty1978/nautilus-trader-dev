"""1m Regime Flip Study — Run 2020-2025 Collection.

Runs FlipStudyCollector on NQ 2020-2025 (1s + 1m bars).
No orders submitted — pure data collection.

Outputs per-year and combined parquet files.
"""

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
    str(project_root / "studies" / "1m_regime_flip_study" / "collector.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
FlipStudyCollector = _mod.FlipStudyCollector
FlipStudyConfig = _mod.FlipStudyConfig


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
    print("1m REGIME FLIP STUDY — NQ 2020-2025")
    print("  Enter every flip at bar+1 open")
    print("  Track flip bar size + HH/LL exits + 1s MFE/MAE")
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
    load_time = _time.time() - t0
    print(f"  1s bars: {len(bars_1s):,}")
    print(f"  1m bars: {len(bars_1m):,}")
    print(f"  Load: {load_time:.0f}s")

    config = FlipStudyConfig(strategy_id="FLIP-STUDY-01")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="FLIP-STUDY-001",
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

    strat = FlipStudyCollector(config)
    engine.add_strategy(strat)

    print("\nRunning collector...", flush=True)
    t0 = _time.time()
    engine.run()
    elapsed = _time.time() - t0
    engine.dispose()

    print(f"Done in {elapsed:.0f}s.")

    results = strat._results
    if not results:
        print("NO TRADES")
        return

    df = pd.DataFrame(results)
    n = len(df)
    print(f"\nTotal trades: {n:,}")

    # Save
    out_dir = Path("studies/1m_regime_flip_study/results")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Combined
    df.to_parquet(out_dir / "flips_all.parquet", index=False)
    print(f"Saved flips_all.parquet ({n:,} trades x {len(df.columns)} cols)")

    # Per year
    if "year" in df.columns:
        for year in sorted(df["year"].unique()):
            ydf = df[df["year"] == year]
            ydf.to_parquet(out_dir / f"flips_{year}.parquet", index=False)
            print(f"  {year}: {len(ydf):,} trades")

    # Checkpoint
    checkpoint = {
        "run_time": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "bars_1s": len(bars_1s),
        "bars_1m": len(bars_1m),
        "trades": n,
        "columns": len(df.columns),
    }
    with open(out_dir.parent / "checkpoint.yaml", "w") as f:
        yaml.dump(checkpoint, f, default_flow_style=False)

    # ---- Summary ----
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}\n")

    # Overall
    avg_regime = df["regime_pnl_dollars"].mean()
    print(f"Regime exit baseline: avg ${avg_regime:+.1f}/trade, "
          f"total ${df['regime_pnl_dollars'].sum():+,.0f}")

    # Bar+1 HH check
    hh_yes = df[df["bar1_made_hh"] == 1]
    hh_no = df[df["bar1_made_hh"] == 0]
    print(f"\nBar+1 made HH: {len(hh_yes):,} ({len(hh_yes)/n*100:.1f}%), "
          f"regime PnL ${hh_yes['regime_pnl_dollars'].mean():+.1f}")
    print(f"Bar+1 no HH:   {len(hh_no):,} ({len(hh_no)/n*100:.1f}%), "
          f"regime PnL ${hh_no['regime_pnl_dollars'].mean():+.1f}")

    # HH exit comparison
    print(f"\nExit comparison:")
    print(f"  {'Strategy':<35} {'Avg$':>8} {'Total$':>11}")
    print(f"  {'-'*56}")
    print(f"  {'Regime exit (baseline)':<35} "
          f"{avg_regime:>+7.1f} {df['regime_pnl_dollars'].sum():>+10,.0f}")

    for thresh in [1, 2, 3]:
        col = f"hh_exit_{thresh}_pnl_dollars"
        vals = df[col].dropna()
        # For trades where HH exit didn't trigger, use regime exit
        combined = df[col].fillna(df["regime_pnl_dollars"])
        print(f"  {'HH exit ' + str(thresh) + ' (pure)':<35} "
              f"{vals.mean():>+7.1f} {vals.sum():>+10,.0f} "
              f"({len(vals):,} triggered)")
        print(f"  {'HH exit ' + str(thresh) + ' (fallback regime)':<35} "
              f"{combined.mean():>+7.1f} {combined.sum():>+10,.0f}")

    for thresh in [1, 2, 3]:
        col = f"combined_bar1_hh{thresh}_pnl_dollars"
        print(f"  {'Bar1 filter + HH exit ' + str(thresh):<35} "
              f"{df[col].mean():>+7.1f} {df[col].sum():>+10,.0f}")

    # Flip bar size buckets
    print(f"\nFlip bar size vs regime PnL:")
    print(f"  {'Bucket':<15} {'N':>7} {'Avg$':>8} {'WR':>6} {'Bar1HH%':>8}")
    print(f"  {'-'*48}")
    for lo, hi, label in [(0, 1.0, "<1.0"),
                          (1.0, 1.5, "1.0-1.5"),
                          (1.5, 2.0, "1.5-2.0"),
                          (2.0, 99, ">2.0")]:
        sub = df[(df["flip_bar_range_atr"] >= lo) &
                 (df["flip_bar_range_atr"] < hi)]
        if len(sub) > 0:
            wr = (sub["regime_pnl_dollars"] > 0).mean() * 100
            b1 = sub["bar1_made_hh"].mean() * 100
            print(f"  {label:<15} {len(sub):>7,} "
                  f"{sub['regime_pnl_dollars'].mean():>+7.1f} "
                  f"{wr:>5.1f}% {b1:>7.1f}%")

    # Per year
    print(f"\nPer-year regime exit PnL:")
    print(f"  {'Year':>6} {'N':>7} {'Avg$':>8} {'Total$':>10} {'WR':>6}")
    print(f"  {'-'*42}")
    for year in sorted(df["year"].unique()):
        ydf = df[df["year"] == year]
        wr = (ydf["regime_pnl_dollars"] > 0).mean() * 100
        print(f"  {year:>6} {len(ydf):>7,} "
              f"{ydf['regime_pnl_dollars'].mean():>+7.1f} "
              f"{ydf['regime_pnl_dollars'].sum():>+9,.0f} {wr:>5.1f}%")

    # RTH vs ETH
    rth = df[df["is_rth"] == 1]
    eth = df[df["is_rth"] == 0]
    print(f"\nRTH: {len(rth):,} trades, "
          f"avg ${rth['regime_pnl_dollars'].mean():+.1f}")
    print(f"ETH: {len(eth):,} trades, "
          f"avg ${eth['regime_pnl_dollars'].mean():+.1f}")

    print(f"\n{'='*70}")
    print("COLLECTION COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
