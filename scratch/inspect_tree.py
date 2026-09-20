import pandas as pd
import numpy as np
from sklearn.tree import DecisionTreeRegressor, _tree

p_train = 'studies/nq_h050_mtf_regime_context_features/results/feature_surface_train.parquet'
df_train = pd.read_parquet(p_train)
df_2023 = df_train[df_train['year'] == '2023'].copy().reset_index(drop=True)

tree_features = [
    'direction_is_long',
    'regime_age_sec__tf_1m',
    'pullback_depth_atr',
    'pullback_velocity_atr_sec',
    'pullback_efficiency',
    'realized_range_15m_atr',
    'atr_change_rate',
    'prior_regime_range_reclaim_ratio__tf_1m',
    'current_price_from_prior_mfe_atr__tf_1m',
    'minutes_from_rth_open'
]

dt = DecisionTreeRegressor(max_depth=4, min_samples_leaf=150, random_state=42)
dt.fit(df_2023[tree_features], df_2023['c1_net_pnl_atr'])

tree_ = dt.tree_
feature_names = [tree_features[i] if i != _tree.TREE_UNDEFINED else 'undefined' for i in tree_.feature]

def recurse(node, path):
    if tree_.feature[node] != _tree.TREE_UNDEFINED:
        recurse(tree_.children_left[node], path + [(feature_names[node], '<=', tree_.threshold[node])])
        recurse(tree_.children_right[node], path + [(feature_names[node], '>', tree_.threshold[node])])
    else:
        p_str = ' and '.join([f'{f} {op} {th:.6f}' for f, op, th in path])
        print(f'Node {node}: n={tree_.n_node_samples[node]}, val={tree_.value[node][0][0]:.4f}, path={p_str}')

recurse(0, [])
