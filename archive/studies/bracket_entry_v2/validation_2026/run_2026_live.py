"""Run LiveBracketStrategy on 2026 YTD — deployment-style test."""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
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
from live_bracket_strategy import (
    LiveBracketStrategy, LiveBracketConfig,
)


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
    ap.add_argument("--catalog", default="data/catalog/NQ_2020_2025")
    ap.add_argument("--model",
                     default="studies/bracket_entry_v2/validation_2026/"
                              "model_top15_v2026.txt")
    ap.add_argument("--features",
                     default="studies/bracket_entry_v2/validation_2026/"
                              "feature_list.json")
    ap.add_argument("--threshold-file",
                     default="studies/bracket_entry_v2/validation_2026/"
                              "score_threshold.json")
    ap.add_argument("--out-dir",
                     default="studies/bracket_entry_v2/validation_2026/"
                              "results/nt_run")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-04-15 23:59:59")
    ap.add_argument("--mode", choices=["select", "exclude"],
                     default="select",
                     help="select: trade when score>=threshold; "
                          "exclude: trade when score<threshold (failure filter)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.threshold_file) as f:
        thr = json.load(f)["threshold_top10"]
    print(f"Score threshold (top-10% from val 2025): {thr:.4f}")

    # Load bars (2-day warmup lead-in reaches into late Dec 2025)
    load_start = pd.Timestamp(args.start, tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(args.end, tz="UTC")
    print(f"Loading bars {load_start} -> {load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(args.catalog)
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
           f"({time.time() - t0:.0f}s)")

    nq = create_nq()

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LIVE-2026",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="INFO",
            log_directory=str(out_dir / "logs"),
        ),
    ))
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

    cfg = LiveBracketConfig(
        instrument_id="NQ.XCME",
        model_path=str(Path(args.model).resolve()),
        feature_list_path=str(Path(args.features).resolve()),
        score_threshold=thr,
        mode=args.mode,
        pt_atr_mult=1.0,
        sl_atr_mult=1.0,
        position_size=1,
        fill_delay_ns=30_000_000_000,
        # Dummy paths for CollectorV2's output params (writes disabled)
        features_output=str(out_dir / "_features.parquet"),
        labels_output=str(out_dir / "_labels.parquet"),
        events_summary_output=str(out_dir / "_events.parquet"),
        qa_log_output=str(out_dir / "_qa.log"),
    )
    strat = LiveBracketStrategy(cfg)
    engine.add_strategy(strat)

    print("Running...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")

    # Reports
    orders = engine.trader.generate_orders_report()
    fills = engine.trader.generate_fills_report()
    positions = engine.trader.generate_positions_report()

    def _drop_struct(df):
        drop = [c for c in df.columns if df[c].dtype == object
                 and df[c].map(lambda v: isinstance(v, dict)).any()]
        return df.drop(columns=drop) if drop else df

    _drop_struct(orders).to_parquet(out_dir / "orders.parquet",
                                       index=False)
    _drop_struct(fills).to_parquet(out_dir / "fills.parquet",
                                      index=False)
    _drop_struct(positions).to_parquet(out_dir / "positions.parquet",
                                          index=False)

    stats_g = engine.portfolio.analyzer.get_performance_stats_general()
    stats_p = engine.portfolio.analyzer.get_performance_stats_pnls()
    stats_r = engine.portfolio.analyzer.get_performance_stats_returns()

    # Dump strategy-side trade records (exit_reason, score, etc.)
    trade_rows = []
    for entry_id, tr in strat._trades.items():
        trade_rows.append({
            "entry_id": entry_id,
            **tr,
        })
    if trade_rows:
        pd.DataFrame(trade_rows).to_parquet(
            out_dir / "strategy_trades.parquet", index=False)

    print("\n===== Results =====")
    print(f"Live diag: {strat._live_diag}")
    print(f"Collector diag: {strat._diag}")
    print(f"Positions closed: {len(positions):,}")
    print(f"PnL total: {stats_p.get('PnL (total)', 'N/A')}")
    print(f"Win rate: {stats_p.get('Win Rate', 'N/A')}")
    print(f"PF: {stats_r.get('Profit Factor', 'N/A')}")
    print(f"Sharpe: {stats_r.get('Sharpe Ratio (252 days)', 'N/A')}")

    import yaml
    with open(out_dir / "metrics.yaml", "w") as f:
        yaml.dump({
            "live_diag": strat._live_diag,
            "collector_diag": {k: int(v)
                                 for k, v in strat._diag.items()},
            "general": {k: float(v) for k, v in stats_g.items()},
            "pnls": {k: float(v) for k, v in stats_p.items()},
            "returns": {k: float(v) for k, v in stats_r.items()},
        }, f, default_flow_style=False)

    engine.dispose()
    print(f"\nResults dir: {out_dir}")


if __name__ == "__main__":
    main()
