import sys
sys.path.insert(0, '.')
import pandas as pd
import numpy as np
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

ck = pd.read_parquet('studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet')
train_ck = ck[ck['split'] == 'TRAIN'].iloc[:5]
for idx, r in train_ck.iterrows():
    print(r['regime_id'], r['direction'], r['regime_start_ts'], r['checkpoint_ts'], r['checkpoint_price'])
