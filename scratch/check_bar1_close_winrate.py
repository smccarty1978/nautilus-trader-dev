import pandas as pd
import numpy as np

df = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")

# Filter for Bar-1 confirmed trades
df_bar1 = df[df["bar1_confirm"] == 1].copy()

print(f"Total Bar-1 confirmed trades in dataset: {len(df_bar1)}")

# Calculate close confirmation directly:
# Long: entry_px_bar1 > entry_px_flip
# Short: entry_px_bar1 < entry_px_flip
# In general: (entry_px_bar1 - entry_px_flip) * signal_direction > 0
df_bar1["bar1_close_confirmed"] = ((df_bar1["entry_px_bar1"] - df_bar1["entry_px_flip"]) * df_bar1["signal_direction"] > 0).astype(int)

# Group by entry_ts to collapse duplicates if any
df_dedup = df_bar1.groupby("entry_ts").first().reset_index()
print(f"Deduplicated trades: {len(df_dedup)}")

# Print overall split
print("\n" + "="*50)
print("  OVERALL RESULTS FOR CLOSE CONFIRMATION FILTER (45k trades)")
print("="*50)

# Filter 1: bar1_close_confirmed == 1 (Close Confirmed)
df_var1 = df_dedup[df_dedup["bar1_close_confirmed"] == 1]
win_var1 = df_var1["regime_win_bar1"].mean()
print(f"Variation 1: Close Confirmed (bar1 close > flip close for longs / < flip close for shorts)")
print(f"  Count: {len(df_var1)} trades ({len(df_var1)/len(df_dedup):.1%})")
print(f"  Win%:  {win_var1:.2%}")

# Filter 2: bar1_close_confirmed == 0 (Only HH/LL Confirmed, close did not exceed flip close)
df_var0 = df_dedup[df_dedup["bar1_close_confirmed"] == 0]
win_var0 = df_var0["regime_win_bar1"].mean()
print(f"\nVariation 0: Only HH/LL Confirmed (close did not exceed flip close)")
print(f"  Count: {len(df_var0)} trades ({len(df_var0)/len(df_dedup):.1%})")
print(f"  Win%:  {win_var0:.2%}")

# Year-by-year split for Close Confirmed (Variation 1)
print("\n" + "="*50)
print("  YEAR-BY-YEAR WIN% FOR CLOSE CONFIRMED (Variation 1)")
print("="*50)
print(f"{'Year':<5} | {'Trades':<6} | {'Win%':<7}")
print("-" * 25)
for y in sorted(df_dedup["year"].unique()):
    df_y = df_var1[df_var1["year"] == y]
    win_pct = df_y["regime_win_bar1"].mean() if len(df_y) > 0 else 0.0
    print(f"{y:<5} | {len(df_y):<6} | {win_pct:.2%}")
