import sys
sys.path.insert(0, ".")
import pandas as pd
import numpy as np
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

p_1s = 'data/raw/NQ_v0_1s_2023.parquet'
df_1s = pd.read_parquet(p_1s, columns=['open', 'high', 'low', 'close']).loc['2023-01-03':'2023-01-04']
df_1m = df_1s.resample('1min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

tracker = DualEmaRegimeTracker(timeframe='1m')
flips = []
for ts, row in df_1m.iterrows():
    up = tracker.observe(row['high'], row['low'], row['close'])
    if up.flipped:
        flips.append((ts, up.regime, up.atr))

print(f"Detected {len(flips)} flips")
for f in flips[:5]:
    print("  Tracker:", f[0], "regime:", f[1], "atr:", f[2])

c0 = pd.read_parquet('studies/nq_persistent_q4_to_q4_regime_capture/results/c0_control_ledger.parquet')
c0_sub = c0[(c0['entry_ts'] >= int(pd.Timestamp('2023-01-03', tz='UTC').value)) & 
            (c0['entry_ts'] <= int(pd.Timestamp('2023-01-05', tz='UTC').value))]
print(f"c0_control_ledger has {len(c0_sub)} regimes")
for _, r in c0_sub.head(5).iterrows():
    print("  c0:", pd.to_datetime(r['entry_ts'], unit='ns', utc=True), "dir:", r['direction'], "start_atr:", r['start_atr'])
