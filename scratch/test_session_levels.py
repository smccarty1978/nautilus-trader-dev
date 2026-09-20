import sys
sys.path.insert(0, '.')
import time
import math
import numpy as np
import pandas as pd

# Load 1s data for Jan 2023
df_1s = pd.read_parquet('data/raw/NQ_v0_1s_2023.parquet', columns=['open', 'high', 'low', 'close', 'volume'])
df_jan = df_1s.loc['2023-01-01':'2023-01-10']

# Resample to 1m
df_1m = df_jan.resample('1min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_1m['close_ts'] = df_1m.index.values.astype(np.int64) + 60_000_000_000

# Convert index to CT
idx_ct = df_1m.index.tz_convert('America/Chicago')
df_1m['ct_date'] = idx_ct.date
df_1m['ct_minute'] = idx_ct.hour * 60 + idx_ct.minute

# Group into trading sessions: session date is next day if hour >= 17
session_dates = []
for dt in idx_ct:
    if dt.hour >= 17:
        session_dates.append((dt + pd.Timedelta(days=1)).date())
    else:
        session_dates.append(dt.date())
df_1m['session_date'] = session_dates

print('Sample session grouping:')
print(df_1m[['ct_date', 'ct_minute', 'session_date']].head())
