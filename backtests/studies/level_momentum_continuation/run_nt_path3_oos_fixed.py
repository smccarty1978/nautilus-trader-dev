"""Re-run Path 3 OOS validation on the FIXED 2026 catalog.

Same strategy config as run_nt_path3_oos.py — only the catalog path
changes (NQ_v0_2026 -> NQ_v0_2026_fixed). If the catalog 1m off-by-one
was the entire cause of the 1s-vs-tick gap, this run should land near
the tick OOS result (-$5.25/tr, -$21,550 total) rather than the
buggy +$4.15/tr, +$17,055 total.
"""
from __future__ import annotations
import os, sys, time
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

from studies.level_momentum_continuation.nt_strategy_v1 import (
    LevelMomentumLiveConfig, LevelMomentumLiveStrategy,
)
from studies.level_momentum_continuation.run_nt_path3_oos import (
    create_nq_v0,
)

NQ_MULT = 20.0
COMMISSION = 5.0


def main():
    t0 = time.time()
    print("=" * 78)
    print("PATH 3 — OOS validation on FIXED 2026 catalog (closed='left')")
    print("=" * 78)

    cat_dir = Path("data/catalog/NQ_v0_2026_fixed")
    if not cat_dir.exists():
        print(f"ERROR: fixed catalog {cat_dir} not built")
        sys.exit(1)
    catalog = ParquetDataCatalog(str(cat_dir))

    print(f"Loading bars from FIXED v0_2026 catalog...")
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"])
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    print(f"  loaded 1s={len(bars_1s):,}  1m={len(bars_1m):,}")

    nq = create_nq_v0()
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-PATH3-OOS-FIXED",
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
        strategy_id="LMC-OOS-FIXED",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        ema_period=13,
        mae_min=3.0,
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    print(f"\nRunning NT BacktestEngine...", flush=True)
    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s")

    trades = strat._trades
    print(f"\nTrades captured: {len(trades):,}")
    if not trades:
        print("NO TRADES")
        return
    df = pd.DataFrame(trades)
    df["c1_fill_dt"] = pd.to_datetime(df["c1_fill_ts"], unit="ns", utc=True)
    df["c1_pnl_dollars"] = df["c1_pnl_pts"] * NQ_MULT - COMMISSION
    df["c2_pnl_dollars"] = np.where(
        df["c2_added"],
        df["c2_pnl_pts"] * NQ_MULT - COMMISSION, 0.0)
    df["total_pnl_dollars"] = df["c1_pnl_dollars"] + df["c2_pnl_dollars"]

    out = Path("studies/level_momentum_continuation/results_breakout")
    df.to_parquet(out / "nt_path3_oos_FIXED_trades.parquet")

    print(f"\nPer-group results (2026 OOS, FIXED catalog):")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        n = len(g)
        wr = (g["exit_reason"] == "win").mean() * 100
        c2_pct = g["c2_added"].mean() * 100
        tot = g["total_pnl_dollars"].sum()
        print(f"  [{grp}] n={n:,}  WR={wr:.1f}%  c2={c2_pct:.1f}%  "
              f"total ${tot:+,.0f}  ({tot/n:+.2f}/tr)")
    total_all = df["total_pnl_dollars"].sum()
    print(f"\nALL GROUPS (FIXED 1s OOS): total ${total_all:+,.0f}  "
          f"({total_all/len(df):+.2f}/tr on {len(df):,} trades)")

    print(f"\nMonthly:")
    df["month"] = df["c1_fill_dt"].dt.tz_convert("UTC").dt.to_period("M")
    for mo, g in df.groupby("month"):
        print(f"  {mo}: n={len(g):,}  total ${g['total_pnl_dollars'].sum():+,.0f}")

    print(f"\n{'='*78}")
    print(f"GAP COLLAPSE TEST — 2026 OOS")
    print(f"{'='*78}")
    print(f"  BUGGY 1s NT (path3 prior):  +$17,055  (+$4.15/tr) on 4,105 trades")
    print(f"  FIXED 1s NT (this run):     ${total_all:+,.0f}  "
          f"(${total_all/len(df):+.2f}/tr) on {len(df):,} trades")
    print(f"  TICK NT (mbp1 prior):       -$21,550  (-$5.25/tr) on 4,105 trades")
    print(f"\n  FIXED-1s vs TICK Δ:  ${total_all - (-21550):+,.0f} total, "
          f"{total_all/len(df) - (-5.25):+.2f}/tr")
    print(f"  BUGGY-1s vs TICK Δ:  $+38,605 total, +9.40/tr (the look-ahead inflation)")

    engine.dispose()
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
