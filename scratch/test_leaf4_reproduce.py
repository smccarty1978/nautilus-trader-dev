import sys
sys.path.insert(0, ".")
import json
import numpy as np
import pandas as pd

p_train = 'studies/nq_h050_mtf_regime_context_features/results/feature_surface_train.parquet'
p_q1 = 'studies/nq_h050_m4_vs_remaining_mfe_model/feature_surface_2025_q1.parquet'
df_train = pd.read_parquet(p_train)
df_q1 = pd.read_parquet(p_q1)
df_all = pd.concat([df_train, df_q1], ignore_index=True)

cond = (
    (df_all['minutes_from_rth_open'] <= 380.649994) &
    (df_all['realized_range_15m_atr'] <= 9.344128) &
    (df_all['current_price_from_prior_mfe_atr__tf_1m'] <= 1.738367)
)

sub = df_all[cond]
print("Matched rows:", len(sub))
print(sub.groupby('year').agg({'c1_net_pnl_atr': ['count', 'mean', 'median'], 'c1_net_pnl_dollars': ['sum', 'mean']}))
