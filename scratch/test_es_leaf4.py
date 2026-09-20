import sys
sys.path.insert(0, ".")
import time
import numpy as np
import pandas as pd
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

print("Testing ES H050 + Leaf 4 on 2023...")
t0 = time.time()
p_es = 'data/raw/ES_v0_1s_2023.parquet'
df_1s = pd.read_parquet(p_es, columns=['open', 'high', 'low', 'close'])
print(f"Loaded {len(df_1s):,} 1s bars in {time.time()-t0:.2f}s")

# Resample to 1m
t_1m = time.time()
df_1m = df_1s.resample('1min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
print(f"Resampled to {len(df_1m):,} 1m bars in {time.time()-t_1m:.2f}s")

# 15m rolling range on 1m
df_1m['roll_15m_range'] = df_1m['high'].rolling(15, min_periods=1).max() - df_1m['low'].rolling(15, min_periods=1).min()

# Run DualEmaRegimeTracker on 1m
tracker = DualEmaRegimeTracker(timeframe='1m')
regimes = []
cur_reg = None
prior_reg = None

df_1m_ts = df_1m.index.values.astype(np.int64)
df_1m_high = df_1m['high'].values
df_1m_low = df_1m['low'].values
df_1m_close = df_1m['close'].values
df_1m_open = df_1m['open'].values
df_1m_r15 = df_1m['roll_15m_range'].values

atrs_1m = []
for i in range(len(df_1m)):
    up = tracker.observe(df_1m_high[i], df_1m_low[i], df_1m_close[i])
    atrs_1m.append(up.atr if up.atr is not None else 1.0)
    if up.flipped:
        if cur_reg is not None:
            cur_reg['end_ts'] = df_1m_ts[i]
            cur_reg['end_close'] = df_1m_close[i]
            prior_reg = cur_reg.copy()
            regimes.append(cur_reg)
        cur_reg = {
            'regime_id': df_1m_ts[i],
            'direction': up.regime,
            'start_ts': df_1m_ts[i],
            'start_price': df_1m_open[i],
            'start_atr': up.atr if up.atr is not None else 1.0,
            'mfe_price': df_1m_high[i] if up.regime == 1 else df_1m_low[i],
            'prior_mfe_price': prior_reg['mfe_price'] if prior_reg is not None else df_1m_open[i]
        }
    elif cur_reg is not None:
        if cur_reg['direction'] == 1:
            cur_reg['mfe_price'] = max(cur_reg['mfe_price'], df_1m_high[i])
        else:
            cur_reg['mfe_price'] = min(cur_reg['mfe_price'], df_1m_low[i])

if cur_reg is not None and 'end_ts' not in cur_reg:
    cur_reg['end_ts'] = df_1m_ts[-1]
    regimes.append(cur_reg)

df_1m['atr'] = atrs_1m
df_1m['range_15m_atr'] = df_1m['roll_15m_range'] / np.maximum(df_1m['atr'], 1e-4)

print(f"Detected {len(regimes)} regimes in 2023 for ES")
