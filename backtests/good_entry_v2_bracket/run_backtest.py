"""NT backtest runner for the v2 good-entry bracket strategy.

Loads 2025 RTH 1s + 1m bars, runs the pre-built trade schedule
through NT's BacktestEngine with bar_execution, and reports PnL.

Usage:
    python backtests/good_entry_v2_bracket/run_backtest.py
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
from strategy import BracketScheduleConfig, BracketScheduleStrategy  # noqa


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp(
        "2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp(
        "2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--schedule",
        default="backtests/good_entry_v2_bracket/results/"
                 "schedule_rth_short_180_300.parquet")
    ap.add_argument(
        "--catalog", default="data/catalog/NQ_2020_2025")
    ap.add_argument(
        "--out-dir",
        default="backtests/good_entry_v2_bracket/results/nt_run")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2025-12-31 23:59:59")
    ap.add_argument("--slippage-ticks", type=int, default=1)
    ap.add_argument("--commission-per-side", type=float, default=2.50)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Narrow the bar load to the schedule window ± buffer
    sched = pd.read_parquet(args.schedule)
    if len(sched) == 0:
        print("Empty schedule; nothing to backtest.")
        return
    first_entry = pd.Timestamp(int(sched["entry_ts_ns"].min()),
                                  unit="ns", tz="UTC")
    last_exit = pd.Timestamp(int(sched["regime_exit_ts_ns"].max()),
                                unit="ns", tz="UTC")
    load_start = max(pd.Timestamp(args.start, tz="UTC"),
                      first_entry - pd.Timedelta(days=2))
    load_end = min(pd.Timestamp(args.end, tz="UTC"),
                    last_exit + pd.Timedelta(hours=6))
    print(f"Schedule: {len(sched):,} trades, "
           f"{sched['direction'].value_counts().to_dict()}")
    print(f"Bar load: {load_start} -> {load_end}")

    catalog = ParquetDataCatalog(args.catalog)
    t0 = time.time()
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
           f"({time.time() - t0:.0f}s)")

    nq = create_nq()

    engine_cfg = BacktestEngineConfig(
        trader_id="GE-V2-BR",
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
    engine.add_data(bars_1m)

    strat_cfg = BracketScheduleConfig(
        instrument_id="NQ.XCME",
        schedule_path=str(Path(args.schedule).resolve()),
        pt_atr_mult=1.0,
        sl_atr_mult=1.0,
        position_size=1,
    )
    strat = BracketScheduleStrategy(strat_cfg)
    engine.add_strategy(strat)

    print("Running...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")

    # Reports
    orders = engine.trader.generate_orders_report()
    fills = engine.trader.generate_fills_report()
    positions = engine.trader.generate_positions_report()

    # NT reports have struct columns (e.g. 'info') that parquet
    # can't serialize — drop them then save
    def _drop_struct_cols(df):
        drop = [c for c in df.columns
                 if df[c].dtype == object
                 and df[c].map(lambda v: isinstance(v, dict)).any()]
        return df.drop(columns=drop) if drop else df

    _drop_struct_cols(orders).to_parquet(
        out_dir / "orders.parquet", index=False)
    _drop_struct_cols(fills).to_parquet(
        out_dir / "fills.parquet", index=False)
    _drop_struct_cols(positions).to_parquet(
        out_dir / "positions.parquet", index=False)

    stats_g = engine.portfolio.analyzer.get_performance_stats_general()
    stats_p = engine.portfolio.analyzer.get_performance_stats_pnls()
    stats_r = engine.portfolio.analyzer.get_performance_stats_returns()

    print("\n===== Results =====")
    print(f"Diag: {strat._diag}")
    print(f"Trades closed: {len(positions):,}")
    print(f"General: {stats_g}")
    print(f"PnLs:    {stats_p}")
    print(f"Returns: {stats_r}")

    import yaml
    with open(out_dir / "metrics.yaml", "w") as f:
        yaml.dump({
            "diag": strat._diag,
            "general": {k: float(v) for k, v in stats_g.items()},
            "pnls": {k: float(v) for k, v in stats_p.items()},
            "returns": {k: float(v) for k, v in stats_r.items()},
        }, f, default_flow_style=False)

    engine.dispose()
    print(f"\nResults dir: {out_dir}")


if __name__ == "__main__":
    main()
