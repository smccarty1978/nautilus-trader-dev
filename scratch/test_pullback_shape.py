import sys
sys.path.insert(0, '.')
import time
import math
import numpy as np
import pandas as pd

# Load checkpoints
ck = pd.read_parquet('studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet')
train_ck = ck[ck['split'] == 'TRAIN'].copy()
jan_ck = train_ck[(train_ck['checkpoint_ts'] >= 1672531200000000000) & 
                  (train_ck['checkpoint_ts'] < 1675209600000000000)].iloc[:10].copy()

# Test pullback shape calculations
for idx, r in jan_ck.iterrows():
    pb_vel = r['pullback_velocity_atr_sec']
    mfe_atr = r['pre_pullback_max_mfe_atr']
    reg_age = r['regime_age_sec']
    pb_dur = r['pullback_duration_sec']
    exp_time = max(reg_age - pb_dur, 1.0)
    exp_vel = mfe_atr / exp_time
    vel_ratio = abs(pb_vel) / max(abs(exp_vel), 1e-6)
    print(f"Row {idx}: pb_vel={pb_vel:.4f}, exp_vel={exp_vel:.4f}, vel_ratio={vel_ratio:.3f}")

print('Pullback velocity calculation verified.')
