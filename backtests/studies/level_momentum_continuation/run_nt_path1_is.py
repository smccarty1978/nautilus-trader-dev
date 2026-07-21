"""Path 1 — IS validation of LevelMomentumLive strategy on
NQ.XCME catalog 2024+2025 RTH.

Compares NT-engine output to offline +$97K combined (A+B+C) sim.

Caveat: NQ.XCME catalog uses front-month / NQ.c.0 contract; offline
sim used NQ.v.0. May differ on quarterly roll days (Mar/Jun/Sep/Dec
3rd Thursday) by ~$5-15K total.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np
import pytz

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

NQ_MULT = 20.0
COMMISSION = 5.0   # round-trip per contract


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2024-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2025-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2024-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def main():
    t0 = time.time()
    print("=" * 78)
    print("PATH 1 — IS validation: NQ.XCME catalog 2024+2025 RTH")
    print("=" * 78)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")
    print(f"Loading bars from catalog (warmup data included)...")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start - pd.DateOffset(days=2), end=end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=start - pd.DateOffset(days=2), end=end)
    print(f"  loaded 1s={len(bars_1s):,}  1m={len(bars_1m):,}")

    nq = create_nq()

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-PATH1-IS",
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
        strategy_id="LMC-IS",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        ema_period=13,
        mae_min=3.0,
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    print(f"\nRunning NT BacktestEngine on 2024+2025...")
    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s")

    trades = strat._trades
    print(f"\nTrades captured: {len(trades):,}")

    # Compute aggregate metrics
    if trades:
        df = pd.DataFrame(trades)
        df["c1_fill_dt"] = pd.to_datetime(df["c1_fill_ts"], unit="ns",
                                            utc=True)
        df["year"] = df["c1_fill_dt"].dt.year
        # Per-trade $ PnL (gross + commission per fill)
        # Each contract has commission charged ONCE on entry (and exit)
        df["c1_pnl_dollars"] = df["c1_pnl_pts"] * NQ_MULT - COMMISSION
        df["c2_pnl_dollars"] = np.where(
            df["c2_added"],
            df["c2_pnl_pts"] * NQ_MULT - COMMISSION, 0.0)
        df["total_pnl_dollars"] = (df["c1_pnl_dollars"] +
                                       df["c2_pnl_dollars"])

        out = Path("studies/level_momentum_continuation/results_breakout")
        out.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out / "nt_path1_is_trades.parquet")
        print(f"  saved trades parquet")

        # Per-group summary
        print(f"\nPer-group results:")
        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            g = df[df["group"] == grp]
            if len(g) == 0:
                print(f"  [{grp}] NO TRADES")
                continue
            n = len(g)
            wr = (g["exit_reason"] == "win").mean() * 100
            c2_pct = g["c2_added"].mean() * 100
            tot = g["total_pnl_dollars"].sum()
            y24 = g[g["year"]==2024]["total_pnl_dollars"].sum()
            y25 = g[g["year"]==2025]["total_pnl_dollars"].sum()
            print(f"  [{grp}] n={n:,}  WR={wr:.1f}%  c2={c2_pct:.1f}%  "
                  f"total ${tot:+,.0f}  (2024 ${y24:+,.0f} / "
                  f"2025 ${y25:+,.0f})")

        total_all = df["total_pnl_dollars"].sum()
        y24_all = df[df["year"]==2024]["total_pnl_dollars"].sum()
        y25_all = df[df["year"]==2025]["total_pnl_dollars"].sum()
        print(f"\nALL GROUPS: total ${total_all:+,.0f}  "
              f"(2024 ${y24_all:+,.0f} / 2025 ${y25_all:+,.0f})")
        print(f"\nOFFLINE SIM EXPECTED: combined +$96,855  "
              f"(2024 +$12,535 / 2025 +$80,915)")
        print(f"NT delta: ${total_all - 96855:+,.0f}")

        # Engine portfolio stats
        try:
            stats = engine.portfolio.analyzer.get_performance_stats_general()
            print(f"\nNT Engine portfolio stats:")
            for k, v in stats.items():
                print(f"  {k}: {v}")
        except Exception as e:
            print(f"  (portfolio stats unavailable: {e})")

    engine.dispose()
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
