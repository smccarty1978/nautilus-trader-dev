"""Re-run NT 1s clean 1-contract design against the FIXED catalog
(closed='left' resample). Compare to the existing NT tick result.

If the off-by-one was the cause of the $94K phantom gap, the fixed-1s
total should align with NT tick (~+$7K, +$0.65/tr).
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
from studies.level_momentum_continuation.run_nt_v0_2025_1s import (
    create_nq_v0,
)

NQ_MULT = 20.0
COMMISSION = 5.0


def main():
    t0 = time.time()
    print("=" * 78)
    print("NT 1s on FIXED catalog (closed='left' resample) — clean 1-ctr")
    print("=" * 78)

    cat_dir = Path("data/catalog/NQ_v0_2025_fixed")
    if not cat_dir.exists():
        print(f"ERROR: fixed catalog {cat_dir} not built")
        sys.exit(1)

    catalog = ParquetDataCatalog(str(cat_dir))
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"])
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    print(f"  loaded 1s={len(bars_1s):,}  1m={len(bars_1m):,}", flush=True)

    nq = create_nq_v0()
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-V0-2025-FIXED-1S",
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
        strategy_id="LMC-V0-2025-FIXED-1S",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        ema_period=13,
        mae_min=3.0,
        bucket_filter_enabled=False,
        disable_v_recovery=True,
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s", flush=True)

    trades = strat._trades
    print(f"\nTrades captured: {len(trades):,}")
    if not trades:
        print("NO TRADES — abort")
        return
    df = pd.DataFrame(trades)
    df["c1_pnl_dollars"] = df["c1_pnl_pts"] * NQ_MULT - COMMISSION
    df["total_pnl_dollars"] = df["c1_pnl_dollars"]
    out = Path("studies/level_momentum_continuation/results_breakout")
    df.to_parquet(out / "nt_v0_2025_FIXED_1s_trades.parquet")

    n = len(df)
    tot = df["total_pnl_dollars"].sum()
    wr = (df["exit_reason"] == "win").mean() * 100
    print(f"\n[FIXED 1s clean 1-ctr] n={n:,}  WR={wr:.1f}%  "
          f"total ${tot:+,.0f}  (${tot/n:+.2f}/tr)")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        gtot = g["total_pnl_dollars"].sum()
        gwr = (g["exit_reason"] == "win").mean() * 100
        print(f"  [{grp}] n={len(g):,}  WR={gwr:.1f}%  "
              f"total ${gtot:+,.0f}  (${gtot/len(g):+.2f}/tr)")

    # Compare to existing tick + buggy 1s
    print(f"\n{'='*78}")
    print(f"GAP COLLAPSE TEST")
    print(f"{'='*78}")
    df_1s_buggy = pd.read_parquet(out / "nt_v0_2025_clean_1s_trades.parquet")
    df_tick = pd.read_parquet(out / "nt_v0_2025_clean_tick_trades.parquet")
    n_b = len(df_1s_buggy); tot_b = df_1s_buggy["total_pnl_dollars"].sum()
    n_t = len(df_tick);    tot_t = df_tick["total_pnl_dollars"].sum()
    print(f"  BUGGY 1s (closed=right): n={n_b:,}  total ${tot_b:+,.0f}  "
          f"(${tot_b/n_b:+.2f}/tr)")
    print(f"  FIXED 1s (closed=left):  n={n:,}  total ${tot:+,.0f}  "
          f"(${tot/n:+.2f}/tr)")
    print(f"  TICK NT:                 n={n_t:,}  total ${tot_t:+,.0f}  "
          f"(${tot_t/n_t:+.2f}/tr)")
    print(f"\n  FIXED-1s vs TICK gap:  ${tot - tot_t:+,.0f} total, "
          f"{(tot/n - tot_t/n_t):+.2f}/tr")
    print(f"  BUGGY-1s vs TICK gap:  ${tot_b - tot_t:+,.0f} total, "
          f"{(tot_b/n_b - tot_t/n_t):+.2f}/tr")

    engine.dispose()
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
