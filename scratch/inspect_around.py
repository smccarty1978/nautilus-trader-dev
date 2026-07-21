import pandas as pd

# Load study parquet
study_path = "studies/v_a_excursion_regime/results_v0/compression_vwap_study.parquet"
df_study = pd.read_parquet(study_path)
df_study_2024 = df_study[df_study["year"] == 2024].copy()

t_target = 1715619120000000000
around = df_study_2024[(df_study_2024["signal_time"] >= t_target - 600 * 1e9) & (df_study_2024["signal_time"] <= t_target + 600 * 1e9)]
print("Study flips around target:")
print(around[["signal_time", "signal_direction", "atr_at_signal", "tot_slow", "cell"]])
