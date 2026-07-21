"""DIAGNOSTIC: 1-contract CLEAN design (no v-recovery) — 2025 1s vs tick.

Goal: isolate the structural 1s-vs-tick gap from the v-recovery/BE
contribution. If clean 1-contract has a small gap, then v-recovery is
the culprit and we know to avoid BE+1tick mechanics. If clean still
shows $5-10/tr gap, then the gap is structural (entry timing,
aggregation) and affects all designs.

Same harness as run_nt_v0_2025_1s.py and run_nt_v0_2025_tick.py but
with disable_v_recovery=True.
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
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract

from studies.level_momentum_continuation.nt_strategy_v1 import (
    LevelMomentumLiveConfig, LevelMomentumLiveStrategy,
)
from studies.level_momentum_continuation.run_nt_v0_2025_1s import (
    create_nq_v0,
)
from studies.level_momentum_continuation.run_nt_v0_2025_tick import (
    load_trades_to_nt_ticks,
)

NQ_MULT = 20.0
COMMISSION = 5.0


def run_1s(nq):
    print("\n=== 1s NT mode ===", flush=True)
    cat_dir = Path("data/catalog/NQ_v0_2025")
    catalog = ParquetDataCatalog(str(cat_dir))
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"])
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    print(f"  loaded 1s={len(bars_1s):,}  1m={len(bars_1m):,}", flush=True)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-V0-2025-CLEAN-1S",
        logging=LoggingConfig(log_level="ERROR"),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    config = LevelMomentumLiveConfig(
        strategy_id="LMC-V0-2025-CLEAN-1S",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        ema_period=13,
        mae_min=3.0,
        bucket_filter_enabled=False,
        disable_v_recovery=True,   # KEY: 1-contract clean
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s", flush=True)

    trades = strat._trades
    engine.dispose()
    return trades


def run_tick(nq):
    print("\n=== TICK NT mode ===", flush=True)
    path = Path("data/raw/NQ_trades_20250101_20251231.parquet")
    ticks = load_trades_to_nt_ticks(path, nq)
    print(f"  TradeTicks: {len(ticks):,}", flush=True)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-V0-2025-CLEAN-TICK",
        logging=LoggingConfig(log_level="ERROR"),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(nq)
    engine.add_data(ticks)
    del ticks; gc.collect()

    config = LevelMomentumLiveConfig(
        strategy_id="LMC-V0-2025-CLEAN-TICK",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-INTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-INTERNAL",
        ema_period=13,
        mae_min=3.0,
        bucket_filter_enabled=False,
        disable_v_recovery=True,   # KEY: 1-contract clean
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s", flush=True)

    trades = strat._trades
    engine.dispose()
    return trades


def report(trades, label):
    if not trades:
        print(f"  [{label}] NO TRADES")
        return
    df = pd.DataFrame(trades)
    df["c1_pnl_dollars"] = df["c1_pnl_pts"] * NQ_MULT - COMMISSION
    df["total_pnl_dollars"] = df["c1_pnl_dollars"]   # 1-contract only
    n = len(df)
    tot = df["total_pnl_dollars"].sum()
    print(f"\n[{label}] n={n:,}  total ${tot:+,.0f}  "
          f"({tot/n:+.2f}/tr)")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        gtot = g["total_pnl_dollars"].sum()
        wr = (g["exit_reason"] == "win").mean() * 100
        print(f"  [{grp}] n={len(g):,}  WR={wr:.1f}%  "
              f"total ${gtot:+,.0f}  ({gtot/len(g):+.2f}/tr)")
    return df


def main():
    t0 = time.time()
    print("=" * 78)
    print("DIAGNOSTIC: 1-contract CLEAN (no v-recovery) — 2025 1s vs tick")
    print("Same trade population (chained); only execution mode differs")
    print("=" * 78)

    nq = create_nq_v0()
    trades_1s = run_1s(nq)
    df_1s = report(trades_1s, "1s NT")
    trades_tick = run_tick(nq)
    df_tick = report(trades_tick, "TICK NT")

    if df_1s is not None and df_tick is not None:
        out = Path("studies/level_momentum_continuation/results_breakout")
        df_1s.to_parquet(out / "nt_v0_2025_clean_1s_trades.parquet")
        df_tick.to_parquet(out / "nt_v0_2025_clean_tick_trades.parquet")

        n_1s = len(df_1s); n_tick = len(df_tick)
        tot_1s = df_1s["total_pnl_dollars"].sum()
        tot_tick = df_tick["total_pnl_dollars"].sum()
        print(f"\n{'='*78}")
        print(f"GAP ANALYSIS — clean 1-contract design")
        print(f"{'='*78}")
        print(f"  1s NT:   n={n_1s:,}  total ${tot_1s:+,.0f}  "
              f"(${tot_1s/n_1s:+.2f}/tr)")
        print(f"  Tick NT: n={n_tick:,}  total ${tot_tick:+,.0f}  "
              f"(${tot_tick/n_tick:+.2f}/tr)")
        print(f"  Δ: ${tot_tick - tot_1s:+,.0f} total, "
              f"${tot_tick/n_tick - tot_1s/n_1s:+.2f}/tr")
        print(f"\nRECALL: EMA13+v-recovery design 2025 had:")
        print(f"  1s: +$154,710 ($+13.78/tr) on 11,231 trades")
        print(f"  tick: +$36,990 ($+3.30/tr) on 11,204 trades")
        print(f"  Δ -$10.48/tr — that design has BOTH C1 and C2 (with re-cross)")
        print(f"\nIf this clean version's gap is MUCH smaller (~$1-2/tr):")
        print(f"  → v-recovery (C2 entries) was the main tick gap source")
        print(f"If gap is similar (~$5-10/tr):")
        print(f"  → Structural NT engine difference affects all designs")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
