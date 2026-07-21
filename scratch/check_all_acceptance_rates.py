import os, sys, random
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from scratch.run_null_benchmark import compute_indicators, run_exit_engine_on_entries

YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
catalog_path = "data/catalog/NQ_v0_2020_2026"
catalog = ParquetDataCatalog(catalog_path)

for y in YEARS:
    load_start = pd.Timestamp(f"{y}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end   = pd.Timestamp(f"{y}-12-31 23:59:59", tz="UTC")
    bars = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end
    )
    ts, open_arr, high_arr, low_arr, close_arr, sma13, atr_arr, regime_arr = compute_indicators(bars)

    p = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{y}_stall_sma13_s3_g0_long/trades.parquet"
    df_cand = pd.read_parquet(p)
    cand_entries = df_cand["entry_ts"].to_numpy().astype(np.int64)
    cand_entry_idx = np.searchsorted(ts, cand_entries, side="left")

    cand_sim_trades = run_exit_engine_on_entries(
        cand_entry_idx, ts, open_arr, high_arr, low_arr, close_arr, sma13, atr_arr, regime_arr
    )

    cand_durs = [t["duration"] for t in cand_sim_trades]
    target_K = len(cand_sim_trades)
    target_D = sum(cand_durs)

    n_bars = len(ts)
    n_flat_bars = n_bars - target_D
    p_target = target_K / n_flat_bars

    # Run 100 fast pass simulations to get acceptance rate
    accepted = 0
    for trial in range(100):
        rng = random.Random(42 + trial)
        j = 150
        K_rand = 0
        D_rand = 0
        target_start_ns = int(pd.Timestamp(f"{y}-01-01", tz="UTC").value)
        
        while j < n_bars:
            if ts[j] < target_start_ns:
                j += 1
                continue
                
            if rng.random() < p_target:
                dur = rng.choice(cand_durs)
                idx_exit = min(n_bars - 1, j + dur)
                K_rand += 1
                D_rand += idx_exit - j
                j = idx_exit + 1
            else:
                j += 1
                
        if target_K > 0 and abs(K_rand - target_K) / target_K <= 0.02 and abs(D_rand - target_D) / target_D <= 0.02:
            accepted += 1
            
    print(f"Year {y}: Target K = {target_K}, Target D = {target_D}, Acceptance Rate = {accepted:.2f}%")
