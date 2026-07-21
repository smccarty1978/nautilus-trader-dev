import pandas as pd
df = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
print("Columns:")
print(df.columns.tolist())
print("\nShape:", df.shape)
print("\nYear value counts:")
print(df["year"].value_counts().sort_index())
print("\nRTH only?")
if "is_rth" in df.columns:
    print(df["is_rth"].value_counts())
elif "hour" in df.columns:
    print(df["hour"].value_counts().sort_index())
