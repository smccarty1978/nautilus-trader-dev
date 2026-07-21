import pandas as pd
import numpy as np

df = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
print(f"Total rows: {len(df)}")
print(df[["hold_min_flip", "regime_pnl_atr_flip", "mfe_5m", "mae_5m"]].describe())

# Check how many are NaN or null
print("\nNull counts:")
print(df[["hold_min_flip", "regime_pnl_atr_flip", "mfe_5m", "mae_5m"]].isnull().sum())

# Let's look at hold_min_flip histogram / quantiles
print("\nQuantiles of hold_min_flip:")
print(df["hold_min_flip"].quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]))
