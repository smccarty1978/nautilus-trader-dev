"""TICK-DRIVEN NT — sweet-spot bucket filter on 2026 OOS.

Same MBP-1 tick infrastructure as run_nt_mbp1_tick_oos.py, but with:
  - bucket_filter_enabled = True (per-group sweet-spot entry filter)
  - disable_v_recovery = True (1-contract clean baseline)

Sweet spots from entry_location_buckets study:
  A_25pt:    progress in [10%, 20%)
  B_14_15pt: progress in [10%, 20%)
  C_10_11pt: progress in [20%, 30%)

All other parameters identical to prior tick OOS.
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
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract

from studies.level_momentum_continuation.nt_strategy_v1 import (
    LevelMomentumLiveConfig, LevelMomentumLiveStrategy,
)
from studies.level_momentum_continuation.run_nt_mbp1_tick_oos import (
    create_nq_v0, load_mbp1_trade_ticks,
)

NQ_MULT = 20.0
COMMISSION = 5.0


def main():
    t0 = time.time()
    months = [1, 2, 3, 4]
    print("=" * 78)
    print(f"BUCKET-FILTER TICK NT — NQ.v.0 MBP-1 OOS (2026-{months})")
    print(f"Bucket filter: ENABLED (per-group sweet spots)")
    print(f"V-recovery: DISABLED (1-contract clean baseline)")
    print("=" * 78)

    nq = create_nq_v0()
    all_ticks = []
    for m in months:
        path = Path(f"data/raw/NQ_v0_mbp1_2026_{m:02d}.parquet")
        if not path.exists():
            print(f"WARNING: {path} not found")
            continue
        ticks = load_mbp1_trade_ticks(path, nq)
        all_ticks.extend(ticks)
        del ticks; gc.collect()
    print(f"\nTotal TradeTicks: {len(all_ticks):,}", flush=True)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-BUCKET-OOS",
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

    config = LevelMomentumLiveConfig(
        strategy_id="LMC-BUCKET",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-INTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-INTERNAL",
        ema_period=13,
        mae_min=3.0,
        bucket_filter_enabled=True,    # NEW
        disable_v_recovery=True,       # NEW
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    print(f"\nRunning NT BacktestEngine...", flush=True)
    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s", flush=True)

    trades = strat._trades
    print(f"\nTrades captured: {len(trades):,}", flush=True)

    if trades:
        df = pd.DataFrame(trades)
        df["c1_fill_dt"] = pd.to_datetime(df["c1_fill_ts"], unit="ns",
                                            utc=True)
        # 1-contract design - C1 only (C2 disabled)
        df["c1_pnl_dollars"] = df["c1_pnl_pts"] * NQ_MULT - COMMISSION
        df["total_pnl_dollars"] = df["c1_pnl_dollars"]

        out = Path("studies/level_momentum_continuation/results_breakout")
        out.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out / "nt_mbp1_bucket_oos_trades.parquet")
        print(f"  saved trades parquet")

        print(f"\nPer-group results (BUCKET-FILTERED TICK OOS 2026):")
        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            g = df[df["group"] == grp]
            if len(g) == 0:
                print(f"  [{grp}] NO TRADES")
                continue
            n = len(g)
            wr = (g["exit_reason"] == "win").mean() * 100
            tot = g["total_pnl_dollars"].sum()
            print(f"  [{grp}] n={n:,}  WR={wr:.1f}%  "
                  f"total ${tot:+,.0f}  ({tot/n:+.2f}/tr)")

        total_all = df["total_pnl_dollars"].sum()
        print(f"\nALL GROUPS: total ${total_all:+,.0f}  "
              f"({total_all/len(df):+.2f}/tr on {len(df):,} trades)")

        df["month"] = df["c1_fill_dt"].dt.to_period("M")
        print(f"\nMonthly breakdown:")
        for mo, g in df.groupby("month"):
            print(f"  {mo}: n={len(g):,}  total ${g['total_pnl_dollars'].sum():+,.0f}")

        print(f"\n{'='*78}")
        print(f"COMPARISON to prior tick OOS designs (2026 Jan-Apr):")
        print(f"  unfiltered EMA13+v-recovery (tick): -$21,550 on 4,105 trades (-$5.25/tr)")
        print(f"  THIS bucket-filter 1-ctr (tick):    ${total_all:+,.0f} on {len(df):,} trades ({total_all/len(df):+.2f}/tr)")
        print(f"\n  bucket study expected (1s sim 2024+2025 IS): +$57K on 5,663 trades ($10/tr)")
        print(f"  scaled to 2026 ~4mo OOS (~1/6 of IS): expect ~$10K (rough)")

    engine.dispose()
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
