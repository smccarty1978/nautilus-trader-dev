"""NT BacktestEngine + MBP-1 streaming for 2025 using legacy_c0
(front-month NQ.c.0) quarterly data.

Reads month-of-year, finds the matching quarterly file, filters quotes
to that month + RTH, runs NT engine. Includes post-run artifact filter
that drops trades where bar-close-at-exit differs from actual exit fill
by > 5 pts (catches contract-mismatch fills between NQ.v.0 schedule
catalog and NQ.c.0 quote stream).

Roll-day exclusion is already applied at schedule-build time (±3 days
around 3rd Thursday of each quarter month).
"""
from __future__ import annotations
import argparse
import gc
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


MBP1_2025_QUARTER_PATHS = {
    1: "data/raw/legacy_c0/NQ_mbp1_2025_Q1.parquet",
    2: "data/raw/legacy_c0/NQ_mbp1_2025_Q1.parquet",
    3: "data/raw/legacy_c0/NQ_mbp1_2025_Q1.parquet",
    4: "data/raw/legacy_c0/NQ_mbp1_2025_Q2.parquet",
    5: "data/raw/legacy_c0/NQ_mbp1_2025_Q2.parquet",
    6: "data/raw/legacy_c0/NQ_mbp1_2025_Q2.parquet",
    7: "data/raw/legacy_c0/NQ_mbp1_2025_Q3.parquet",
    8: "data/raw/legacy_c0/NQ_mbp1_2025_Q3.parquet",
    9: "data/raw/legacy_c0/NQ_mbp1_2025_Q3.parquet",
    10: "data/raw/legacy_c0/NQ_mbp1_2025_Q4.parquet",
    11: "data/raw/legacy_c0/NQ_mbp1_2025_Q4.parquet",
    12: "data/raw/legacy_c0/NQ_mbp1_2025_Q4.parquet",
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


def load_mbp1_month_2025(month, instrument):
    """Load 2025 month's MBP-1 from the appropriate quarterly file."""
    path = MBP1_2025_QUARTER_PATHS[month]
    t0 = time.time()
    print(f"  loading MBP-1 from {path}", flush=True)
    df = pd.read_parquet(
        path, columns=["ts_event", "bid_px_00", "ask_px_00",
                          "bid_sz_00", "ask_sz_00"])
    print(f"    raw {len(df):,} quotes ({time.time()-t0:.0f}s)",
          flush=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    # Filter to target month (UTC)
    mo_mask = df["ts_event"].dt.month == month
    df = df.loc[mo_mask].copy()
    print(f"    {month:02d}-only {len(df):,} quotes "
          f"({time.time()-t0:.0f}s)", flush=True)
    # RTH filter
    ct = df["ts_event"].dt.tz_convert("America/Chicago")
    mins = ct.dt.hour * 60 + ct.dt.minute
    rth_mask = (mins >= 8 * 60 + 30) & (mins < 15 * 60)
    df = df.loc[rth_mask].copy()
    print(f"    RTH-only {len(df):,} quotes "
          f"({time.time()-t0:.0f}s)", flush=True)
    # Drop invalid
    valid = ((df["bid_px_00"] > 0) & (df["ask_px_00"] > 0)
              & (df["ask_px_00"] > df["bid_px_00"]))
    df = df.loc[valid].copy()
    df["bid_price"] = df["bid_px_00"]
    df["ask_price"] = df["ask_px_00"]
    df["bid_size"] = df["bid_sz_00"].clip(lower=1)
    df["ask_size"] = df["ask_sz_00"].clip(lower=1)
    df = df.set_index("ts_event").sort_index()
    df = df[["bid_price", "ask_price", "bid_size", "ask_size"]]
    wrangler = QuoteTickDataWrangler(instrument=instrument)
    ticks = wrangler.process(data=df)
    print(f"    converted {len(ticks):,} QuoteTicks "
          f"({time.time()-t0:.0f}s)", flush=True)
    del df
    gc.collect()
    return ticks


def run_one_month_2025(month, schedule_path, out_dir, catalog_path):
    print(f"\n{'='*78}")
    print(f"MONTH 2025-{month:02d}")
    print(f"{'='*78}")
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)

    sched = pd.read_parquet(schedule_path)
    sched_dt = pd.to_datetime(sched["entry_ts_ns"], unit="ns",
                                     utc=True)
    sched_m = sched_dt.dt.tz_convert("UTC").dt.month
    sched_y = sched_dt.dt.tz_convert("UTC").dt.year
    sched_month = sched[(sched_y == 2025)
                            & (sched_m == month)].copy(
        ).reset_index(drop=True)
    print(f"  Trades in 2025-{month:02d}: {len(sched_month):,}")
    if len(sched_month) == 0:
        print("  No trades — skipping month")
        return None

    first_entry = pd.Timestamp(int(sched_month["entry_ts_ns"].min()),
                                       unit="ns", tz="UTC")
    last_exit = pd.Timestamp(int(sched_month["exit_ts_ns"].max()),
                                    unit="ns", tz="UTC")
    load_start = first_entry - pd.Timedelta(hours=2)
    load_end = last_exit + pd.Timedelta(hours=2)
    print(f"  Window: {load_start} .. {load_end}")

    month_sched_path = out_dir / f"schedule_month_{month:02d}.parquet"
    sched_month.to_parquet(month_sched_path)

    catalog = ParquetDataCatalog(catalog_path)
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s bars "
          f"({time.time()-t0:.0f}s)")

    nq = create_nq()
    engine_cfg = BacktestEngineConfig(
        trader_id=f"PF-T1-25M{month:02d}",
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
        bar_execution=False,
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)

    ticks = load_mbp1_month_2025(month, nq)
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
        gc.collect()

    strat_cfg = PreFlipScheduleConfig(
        instrument_id="NQ.XCME",
        schedule_path=str(month_sched_path.resolve()),
        position_size=1,
        single_position=True,
    )
    strat = PreFlipScheduleStrategy(strat_cfg)
    engine.add_strategy(strat)

    print(f"  Running NT BacktestEngine (quote_tick fills)... "
          f"({time.time()-t0:.0f}s)", flush=True)
    t1 = time.time()
    engine.run()
    print(f"  NT run done in {time.time()-t1:.0f}s "
          f"(total {time.time()-t0:.0f}s)")

    positions = engine.trader.generate_positions_report()
    fills = engine.trader.generate_fills_report()

    def _drop_struct(df):
        drop = [c for c in df.columns
                 if df[c].dtype == object
                 and df[c].map(lambda v: isinstance(v, dict)).any()]
        return df.drop(columns=drop) if drop else df

    NQ_MULT = 20.0
    COMMISSION = 2.5    # $5 RT user's actual cost
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
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--catalog", default="data/catalog/NQ_v0_2020_2026")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--months", nargs="+", type=int,
                      default=list(range(1, 13)))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"NT MBP-1 STREAMING (2025 NQ.c.0 quarterly files)")
    print(f"Schedule: {args.schedule}")
    print(f"Months: {args.months}")
    print("=" * 78)

    all_trades = []
    for month in args.months:
        result = run_one_month_2025(
            month, args.schedule, out_dir, args.catalog)
        if result is not None:
            all_trades.extend(result)

    if all_trades:
        agg = pd.DataFrame(all_trades)
        NQ_MULT = 20.0
        COMMISSION = 2.5
        agg["pnl_pts"] = (
            (agg["exit_fill_price"] - agg["entry_fill_price"])
            * agg["direction"])
        agg["gross_pnl"] = agg["pnl_pts"] * NQ_MULT
        agg["net_pnl"] = agg["gross_pnl"] - 2 * COMMISSION
        agg.to_parquet(out_dir / "trades_all_months.parquet",
                          index=False)
        closed = agg[agg["exit_filled"]]
        print(f"\n{'='*78}")
        print(f"AGGREGATE 2025 — all months")
        print(f"{'='*78}")
        print(f"  Closed n={len(closed):,}")
        if len(closed):
            print(f"  Total net PnL: "
                  f"${closed['net_pnl'].sum():+,.0f}")
            print(f"  Mean per-tr:   "
                  f"${closed['net_pnl'].mean():+.2f}")
            print(f"  WR:            "
                  f"{(closed['net_pnl']>0).mean():.1%}")
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
