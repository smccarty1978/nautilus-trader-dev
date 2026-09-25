import pandas as pd
from pathlib import Path

PARTITION_PATHS = {
    "2023": {
        "candidates": r"C:\Users\Scott McCarty\Projects\Nautilus-Trader-V2-nq_p90_reversal_entry_quality\studies\nq_p90_reversal_entry_quality\_work\controller\partitions\train\2023\candidates.parquet",
        "observations": r"C:\Users\Scott McCarty\Projects\Nautilus-Trader-V2-nq_p90_reversal_entry_quality\studies\nq_p90_reversal_entry_quality\_work\controller\partitions\train\2023\observations.parquet",
    },
    "2024": {
        "candidates": r"C:\Users\Scott McCarty\Projects\Nautilus-Trader-V2-nq_p90_reversal_entry_quality\studies\nq_p90_reversal_entry_quality\_work\controller\partitions\train\2024\candidates.parquet",
        "observations": r"C:\Users\Scott McCarty\Projects\Nautilus-Trader-V2-nq_p90_reversal_entry_quality\studies\nq_p90_reversal_entry_quality\_work\controller\partitions\train\2024\observations.parquet",
    },
    "2025_Q1": {
        "candidates": r"C:\Users\Scott McCarty\Projects\Nautilus-Trader-V2-nq_p90_reversal_entry_quality\studies\nq_p90_reversal_entry_quality\_work\controller\partitions\oos\2025\candidates.parquet",
        "observations": r"C:\Users\Scott McCarty\Projects\Nautilus-Trader-V2-nq_p90_reversal_entry_quality\studies\nq_p90_reversal_entry_quality\_work\controller\partitions\oos\2025\observations.parquet",
    },
}

for yr, paths in PARTITION_PATHS.items():
    df_c = pd.read_parquet(paths["candidates"])
    df_o = pd.read_parquet(paths["observations"])
    print(f"=== {yr} ===")
    print(f"candidates shape: {df_c.shape}, unique regimes: {df_c['regime_start_ns'].nunique()}")
    print(f"observations shape: {df_o.shape}, unique regimes: {df_o['regime_start_ns'].nunique()}")
    print("candidates cols:", list(df_c.columns)[:15])
    print("observations cols:", list(df_o.columns)[:15])
    # Check first regime
    r0 = df_c.iloc[0]
    r0_ns = r0["regime_start_ns"]
    obs_r0 = df_o[df_o["regime_start_ns"] == r0_ns]
    cand_r0 = df_c[df_c["regime_start_ns"] == r0_ns]
    print(f"Sample regime {r0_ns}: cand rows = {len(cand_r0)}, obs rows = {len(obs_r0)}")
    print(f"  Cand ts range: {cand_r0['observation_ts'].min()} to {cand_r0['observation_ts'].max()}")
    print(f"  Obs ts range: {obs_r0['observation_ts'].min()} to {obs_r0['observation_ts'].max()}")
