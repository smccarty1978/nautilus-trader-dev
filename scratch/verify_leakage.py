import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
df_trades = pd.read_parquet("scratch/predict_bar1_excursions.parquet")
print("Total trades in predict_bar1_excursions:", len(df_trades))

# Check some sample columns and values
print(df_trades[["entry_ts", "entry_ts_bar1", "entry_px_bar1", "exit_ts", "year"]].head())

# Let's inspect the merged conditioning dataset
cond_path = "scratch/bar1_conditioning_dataset.parquet"
if os.path.exists(cond_path):
    df_cond = pd.read_parquet(cond_path)
    print("\nTotal trades in conditioning dataset:", len(df_cond))
    print("Columns in conditioning dataset:", list(df_cond.columns[:15]))
    
    # Check alignment for a few rows
    sample = df_cond.sample(5, random_state=42)
    for idx, row in sample.iterrows():
        print(f"\nTrade Year: {row['year']} | Direction: {row['signal_direction']}")
        print(f"entry_ts:      {pd.to_datetime(row['entry_ts'], unit='ns', utc=True)}")
        print(f"entry_ts_bar1: {pd.to_datetime(row['entry_ts_bar1'], unit='ns', utc=True)}")
        print(f"exit_ts:       {pd.to_datetime(row['exit_ts'], unit='ns', utc=True)}")
        print(f"entry_px_bar1: {row['entry_px_bar1']}")
        print(f"dist_ema3:     {row['dist_ema3']}")
        print(f"dist_ema3_atr: {row['dist_ema3_atr']}")
        print(f"regime_pnl_pts_bar1: {row['regime_pnl_pts_bar1']}")
else:
    print("bar1_conditioning_dataset.parquet does not exist.")
