import pandas as pd
df = pd.read_parquet("studies/v_a_excursion_regime/results_v0/nt_regime_exit_nq.parquet")
print("Columns in nt_regime_exit_nq.parquet:")
print(list(df.columns))
print(df.head(2))
