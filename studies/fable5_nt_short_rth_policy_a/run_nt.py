"""BacktestEngine runner for NT event-driven W4 short-RTH Policy A (Phase 1).

Loads catalog 1s+1m bars from Jan 1 of the year (fresh RegimeEngine warmup,
matching the per-year atlas construction) and runs the Policy A short-RTH
strategy over the frozen entry schedule. Outputs trades/flips/skips/timing
per year under _work/nt_runs/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
import os  # noqa: E402
os.chdir(PROJECT_ROOT)

import pandas as pd  # noqa: E402

from nautilus_trader.backtest.engine import BacktestEngine  # noqa: E402
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig  # noqa: E402
from nautilus_trader.model.currencies import USD  # noqa: E402
from nautilus_trader.model.enums import AccountType, OmsType  # noqa: E402
from nautilus_trader.model.identifiers import Venue  # noqa: E402
from nautilus_trader.model.objects import Money  # noqa: E402
from nautilus_trader.persistence.catalog import ParquetDataCatalog  # noqa: E402

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import (  # noqa: E402
    create_instrument,
)
import studies.fable5_nt_short_rth_policy_a.common as C  # noqa: E402
from studies.fable5_nt_short_rth_policy_a.strategy import (  # noqa: E402
    PolicyAShortRTHConfig, PolicyAShortRTHStrategy,
)


def run_one(year: int, log_guard=None):
    t0 = time.time()
    if not C.schedule_path(year).exists():
        raise RuntimeError(f"missing schedule for {year}; run build_schedule.py")
    load_start, load_end = C.LOAD_WINDOWS[year]
    catalog = ParquetDataCatalog(str(C.CATALOG_PATH))
    bars_1s = catalog.bars(bar_types=[C.BAR_1S], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=[C.BAR_1M], start=load_start, end=load_end)
    print(f"[{year}] {len(bars_1s):,} 1s bars, {len(bars_1m):,} 1m bars "
          f"({time.time()-t0:.0f}s)")
    if not bars_1s or not bars_1m:
        raise RuntimeError(f"catalog returned no bars for {year}")

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="FABLE5-SRTH",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False)))
    if log_guard is None:
        log_guard = engine.get_log_guard()
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(5_000_000, USD)],
        bar_execution=True, bar_adaptive_high_low_ordering=True)
    engine.add_instrument(create_instrument())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = PolicyAShortRTHConfig(
        year=year, schedule_path=str(C.schedule_path(year)),
        preflip_stop_atr=C.PREFLIP_STOP_ATR, postflip_stop_atr=C.POSTFLIP_STOP_ATR,
        timeout_s=C.TIMEOUT_S, multiplier=C.NQ_MULT, cost_rt=C.COST_RT)
    strat = PolicyAShortRTHStrategy(config=cfg)
    engine.add_strategy(strat)
    engine.run(start=load_start)

    out_dir = C.WORK / "nt_runs" / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in [("trades", strat.trades), ("flips", strat.flips),
                       ("skips", strat.skips), ("entry_timing", strat.entry_timing),
                       ("boundary_cases", strat.boundary_cases)]:
        pd.DataFrame(rows).to_parquet(out_dir / f"{name}.parquet", index=False)
    strat_src = Path(__file__).resolve().parent / "strategy.py"
    meta = {
        "year": year, "n_trades": len(strat.trades),
        "n_skips": len(strat.skips), "n_flips": len(strat.flips),
        "n_boundary_cases": len(strat.boundary_cases),
        "n_scheduled": len(strat._sched),
        "strategy_sha256": C.sha256_file(strat_src),
        "runtime_s": time.time() - t0}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[{year}] {len(strat.trades)} trades, {len(strat.skips)} skips "
          f"({time.time()-t0:.0f}s)")
    engine.dispose()
    return log_guard


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=(2025, 2026, 0), default=0,
                    help="0 = both years")
    args = ap.parse_args()
    years = (2025, 2026) if args.year == 0 else (args.year,)
    guard = None
    for y in years:
        guard = run_one(y, guard)


if __name__ == "__main__":
    main()
