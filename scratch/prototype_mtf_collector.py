import sys
sys.path.insert(0, '.')
import time
import pandas as pd
import numpy as np
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

# Load checkpoints
ck = pd.read_parquet('studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet')
train_ck = ck[ck['split'] == 'TRAIN'].copy()
print(f'Total TRAIN checkpoints: {len(train_ck)}')

# Take first 100
sample = train_ck.iloc[:100]
print(f'Testing on first 100 checkpoints: {sample["checkpoint_ts"].min()} to {sample["checkpoint_ts"].max()}')
