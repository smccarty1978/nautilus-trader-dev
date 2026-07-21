import pandas as pd
import numpy as np

df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
match = df_ex[np.abs(df_ex["entry_ts"] - 1769783460000000000) < 60_000_000_000]
print(match.to_string())
