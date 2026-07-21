"""Run Keltner Extension Fade backtests sweep for NQ across all years (2020-2026)."""
from __future__ import annotations
import os, sys, time, json
from pathlib import Path
import pandas as pd
from concurrent.futures import ProcessPoolExecutor

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

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
    year: int,
    bars_1s,
    out_dir: Path
):
    out_dir.mkdir(parents=True, exist_ok=True)
    engine_config = BacktestEngineConfig(
        trader_id=f"KF-{variant}-{stop_type}-{year}-{target_offset_atr}".replace(".", "_"),
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
        rth_only=True,          # Strictly RTH-only entries!
        start_date_utc=f"{year}-01-01"
    )
    strat = KeltnerFadeStrategy(cfg)
    engine.add_strategy(strat)
    
    t0 = time.time()
    engine.run()
    elapsed = time.time() - t0
    engine.dispose()
    
    return elapsed, strat._diag

def run_job_worker(job):
    import os, sys, time
    from pathlib import Path
    import pandas as pd
    
    PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
    sys.path.insert(0, str(PROJECT_ROOT))
    os.chdir(PROJECT_ROOT)
    
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from studies.keltner_fade.run_keltner_all_years import run_backtest_cell
    
    cell_name = job["cell_name"]
    year = job["year"]
    job_name = f"{cell_name}_year_{year}"
    print(f"[{job_name}] Starting...", flush=True)
    
    catalog_path = PROJECT_ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start,
        end=load_end
    )
    
    out_dir = PROJECT_ROOT / "studies" / "keltner_fade" / "results_all_years" / job_name
    elapsed, diag = run_backtest_cell(
        variant=job["variant"],
        stop_type=job["stop_type"],
        stop_atr_mult=job["stop_atr_mult"],
        stop_rr_ratio=job["stop_rr_ratio"],
        target_offset_atr=job["target_offset_atr"],
        year=year,
        bars_1s=bars_1s,
        out_dir=out_dir
    )
    
    # Load trade count
    trades_file = out_dir / "trades.parquet"
    trade_count = 0
    net_pnl = 0.0
    
    if trades_file.exists():
        df_trades = pd.read_parquet(trades_file)
        trade_count = len(df_trades)
        if trade_count > 0:
            net_pnl = df_trades["net_pnl"].sum()
            
    print(f"[{job_name}] Finished in {elapsed:.1f}s | Trades: {trade_count} | Net PnL: ${net_pnl:+.2f}", flush=True)
    
    return {
        "cell": cell_name,
        "year": year,
        "trade_count": trade_count,
        "net_pnl": net_pnl,
        "elapsed_s": elapsed,
        "diag": diag
    }

def main():
    # Grid of configurations to sweep across all years:
    # 1. A_rr_0_5_target_0.25 (Variant A, 1:2 RR stop, 0.25 target)
    # 2. A_rr_0_5_target_0.5 (Variant A, 1:2 RR stop, 0.5 target)
    # 3. B_stop_2_5_target_0.25 (Variant B, 2.5 disaster stop, 0.25 target)
    # 4. B_stop_2_5_target_0.5 (Variant B, 2.5 disaster stop, 0.5 target)
    
    grid = [
        # Variant A
        {
            "variant": "A",
            "stop_type": "rr",
            "stop_atr_mult": 0.0,
            "stop_rr_ratio": 0.5,
            "target_offset_atr": 0.25,
            "cell_name": "A_rr_0_5_target_0.25"
        },
        {
            "variant": "A",
            "stop_type": "rr",
            "stop_atr_mult": 0.0,
            "stop_rr_ratio": 0.5,
            "target_offset_atr": 0.5,
            "cell_name": "A_rr_0_5_target_0.5"
        },
        # Variant B
        {
            "variant": "B",
            "stop_type": "band_atr",
            "stop_atr_mult": 2.5,
            "stop_rr_ratio": 0.0,
            "target_offset_atr": 0.25,
            "cell_name": "B_stop_2_5_target_0.25"
        },
        {
            "variant": "B",
            "stop_type": "band_atr",
            "stop_atr_mult": 2.5,
            "stop_rr_ratio": 0.0,
            "target_offset_atr": 0.5,
            "cell_name": "B_stop_2_5_target_0.5"
        }
    ]
    
    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    
    jobs = []
    for cell in grid:
        for year in years:
            job = dict(cell)
            job["year"] = year
            jobs.append(job)
            
    print(f"Total jobs to run in parallel: {len(jobs)}", flush=True)
    t_start = time.time()
    
    # Use max 3 workers to prevent using too much memory
    max_workers = 3
    print(f"Using {max_workers} worker processes...", flush=True)
    
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_job_worker, job) for job in jobs]
        for fut in futures:
            try:
                res = fut.result()
                results.append(res)
            except Exception as e:
                print(f"Error running job worker: {e}", flush=True)
                
    # Compile and merge parquets for each configuration cell
    results_dir = PROJECT_ROOT / "studies" / "keltner_fade" / "results_all_years"
    for cell in grid:
        cell_name = cell["cell_name"]
        print(f"\nMerging trade records for {cell_name}...", flush=True)
        
        all_dfs = []
        for year in years:
            job_name = f"{cell_name}_year_{year}"
            trades_file = results_dir / job_name / "trades.parquet"
            if trades_file.exists():
                df = pd.read_parquet(trades_file)
                if len(df) > 0:
                    all_dfs.append(df)
                    
        cell_merged_dir = results_dir / cell_name
        cell_merged_dir.mkdir(parents=True, exist_ok=True)
        merged_file = cell_merged_dir / "trades.parquet"
        
        if all_dfs:
            df_merged = pd.concat(all_dfs, ignore_index=True)
            # Sort by exit timestamp to maintain chronological order
            df_merged = df_merged.sort_values("exit_ts").reset_index(drop=True)
            df_merged.to_parquet(merged_file, index=False)
            print(f"  Merged {len(df_merged)} trades for {cell_name} into {merged_file}", flush=True)
        else:
            print(f"  No trades found for {cell_name}", flush=True)
            
    # Write metadata summary
    summary_path = results_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nAll backtests complete in {time.time() - t_start:.1f}s. Summary report written to {summary_path}", flush=True)

if __name__ == "__main__":
    main()
