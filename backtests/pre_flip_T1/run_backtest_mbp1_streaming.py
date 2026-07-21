"""NT BacktestEngine + MBP-1 quote-tick streaming for pre-flip T-1.

Streams 1s bars (for strategy scheduling) AND MBP-1 quote ticks (for
MatchingEngine fills) chronologically through NT. Market orders fill at
the next available quote tick after submission, modeling real
bid/ask execution mechanics.

Memory strategy: process ONE MONTH at a time. Each month's run:
  - Loads 1s bars (for that month's schedule + buffer)
  - Loads MBP-1 quote ticks for that month
  - Filters schedule to the month's entries
  - Runs NT engine with `bar_execution=False`
  - Aggregates results

For trades spanning month boundaries (rare — typical trade is 60s),
the trade is run in the month containing the entry. If the exit_ts
falls outside the loaded data, the trade is left open.

Usage:
    python backtests/pre_flip_T1/run_backtest_mbp1_streaming.py \
        --schedule backtests/pre_flip_T1/results/schedule_T1_2026_top10.parquet \
        --months 1 2 3 4 \
        --out-dir backtests/pre_flip_T1/results/nt_mbp1_2026_top10
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

import numpy as np
import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import QuoteTickDataWrangler
from nautilus_trader.test_kit.providers import TestInstrumentProvider

sys.path.insert(0, str(Path(__file__).parent))
from strategy import PreFlipScheduleConfig, PreFlipScheduleStrategy  # noqa


MBP1_PATHS = {
    1: "data/raw/NQ_v0_mbp1_2026_01.parquet",
    2: "data/raw/NQ_v0_mbp1_2026_02.parquet",
    3: "data/raw/NQ_v0_mbp1_2026_03.parquet",
    4: "data/raw/NQ_v0_mbp1_2026_04.parquet",
}


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


def load_mbp1_as_quote_ticks(mbp_path: str, instrument,
                                   rth_only: bool = True):
    """Load MBP-1 parquet and convert to QuoteTick list via wrangler.

    Filters to RTH only by default to cut memory usage.
    """
    print(f"  loading MBP-1 from {mbp_path}", flush=True)
    t0 = time.time()
    df = pd.read_parquet(
        mbp_path,
        columns=["ts_event", "bid_px_00", "ask_px_00",
                   "bid_sz_00", "ask_sz_00"])
    print(f"    raw {len(df):,} quotes ({time.time()-t0:.0f}s)",
          flush=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    if rth_only:
        ct = df["ts_event"].dt.tz_convert("America/Chicago")
        mins = ct.dt.hour * 60 + ct.dt.minute
        rth_mask = (mins >= 8 * 60 + 30) & (mins < 15 * 60)
        df = df.loc[rth_mask].copy()
        print(f"    RTH-only {len(df):,} quotes "
              f"({time.time()-t0:.0f}s)", flush=True)
    # Drop rows with invalid quotes
    valid = ((df["bid_px_00"] > 0) & (df["ask_px_00"] > 0)
              & (df["ask_px_00"] > df["bid_px_00"]))
    df = df.loc[valid].copy()
    df["bid_price"] = df["bid_px_00"]
    df["ask_price"] = df["ask_px_00"]
    df["bid_size"] = df["bid_sz_00"].clip(lower=1)
    df["ask_size"] = df["ask_sz_00"].clip(lower=1)
    df = df.set_index("ts_event").sort_index()
    df = df[["bid_price", "ask_price", "bid_size", "ask_size"]]
    print(f"    converting to QuoteTick objects "
          f"({time.time()-t0:.0f}s)...", flush=True)
    wrangler = QuoteTickDataWrangler(instrument=instrument)
    ticks = wrangler.process(data=df)
    print(f"    converted {len(ticks):,} QuoteTicks "
          f"({time.time()-t0:.0f}s)", flush=True)
    return ticks


def run_one_month(month: int, schedule_path: str, out_dir: Path,
                       catalog_path: str, year: int = 2026):
    """Run NT backtest with MBP-1 streaming for a single month."""
    print(f"\n{'='*78}")
    print(f"MONTH {year}-{month:02d}")
    print(f"{'='*78}")
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)

    sched = pd.read_parquet(schedule_path)
    sched_dt = pd.to_datetime(sched["entry_ts_ns"], unit="ns", utc=True)
    sched_m = sched_dt.dt.tz_convert("UTC").dt.month
    sched_y = sched_dt.dt.tz_convert("UTC").dt.year
    sched_month = sched[(sched_y == year) & (sched_m == month)].copy(
        ).reset_index(drop=True)
    print(f"  Trades in {year}-{month:02d}: {len(sched_month):,}")
    if len(sched_month) == 0:
        print("  No trades — skipping month")
        return None

    # Time window for data load: from first entry to last exit + buffer
    first_entry = pd.Timestamp(int(sched_month["entry_ts_ns"].min()),
                                  unit="ns", tz="UTC")
    last_exit = pd.Timestamp(int(sched_month["exit_ts_ns"].max()),
                                unit="ns", tz="UTC")
    load_start = first_entry - pd.Timedelta(hours=2)
    load_end = last_exit + pd.Timedelta(hours=2)
    print(f"  Window: {load_start} .. {load_end}")

    # Save month-only schedule (strategy reads from disk)
    month_sched_path = out_dir / f"schedule_month_{month:02d}.parquet"
    sched_month.to_parquet(month_sched_path)

    # Load 1s bars for the month
    catalog = ParquetDataCatalog(catalog_path)
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s bars "
          f"({time.time()-t0:.0f}s)")

    # Build instrument & engine
    nq = create_nq()
    engine_cfg = BacktestEngineConfig(
        trader_id=f"PF-T1-M{month:02d}",
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
        bar_execution=False,    # use quote_ticks for fills
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)

    # Load MBP-1 quote ticks for the month
    if month not in MBP1_PATHS:
        print(f"  WARN: no MBP-1 file for month {month}")
        engine.dispose()
        return None
    ticks = load_mbp1_as_quote_ticks(MBP1_PATHS[month], nq,
                                              rth_only=True)
    # Filter ticks to load window (further memory savings)
    if ticks:
        first_ns = int(load_start.value)
        last_ns = int(load_end.value)
        ticks_window = [t for t in ticks
                          if first_ns <= t.ts_event <= last_ns]
        print(f"  Filtered to window: {len(ticks_window):,} "
              f"({time.time()-t0:.0f}s)")
        engine.add_data(ticks_window)
        del ticks
        del ticks_window

    # Strategy
    strat_cfg = PreFlipScheduleConfig(
        instrument_id="NQ.XCME",
        schedule_path=str(month_sched_path.resolve()),
        position_size=1,
        single_position=True,
    )
    strat = PreFlipScheduleStrategy(strat_cfg)
    engine.add_strategy(strat)

    print(f"  Running NT BacktestEngine (quote_tick fills)..."
          f"  ({time.time()-t0:.0f}s)", flush=True)
    t1 = time.time()
    engine.run()
    print(f"  NT run done in {time.time()-t1:.0f}s "
          f"(total {time.time()-t0:.0f}s)")

    # Reports
    positions = engine.trader.generate_positions_report()
    fills = engine.trader.generate_fills_report()

    def _drop_struct(df):
        drop = [c for c in df.columns
                 if df[c].dtype == object
                 and df[c].map(lambda v: isinstance(v, dict)).any()]
        return df.drop(columns=drop) if drop else df

    stats_p = engine.portfolio.analyzer.get_performance_stats_pnls()
    print(f"  Diag: {strat._diag}")
    print(f"  Positions closed: {len(positions):,}")
    print(f"  PnLs: {stats_p}")

    # Trade-level extract
    NQ_MULT = 20.0
    COMMISSION = 2.5
    trade_df = pd.DataFrame(strat.all_trades) if hasattr(
        strat, "all_trades") else pd.DataFrame()
    if len(trade_df):
        trade_df["pnl_pts"] = (
            (trade_df["exit_fill_price"] - trade_df["entry_fill_price"])
            * trade_df["direction"])
        trade_df["gross_pnl"] = trade_df["pnl_pts"] * NQ_MULT
        trade_df["net_pnl"] = trade_df["gross_pnl"] - 2 * COMMISSION
        trade_df["month"] = month
        trade_out = out_dir / f"trades_month_{month:02d}.parquet"
        trade_df.to_parquet(trade_out, index=False)
        closed = trade_df[trade_df["exit_filled"]]
        print(f"  Closed n={len(closed):,}  "
              f"total=${closed['net_pnl'].sum():+,.0f}  "
              f"mean=${closed['net_pnl'].mean():+.2f}/tr  "
              f"WR={(closed['net_pnl']>0).mean():.1%}")

    _drop_struct(fills).to_parquet(
        out_dir / f"fills_month_{month:02d}.parquet", index=False)
    _drop_struct(positions).to_parquet(
        out_dir / f"positions_month_{month:02d}.parquet", index=False)

    engine.dispose()
    return strat.all_trades if hasattr(strat, "all_trades") else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--schedule",
        default="backtests/pre_flip_T1/results/schedule_T1_2026_top10.parquet")
    ap.add_argument(
        "--catalog", default="data/catalog/NQ_v0_2020_2026")
    ap.add_argument(
        "--out-dir",
        default="backtests/pre_flip_T1/results/nt_mbp1_2026_top10")
    ap.add_argument("--months", nargs="+", type=int,
                      default=[1, 2, 3, 4])
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"NT BACKTEST + MBP-1 STREAMING — {args.schedule}")
    print(f"Months: {args.months}")
    print("=" * 78)

    all_trades = []
    for month in args.months:
        result = run_one_month(
            month, args.schedule, out_dir, args.catalog, year=args.year)
        if result is not None:
            all_trades.extend(result)

    # Aggregate
    if all_trades:
        agg = pd.DataFrame(all_trades)
        NQ_MULT = 20.0
        COMMISSION = 2.5
        agg["pnl_pts"] = (
            (agg["exit_fill_price"] - agg["entry_fill_price"])
            * agg["direction"])
        agg["gross_pnl"] = agg["pnl_pts"] * NQ_MULT
        agg["net_pnl"] = agg["gross_pnl"] - 2 * COMMISSION
        agg.to_parquet(out_dir / "trades_all_months.parquet", index=False)
        closed = agg[agg["exit_filled"]]
        print(f"\n{'='*78}")
        print(f"AGGREGATE — all months")
        print(f"{'='*78}")
        print(f"  Closed n={len(closed):,}")
        if len(closed):
            print(f"  Total net PnL: ${closed['net_pnl'].sum():+,.0f}")
            print(f"  Mean per-tr:   ${closed['net_pnl'].mean():+.2f}")
            print(f"  WR:            {(closed['net_pnl']>0).mean():.1%}")
            va = closed[closed["is_va_confirm"]]
            nf = closed[~closed["is_va_confirm"]]
            print(f"  VA-confirm n={len(va)}: "
                  f"${va['net_pnl'].sum():+,.0f}  "
                  f"mean=${va['net_pnl'].mean():+.2f}/tr")
            print(f"  No-flip   n={len(nf)}: "
                  f"${nf['net_pnl'].sum():+,.0f}  "
                  f"mean=${nf['net_pnl'].mean():+.2f}/tr")


if __name__ == "__main__":
    main()
