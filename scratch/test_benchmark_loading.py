import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from scratch.run_null_benchmark import compute_indicators, run_exit_engine_on_entries, calculate_trades_summary

YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
catalog_path = "data/catalog/NQ_v0_2020_2026"
catalog = ParquetDataCatalog(catalog_path)

print("Starting loading test...")
for y in YEARS:
    t0 = time.time()
    print(f"\nYear {y}: loading 1m bars from catalog...")
    load_start = pd.Timestamp(f"{y}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end   = pd.Timestamp(f"{y}-12-31 23:59:59", tz="UTC")
    bars = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end
    )
    print(f"  Loaded {len(bars):,} bars. Computing indicators...")
    ts, open_arr, high_arr, low_arr, close_arr, sma13, atr_arr, regime_arr = compute_indicators(bars)
    print(f"  Done in {time.time()-t0:.1f}s")
    
    # Load candidate
    p = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{y}_stall_sma13_s3_g0_long/trades.parquet"
    if not p.exists():
        print(f"  Candidate parquet not found at {p}")
        continue
    df_cand = pd.read_parquet(p)
    print(f"  Candidate has {len(df_cand):,} trades from NT parquet")
    
    cand_entries = df_cand["entry_ts"].to_numpy().astype(np.int64)
    cand_entry_idx = np.searchsorted(ts, cand_entries, side="left")
    
    cand_sim_trades = run_exit_engine_on_entries(
        cand_entry_idx, ts, open_arr, high_arr, low_arr, close_arr, sma13, atr_arr, regime_arr
    )
    print(f"  Simulated candidate trades: {len(cand_sim_trades):,}")
    if len(cand_sim_trades) > 0:
        cand_stats = calculate_trades_summary(cand_sim_trades)
        print(f"  Simulated candidate Mean ATR: {cand_stats['mean_atr']:.4f}, Net PF: {cand_stats['net_pf']:.2f}")
