"""NT BacktestEngine runner for the live-style pre-flip strategy.

One year per invocation. Streams 1s bars from data/catalog/NQ_v0_2020_2026
through the engine; the strategy computes all 20 model features on the
fly, scores a frozen LightGBM model, and trades. bar_execution=True means
market orders fill at the next 1s bar's OPEN.

Usage:
    python backtests/pre_flip_live/run_backtest.py --year 2026
"""
from __future__ import annotations

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
from strategy import PreFlipLiveConfig, PreFlipLiveStrategy  # noqa

FROZEN_DIR = project_root / "studies" / "v_a_excursion_regime" \
    / "results_v0" / "frozen_t1"


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--catalog", default="data/catalog/NQ_v0_2020_2026")
    ap.add_argument("--lead-in-days", type=int, default=5,
                    help="Days of warmup data loaded before Jan 1.")
    ap.add_argument("--feature-log", default="",
                    help="If set, log every candidate's on-stream "
                         "features to this parquet (collection pass).")
    ap.add_argument("--rolling-dir", default="",
                    help="If set, ROLLING mode: directory of monthly "
                         "models + manifest.json.")
    ap.add_argument("--out-suffix", default="",
                    help="Suffix for the results dir (e.g. _rolling).")
    args = ap.parse_args()

    year = args.year
    out_dir = Path(f"backtests/pre_flip_live/results/"
                       f"live_{year}{args.out_suffix}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load the target year plus a lead-in for indicator/ATR warmup.
    # The lead-in bars warm EMAs/ATR; trades placed during lead-in are
    # acceptable but the strategy only fires after all TFs are warm.
    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") \
        - pd.Timedelta(days=args.lead_in_days)
    load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"Year {year}: bar load range {load_start} .. {load_end}")

    catalog = ParquetDataCatalog(args.catalog)
    t0 = time.time()
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s bars  ({time.time()-t0:.0f}s)")
    if not bars_1s:
        print("No bars loaded; aborting.")
        return

    nq = create_nq()
    engine_cfg = BacktestEngineConfig(
        trader_id="PF-LIVE",
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
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)

    strat_cfg = PreFlipLiveConfig(
        instrument_id="NQ.XCME",
        model_path=str(FROZEN_DIR / "model.txt"),
        feature_list_path=str(FROZEN_DIR / "feature_list.json"),
        thresholds_path=str(FROZEN_DIR / "thresholds.json"),
        position_size=1,
        max_hold_s=600,
        feature_log_path=args.feature_log,
        rolling_dir=args.rolling_dir,
    )
    strat = PreFlipLiveStrategy(strat_cfg)
    engine.add_strategy(strat)

    print("\nRunning NT backtest...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time()-t0:.0f}s")

    # ---- Per-trade record from the strategy ----
    trades = pd.DataFrame(strat.all_trades)
    print(f"\nDiag: {strat._diag}")

    if len(trades) == 0:
        print("No completed trades.")
        engine.dispose()
        return

    # Keep only trades whose decision time falls inside the target year
    # (drop any that fired during the lead-in warmup window).
    yr_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr_end_ns = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    in_year = trades[(trades["entry_ts"] >= yr_start_ns)
                     & (trades["entry_ts"] <= yr_end_ns)].copy()
    trades.to_parquet(out_dir / "trades.parquet", index=False)

    closed = in_year
    print(f"\n===== Live-style results — {year} =====")
    print(f"Completed trades (in-year): {len(closed):,}")
    if len(closed) == 0:
        engine.dispose()
        return
    total = closed["net_pnl"].sum()
    print(f"  Total net PnL : ${total:+,.0f}")
    print(f"  Mean          : ${closed['net_pnl'].mean():+.2f}/tr")
    print(f"  Win rate      : {(closed['net_pnl'] > 0).mean():.1%}")
    va = closed[closed["is_va_confirm"]]
    nf = closed[~closed["is_va_confirm"]]
    print(f"  VA-confirm (n={len(va)}): ${va['net_pnl'].sum():+,.0f}"
          f"  mean ${va['net_pnl'].mean() if len(va) else 0:+.2f}/tr")
    print(f"  No-flip   (n={len(nf)}): ${nf['net_pnl'].sum():+,.0f}"
          f"  mean ${nf['net_pnl'].mean() if len(nf) else 0:+.2f}/tr")
    print(f"  Exit reasons  : "
          f"{closed['exit_reason'].value_counts().to_dict()}")
    print(f"  Direction     : "
          f"{closed['direction'].value_counts().to_dict()}")

    engine.dispose()
    print(f"\nResults dir: {out_dir}")


if __name__ == "__main__":
    main()
