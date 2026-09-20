import sys
sys.path.insert(0, ".")
import time
import numpy as np
import pandas as pd
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

t0 = time.time()
p_es = 'data/canonical/ES_dense_1s_2016_2026.parquet'
print("Loading 1 month of ES 1s data (Jan 2023)...")
df_1s = pd.read_parquet(p_es, columns=['open', 'high', 'low', 'close']).loc['2023-01-01':'2023-01-31']
print(f"Loaded {len(df_1s):,} bars in {time.time()-t0:.2f}s")

# Resample to 1m
df_1m = df_1s.resample('1min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
print(f"Resampled to {len(df_1m):,} 1m bars")

# Run tracker
tracker = DualEmaRegimeTracker(timeframe='1m')
regimes = []
cur_regime = None
for ts, row in df_1m.iterrows():
    up = tracker.observe(row['high'], row['low'], row['close'])
    if up.flipped:
        if cur_regime is not None:
            cur_regime['end_ts'] = ts
            cur_regime['end_close'] = row['close']
            regimes.append(cur_regime)
        cur_regime = {
            'direction': up.regime,
            'start_ts': ts,
            'start_price': row['open'],
            'start_atr': up.atr,
            'mfe_price': row['high'] if up.regime == 1 else row['low'],
            'mae_price': row['low'] if up.regime == 1 else row['high']
        }
    elif cur_regime is not None:
        if cur_regime['direction'] == 1:
            cur_regime['mfe_price'] = max(cur_regime['mfe_price'], row['high'])
            cur_regime['mae_price'] = min(cur_regime['mae_price'], row['low'])
        else:
            cur_regime['mfe_price'] = min(cur_regime['mfe_price'], row['low'])
            cur_regime['mae_price'] = max(cur_regime['mae_price'], row['high'])

print(f"Detected {len(regimes)} regimes in Jan 2023")
for r in regimes[:3]:
    print(" ", r['start_ts'], "to", r.get('end_ts'), "dir:", r['direction'], "start_atr:", r['start_atr'])
