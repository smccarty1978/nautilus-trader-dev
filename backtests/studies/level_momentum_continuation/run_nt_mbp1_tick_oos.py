"""TICK-DRIVEN NT validation: NQ.v.0 MBP-1 trade ticks, 2026 OOS.

Loads MBP-1 parquet, extracts trade events (action='T'), converts to
NT TradeTick objects. NT BacktestEngine consumes ticks and builds
1m + 1s bars INTERNALLY via BarAggregator. Strategy subscribes to
those INTERNAL bars for triggers and MAE tracking. Matching engine
fires fills on actual trade ticks (sub-second precision).

This is the deployment-gate test per memory rule:
  TAPE-REPLAY MECHANICAL EXITS OVERSTATE EDGE 5-10x VS TICK-NT

Usage:
    python run_nt_mbp1_tick_oos.py [month]
        month: 1, 2, 3, 4, or 'all' (default: 1 for fast validation)
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.enums import OmsType, AccountType
from nautilus_trader.model.objects import Money
from nautilus_trader.model.currencies import USD
from nautilus_trader.persistence.wranglers import TradeTickDataWrangler
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract

from studies.level_momentum_continuation.nt_strategy_v1 import (
    LevelMomentumLiveConfig, LevelMomentumLiveStrategy,
)

NQ_MULT = 20.0
COMMISSION = 5.0


def create_nq_v0():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2026-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2026-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def load_mbp1_trade_ticks(parquet_path: Path, instrument):
    """Load MBP-1, filter trades, convert to NT TradeTick list."""
    print(f"  loading {parquet_path.name}...", flush=True)
    df = pd.read_parquet(
        parquet_path,
        columns=["action", "side", "price", "size", "ts_event"])
    print(f"    {len(df):,} rows", flush=True)
    trades = df[df["action"] == "T"].copy()
    del df; gc.collect()
    print(f"    {len(trades):,} trade events", flush=True)

    # Build NT-compatible DataFrame
    # Required columns: price, quantity, aggressor_side, trade_id
    # Index: ts_event (datetime UTC)
    # Databento side: 'A' = trade lifted the ASK (BUYER aggressor)
    #                 'B' = trade hit the BID (SELLER aggressor)
    side_map = {"A": "BUYER", "B": "SELLER"}
    trades["aggressor_side"] = (
        trades["side"].map(side_map).fillna("NO_AGGRESSOR"))
    # Use sequence-based trade_id for uniqueness
    trades["trade_id"] = (
        "T" + trades.index.astype(str))
    # ts_event index
    if pd.api.types.is_datetime64_any_dtype(trades["ts_event"]):
        idx = pd.DatetimeIndex(trades["ts_event"])
    else:
        idx = pd.to_datetime(trades["ts_event"], utc=True)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    nt_df = pd.DataFrame({
        "price": trades["price"].values,
        "quantity": trades["size"].values.astype(float),
        "aggressor_side": trades["aggressor_side"].values,
        "trade_id": trades["trade_id"].values,
    }, index=idx)
    nt_df = nt_df.sort_index()
    del trades; gc.collect()
    print(f"    wrangling to NT TradeTick...", flush=True)
    wrangler = TradeTickDataWrangler(instrument=instrument)
    ticks = wrangler.process(nt_df)
    print(f"    {len(ticks):,} TradeTick objects", flush=True)
    del nt_df; gc.collect()
    return ticks


def main():
    t0 = time.time()
    month_arg = sys.argv[1] if len(sys.argv) > 1 else "1"
    if month_arg == "all":
        months = [1, 2, 3, 4]
    else:
        months = [int(month_arg)]
    print("=" * 78)
    print(f"TICK-DRIVEN NT — NQ.v.0 MBP-1 OOS (2026-{months})")
    print("=" * 78)

    nq = create_nq_v0()

    # Load all months requested
    all_ticks = []
    for m in months:
        path = Path(f"data/raw/NQ_v0_mbp1_2026_{m:02d}.parquet")
        if not path.exists():
            print(f"WARNING: {path} not found, skipping")
            continue
        ticks = load_mbp1_trade_ticks(path, nq)
        all_ticks.extend(ticks)
        del ticks; gc.collect()
    print(f"\nTotal TradeTicks: {len(all_ticks):,}", flush=True)
    print(f"Memory after tick load... continuing.", flush=True)

    # Set up engine
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-MBP1-OOS",
        logging=LoggingConfig(log_level="ERROR"),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(nq)
    engine.add_data(all_ticks)
    print(f"Loaded ticks into engine.", flush=True)
    del all_ticks; gc.collect()

    # Strategy uses INTERNAL bar types - NT will auto-aggregate from ticks
    config = LevelMomentumLiveConfig(
        strategy_id="LMC-MBP1",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-INTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-INTERNAL",
        ema_period=13,
        mae_min=3.0,
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    print(f"\nRunning NT BacktestEngine on tick data...", flush=True)
    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s", flush=True)

    trades = strat._trades
    print(f"\nTrades captured: {len(trades):,}", flush=True)

    if trades:
        df = pd.DataFrame(trades)
        df["c1_fill_dt"] = pd.to_datetime(df["c1_fill_ts"], unit="ns",
                                            utc=True)
        df["c1_pnl_dollars"] = df["c1_pnl_pts"] * NQ_MULT - COMMISSION
        df["c2_pnl_dollars"] = np.where(
            df["c2_added"],
            df["c2_pnl_pts"] * NQ_MULT - COMMISSION, 0.0)
        df["total_pnl_dollars"] = (df["c1_pnl_dollars"] +
                                       df["c2_pnl_dollars"])

        out = Path("studies/level_momentum_continuation/results_breakout")
        out.mkdir(parents=True, exist_ok=True)
        suffix = "all" if month_arg == "all" else f"m{month_arg}"
        df.to_parquet(out / f"nt_mbp1_oos_{suffix}_trades.parquet")
        print(f"  saved trades parquet")

        print(f"\nPer-group results (TICK-DRIVEN OOS 2026-{months}):")
        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            g = df[df["group"] == grp]
            if len(g) == 0:
                print(f"  [{grp}] NO TRADES")
                continue
            n = len(g)
            wr = (g["exit_reason"] == "win").mean() * 100
            c2_pct = g["c2_added"].mean() * 100
            tot = g["total_pnl_dollars"].sum()
            print(f"  [{grp}] n={n:,}  WR={wr:.1f}%  c2={c2_pct:.1f}%  "
                  f"total ${tot:+,.0f}  ({tot/n:+.2f}/tr)")

        total_all = df["total_pnl_dollars"].sum()
        print(f"\nALL GROUPS (TICK-DRIVEN): total ${total_all:+,.0f}  "
              f"({total_all/len(df):+.2f}/tr on {len(df):,} trades)")

        # Per-month
        df["month"] = df["c1_fill_dt"].dt.to_period("M")
        print(f"\nMonthly breakdown:")
        for mo, g in df.groupby("month"):
            print(f"  {mo}: n={len(g):,}  total ${g['total_pnl_dollars'].sum():+,.0f}")

        # Comparison vs 1s-bar OOS (Path 3)
        print(f"\n{'='*78}")
        print(f"COMPARISON vs 1s-bar Path 3 OOS:")
        print(f"  1s-bar NT Path 3 (full Jan-Apr): +$17,055 on 4,105 trades (+$4.15/tr)")
        print(f"  Tick NT this run: ${total_all:+,.0f} on {len(df):,} trades")

    engine.dispose()
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
