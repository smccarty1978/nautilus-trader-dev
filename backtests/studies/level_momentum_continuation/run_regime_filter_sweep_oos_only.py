"""Re-run ONLY the OOS_2026 leg of the regime filter sweep — the IS_2025
results from the prior run are valid (they used the 2025 instrument
correctly); only the OOS leg was broken by the missing
create_nq_v0_2026() call. With that bug fixed, this re-runs the 4
variants on FIXED 2026 catalog.
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

from studies.level_momentum_continuation.nt_strategy_v1 import (
    LevelMomentumLiveConfig, LevelMomentumLiveStrategy,
)
from studies.level_momentum_continuation.run_nt_path3_oos import (
    create_nq_v0,
)

NQ_MULT = 20.0
COMMISSION = 5.0

VARIANTS = [
    {"name": "baseline",   "regime_filter_v2": False, "ema_trend_filter": False},
    {"name": "A_regime",   "regime_filter_v2": True,  "ema_trend_filter": False},
    {"name": "D_emaTrend", "regime_filter_v2": False, "ema_trend_filter": True},
    {"name": "A+D_both",   "regime_filter_v2": True,  "ema_trend_filter": True},
]


def run_variant(v):
    print(f"\n--- OOS_2026 | variant={v['name']} ---", flush=True)
    catalog = ParquetDataCatalog("data/catalog/NQ_v0_2026_fixed")
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"])
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    print(f"  loaded 1s={len(bars_1s):,}  1m={len(bars_1m):,}", flush=True)

    nq = create_nq_v0()  # 2026 instrument from run_nt_path3_oos
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"LMC-FILTER-{v['name']}-OOS",
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
        strategy_id=f"LMC-FILTER-{v['name']}-OOS",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        ema_period=13,
        mae_min=3.0,
        bucket_filter_enabled=False,
        disable_v_recovery=True,
        regime_filter_v2=v["regime_filter_v2"],
        regime_short_period=3,
        regime_long_period=9,
        ema_trend_filter=v["ema_trend_filter"],
        ema_trend_lookback=5,
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s", flush=True)

    trades = strat._trades
    df = pd.DataFrame(trades) if trades else pd.DataFrame()
    if len(df):
        df["c1_pnl_dollars"] = df["c1_pnl_pts"] * NQ_MULT - COMMISSION
        df["total_pnl_dollars"] = df["c1_pnl_dollars"]
    engine.dispose()
    del bars_1s, bars_1m, engine, strat
    gc.collect()
    return df


def main():
    t0 = time.time()
    print("=" * 78)
    print("REGIME FILTER OOS_2026 RERUN — bug-fixed (FIXED 2026 catalog)")
    print("=" * 78)
    rows = []
    out = Path("studies/level_momentum_continuation/results_breakout")
    for v in VARIANTS:
        df = run_variant(v)
        if len(df) == 0:
            print(f"  [{v['name']}]: NO TRADES")
            continue
        df.to_parquet(out / f"regime_filter_{v['name']}_OOS_2026_FIXED.parquet")
        n = len(df)
        tot = df["total_pnl_dollars"].sum()
        wr = (df["exit_reason"] == "win").mean() * 100
        print(f"  [{v['name']}] OOS_2026: n={n:,}  WR={wr:.1f}%  "
              f"total ${tot:+,.0f}  (${tot/n:+.2f}/tr)")
        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            g = df[df["group"] == grp]
            if len(g) == 0: continue
            gtot = g["total_pnl_dollars"].sum()
            gwr = (g["exit_reason"] == "win").mean() * 100
            print(f"     [{grp}] n={len(g):,}  WR={gwr:.1f}%  "
                  f"total ${gtot:+,.0f}  (${gtot/len(g):+.2f}/tr)")
            rows.append({"variant": v["name"], "group": grp,
                         "n": len(g), "wr": gwr, "total": gtot,
                         "per_trade": gtot/len(g)})
        rows.append({"variant": v["name"], "group": "ALL",
                     "n": n, "wr": wr, "total": tot, "per_trade": tot/n})
    pd.DataFrame(rows).to_csv(
        out / "regime_filter_OOS_2026_FIXED_summary.csv", index=False)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
