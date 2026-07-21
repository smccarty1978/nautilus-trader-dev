import pandas as pd
import numpy as np

# Load study parquet
parquet_path = "studies/v_a_excursion_regime/results_v0/compression_vwap_study.parquet"
df = pd.read_parquet(parquet_path)

print(f"Dataset shape: {df.shape}")
print(f"Columns: {list(df.columns)}")

# Let's inspect unique values for tot_slow_bkt
print("\ntot_slow_bkt value counts:")
print(df["tot_slow_bkt"].value_counts())

# Filter to low excursion (low tot_slow_bkt) and near-away VWAP cell (z_dir > 0 and |z| < 1.0)
print("\nFilters:")
# Low excursion
is_low_excursion = df["tot_slow_bkt"] == "low"
# VWAP cell is 'near-away'
is_near_away = df["cell"] == "near-away"
# RTH only (we need to see if RTH is coded or filter by time)
# Let's see what time columns are available. We have signal_time. Let's see if we have RTH column.
print("\nFirst 5 rows:")
print(df.head())

print("\nValue counts for cell:")
print(df["cell"].value_counts())

print("\nValue counts for year:")
print(df["year"].value_counts())

# Let's count low-excursion flips in near-away cell per year
low_near_away = df[is_low_excursion & is_near_away]
print("\nLow excursion near-away flips per year:")
print(low_near_away["year"].value_counts().sort_index())

# Win rates for Entry A (flip-bar entry) on low excursion near-away
print("\nEntry A win rates by year on low excursion near-away:")
for y in sorted(df["year"].unique()):
    y_df = low_near_away[low_near_away["year"] == y]
    if len(y_df) > 0:
        resolved = y_df[y_df["hit"] != -1]
        win_rate = (resolved["hit"] == 1).mean()
        print(f"  {y}: count={len(y_df)}, resolved={len(resolved)}, win_rate={win_rate:.1%}")
    else:
        print(f"  {y}: count=0")
