import pandas as pd
import glob
import os

path = "backtests/compression_vwap_launchpad/results/live_2020/trades.parquet"
if os.path.exists(path):
    df = pd.read_parquet(path)
    print("Columns in trades.parquet:")
    print(df.columns.tolist())
    print("\nFirst 5 trades:")
    print(df.head())
    print("\nExit reason value counts:")
    print(df["exit_reason"].value_counts())
else:
    print(f"File {path} does not exist")
