import pandas as pd
df = pd.read_parquet("studies/1m_regime_collector_v2/results/v2_feature_snapshots_2023.parquet")
print("Unique checkpoint_s values:", df["checkpoint_s"].value_counts())
print("\nUnique event_id count:", df["event_id"].nunique())
print("Rows per event_id statistics:")
print(df.groupby("event_id").size().describe())
