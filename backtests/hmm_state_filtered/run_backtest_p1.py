"""Runner for HMM state-filtered P1 (partial+BE) NT validation."""
import argparse
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

sys.path.insert(0, str(Path(__file__).parent))
from strategy_p1 import HMMStateFilteredP1Config, HMMStateFilteredP1Strategy


PRODUCT_CFG = {
    "NQ": dict(symbol="NQ", multiplier="20", price_increment="0.25",
                bar_type="NQ.XCME-1-SECOND-LAST-EXTERNAL",
                instrument_id="NQ.XCME",
                catalog="data/catalog/NQ_v0_2020_2026",
                state_path="studies/regime_classification/results/states_nq_1m.parquet"),
    "ES": dict(symbol="ES", multiplier="50", price_increment="0.25",
                bar_type="ES.XCME-1-SECOND-LAST-EXTERNAL",
                instrument_id="ES.XCME",
                catalog="data/catalog/ES_v0_2020_2026",
                state_path="studies/regime_classification/results/states_es_1m.parquet"),
}


def create_instrument(product: str):
    cfg = PRODUCT_CFG[product]
    t = TestInstrumentProvider.future(
        symbol=cfg["symbol"], underlying=cfg["symbol"],
        venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"] = cfg["multiplier"]
    d["price_increment"] = cfg["price_increment"]
    return FuturesContract.from_dict(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--product", choices=["NQ", "ES"], default="NQ")
    ap.add_argument("--state-col", default="hmm_4")
    ap.add_argument("--target-state", type=int, default=3)
    ap.add_argument("--lead-in-days", type=int, default=5)
    ap.add_argument("--min-state-dur", type=int, default=0)
    ap.add_argument("--entry-size", type=int, default=2)
    ap.add_argument("--partial-atr", type=float, default=1.0)
    ap.add_argument("--partial-size", type=int, default=1)
    ap.add_argument("--be-after-partial", type=int, default=1,
                    help="1=arm BE on runner after partial fill; 0=no BE")
    ap.add_argument("--entry-anchor", default="bar1_confirm",
                    choices=["bar1_confirm", "bar1", "flip"])
    ap.add_argument("--state-path-5m", default="")
    ap.add_argument("--state-col-5m", default="")
    ap.add_argument("--target-state-5m", type=int, default=-1)
    ap.add_argument("--anchor-5m", default="bar1", choices=["flip", "bar1"])
    args = ap.parse_args()

    product = args.product
    cfg = PRODUCT_CFG[product]

    if args.state_col_5m and not args.state_path_5m:
        args.state_path_5m = f"studies/regime_classification/results/states_{product.lower()}_5m.parquet"

    year = args.year
    dur_suffix = f"_dur{args.min_state_dur}" if args.min_state_dur > 0 else ""
    p1_suffix = (f"_p1_e{args.entry_size}p{args.partial_size}@"
                  f"{args.partial_atr}".replace(".", "p")
                  + ("_BE" if args.be_after_partial else "_noBE"))
    anchor_suffix = f"_anc{args.entry_anchor}" if args.entry_anchor != "bar1_confirm" else ""
    m5_suffix = f"_m5_{args.state_col_5m}_s{args.target_state_5m}_{args.anchor_5m}" if args.state_col_5m else ""
    out_dir = Path(f"backtests/hmm_state_filtered/results/"
                   f"{product.lower()}_{args.state_col}_s{args.target_state}"
                   f"{dur_suffix}{p1_suffix}{anchor_suffix}{m5_suffix}_{year}")
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=args.lead_in_days)
    load_end   = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"Year {year}: bar load {load_start} .. {load_end}")

    catalog = ParquetDataCatalog(cfg["catalog"])
    t0 = time.time()
    bars_1s = catalog.bars(
        bar_types=[cfg["bar_type"]],
        start=load_start, end=load_end)
    print(f"  Loaded {len(bars_1s):,} 1s bars  ({time.time()-t0:.0f}s)")
    if not bars_1s:
        return

    inst = create_instrument(product)
    engine_cfg = BacktestEngineConfig(
        trader_id="HMM-P1",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="INFO",
            log_directory=str(out_dir / "logs"),
        ),
    )
    engine = BacktestEngine(config=engine_cfg)
    engine.add_venue(
        venue=Venue("XCME"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True,
        bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(inst)
    engine.add_data(bars_1s)

    strat = HMMStateFilteredP1Strategy(
        HMMStateFilteredP1Config(
            instrument_id=cfg["instrument_id"],
            bar_type_1s=cfg["bar_type"],
            state_lookup_path=cfg["state_path"],
            state_col=args.state_col,
            target_state=args.target_state,
            min_state_dur=args.min_state_dur,
            entry_size=args.entry_size,
            partial_atr=args.partial_atr,
            partial_size=args.partial_size,
            be_after_partial=bool(args.be_after_partial),
            tick_size=float(cfg["price_increment"]),
            entry_anchor=args.entry_anchor,
            state_lookup_path_5m=args.state_path_5m,
            state_col_5m=args.state_col_5m,
            target_state_5m=args.target_state_5m,
            anchor_5m=args.anchor_5m))
    engine.add_strategy(strat)

    print("\nRunning backtest...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time()-t0:.0f}s")

    trades = pd.DataFrame(strat.all_trades)
    print(f"\nTotal trades: {len(trades)}")
    if len(trades) > 0:
        yr_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
        yr_end_ns   = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
        in_year = trades[
            (trades["entry_ts"] >= yr_start_ns) &
            (trades["entry_ts"] <= yr_end_ns)].copy()
        print(f"In-year trades: {len(in_year)}")
        print(f"\nBy direction:\n{in_year['signal_direction'].value_counts().to_string()}")
        print(f"\nPartial-fill rate: {in_year['partial_filled'].mean():.1%}")
        print(f"Runner exit reasons:\n{in_year['runner_exit_reason'].value_counts().to_string()}")
        out_path = out_dir / "trades.parquet"
        in_year.to_parquet(out_path, index=False)
        print(f"\nWrote {len(in_year)} trade records → {out_path}")

    print("\n--- Signal Gate Diagnostics ---")
    for k, v in strat._diag.items():
        print(f"  {k}: {v}")

    engine.dispose()


if __name__ == "__main__":
    main()
