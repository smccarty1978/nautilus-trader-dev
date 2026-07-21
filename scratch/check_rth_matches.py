import pandas as pd

df_bt = pd.read_parquet("backtests/baseline_flip_parity/results/nq_live_2025/trades.parquet")
df_ds = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
df_ds = df_ds[df_ds["year"] == 2025]

df_bt["minute_ts"] = (df_bt["entry_ts"] // 60_000_000_000) * 60_000_000_000
df_ds["minute_ts"] = (df_ds["entry_ts_bar1"] // 60_000_000_000) * 60_000_000_000

# Let's add RTH flag to backtest trades
# RTH in NQ is 09:30 to 16:00 Chicago time (which is 14:30 to 21:00 UTC, or 15:30 to 22:00 UTC depending on DST).
# Let's look at is_rth column in dataset to see what it uses.
# In the dataset, is_rth is a column. Let's merge bt and ds on minute_ts to see if we can get is_rth,
# or we can check the time of day in UTC.
df_bt["dt_utc"] = pd.to_datetime(df_bt["minute_ts"], unit="ns", utc=True)
df_bt["hour"] = df_bt["dt_utc"].dt.hour
df_bt["minute"] = df_bt["dt_utc"].dt.minute
df_bt["time_str"] = df_bt["dt_utc"].dt.time

# Let's see how many backtest trades are in RTH (14:30 to 21:00 UTC) vs ETH
# Note: we can check is_rth definition.
# In NQ, Chicago time is UTC-6 (or UTC-5 in DST).
# Let's see: we can look at the dataset's is_rth for matched trades.
matched_ds = df_ds[df_ds["minute_ts"].isin(df_bt["minute_ts"])]
print("Matched dataset trades RTH distribution:")
print(matched_ds["is_rth"].value_counts())

unmatched_ds = df_ds[~df_ds["minute_ts"].isin(df_bt["minute_ts"])]
print("\nUnmatched dataset trades RTH distribution:")
print(unmatched_ds["is_rth"].value_counts())

# For backtest trades:
# Let's match backtest trades to the dataset and see if they are in RTH or not.
# Since we don't have is_rth directly in df_bt, let's look at the time of day for unmatched BT trades.
df_bt["is_matched"] = df_bt["minute_ts"].isin(df_ds["minute_ts"])
print("\nBacktest trades matched vs unmatched:")
print(df_bt["is_matched"].value_counts())

print("\nUnmatched backtest trades hour of day (UTC) distribution:")
print(df_bt[~df_bt["is_matched"]]["hour"].value_counts().sort_index())
