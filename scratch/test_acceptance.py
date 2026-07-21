import os, sys, time, random
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from scratch.run_null_benchmark import compute_indicators, run_exit_engine_on_entries, run_flavor_b_simulation

y = 2026
catalog_path = "data/catalog/NQ_v0_2020_2026"
catalog = ParquetDataCatalog(catalog_path)

print(f"Loading Year {y}...")
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

print(f"Target K: {target_K}")
print(f"Target D: {target_D}")

# Run 50 trials of Flavor B
accepted = 0
rejections = 0
t0 = time.time()

for trial in range(50):
    rng = random.Random(42 + trial)
    fb_trades = run_flavor_b_simulation(
        p_target, cand_durs, ts, close_arr, atr_arr, high_arr, rng, y
    )
    K_rand = len(fb_trades)
    D_rand = sum([t["duration"] for t in fb_trades])
    
    if target_K > 0 and abs(K_rand - target_K) / target_K <= 0.02 and abs(D_rand - target_D) / target_D <= 0.02:
        accepted += 1
    else:
        rejections += 1

t1 = time.time()
print(f"Accepted: {accepted}/50")
print(f"Rejections: {rejections}/50")
print(f"Acceptance Rate: {accepted/50 * 100:.2f}%")
print(f"Time taken for 50 simulations: {t1-t0:.2f}s")
print(f"Average time per simulation (including rejected runs): {(t1-t0)/50:.4f}s")
