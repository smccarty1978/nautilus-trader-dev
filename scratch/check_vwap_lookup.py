import pandas as pd
import numpy as np

# Load features
feat_df = pd.read_parquet("studies/regime_classification/results/features_nq_1m.parquet")
print("Index name:", feat_df.index.name)
print("Index dtype:", feat_df.index.dtype)

# Convert to int64
feat_ts = feat_df.index.values.astype("int64")
print("First few timestamps in nanoseconds:")
for i in range(5):
    print(f"  {feat_df.index[i]} -> {feat_ts[i]}")

# Sample test: a 1s timestamp in 2023
sample_ts = pd.Timestamp("2023-01-03 09:30:15", tz="UTC").value
t_closed_open = (sample_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
print(f"\nSample 1s ts: {sample_ts} (2023-01-03 09:30:15 UTC)")
print(f"t_closed_open calculated: {t_closed_open} ({pd.Timestamp(t_closed_open, tz='UTC')})")

# Check if t_closed_open is in the index keys
found = t_closed_open in feat_ts
print(f"Is t_closed_open in feat_ts? {found}")

# Find closest match if not found
if not found:
    diffs = np.abs(feat_ts - t_closed_open)
    min_idx = np.argmin(diffs)
    print(f"Closest match in index: {feat_ts[min_idx]} ({pd.Timestamp(feat_ts[min_idx], tz='UTC')}) with diff of {diffs[min_idx]} ns")
