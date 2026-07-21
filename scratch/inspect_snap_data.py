import pandas as pd
df = pd.read_parquet("studies/1m_regime_collector_v2/results/v2_feature_snapshots_2023.parquet")
print("Total rows:", len(df))
print("Columns:", list(df.columns))
print("Sample row:")
print(df.iloc[0])
