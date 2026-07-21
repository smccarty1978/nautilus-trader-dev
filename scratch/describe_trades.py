import pandas as pd
from pathlib import Path

df = pd.read_parquet("studies/keltner_fade/results/A_stop_0.5_target_0.25/trades.parquet")
print(f"Total trades loaded: {len(df):,}")
print("Columns:", df.columns.tolist())
print(df.describe())
print("\nExit reason value counts:")
print(df["exit_reason"].value_counts())
print("\nFirst 10 trades:")
print(df[["entry_ts", "exit_ts", "direction", "fill_price", "exit_price", "net_pnl", "exit_reason", "hold_s"]].head(10))
