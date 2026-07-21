import pandas as pd
df = pd.read_parquet("scratch/tick_fill_simulation_results.parquet")
print(df[["entry_ts", "direction", "entry_px", "atr", "c1_ideal_px", "c1_nt_px", "c1_tick_px", "c1_tick_reason", "c2_tick_px", "c2_tick_reason"]].head(10).to_string())
print("\nNull counts:")
print(df.isnull().sum())
