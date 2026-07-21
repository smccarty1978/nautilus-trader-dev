"""V_A + HH/LL Structural Exit — Tick-Driven NT Validation.

Loads:
  - 1s + 1m bars from catalog (drives strategy state)
  - TradeTick stream from raw Databento parquet (drives execution)

Configuration:
  - bar_execution=False — fills must come from ticks
  - HH/LL exit overlay enabled (C_lock50_30s_5)
  - tick_dollar=0.0 — real tick fills replace the proxy slip;
    commission only

Outputs:
  collectors/collector_v2/results/tick_nt/<label>_<window>/
    trades.parquet, snapshots.parquet, micro_pre.parquet,
    micro_post.parquet, diag.json
"""

from __future__ import annotations
import argparse, os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import (
    AccountType, OmsType, AggressorSide,
)
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import (
    TradeTickDataWrangler,
)

from collectors.collector_v2.strategy import (
    CollectorV2Strategy, CollectorV2Config,
)
from collectors.collector_v2.run_portfolio import (
    PRODUCT_CFG, create_instrument,
)


def load_trade_ticks(
    raw_paths: list[str], instrument,
    start: pd.Timestamp, end: pd.Timestamp,
) -> list:
    """Load trade ticks from one or more raw Databento parquet
    files, filtering to [start, end) and wrangling to NT
    TradeTick objects."""
    import pyarrow.parquet as pq
    frames = []
    for p in raw_paths:
        if not os.path.exists(p):
            print(f"  WARN: {p} not found, skipping")
            continue
        print(f"  Reading {p}...", flush=True)
        tbl = pq.read_table(
            p,
            columns=["ts_event", "price", "size", "side",
                       "action", "sequence"],
            filters=[
                ("ts_event", ">=", start),
                ("ts_event", "<", end),
                ("action", "=", "T"),
            ],
        )
        df = tbl.to_pandas()
        if len(df):
            frames.append(df)
        print(f"    {len(df):,} trade rows in window")
    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"  Total combined: {len(df):,} trade ticks")
    print(f"  Wrangling to NT TradeTick objects...", flush=True)
    df = df.set_index("ts_event")
    side_map = {
        "A": int(AggressorSide.SELLER),
        "B": int(AggressorSide.BUYER),
        "N": int(AggressorSide.NO_AGGRESSOR),
    }
    df["aggressor_side"] = (
        df["side"].map(side_map).fillna(
            int(AggressorSide.NO_AGGRESSOR)).astype("int8"))
    df["trade_id"] = df["sequence"].astype(str)
    df = df.rename(columns={"size": "quantity"})
    wrangler = TradeTickDataWrangler(instrument=instrument)
    ticks = wrangler.process(
        data=df[["price", "quantity", "aggressor_side",
                  "trade_id"]],
        ts_init_delta=0,   # tick ts already correct
    )
    print(f"  Built {len(ticks):,} TradeTick objects")
    return ticks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True,
                     help="Start date YYYY-MM-DD (UTC)")
    ap.add_argument("--end", required=True,
                     help="End date YYYY-MM-DD (UTC, exclusive)")
    ap.add_argument("--label", default="hhll_lock50_30s_5")
    ap.add_argument("--ticks_paths", nargs="+",
                     default=[
                         "data/raw/NQ_trades_jan2025.parquet",
                         "data/raw/NQ_trades_20250201_20250930.parquet",
                         "data/raw/NQ_trades_oct_dec_2025.parquet",
                     ])
    ap.add_argument("--enable_hhll", action="store_true",
                     default=False)
    ap.add_argument("--no_entry_after_min_ct", type=int, default=0,
                     help="CT minute (e.g., 885=14:45) to stop new "
                     "entries; 0=off")
    ap.add_argument("--force_flat_at_min_ct", type=int, default=0,
                     help="CT minute (e.g., 898=14:58) to force "
                     "flat any open trade; 0=off")
    args = ap.parse_args()

    pcfg = PRODUCT_CFG["NQ"]
    out_dir = Path(
        f"collectors/collector_v2/results/tick_nt/"
        f"{args.label}_{args.start}_{args.end}")
    out_dir.mkdir(parents=True, exist_ok=True)

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    # Load extra warmup bars for indicator initialization
    load_start = start - pd.Timedelta(days=5)
    print(f"[{args.label} {args.start}→{args.end}] Loading bars "
          f"{load_start} -> {end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(pcfg["catalog"])
    bars_1s = catalog.bars(
        bar_types=[pcfg["bar_type_1s"]],
        start=load_start, end=end)
    bars_1m = catalog.bars(
        bar_types=[pcfg["bar_type_1m"]],
        start=load_start, end=end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
          f"({time.time()-t0:.0f}s)")
    if not bars_1s or not bars_1m:
        print("  NO DATA — abort"); return

    instrument = create_instrument("NQ", pcfg)
    print(f"\nLoading TradeTicks for [{args.start}, {args.end})...",
          flush=True)
    t0 = time.time()
    ticks = load_trade_ticks(
        args.ticks_paths, instrument, start, end)
    print(f"  TradeTick load complete ({time.time()-t0:.0f}s)")
    if not ticks:
        print("  NO TICKS — abort"); return

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"TICK-NQ25-001",
        logging=LoggingConfig(
            log_level="WARNING",
            log_directory=str(out_dir / "logs")),
    ))
    # IMPORTANT: bar_execution=False so the matching engine
    # uses incoming TradeTicks for fills (realistic).
    engine.add_venue(
        venue=Venue(pcfg["venue"]), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=False,
        trade_execution=True,
    )
    engine.add_instrument(instrument)
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)
    engine.add_data(ticks)

    cfg = CollectorV2Config(
        instrument_id=pcfg["instrument_id"],
        bar_type_1m=pcfg["bar_type_1m"],
        bar_type_1s=pcfg["bar_type_1s"],
        mode="trading",
        rth_only=False,
        position_size=1,
        require_5m_aligned=False,
        output_dir=str(out_dir),
        multiplier=pcfg["multiplier"],
        # Tick fills replace the proxy slip — commission only
        tick_dollar=0.0,
        commission_per_rt=5.0,
        # HH/LL structural exit overlay
        enable_hhll_exit=args.enable_hhll,
        hhll_min_mfe_atr=1.0,
        hhll_stall_buckets_30s=5,
        hhll_lock_pct=0.50,
        # Live-tradable guardrails
        no_entry_after_min_ct=args.no_entry_after_min_ct,
        force_flat_at_min_ct=args.force_flat_at_min_ct,
    )
    strat = CollectorV2Strategy(cfg)
    engine.add_strategy(strat)

    print(f"\nRunning tick-driven NT (HH/LL exit "
          f"{'ENABLED' if args.enable_hhll else 'DISABLED'})...",
          flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")
    print(f"  Diag: {strat._diag}")
    engine.dispose()


if __name__ == "__main__":
    main()
