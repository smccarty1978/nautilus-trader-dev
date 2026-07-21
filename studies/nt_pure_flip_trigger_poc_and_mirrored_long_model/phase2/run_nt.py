"""BacktestEngine runner for the pure flip-trigger POC. Runs the 3 variants
(T1/T2/T3) as independent strategy instances -- no pooling until all 3 are
complete, per SPEC.md."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
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

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument  # noqa: E402
import studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase2.common as C  # noqa: E402
from studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase2.strategy import (  # noqa: E402
    SimpleFlipTriggerConfig, SimpleFlipTriggerStrategy,
)


def run_one(variant_label: str, log_guard=None):
    t0 = time.time()
    sched_path = C.schedule_path(variant_label)
    if not sched_path.exists():
        raise RuntimeError(f"missing schedule for {variant_label}; run build_schedules.py")

    catalog = ParquetDataCatalog(str(C.CATALOG_PATH))
    bars_1s = catalog.bars(bar_types=[C.BAR_1S], start=C.LOAD_START, end=C.LOAD_END)
    bars_1m = catalog.bars(bar_types=[C.BAR_1M], start=C.LOAD_START, end=C.LOAD_END)
    print(f"[{variant_label}] {len(bars_1s):,} 1s bars, {len(bars_1m):,} 1m bars "
          f"({time.time()-t0:.0f}s)")
    if not bars_1s or not bars_1m:
        raise RuntimeError(f"catalog returned no bars for {variant_label}")

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=f"NTPOC-{variant_label}",
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

    cfg = SimpleFlipTriggerConfig(
        variant_label=variant_label, schedule_path=str(sched_path),
        stop_atr_mult=C.STOP_ATR_MULT, multiplier=C.NQ_MULT, cost_rt=C.COST_RT)
    strat = SimpleFlipTriggerStrategy(config=cfg)
    engine.add_strategy(strat)
    engine.run(start=C.LOAD_START)

    out_dir = C.WORK / "nt_runs" / variant_label
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in [("trades", strat.trades), ("flips", strat.flips),
                       ("skips", strat.skips), ("raw_paths", strat.raw_paths)]:
        pd.DataFrame(rows).to_parquet(out_dir / f"{name}.parquet", index=False)
    strat_src = Path(__file__).resolve().parent / "strategy.py"
    ts_src = Path(__file__).resolve().parent / "trade_state.py"
    meta = {
        "variant": variant_label, "n_trades": len(strat.trades),
        "n_skips": len(strat.skips), "n_flips": len(strat.flips),
        "n_scheduled": len(strat._sched),
        "strategy_sha256": C.sha256_file(strat_src),
        "trade_state_sha256": C.sha256_file(ts_src),
        "runtime_s": time.time() - t0}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[{variant_label}] {len(strat.trades)} trades, {len(strat.skips)} skips "
          f"({time.time()-t0:.0f}s)")
    engine.dispose()
    return log_guard


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=list(C.VARIANTS) + ["ALL"], default="ALL")
    args = ap.parse_args()
    labels = list(C.VARIANTS) if args.variant == "ALL" else [args.variant]
    guard = None
    for label in labels:
        guard = run_one(label, guard)


if __name__ == "__main__":
    main()
