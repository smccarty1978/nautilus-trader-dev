import pandas as pd
df = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
print("Columns in flips_excursion_paths.parquet:")
print(list(df.columns))
print("Sample data:")
print(df.head(2))
