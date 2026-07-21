import pandas as pd
df = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
print(df.columns.tolist())
print(f"Total rows: {len(df)}")
