import pandas as pd
import numpy as np

# Load 1s bars for 2025
# Let's see: we can load from data/raw/NQ_v0_1s_2025.parquet or catalog
bars_1s = pd.read_parquet("data/raw/NQ_v0_1s_2025.parquet")
if bars_1s.index.tz is None:
    bars_1s.index = bars_1s.index.tz_localize("UTC")

# Let's inspect the minute around 2025-01-02 00:01:00 and 00:02:00
t_start = pd.Timestamp("2025-01-02 00:00:00", tz="UTC")
t_end = pd.Timestamp("2025-01-02 00:04:00", tz="UTC")
sub = bars_1s.loc[t_start:t_end]

print("1s bars:")
print(sub)

# Let's resample to 1m
df_1m = pd.DataFrame()
df_1m["open"] = sub["open"].resample("1Min").first()
df_1m["high"] = sub["high"].resample("1Min").max()
df_1m["low"] = sub["low"].resample("1Min").min()
df_1m["close"] = sub["close"].resample("1Min").last()
print("\nResampled 1m bars:")
print(df_1m)
