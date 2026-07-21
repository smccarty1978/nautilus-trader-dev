import pandas as pd
df = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
print("kmeans_4_state value counts:")
print(df["kmeans_4_state"].value_counts(dropna=False))
print("\nIs there any other filter?")
print("resolved:", df["resolved"].value_counts(dropna=False))
print("bar1_confirm:", df["bar1_confirm"].value_counts(dropna=False))
