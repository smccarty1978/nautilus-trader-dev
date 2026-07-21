"""Regime filter sweep on FIXED catalogs.

Tests four variants of the clean 1-contract design:
  - baseline: no regime filter
  - A: RegimeIndicatorsV2 alignment (long if regime=+1, short if regime=-1)
  - D: EMA13 trend (long if ema_now > ema_5_ago, short if <)
  - A+D: both filters (intersection)

Runs each on:
  - 2025 IS  (data/catalog/NQ_v0_2025_fixed/)
  - 2026 OOS (data/catalog/NQ_v0_2026_fixed/)

Reports per-group bucket-level deltas and tradability.
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
from studies.level_momentum_continuation.run_nt_v0_2025_1s import (
    create_nq_v0 as create_nq_v0_2025,
)
from studies.level_momentum_continuation.run_nt_path3_oos import (
    create_nq_v0 as create_nq_v0_2026,
)

NQ_MULT = 20.0
COMMISSION = 5.0


VARIANTS = [
    {"name": "baseline", "regime_filter_v2": False, "ema_trend_filter": False},
    {"name": "A_regime", "regime_filter_v2": True,  "ema_trend_filter": False},
    {"name": "D_emaTrend", "regime_filter_v2": False, "ema_trend_filter": True},
    {"name": "A+D_both", "regime_filter_v2": True,  "ema_trend_filter": True},
]


def run_one(catalog_dir: Path, variant: dict, label: str):
    print(f"\n--- {label} | variant={variant['name']} ---", flush=True)
    catalog = ParquetDataCatalog(str(catalog_dir))
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"])
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    print(f"  loaded 1s={len(bars_1s):,}  1m={len(bars_1m):,}", flush=True)

    # Pick instrument based on period — instrument carries activation
    # and expiration timestamps; using the 2025 instrument against 2026
    # data silently produces 0 trades (NT rejects orders on expired
    # contracts).
    nq = create_nq_v0_2025() if label == "IS_2025" else create_nq_v0_2026()
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"LMC-FILTER-{variant['name']}-{label}",
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
        strategy_id=f"LMC-FILTER-{variant['name']}-{label}",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        ema_period=13,
        mae_min=3.0,
        bucket_filter_enabled=False,
        disable_v_recovery=True,
        regime_filter_v2=variant["regime_filter_v2"],
        regime_short_period=3,
        regime_long_period=9,
        ema_trend_filter=variant["ema_trend_filter"],
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


def report(df: pd.DataFrame, label: str, variant_name: str):
    if not len(df):
        print(f"  [{variant_name}] {label}: NO TRADES")
        return None
    n = len(df)
    tot = df["total_pnl_dollars"].sum()
    wr = (df["exit_reason"] == "win").mean() * 100
    print(f"  [{variant_name}] {label}: n={n:,}  WR={wr:.1f}%  "
          f"total ${tot:+,.0f}  (${tot/n:+.2f}/tr)")
    rows = []
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        gtot = g["total_pnl_dollars"].sum()
        gwr = (g["exit_reason"] == "win").mean() * 100
        print(f"     [{grp}] n={len(g):,}  WR={gwr:.1f}%  "
              f"total ${gtot:+,.0f}  (${gtot/len(g):+.2f}/tr)")
        rows.append({"variant": variant_name, "period": label, "group": grp,
                     "n": len(g), "wr": gwr, "total": gtot,
                     "per_trade": gtot/len(g)})
    rows.append({"variant": variant_name, "period": label, "group": "ALL",
                 "n": n, "wr": wr, "total": tot, "per_trade": tot/n})
    return rows


def main():
    t0 = time.time()
    print("=" * 78)
    print("REGIME FILTER SWEEP — FIXED CATALOGS  (NT 1s, clean 1-ctr)")
    print("=" * 78)

    out_dir = Path("studies/level_momentum_continuation/results_breakout")
    all_rows = []

    for label, cat_dir in [
        ("IS_2025",  Path("data/catalog/NQ_v0_2025_fixed")),
        ("OOS_2026", Path("data/catalog/NQ_v0_2026_fixed")),
    ]:
        print(f"\n{'='*78}")
        print(f"{label}  catalog={cat_dir}")
        print(f"{'='*78}")
        for v in VARIANTS:
            df = run_one(cat_dir, v, label)
            if len(df):
                df.to_parquet(
                    out_dir / f"regime_filter_{v['name']}_{label}.parquet")
            rows = report(df, label, v["name"])
            if rows:
                all_rows.extend(rows)

    # Summary table
    print(f"\n{'='*78}")
    print("SUMMARY")
    print(f"{'='*78}")
    summary = pd.DataFrame(all_rows)
    summary.to_csv(out_dir / "regime_filter_sweep_summary.csv", index=False)

    print(f"\n{'period':<10} {'variant':<12} {'group':<14} "
          f"{'n':>6} {'WR%':>6} {'total$':>12} {'$/tr':>8}")
    for _, r in summary.iterrows():
        print(f"{r['period']:<10} {r['variant']:<12} {r['group']:<14} "
              f"{int(r['n']):>6,} {r['wr']:>5.1f}% "
              f"{r['total']:>+11,.0f} {r['per_trade']:>+7.2f}")

    # Compare ALL-row delta vs baseline per period
    print(f"\n{'='*78}")
    print("BASELINE-RELATIVE PnL Δ (ALL groups)")
    print(f"{'='*78}")
    pivot = summary[summary["group"] == "ALL"].pivot(
        index="period", columns="variant", values="total")
    if "baseline" in pivot.columns:
        for v in ("A_regime", "D_emaTrend", "A+D_both"):
            if v in pivot.columns:
                pivot[f"Δ_{v}"] = pivot[v] - pivot["baseline"]
        print(pivot.to_string())

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
