import pandas as pd
df = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
print("Total rows in merged dataset:", len(df))
if "checkpoint_s" in df.columns:
    print("\ncheckpoint_s value counts:")
    print(df["checkpoint_s"].value_counts(dropna=False))
else:
    print("\ncheckpoint_s is not in columns.")
    
# Let's see some columns of df
print("\nSome columns in df:")
print(list(df.columns[:30]))
