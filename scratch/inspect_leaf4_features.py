import pandas as pd
p_train = 'studies/nq_h050_mtf_regime_context_features/results/feature_surface_train.parquet'
df_train = pd.read_parquet(p_train)
cols = ['minutes_from_rth_open', 'realized_range_15m_atr', 'current_price_from_prior_mfe_atr__tf_1m']
print(df_train[cols].describe())
