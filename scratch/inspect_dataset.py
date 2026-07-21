import pandas as pd
import numpy as np

df = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
print("Columns:")
print(df.columns.tolist())
print("\nShape:", df.shape)
print("\nSummary of regime_pnl_atr_bar1:")
print(df["regime_pnl_atr_bar1"].describe())
print("\nNull counts:")
print(df.isnull().sum())
