import pandas as pd
import os

df_ex = pd.read_parquet("scratch/predict_bar1_excursions.parquet")
print("Total bar1 trades:", len(df_ex))

# Ensure entry_ts_bar1 is defined correctly
df_ex["entry_ts_bar1"] = df_ex["entry_ts"] + 60 * 1_000_000_000

match_count = 0
for y in sorted(df_ex["year"].unique()):
    df_y = df_ex[df_ex["year"] == y]
    p = f"studies/1m_regime_collector_v2/results/v2_feature_snapshots_{y}.parquet"
    if os.path.exists(p):
        df_snap = pd.read_parquet(p, columns=["signal_time", "signal_direction", "event_id"])
        # Cast to int64 for clean matching
        df_snap["signal_time"] = df_snap["signal_time"].astype("int64")
        # De-duplicate snapshots on signal_time and direction to prevent row inflation
        df_snap = df_snap.drop_duplicates(subset=["signal_time", "signal_direction"])
        
        merged = df_y.merge(
            df_snap,
            left_on=["entry_ts_bar1", "signal_direction"],
            right_on=["signal_time", "signal_direction"],
            how="inner"
        )
        match_count += len(merged)
        print(f"  {y}: trades={len(df_y)}, matches={len(merged)}")
    else:
        print(f"  {y}: snapshot file not found")

print("Total matched:", match_count)
