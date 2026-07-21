import pandas as pd
df = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
df = df[df["year"] == 2025]
print("Dataset dates:")
print("Min:", pd.to_datetime(df["entry_ts_bar1"].min(), unit="ns", utc=True))
print("Max:", pd.to_datetime(df["entry_ts_bar1"].max(), unit="ns", utc=True))
print("\nMonth distribution:")
print(pd.to_datetime(df["entry_ts_bar1"], unit="ns", utc=True).dt.month.value_counts().sort_index())
