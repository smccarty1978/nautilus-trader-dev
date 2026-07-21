import pandas as pd

df_bt = pd.read_parquet("backtests/baseline_flip_parity/results/nq_live_2025/trades.parquet")
df_ds = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
df_ds = df_ds[df_ds["year"] == 2025]

# Convert timestamps to minute-level (rounded down to the minute)
# entry_ts in backtest is expected_bar1_close (which is 23:37:01 or similar, so divide by 60s)
df_bt["minute_ts"] = (df_bt["entry_ts"] // 60_000_000_000) * 60_000_000_000
df_ds["minute_ts"] = (df_ds["entry_ts_bar1"] // 60_000_000_000) * 60_000_000_000

bt_mins = set(df_bt["minute_ts"].astype("int64"))
ds_mins = set(df_ds["minute_ts"].astype("int64"))

matched = bt_mins.intersection(ds_mins)
print(f"Matched minutes: {len(matched)}")
print(f"Backtest minutes not in dataset: {len(bt_mins - ds_mins)}")
print(f"Dataset minutes not in backtest: {len(ds_mins - bt_mins)}")

unmatched_bt = df_bt[df_bt["minute_ts"].isin(bt_mins - ds_mins)].head(15)
print("\nUnmatched backtest minutes (in BT but not in DS):")
for idx, row in unmatched_bt.iterrows():
    print(f"TS: {pd.to_datetime(row['minute_ts'], unit='ns', utc=True)} | Dir: {row['signal_direction']}")

unmatched_ds = df_ds[df_ds["minute_ts"].isin(ds_mins - bt_mins)].head(15)
print("\nUnmatched dataset minutes (in DS but not in BT):")
for idx, row in unmatched_ds.iterrows():
    print(f"TS: {pd.to_datetime(row['minute_ts'], unit='ns', utc=True)} | Dir: {row['signal_direction']}")
