import pandas as pd
df = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
print("bar1_confirm value counts:")
print(df["bar1_confirm"].value_counts())
print("\nresolved value counts:")
print(df["resolved"].value_counts())
