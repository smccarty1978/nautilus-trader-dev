import pandas as pd
import numpy as np

# Load study parquet
parquet_path = "studies/v_a_excursion_regime/results_v0/compression_vwap_study.parquet"
df = pd.read_parquet(parquet_path)

# Convert signal_time to ET
df["datetime_et"] = pd.to_datetime(df["signal_time"], utc=True).dt.tz_convert("America/New_York")
df["time_et"] = df["datetime_et"].dt.time

# RTH check: 09:30 to 16:00 ET
is_rth = (df["time_et"] >= pd.to_datetime("09:30:00").time()) & (df["time_et"] < pd.to_datetime("16:00:00").time())

# Long only
is_long = df["signal_direction"] == 1

# Excursion < 22
is_compressed = df["tot_slow"] < 22.0

# VWAP Cell is near-away
is_near_away = df["cell"] == "near-away"

# Let's see the tot_slow range for tot_slow_bkt == "low"
print("tot_slow statistics for tot_slow_bkt == 'low':")
print(df[df["tot_slow_bkt"] == "low"]["tot_slow"].describe())

# Apply all filters
filtered_df = df[is_rth & is_long & is_compressed & is_near_away]

print(f"\nFiltered flips shape: {filtered_df.shape}")
print("\nCounts per year of the filtered long-only RTH compressed flips:")
print(filtered_df["year"].value_counts().sort_index())

print("\nWin rate for Entry A on these filtered flips per year:")
for y in sorted(filtered_df["year"].unique()):
    y_df = filtered_df[filtered_df["year"] == y]
    resolved = y_df[y_df["hit"] != -1]
    win_rate = (resolved["hit"] == 1).mean()
    print(f"  {y}: flips={len(y_df)}, resolved={len(resolved)}, win_rate={win_rate:.1%}")
