import pandas as pd
import numpy as np

# Load NQ 1s bars for 2025 and 2024
bars_2025 = pd.read_parquet("data/raw/NQ_v0_1s_2025.parquet")
bars_2024 = pd.read_parquet("data/raw/NQ_v0_1s_2024.parquet")
bars_1s = pd.concat([bars_2024, bars_2025]).sort_index()
bars_1s = bars_1s[~bars_1s.index.duplicated(keep="first")]

if bars_1s.index.tz is None:
    bars_1s.index = bars_1s.index.tz_localize("UTC")

# We start from 2024-12-27 to match backtest warmup
t_start = pd.Timestamp("2024-12-27 00:00:00", tz="UTC")
t_end = pd.Timestamp("2025-01-02 02:00:00", tz="UTC")
sub = bars_1s.loc[t_start:t_end]

df_1m = pd.DataFrame()
df_1m["open"] = sub["open"].resample("1Min").first()
df_1m["high"] = sub["high"].resample("1Min").max()
df_1m["low"] = sub["low"].resample("1Min").min()
df_1m["close"] = sub["close"].resample("1Min").last()
df_1m = df_1m.dropna()

# Let's compute EMAs exactly as in strategy
def _ema(prev, x, alpha):
    return x if prev is None else alpha * x + (1.0 - alpha) * prev

ema3_h = ema9_h = ema3_l = ema9_l = None
ema3_h_list = []
ema9_h_list = []
ema3_l_list = []
ema9_l_list = []
regime_list = []
flip_list = []

regime = 0
for idx, row in df_1m.iterrows():
    h, l, c = row["high"], row["low"], row["close"]
    ema3_h = _ema(ema3_h, h, 0.5)
    ema9_h = _ema(ema9_h, h, 0.2)
    ema3_l = _ema(ema3_l, l, 0.5)
    ema9_l = _ema(ema9_l, l, 0.2)
    
    ema3_h_list.append(ema3_h)
    ema9_h_list.append(ema9_h)
    ema3_l_list.append(ema3_l)
    ema9_l_list.append(ema9_l)
    
    prev = regime
    if c > ema3_h and c > ema9_h:
        regime = 1
    elif c < ema3_l and c < ema9_l:
        regime = -1
    
    regime_list.append(regime)
    flip = (regime != prev and regime != 0)
    flip_list.append(flip)

df_1m["ema3_h"] = ema3_h_list
df_1m["ema9_h"] = ema9_h_list
df_1m["ema3_l"] = ema3_l_list
df_1m["ema9_l"] = ema9_l_list
df_1m["regime"] = regime_list
df_1m["flip"] = flip_list

# Print rows around 2025-01-01 23:30:00 to 2025-01-02 00:10:00
print(df_1m.loc[pd.Timestamp("2025-01-01 23:30:00", tz="UTC"):pd.Timestamp("2025-01-02 00:10:00", tz="UTC"), ["close", "regime", "flip"]])
