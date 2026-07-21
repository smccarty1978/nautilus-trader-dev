"""NT 1s-bar on NQ.v.0 2025 catalog. Reference for the 2025 1s-vs-tick
diagnostic. Uses EMA13+v-recovery design (matches prior tick OOS).
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
    d["activation_ns"] = pd.Timestamp("2025-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2025-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2025-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def main():
    t0 = time.time()
    print("=" * 78)
    print("NT 1s-bar on NQ.v.0 2025 catalog (EMA13 + v-recovery)")
    print("=" * 78)

    cat_dir = Path("data/catalog/NQ_v0_2025")
    if not cat_dir.exists():
        print(f"ERROR: catalog {cat_dir} not built")
        sys.exit(1)
    catalog = ParquetDataCatalog(str(cat_dir))
    print(f"Loading bars...")
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"])
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    print(f"  loaded 1s={len(bars_1s):,}  1m={len(bars_1m):,}")

    nq = create_nq_v0()
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="LMC-V0-2025-1S",
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
        strategy_id="LMC-V0-2025-1S",
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        ema_period=13,
        mae_min=3.0,
        bucket_filter_enabled=False,
        disable_v_recovery=False,
    )
    strat = LevelMomentumLiveStrategy(config=config)
    engine.add_strategy(strat)

    print(f"\nRunning NT BacktestEngine...", flush=True)
    t1 = time.time()
    engine.run()
    print(f"  engine.run() took {time.time()-t1:.0f}s")

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
        df.to_parquet(out / "nt_v0_2025_1s_trades.parquet")
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
