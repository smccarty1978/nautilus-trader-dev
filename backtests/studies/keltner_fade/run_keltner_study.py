"""Run Keltner Extension Fade backtests sweep for NQ in 2025."""
from __future__ import annotations
import os, sys, time, json
from pathlib import Path
import pandas as pd

# Repo root on path
PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from studies.keltner_fade.collect import KeltnerFadeStrategy, KeltnerFadeConfig


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def run_backtest_cell(
    variant: str,
    stop_type: str,
    stop_atr_mult: float,
    stop_rr_ratio: float,
    target_offset_atr: float,
    bars_1s,
    out_dir: Path
):
    out_dir.mkdir(parents=True, exist_ok=True)
    engine_config = BacktestEngineConfig(
        trader_id=f"KF-{variant}-{stop_type}-{stop_atr_mult}-{stop_rr_ratio}-{target_offset_atr}".replace(".", "_"),
        logging=LoggingConfig(
            log_level="WARNING",
            log_directory=str(out_dir / "logs")
        ),
    )
    engine = BacktestEngine(config=engine_config)
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True
    )
    engine.add_instrument(create_nq())
    engine.add_data(bars_1s)

    cfg = KeltnerFadeConfig(
        instrument_id="NQ.XCME",
        bar_type_30s="NQ.XCME-30-SECOND-LAST-EXTERNAL",
        bar_type_3m="NQ.XCME-3-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        variant=variant,
        stop_type=stop_type,
        stop_atr_mult=stop_atr_mult,
        stop_rr_ratio=stop_rr_ratio,
        target_offset_atr=target_offset_atr,
        v_b_filter1_threshold=0.5,
        v_b_filter2_n=6,
        v_b_filter2_x_atr=0.25,
        disaster_stop_atr_mult=2.5,
        output_dir=str(out_dir),
        position_size=1,
        rth_only=False,  # Run all hours / regimes
    )
    strat = KeltnerFadeStrategy(cfg)
    engine.add_strategy(strat)
    
    t0 = time.time()
    engine.run()
    elapsed = time.time() - t0
    engine.dispose()
    
    return elapsed, strat._diag


def run_cell_worker(cell):
    import os, sys, time, json
    from pathlib import Path
    import pandas as pd
    
    PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
    sys.path.insert(0, str(PROJECT_ROOT))
    os.chdir(PROJECT_ROOT)
    
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from studies.keltner_fade.run_keltner_study import run_backtest_cell
    
    cell_name = cell["name"]
    print(f"[{cell_name}] Started...", flush=True)
    
    catalog_path = PROJECT_ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    load_start = pd.Timestamp("2025-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")
    
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start,
        end=load_end
    )
    
    out_dir = PROJECT_ROOT / "studies" / "keltner_fade" / "results" / cell_name
    elapsed, diag = run_backtest_cell(
        variant=cell["variant"],
        stop_type=cell["stop_type"],
        stop_atr_mult=cell["stop_atr_mult"],
        stop_rr_ratio=cell["stop_rr_ratio"],
        target_offset_atr=cell["target_offset_atr"],
        bars_1s=bars_1s,
        out_dir=out_dir
    )
    
    # Load trade counts
    trades_file = out_dir / "trades.parquet"
    trade_count = 0
    net_pnl = 0.0
    win_rate = 0.0
    
    if trades_file.exists():
        df_trades = pd.read_parquet(trades_file)
        trade_count = len(df_trades)
        if trade_count > 0:
            net_pnl = df_trades["net_pnl"].sum()
            win_rate = (df_trades["net_pnl"] > 0).mean() * 100
            
    print(f"[{cell_name}] Finished in {elapsed:.1f}s | Trades: {trade_count} | Net PnL: ${net_pnl:+.2f} | Win Rate: {win_rate:.1f}%", flush=True)
    
    stop_val = cell["stop_rr_ratio"] if cell["stop_type"] == "rr" else cell["stop_atr_mult"]
    
    return {
        "cell": cell_name,
        "variant": cell["variant"],
        "stop": stop_val,
        "stop_type": cell["stop_type"],
        "stop_atr_mult": cell["stop_atr_mult"],
        "stop_rr_ratio": cell["stop_rr_ratio"],
        "target": cell["target_offset_atr"],
        "trade_count": trade_count,
        "net_pnl": net_pnl,
        "win_rate": win_rate,
        "elapsed_s": elapsed,
        "diag": diag
    }


def main():
    # Grid of configurations to sweep
    # Variant A (control): 3 RR ratios (0.3333, 0.5, 0.6667) x 2 target offsets (0.25, 0.5) = 6 cells
    # Variant B (regime flip): 2 target offsets (0.25, 0.5) (uses disaster stop 2.5) = 2 cells
    # Total cells = 8
    
    grid = []
    # Variant A cells
    for ratio in [0.3333, 0.5, 0.6667]:
        for target in [0.25, 0.5]:
            ratio_name = str(round(ratio, 2)).replace(".", "_")
            grid.append({
                "variant": "A",
                "stop_type": "rr",
                "stop_atr_mult": 0.0,
                "stop_rr_ratio": ratio,
                "target_offset_atr": target,
                "name": f"A_rr_{ratio_name}_target_{target}"
            })
            
    # Variant B cells
    for target in [0.25, 0.5]:
        grid.append({
            "variant": "B",
            "stop_type": "band_atr",
            "stop_atr_mult": 2.5,  # Placed in the stop_atr_mult slot as it is the disaster backstop
            "stop_rr_ratio": 0.0,
            "target_offset_atr": target,
            "name": f"B_stop_2_5_target_{target}"
        })
        
    print(f"Total cells to run in parallel: {len(grid)}", flush=True)

    # Run in parallel using ProcessPoolExecutor
    from concurrent.futures import ProcessPoolExecutor
    
    results_summary = []
    t_start = time.time()
    
    # Use max 4 workers to avoid using too much memory
    max_workers = min(4, len(grid))
    print(f"Using {max_workers} worker processes...", flush=True)
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_cell_worker, cell) for cell in grid]
        for fut in futures:
            try:
                res = fut.result()
                results_summary.append(res)
            except Exception as e:
                print(f"Error running worker: {e}", flush=True)
                
    # Sort results by cell name
    results_summary = sorted(results_summary, key=lambda x: x["cell"])
    
    # Write summary configuration report
    summary_path = PROJECT_ROOT / "studies" / "keltner_fade" / "results" / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(results_summary, f, indent=2)
        
    print(f"\nAll backtests complete in {time.time() - t_start:.1f}s. Summary report written to {summary_path}", flush=True)


if __name__ == "__main__":
    main()
