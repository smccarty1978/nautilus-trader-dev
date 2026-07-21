"""Runner for HMM-state-filtered, bar1-confirmed, regime-exit NT validation."""
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
from strategy import HMMStateFilteredConfig, HMMStateFilteredStrategy


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
    ap.add_argument("--pt-atr", type=float, default=2.0,
                    help="profit-target in ATR units (0 = regime-exit only baseline)")
    ap.add_argument("--sl-atr", type=float, default=0.0,
                    help="stop-loss in ATR units (0 = regime-exit only baseline)")
    ap.add_argument("--state-path-5m", default="",
                    help="Path to 5m states parquet (default empty = disabled)")
    ap.add_argument("--state-col-5m", default="")
    ap.add_argument("--target-state-5m", type=int, default=-1)
    ap.add_argument("--anchor-5m", default="bar1", choices=["flip", "bar1"])
    ap.add_argument("--entry-anchor", default="bar1_confirm",
                    choices=["bar1_confirm", "bar1", "flip"],
                    help="bar1_confirm = current default; bar1 = enter at T+60s no shape filter; "
                         "flip = enter at T+1s, raw-flip + state-only")
    ap.add_argument("--state-path", default="",
                    help="Override state parquet path (default: product config)")
    ap.add_argument("--state-tag", default="",
                    help="Optional suffix tag for output dir (e.g. 'rollq')")
    ap.add_argument("--be-trig-atr", type=float, default=0.0,
                    help="Trigger BE stop once peak MFE reaches this * ATR")
    ap.add_argument("--be-level-atr", type=float, default=0.0,
                    help="Level to move stop to (e.g. -0.25 ATR or 0.0 ATR)")
    ap.add_argument("--min-atr", type=float, default=0.0,
                    help="Filter out signals below this ATR threshold")
    ap.add_argument("--max-hold-s", type=int, default=60,
                    help="Maximum hold time in seconds (time-exit)")
    ap.add_argument("--vwap-exit-active", action="store_true",
                    help="Activate Strategy F VWAP-conditioned exit policy")
    ap.add_argument("--qty", type=int, default=1,
                    help="Quantity of contracts to enter (2 for Strategy F)")
    ap.add_argument("--pt-runner-atr", type=float, default=2.0,
                    help="Runner profit target in ATR units for Strategy F")
    ap.add_argument("--pt-c1-atr", type=float, default=0.50,
                    help="Contract 1 scale-out profit target in ATR units for Strategy F")
    ap.add_argument("--vwap-z-threshold", type=float, default=1.0,
                    help="VWAP z-score threshold for exhaustion")
    ap.add_argument("--features-path", default="",
                    help="Path to features parquet for causal VWAP lookup")
    ap.add_argument("--post-entry-gates-active", action="store_true",
                    help="Activate Speed Gate + 60s Causal PnL Gate strategy")
    ap.add_argument("--speed-gate-threshold-s", type=float, default=30.0,
                    help="Speed Gate threshold in seconds")
    ap.add_argument("--gate-60s-pnl-atr", type=float, default=0.30,
                    help="60s Causal PnL target in ATR units")
    ap.add_argument("--wide-sl-atr", type=float, default=0.0,
                    help="Wide stop-loss in ATR units for Strategy G adaptive stop logic")
    args = ap.parse_args()

    product = args.product
    cfg = PRODUCT_CFG[product]

    if args.state_col_5m and not args.state_path_5m:
        args.state_path_5m = f"studies/regime_classification/results/states_{product.lower()}_5m.parquet"

    year = args.year
    dur_suffix = f"_dur{args.min_state_dur}" if args.min_state_dur > 0 else ""
    pt_suffix  = f"_pt{args.pt_atr}".replace(".", "p") if args.pt_atr > 0 else ""
    sl_suffix  = f"_sl{args.sl_atr}".replace(".", "p") if args.sl_atr > 0 else ""
    anchor_suffix = f"_anc{args.entry_anchor}" if args.entry_anchor != "bar1_confirm" else ""
    tag_suffix = f"_{args.state_tag}" if args.state_tag else ""
    m5_suffix = f"_m5_{args.state_col_5m}_s{args.target_state_5m}_{args.anchor_5m}" if args.state_col_5m else ""
    be_suffix = f"_be{args.be_trig_atr}_lvl{args.be_level_atr}".replace(".", "p").replace("-", "m") if args.be_trig_atr > 0 else ""
    atr_suffix = f"_minatr{args.min_atr}".replace(".", "p") if args.min_atr > 0 else ""
    vwap_suffix = f"_vwapF_qty{args.qty}_ptr{args.pt_runner_atr}".replace(".", "p") if args.vwap_exit_active else ""
    gates_suffix = f"_gates_qty{args.qty}_ptr{args.pt_runner_atr}".replace(".", "p") if args.post_entry_gates_active else ""
    if args.post_entry_gates_active and args.wide_sl_atr > 0:
        gates_suffix += f"_wsl{args.wide_sl_atr}".replace(".", "p")
    out_dir = Path(f"backtests/hmm_state_filtered/results/"
                   f"{product.lower()}_{args.state_col}_s{args.target_state}"
                   f"{dur_suffix}{pt_suffix}{sl_suffix}{anchor_suffix}{tag_suffix}{m5_suffix}{be_suffix}{atr_suffix}{vwap_suffix}{gates_suffix}_{year}")
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=args.lead_in_days)
    load_end   = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"Year {year}: bar load range {load_start} .. {load_end}")

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
        trader_id="HMM-STATE-FILT",
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

    state_path = args.state_path if args.state_path else cfg["state_path"]
    print(f"  state lookup: {state_path}  (col={args.state_col})")
    strat = HMMStateFilteredStrategy(
        HMMStateFilteredConfig(
            instrument_id=cfg["instrument_id"],
            bar_type_1s=cfg["bar_type"],
            state_lookup_path=state_path,
            state_col=args.state_col,
            target_state=args.target_state,
            min_state_dur=args.min_state_dur,
            pt_atr=args.pt_atr,
            sl_atr=args.sl_atr,
            tick_size=float(cfg["price_increment"]),
            entry_anchor=args.entry_anchor,
            state_lookup_path_5m=args.state_path_5m,
            state_col_5m=args.state_col_5m,
            target_state_5m=args.target_state_5m,
            anchor_5m=args.anchor_5m,
            be_trig_atr=args.be_trig_atr,
            be_level_atr=args.be_level_atr,
            min_atr=args.min_atr,
            max_hold_s=args.max_hold_s,
            vwap_exit_active=args.vwap_exit_active,
            qty=args.qty,
            pt_runner_atr=args.pt_runner_atr,
            pt_c1_atr=args.pt_c1_atr,
            vwap_z_threshold=args.vwap_z_threshold,
            post_entry_gates_active=args.post_entry_gates_active,
            speed_gate_threshold_s=args.speed_gate_threshold_s,
            gate_60s_pnl_atr=args.gate_60s_pnl_atr,
            wide_sl_atr=args.wide_sl_atr,
            features_lookup_path=args.features_path if args.features_path else f"studies/regime_classification/results/features_{product.lower()}_1m.parquet"))
    engine.add_strategy(strat)

    print("\nRunning backtest...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time()-t0:.0f}s")

    print("\n--- Signal Gate Diagnostics ---")
    for k, v in strat._diag.items():
        print(f"  {k}: {v}")

    # Dispose the engine first to ensure all engine log directories and handles are closed
    engine.dispose()

    # Now write the parquet file safely
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
        out_path = out_dir / "trades.parquet"
        in_year.to_parquet(out_path, index=False)
        import os
        print(f"DEBUG: out_path absolute: {os.path.abspath(out_path)}")
        print(f"DEBUG: out_path exists immediately: {os.path.exists(out_path)}")
        print(f"\nWrote {len(in_year)} trade records → {out_path}")


if __name__ == "__main__":
    main()
