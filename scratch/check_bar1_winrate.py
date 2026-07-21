import pandas as pd

df = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")

# Filter for Bar-1 confirmed trades
df_bar1 = df[df["bar1_confirm"] == 1]

print(f"Total Bar-1 confirmed trades in dataset: {len(df_bar1)}")

# Since each trade-event can be duplicated in flips_excursion_paths.parquet (let's check if flips has duplicates)
# Let's check unique entry_ts counts
unique_ts_count = df_bar1["entry_ts"].nunique()
print(f"Unique trade events (deduplicated by entry_ts): {unique_ts_count}")

# Win rate on raw flips (not deduplicated)
raw_win_rate = df_bar1["regime_win_bar1"].mean()
print(f"Raw win% (all rows): {raw_win_rate:.2%}")

# Deduplicated win rate
df_dedup = df_bar1.groupby("entry_ts").first()
dedup_win_rate = df_dedup["regime_win_bar1"].mean()
print(f"Deduplicated win% (by entry_ts): {dedup_win_rate:.2%}")

# Year-by-year win rate (deduplicated)
print("\nYear-by-year Win% (deduplicated):")
print(f"{'Year':<5} | {'Trades':<6} | {'Win%':<7}")
print("-" * 25)
for y in sorted(df_dedup["year"].unique()):
    df_y = df_dedup[df_dedup["year"] == y]
    win_pct = df_y["regime_win_bar1"].mean()
    print(f"{y:<5} | {len(df_y):<6} | {win_pct:.2%}")
