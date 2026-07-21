"""NT TICK-DRIVEN on NQ.v.0 2025 trade ticks (full year).

Same EMA13+v-recovery design as run_nt_v0_2025_1s.py — direct
1s-vs-tick comparison within 2025 on the same NQ.v.0 contract.

Goal: determine if tick degradation seen in 2026 (-$22K vs +$17K
1s-bar) is a tick implementation issue OR specific to 2026.
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
from studies.level_momentum_continuation.run_nt_v0_2025_1s import (
    create_nq_v0,
)

NQ_MULT = 20.0
COMMISSION = 5.0


def load_trades_to_nt_ticks(parquet_path, instrument):
    """Load NQ_trades parquet (already filtered to trade events).
    Convert to NT TradeTick list."""
    print(f"  loading {parquet_path.name}...", flush=True)
    df = pd.read_parquet(
        parquet_path,
        columns=["action", "side", "price", "size", "ts_event"])
    print(f"    {len(df):,} rows", flush=True)
    # Already trade-only since this is the trades parquet, but filter
    # for safety
    if "action" in df.columns:
        trades = df[df["action"] == "T"].copy()
        del df; gc.collect()
        print(f"    {len(trades):,} trade events", flush=True)
    else:
        trades = df

    side_map = {"A": "BUYER", "B": "SELLER"}
    trades["aggressor_side"] = (
        trades["side"].map(side_map).fillna("NO_AGGRESSOR"))
    trades["trade_id"] = "T" + trades.index.astype(str)
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
    print("=" * 78)
    print("NT TICK-DRIVEN on NQ.v.0 2025 trade ticks (FULL YEAR)")
    print("Same EMA13+v-recovery design as v0 2025 1s reference")
    print("=" * 78)

    nq = create_nq_v0()
    # Use full-year file
    path = Path("data/raw/NQ_trades_20250101_20251231.parquet")
    if not path.exists():
        print(f"ERROR: {path} not found")
        sys.exit(1)
    ticks = load_trades_to_nt_ticks(path, nq)
    print(f"\nTotal TradeTicks: {len(ticks):,}", flush=True)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-V0-2025-TICK",
        logging=LoggingConfig(log_level="ERROR"),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(nq)
    engine.add_data(ticks)
    print(f"Loaded ticks into engine.", flush=True)
    del ticks; gc.collect()

    config = LevelMomentumLiveConfig(
        strategy_id="LMC-V0-2025-TICK",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-INTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-INTERNAL",
        ema_period=13,
        mae_min=3.0,
        bucket_filter_enabled=False,
        disable_v_recovery=False,
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    print(f"\nRunning NT BacktestEngine on tick data...", flush=True)
    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s", flush=True)

    trades = strat._trades
    print(f"\nTrades captured: {len(trades):,}")
    if trades:
        df = pd.DataFrame(trades)
        df["c1_fill_dt"] = pd.to_datetime(df["c1_fill_ts"], unit="ns",
                                            utc=True)
        df["c1_pnl_dollars"] = df["c1_pnl_pts"] * NQ_MULT - COMMISSION
        df["c2_pnl_dollars"] = np.where(
            df["c2_added"],
            df["c2_pnl_pts"] * NQ_MULT - COMMISSION, 0.0)
        df["total_pnl_dollars"] = df["c1_pnl_dollars"] + df["c2_pnl_dollars"]

        out = Path("studies/level_momentum_continuation/results_breakout")
        df.to_parquet(out / "nt_v0_2025_tick_trades.parquet")
        print(f"  saved trades parquet")

        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            g = df[df["group"] == grp]
            if len(g) == 0: continue
            tot = g["total_pnl_dollars"].sum()
            wr = (g["exit_reason"] == "win").mean() * 100
            print(f"  [{grp}] n={len(g):,}  WR={wr:.1f}%  "
                  f"total ${tot:+,.0f}  ({tot/len(g):+.2f}/tr)")
        total_all = df["total_pnl_dollars"].sum()
        print(f"\nALL: total ${total_all:+,.0f}  ({total_all/len(df):+.2f}/tr "
              f"on {len(df):,} trades)")

        df["month"] = df["c1_fill_dt"].dt.to_period("M")
        print(f"\nMonthly:")
        for mo, g in df.groupby("month"):
            print(f"  {mo}: n={len(g):,}  total ${g['total_pnl_dollars'].sum():+,.0f}")

    engine.dispose()
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
