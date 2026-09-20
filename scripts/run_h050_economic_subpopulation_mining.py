"""
run_h050_economic_subpopulation_mining.py

Bounded economic subpopulation mining study on the existing NQ H050 causal feature surface.
Objective: Determine whether the existing causal H050 feature surface contains a sufficiently
large subpopulation that can realistically support 5-10 trades/day at approximately
+0.30 ATR/trade net of slippage/costs, with materially controlled drawdown.

Lineage: Pre-2025 TRAIN (2023 discovery, 2024 untouched validation) and 2025 Q1 frozen forward diagnostic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Set REPO_ROOT
REPO_ROOT = Path(r"c:\Users\Scott McCarty\Projects\Nautilus Trader")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json
import time
import math
import hashlib
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import KFold
from sklearn.tree import DecisionTreeRegressor, export_text

def compute_metrics(pnl_atr_series, pnl_dollars_series=None, n_days=None, total_pop_len=None):
    n = len(pnl_atr_series)
    if n == 0:
        return {
            'N': 0, 'trades_per_day': 0.0, 'coverage_pct': 0.0,
            'mean_pnl_atr': 0.0, 'median_pnl_atr': 0.0, 'std_pnl_atr': 0.0,
            'net_dollars_per_trade': 0.0, 'total_pnl_dollars': 0.0,
            'win_rate': 0.0, 'profit_factor': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0, 'win_loss_ratio': 0.0,
            'catastrophic_rate': 0.0, 'winner_gte_1a_rate': 0.0, 'winner_gte_2a_rate': 0.0, 'winner_gte_3a_rate': 0.0,
            'max_dd_atr': 0.0, 'max_dd_dollars': 0.0, 'max_dd_trade_count': 0, 'longest_losing_streak': 0,
            'worst_20_trade_pnl': 0.0, 'worst_50_trade_pnl': 0.0, 'worst_100_trade_pnl': 0.0,
            'p5_outcome': 0.0, 'expected_shortfall_5pct': 0.0, 'top_1pct_pnl_share': 0.0
        }
    
    pnl = pnl_atr_series.values
    t_day = n / n_days if n_days and n_days > 0 else 0.0
    cov = (n / total_pop_len * 100.0) if total_pop_len and total_pop_len > 0 else 0.0
    
    mean_atr = float(np.mean(pnl))
    median_atr = float(np.median(pnl))
    std_atr = float(np.std(pnl, ddof=1)) if n > 1 else 0.0
    
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    win_rate = float(len(wins) / n)
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    wl_ratio = float(abs(avg_win / avg_loss)) if abs(avg_loss) > 1e-6 else 0.0
    sum_win = float(np.sum(wins))
    sum_loss = float(np.abs(np.sum(losses)))
    pf = float(sum_win / sum_loss) if sum_loss > 1e-6 else (999.0 if sum_win > 0 else 0.0)
    
    cat_rate = float(np.mean(pnl <= -3.0))
    w1_rate = float(np.mean(pnl >= 1.0))
    w2_rate = float(np.mean(pnl >= 2.0))
    w3_rate = float(np.mean(pnl >= 3.0))
    
    cum_pnl = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum_pnl)
    dd_arr = peak - cum_pnl
    max_dd_atr = float(np.max(dd_arr)) if len(dd_arr) > 0 else 0.0
    
    longest_loss_streak = 0
    cur_streak = 0
    for val in pnl:
        if val <= 0:
            cur_streak += 1
            if cur_streak > longest_loss_streak:
                longest_loss_streak = cur_streak
        else:
            cur_streak = 0
            
    max_dd_trade_count = 0
    cur_dd_trades = 0
    cur_peak = -1e9
    for val in cum_pnl:
        if val >= cur_peak:
            cur_peak = val
            cur_dd_trades = 0
        else:
            cur_dd_trades += 1
            if cur_dd_trades > max_dd_trade_count:
                max_dd_trade_count = cur_dd_trades

    s_pnl = pd.Series(pnl)
    worst_20 = float(s_pnl.rolling(20).sum().min()) if n >= 20 else float(s_pnl.sum())
    worst_50 = float(s_pnl.rolling(50).sum().min()) if n >= 50 else float(s_pnl.sum())
    worst_100 = float(s_pnl.rolling(100).sum().min()) if n >= 100 else float(s_pnl.sum())
    
    p5 = float(np.percentile(pnl, 5))
    tail_5 = pnl[pnl <= p5]
    cvar_5 = float(np.mean(tail_5)) if len(tail_5) > 0 else p5
    
    sorted_pnl = np.sort(pnl)
    top1_n = max(1, int(math.ceil(0.01 * n)))
    top1_sum = float(np.sum(sorted_pnl[-top1_n:]))
    tot_sum = float(np.sum(pnl))
    top1_share = float(top1_sum / tot_sum) if tot_sum > 0 else 999.0
    
    net_dollars_trade = 0.0
    tot_dollars = 0.0
    max_dd_dollars = 0.0
    if pnl_dollars_series is not None:
        p_dol = pnl_dollars_series.values
        net_dollars_trade = float(np.mean(p_dol))
        tot_dollars = float(np.sum(p_dol))
        cum_dol = np.cumsum(p_dol)
        peak_dol = np.maximum.accumulate(cum_dol)
        max_dd_dollars = float(np.max(peak_dol - cum_dol))

    return {
        'N': int(n),
        'trades_per_day': round(t_day, 2),
        'coverage_pct': round(cov, 2),
        'mean_pnl_atr': round(mean_atr, 4),
        'median_pnl_atr': round(median_atr, 4),
        'std_pnl_atr': round(std_atr, 4),
        'net_dollars_per_trade': round(net_dollars_trade, 2),
        'total_pnl_dollars': round(tot_dollars, 2),
        'win_rate': round(win_rate, 4),
        'profit_factor': round(pf, 4),
        'avg_win': round(avg_win, 4),
        'avg_loss': round(avg_loss, 4),
        'win_loss_ratio': round(wl_ratio, 4),
        'catastrophic_rate': round(cat_rate, 4),
        'winner_gte_1a_rate': round(w1_rate, 4),
        'winner_gte_2a_rate': round(w2_rate, 4),
        'winner_gte_3a_rate': round(w3_rate, 4),
        'max_dd_atr': round(max_dd_atr, 4),
        'max_dd_dollars': round(max_dd_dollars, 2),
        'max_dd_trade_count': int(max_dd_trade_count),
        'longest_losing_streak': int(longest_loss_streak),
        'worst_20_trade_pnl': round(worst_20, 2),
        'worst_50_trade_pnl': round(worst_50, 2),
        'worst_100_trade_pnl': round(worst_100, 2),
        'p5_outcome': round(p5, 4),
        'expected_shortfall_5pct': round(cvar_5, 4),
        'top_1pct_pnl_share': round(top1_share, 4)
    }

def run_tail_stress_test(pnl_series):
    n = len(pnl_series)
    if n == 0:
        return {}
    pnl = np.sort(pnl_series.values)
    base_mean = float(np.mean(pnl))
    
    drop_1 = pnl[:-1] if n > 1 else pnl
    mean_drop_1 = float(np.mean(drop_1))
    
    n_05 = max(1, int(math.ceil(0.005 * n)))
    drop_05 = pnl[:-n_05] if n > n_05 else pnl
    mean_drop_05 = float(np.mean(drop_05))
    
    n_10 = max(1, int(math.ceil(0.01 * n)))
    drop_10 = pnl[:-n_10] if n > n_10 else pnl
    mean_drop_10 = float(np.mean(drop_10))
    
    n_20 = max(1, int(math.ceil(0.02 * n)))
    drop_20 = pnl[:-n_20] if n > n_20 else pnl
    mean_drop_20 = float(np.mean(drop_20))
    
    tot_pnl = float(np.sum(pnl))
    top1_sum = float(np.sum(pnl[-n_10:]))
    top1_share = float(top1_sum / tot_pnl) if tot_pnl > 0 else 999.0
    
    is_tail_dep = (top1_share > 0.40) or (mean_drop_10 <= 0.0) or (mean_drop_10 < 0.5 * base_mean)
    
    return {
        'base_mean_pnl_atr': round(base_mean, 4),
        'mean_ex_largest_winner': round(mean_drop_1, 4),
        'mean_ex_top_0p5pct': round(mean_drop_05, 4),
        'mean_ex_top_1pct': round(mean_drop_10, 4),
        'mean_ex_top_2pct': round(mean_drop_20, 4),
        'top_1pct_share_of_total_pnl': round(top1_share, 4),
        'tail_dependent': bool(is_tail_dep)
    }

def run_loss_concentration_test(pnl_series):
    n = len(pnl_series)
    if n == 0:
        return {}
    pnl = pnl_series.values
    losses = pnl[pnl < 0]
    if len(losses) == 0:
        return {'share_losses_worst_1pct': 0.0, 'share_losses_worst_5pct': 0.0, 'catastrophic_loss_share': 0.0}
    
    losses_sorted = np.sort(losses)
    tot_loss = float(np.abs(np.sum(losses)))
    
    n_1 = max(1, int(math.ceil(0.01 * len(losses))))
    loss_1_sum = float(np.abs(np.sum(losses_sorted[:n_1])))
    
    n_5 = max(1, int(math.ceil(0.05 * len(losses))))
    loss_5_sum = float(np.abs(np.sum(losses_sorted[:n_5])))
    
    cat_losses = losses[losses <= -3.0]
    cat_sum = float(np.abs(np.sum(cat_losses)))
    
    return {
        'share_losses_worst_1pct': round(loss_1_sum / tot_loss, 4),
        'share_losses_worst_5pct': round(loss_5_sum / tot_loss, 4),
        'catastrophic_loss_share': round(cat_sum / tot_loss, 4)
    }

def main():
    print('=' * 80)
    print('STARTING H050 ECONOMIC SUBPOPULATION MINING STUDY')
    print('=' * 80)
    
    study_dir = REPO_ROOT / 'studies/nq_h050_economic_subpopulation_mining'
    results_dir = study_dir / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    
    print('\n--- 1. Ingesting Causal Surfaces and Outcomes ---')
    p_train = REPO_ROOT / 'studies/nq_h050_mtf_regime_context_features/results/feature_surface_train.parquet'
    p_q1 = REPO_ROOT / 'studies/nq_h050_m4_vs_remaining_mfe_model/feature_surface_2025_q1.parquet'
    p_c1 = REPO_ROOT / 'studies/nq_h050_to_opposing_h050_exit_nt_validation/results/c1_nt_trades_ledger.parquet'
    
    df_train = pd.read_parquet(p_train)
    df_q1 = pd.read_parquet(p_q1)
    df_c1 = pd.read_parquet(p_c1)
    
    print(f'Loaded Train: {df_train.shape}, Q1: {df_q1.shape}, C1 Ledger: {df_c1.shape}')
    
    for col in ['age_cell', 'direction_name', 'model_cell']:
        if col in df_train.columns and col not in df_q1.columns:
            if col == 'direction_name':
                df_q1['direction_name'] = df_q1['direction_is_long'].map({1: 'Counter-LONG', 0: 'Counter-SHORT'})
            elif col == 'age_cell':
                df_q1['age_cell'] = pd.cut(df_q1['regime_age_sec__tf_1m'], bins=[-1, 300, 900, 1e9], labels=['0-300s', '>300-900s', '>900s'])
            elif col == 'model_cell':
                d_name = df_q1['direction_is_long'].map({1: 'Counter-LONG', 0: 'Counter-SHORT'})
                a_name = pd.cut(df_q1['regime_age_sec__tf_1m'], bins=[-1, 300, 900, 1e9], labels=['0-300s', '>300-900s', '>900s'])
                df_q1['model_cell'] = d_name.astype(str) + '_' + a_name.astype(str)
                
    df_all = pd.concat([df_train, df_q1], ignore_index=True)
    df_all['dt'] = pd.to_datetime(df_all['checkpoint_ts'], unit='ns', utc=True)
    df_all['date'] = df_all['dt'].dt.date
    df_all['month'] = df_all['dt'].dt.to_period('M').astype(str)
    df_all['quarter'] = df_all['dt'].dt.to_period('Q').astype(str)
    
    c1_sub = df_c1[['entry_signal_ts', 'duration_seconds']].drop_duplicates(subset=['entry_signal_ts'])
    df_all = df_all.merge(c1_sub, left_on='checkpoint_ts', right_on='entry_signal_ts', how='left')
    
    meta_cols = {'trade_id', 'checkpoint_ts', 'regime_id', 'year', 'split', 'direction', 
                 'counter_direction', 'direction_is_long', 'checkpoint_price', 'frozen_atr',
                 'remaining_incumbent_mfe_atr', 'remaining_incumbent_mfe_gte_0p5a',
                 'remaining_incumbent_mfe_gte_1p0a', 'remaining_incumbent_mfe_gte_2p0a',
                 'c1_net_pnl_atr', 'c1_net_pnl_dollars', 'outcome_bucket', 'is_top10',
                 'severe_loss', 'catastrophic_loss', 'winner_gte_2a', 'winner_gte_3a',
                 'age_cell', 'direction_name', 'model_cell', 'dt', 'date', 'month', 'quarter',
                 'entry_signal_ts', 'duration_seconds'}
    feature_cols = [c for c in df_train.columns if c not in meta_cols]
    print(f'Total causal feature columns: {len(feature_cols)}')
    
    print('\n--- 2. Population Frequency & Coverage Calibration ---')
    freq_summary = {}
    trading_days = {}
    for period in ['2023', '2024', '2025_Q1']:
        sub = df_all[df_all['year'] == period]
        days = int(sub['date'].nunique())
        trading_days[period] = days
        n_ev = len(sub)
        ev_day = n_ev / days
        freq_summary[period] = {
            'total_events': n_ev,
            'trading_days': days,
            'avg_events_per_day': round(ev_day, 2),
            'coverage_for_5_trades_day_pct': round((5.0 / ev_day) * 100.0, 2),
            'coverage_for_7p5_trades_day_pct': round((7.5 / ev_day) * 100.0, 2),
            'coverage_for_10_trades_day_pct': round((10.0 / ev_day) * 100.0, 2)
        }
        print(f"Period {period}: {n_ev} events across {days} days -> {ev_day:.2f} ev/day. 5/day={freq_summary[period]['coverage_for_5_trades_day_pct']}%, 10/day={freq_summary[period]['coverage_for_10_trades_day_pct']}%")
        
    with open(results_dir / 'population_frequency_summary.json', 'w') as f:
        json.dump(freq_summary, f, indent=2)

    print('\n--- 3. 2023 OOF Model Fitting & Training ---')
    df_2023 = df_all[df_all['year'] == '2023'].copy().reset_index(drop=True)
    df_2024 = df_all[df_all['year'] == '2024'].copy().reset_index(drop=True)
    df_2025 = df_all[df_all['year'] == '2025_Q1'].copy().reset_index(drop=True)
    
    X_2023 = df_2023[feature_cols].values
    y_pnl_2023 = df_2023['c1_net_pnl_atr'].values
    
    y_cat_2023 = (y_pnl_2023 <= -3.0).astype(int)
    y_loss2_2023 = (y_pnl_2023 <= -2.0).astype(int)
    y_loss1_2023 = (y_pnl_2023 <= -1.0).astype(int)
    y_win1_2023 = (y_pnl_2023 >= 1.0).astype(int)
    y_win2_2023 = (y_pnl_2023 >= 2.0).astype(int)
    y_win3_2023 = (y_pnl_2023 >= 3.0).astype(int)
    
    oof_ev = np.zeros(len(df_2023))
    oof_p_cat = np.zeros(len(df_2023))
    oof_p_loss2 = np.zeros(len(df_2023))
    oof_p_loss1 = np.zeros(len(df_2023))
    oof_p_win1 = np.zeros(len(df_2023))
    oof_p_win2 = np.zeros(len(df_2023))
    oof_p_win3 = np.zeros(len(df_2023))
    
    kf = KFold(n_splits=5, shuffle=False)
    
    lgb_reg_params = {
        'objective': 'regression',
        'metric': 'rmse',
        'max_depth': 4,
        'num_leaves': 15,
        'learning_rate': 0.03,
        'min_child_samples': 50,
        'colsample_bytree': 0.8,
        'subsample': 0.8,
        'n_estimators': 150,
        'random_state': 42,
        'verbosity': -1
    }
    
    lgb_clf_params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'max_depth': 4,
        'num_leaves': 15,
        'learning_rate': 0.03,
        'min_child_samples': 50,
        'colsample_bytree': 0.8,
        'subsample': 0.8,
        'n_estimators': 150,
        'random_state': 42,
        'verbosity': -1
    }
    
    for tr_idx, val_idx in kf.split(X_2023):
        X_tr, X_val = X_2023[tr_idx], X_2023[val_idx]
        
        reg = lgb.LGBMRegressor(**lgb_reg_params)
        reg.fit(X_tr, y_pnl_2023[tr_idx])
        oof_ev[val_idx] = reg.predict(X_val)
        
        clf_cat = lgb.LGBMClassifier(**lgb_clf_params)
        clf_cat.fit(X_tr, y_cat_2023[tr_idx])
        oof_p_cat[val_idx] = clf_cat.predict_proba(X_val)[:, 1]
        
        clf_l2 = lgb.LGBMClassifier(**lgb_clf_params)
        clf_l2.fit(X_tr, y_loss2_2023[tr_idx])
        oof_p_loss2[val_idx] = clf_l2.predict_proba(X_val)[:, 1]

        clf_l1 = lgb.LGBMClassifier(**lgb_clf_params)
        clf_l1.fit(X_tr, y_loss1_2023[tr_idx])
        oof_p_loss1[val_idx] = clf_l1.predict_proba(X_val)[:, 1]
        
        clf_w1 = lgb.LGBMClassifier(**lgb_clf_params)
        clf_w1.fit(X_tr, y_win1_2023[tr_idx])
        oof_p_win1[val_idx] = clf_w1.predict_proba(X_val)[:, 1]
        
        clf_w2 = lgb.LGBMClassifier(**lgb_clf_params)
        clf_w2.fit(X_tr, y_win2_2023[tr_idx])
        oof_p_win2[val_idx] = clf_w2.predict_proba(X_val)[:, 1]
        
        clf_w3 = lgb.LGBMClassifier(**lgb_clf_params)
        clf_w3.fit(X_tr, y_win3_2023[tr_idx])
        oof_p_win3[val_idx] = clf_w3.predict_proba(X_val)[:, 1]

    df_2023['pred_ev'] = oof_ev
    df_2023['pred_p_cat'] = oof_p_cat
    df_2023['pred_p_loss2'] = oof_p_loss2
    df_2023['pred_p_loss1'] = oof_p_loss1
    df_2023['pred_p_win1'] = oof_p_win1
    df_2023['pred_p_win2'] = oof_p_win2
    df_2023['pred_p_win3'] = oof_p_win3

    print('2023 OOF fitting complete. Fitting frozen full-sample 2023 models for 2024/2025...')
    full_reg = lgb.LGBMRegressor(**lgb_reg_params).fit(X_2023, y_pnl_2023)
    full_cat = lgb.LGBMClassifier(**lgb_clf_params).fit(X_2023, y_cat_2023)
    full_l2 = lgb.LGBMClassifier(**lgb_clf_params).fit(X_2023, y_loss2_2023)
    full_l1 = lgb.LGBMClassifier(**lgb_clf_params).fit(X_2023, y_loss1_2023)
    full_w1 = lgb.LGBMClassifier(**lgb_clf_params).fit(X_2023, y_win1_2023)
    full_w2 = lgb.LGBMClassifier(**lgb_clf_params).fit(X_2023, y_win2_2023)
    full_w3 = lgb.LGBMClassifier(**lgb_clf_params).fit(X_2023, y_win3_2023)
    
    X_2024 = df_2024[feature_cols].values
    df_2024['pred_ev'] = full_reg.predict(X_2024)
    df_2024['pred_p_cat'] = full_cat.predict_proba(X_2024)[:, 1]
    df_2024['pred_p_loss2'] = full_l2.predict_proba(X_2024)[:, 1]
    df_2024['pred_p_loss1'] = full_l1.predict_proba(X_2024)[:, 1]
    df_2024['pred_p_win1'] = full_w1.predict_proba(X_2024)[:, 1]
    df_2024['pred_p_win2'] = full_w2.predict_proba(X_2024)[:, 1]
    df_2024['pred_p_win3'] = full_w3.predict_proba(X_2024)[:, 1]
    
    X_2025 = df_2025[feature_cols].values
    df_2025['pred_ev'] = full_reg.predict(X_2025)
    df_2025['pred_p_cat'] = full_cat.predict_proba(X_2025)[:, 1]
    df_2025['pred_p_loss2'] = full_l2.predict_proba(X_2025)[:, 1]
    df_2025['pred_p_loss1'] = full_l1.predict_proba(X_2025)[:, 1]
    df_2025['pred_p_win1'] = full_w1.predict_proba(X_2025)[:, 1]
    df_2025['pred_p_win2'] = full_w2.predict_proba(X_2025)[:, 1]
    df_2025['pred_p_win3'] = full_w3.predict_proba(X_2025)[:, 1]

    feat_importances = dict(zip(feature_cols, [float(x) for x in full_reg.feature_importances_]))
    sorted_imp = sorted(feat_importances.items(), key=lambda x: x[1], reverse=True)
    
    model_manifest = {
        'model_type': 'LightGBM Regressor (EV) & Classifiers (Tail)',
        'hyperparameters': lgb_reg_params,
        'feature_count': len(feature_cols),
        'top_20_features_by_split_importance': sorted_imp[:20]
    }
    with open(results_dir / 'oof_model_manifest.json', 'w') as f:
        json.dump(model_manifest, f, indent=2)

    print('\n--- 4. Evaluating Fixed Coverage Bands & Rankings ---')
    cov_bands = [
        ('top_10pct', 10.0),
        ('req_5_per_day', 12.16),
        ('top_15pct', 15.0),
        ('req_7p5_per_day', 18.25),
        ('top_20pct', 20.0),
        ('req_10_per_day', 24.33),
        ('top_25pct', 25.0)
    ]
    
    ev_rank_results = {'2023_OOF': {}, '2024_VALIDATION': {}, '2025_Q1_FROZEN': {}}
    coverage_results = {'2023_OOF': {}, '2024_VALIDATION': {}, '2025_Q1_FROZEN': {}}
    frozen_thresholds = {}
    
    for band_name, pct in cov_bands:
        th_val = float(np.percentile(df_2023['pred_ev'], 100.0 - pct))
        frozen_thresholds[band_name] = {'percentile': pct, 'threshold_pred_ev': th_val}
        
        sub_23 = df_2023[df_2023['pred_ev'] >= th_val]
        m_23 = compute_metrics(sub_23['c1_net_pnl_atr'], sub_23['c1_net_pnl_dollars'], trading_days['2023'], len(df_2023))
        ev_rank_results['2023_OOF'][band_name] = m_23
        coverage_results['2023_OOF'][band_name] = m_23
        
        sub_24 = df_2024[df_2024['pred_ev'] >= th_val]
        m_24 = compute_metrics(sub_24['c1_net_pnl_atr'], sub_24['c1_net_pnl_dollars'], trading_days['2024'], len(df_2024))
        ev_rank_results['2024_VALIDATION'][band_name] = m_24
        coverage_results['2024_VALIDATION'][band_name] = m_24
        
        sub_25 = df_2025[df_2025['pred_ev'] >= th_val]
        m_25 = compute_metrics(sub_25['c1_net_pnl_atr'], sub_25['c1_net_pnl_dollars'], trading_days['2025_Q1'], len(df_2025))
        ev_rank_results['2025_Q1_FROZEN'][band_name] = m_25
        coverage_results['2025_Q1_FROZEN'][band_name] = m_25

    with open(results_dir / 'ev_rank_metrics.json', 'w') as f:
        json.dump(ev_rank_results, f, indent=2)
    with open(results_dir / 'coverage_band_results.json', 'w') as f:
        json.dump(coverage_results, f, indent=2)

    print('\n--- 5. Evaluating Risk-Adjusted & Tail Preserving Rankings ---')
    cat_med_th = float(np.median(df_2023['pred_p_cat']))
    cat_q75_th = float(np.percentile(df_2023['pred_p_cat'], 75.0))
    win2_q75_th = float(np.percentile(df_2023['pred_p_win2'], 75.0))
    
    risk_results = {'2023_OOF': {}, '2024_VALIDATION': {}, '2025_Q1_FROZEN': {}}
    right_tail_results = {'2023_OOF': {}, '2024_VALIDATION': {}, '2025_Q1_FROZEN': {}}
    
    for base_band in ['req_5_per_day', 'req_10_per_day', 'top_20pct']:
        th_ev = frozen_thresholds[base_band]['threshold_pred_ev']
        
        f_name_a = f"{base_band}_AND_p_cat_below_median"
        m23_a = compute_metrics(df_2023[(df_2023['pred_ev'] >= th_ev) & (df_2023['pred_p_cat'] < cat_med_th)]['c1_net_pnl_atr'], n_days=trading_days['2023'], total_pop_len=len(df_2023))
        m24_a = compute_metrics(df_2024[(df_2024['pred_ev'] >= th_ev) & (df_2024['pred_p_cat'] < cat_med_th)]['c1_net_pnl_atr'], n_days=trading_days['2024'], total_pop_len=len(df_2024))
        m25_a = compute_metrics(df_2025[(df_2025['pred_ev'] >= th_ev) & (df_2025['pred_p_cat'] < cat_med_th)]['c1_net_pnl_atr'], n_days=trading_days['2025_Q1'], total_pop_len=len(df_2025))
        risk_results['2023_OOF'][f_name_a] = m23_a
        risk_results['2024_VALIDATION'][f_name_a] = m24_a
        risk_results['2025_Q1_FROZEN'][f_name_a] = m25_a
        
        f_name_b = f"{base_band}_AND_p_cat_below_q75"
        m23_b = compute_metrics(df_2023[(df_2023['pred_ev'] >= th_ev) & (df_2023['pred_p_cat'] < cat_q75_th)]['c1_net_pnl_atr'], n_days=trading_days['2023'], total_pop_len=len(df_2023))
        m24_b = compute_metrics(df_2024[(df_2024['pred_ev'] >= th_ev) & (df_2024['pred_p_cat'] < cat_q75_th)]['c1_net_pnl_atr'], n_days=trading_days['2024'], total_pop_len=len(df_2024))
        m25_b = compute_metrics(df_2025[(df_2025['pred_ev'] >= th_ev) & (df_2025['pred_p_cat'] < cat_q75_th)]['c1_net_pnl_atr'], n_days=trading_days['2025_Q1'], total_pop_len=len(df_2025))
        risk_results['2023_OOF'][f_name_b] = m23_b
        risk_results['2024_VALIDATION'][f_name_b] = m24_b
        risk_results['2025_Q1_FROZEN'][f_name_b] = m25_b
        
        f_name_c = f"{base_band}_AND_high_right_tail"
        m23_c = compute_metrics(df_2023[(df_2023['pred_ev'] >= th_ev) & (df_2023['pred_p_win2'] >= win2_q75_th)]['c1_net_pnl_atr'], n_days=trading_days['2023'], total_pop_len=len(df_2023))
        m24_c = compute_metrics(df_2024[(df_2024['pred_ev'] >= th_ev) & (df_2024['pred_p_win2'] >= win2_q75_th)]['c1_net_pnl_atr'], n_days=trading_days['2024'], total_pop_len=len(df_2024))
        m25_c = compute_metrics(df_2025[(df_2025['pred_ev'] >= th_ev) & (df_2025['pred_p_win2'] >= win2_q75_th)]['c1_net_pnl_atr'], n_days=trading_days['2025_Q1'], total_pop_len=len(df_2025))
        right_tail_results['2023_OOF'][f_name_c] = m23_c
        right_tail_results['2024_VALIDATION'][f_name_c] = m24_c
        right_tail_results['2025_Q1_FROZEN'][f_name_c] = m25_c

    with open(results_dir / 'left_tail_rank_metrics.json', 'w') as f:
        json.dump(risk_results, f, indent=2)
    with open(results_dir / 'right_tail_rank_metrics.json', 'w') as f:
        json.dump(right_tail_results, f, indent=2)

    print('\n--- 6. Direction x Regime Age Matrix ---')
    matrix_results = {}
    for period, df_p in [('2023', df_2023), ('2024', df_2024), ('2025_Q1', df_2025)]:
        matrix_results[period] = {}
        for d_name, d_val in [('LONG', 1), ('SHORT', 0)]:
            for age_name, a_min, a_max in [('Young_le_600s', 0, 600), ('Middle_600_1800s', 600, 1800), ('Mature_gt_1800s', 1800, 1e9)]:
                cell_key = f"{d_name}_{age_name}"
                sub = df_p[(df_p['direction_is_long'] == d_val) & (df_p['regime_age_sec__tf_1m'] > a_min) & (df_p['regime_age_sec__tf_1m'] <= a_max)]
                matrix_results[period][cell_key] = compute_metrics(sub['c1_net_pnl_atr'], sub['c1_net_pnl_dollars'], trading_days[period], len(df_p))
                
    with open(results_dir / 'direction_age_matrix.json', 'w') as f:
        json.dump(matrix_results, f, indent=2)

    print('\n--- 7. Human-Readable Rule Mining ---')
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
    
    dt_model = DecisionTreeRegressor(max_depth=4, min_samples_leaf=150, random_state=42)
    dt_model.fit(df_2023[tree_features], df_2023['c1_net_pnl_atr'])
    
    tree_text = export_text(dt_model, feature_names=tree_features)
    
    leaf_23 = dt_model.apply(df_2023[tree_features])
    leaf_24 = dt_model.apply(df_2024[tree_features])
    leaf_25 = dt_model.apply(df_2025[tree_features])
    
    df_2023['dt_leaf'] = leaf_23
    df_2024['dt_leaf'] = leaf_24
    df_2025['dt_leaf'] = leaf_25
    
    unique_leaves = np.unique(leaf_23)
    leaf_validation = {}
    
    for leaf_id in unique_leaves:
        s23 = df_2023[df_2023['dt_leaf'] == leaf_id]
        s24 = df_2024[df_2024['dt_leaf'] == leaf_id]
        s25 = df_2025[df_2025['dt_leaf'] == leaf_id]
        
        m23 = compute_metrics(s23['c1_net_pnl_atr'], s23['c1_net_pnl_dollars'], trading_days['2023'], len(df_2023))
        m24 = compute_metrics(s24['c1_net_pnl_atr'], s24['c1_net_pnl_dollars'], trading_days['2024'], len(df_2024))
        m25 = compute_metrics(s25['c1_net_pnl_atr'], s25['c1_net_pnl_dollars'], trading_days['2025_Q1'], len(df_2025))
        
        leaf_validation[int(leaf_id)] = {
            'leaf_id': int(leaf_id),
            '2023_OOF': m23,
            '2024_VALIDATION': m24,
            '2025_Q1_FROZEN': m25
        }
        
    with open(results_dir / 'interpretable_rule_tree.json', 'w') as f:
        json.dump({'tree_text': tree_text, 'features': tree_features}, f, indent=2)
    with open(results_dir / 'interpretable_rule_validation.json', 'w') as f:
        json.dump(leaf_validation, f, indent=2)

    print('\n--- 8. Synthesizing Master Candidate Matrix & Baselines ---')
    sorted_leaves = sorted([l for l in leaf_validation.values() if l['2023_OOF']['N'] >= 200], 
                           key=lambda x: x['2023_OOF']['mean_pnl_atr'], reverse=True)
    best_leaf_id = sorted_leaves[0]['leaf_id'] if len(sorted_leaves) > 0 else unique_leaves[0]
    
    candidate_defs = [
        ('Broad_H050_Baseline', 'Baseline', 'All unconditioned H050 events',
         lambda df: np.ones(len(df), dtype=bool)),
        ('LONG_Only', 'Structural', 'direction_is_long == 1',
         lambda df: df['direction_is_long'] == 1),
        ('SHORT_Only', 'Structural', 'direction_is_long == 0',
         lambda df: df['direction_is_long'] == 0),
        ('Young_Regime_Only', 'Structural', 'regime_age <= 600s',
         lambda df: df['regime_age_sec__tf_1m'] <= 600.0),
        ('Middle_Regime_Only', 'Structural', '600s < regime_age <= 1800s',
         lambda df: (df['regime_age_sec__tf_1m'] > 600.0) & (df['regime_age_sec__tf_1m'] <= 1800.0)),
        ('Mature_Regime_Only', 'Structural', 'regime_age > 1800s',
         lambda df: df['regime_age_sec__tf_1m'] > 1800.0),
        ('LONG_x_Young', 'Structural', 'direction_is_long == 1 & regime_age <= 600s',
         lambda df: (df['direction_is_long'] == 1) & (df['regime_age_sec__tf_1m'] <= 600.0)),
        ('LONG_x_Mature', 'Structural', 'direction_is_long == 1 & regime_age > 1800s',
         lambda df: (df['direction_is_long'] == 1) & (df['regime_age_sec__tf_1m'] > 1800.0)),
        ('ML_Top10pct_EV', 'ML_Ranker', f"pred_ev >= {frozen_thresholds['top_10pct']['threshold_pred_ev']:.4f}",
         lambda df: df['pred_ev'] >= frozen_thresholds['top_10pct']['threshold_pred_ev']),
        ('ML_5_trades_day_EV', 'ML_Ranker', f"pred_ev >= {frozen_thresholds['req_5_per_day']['threshold_pred_ev']:.4f}",
         lambda df: df['pred_ev'] >= frozen_thresholds['req_5_per_day']['threshold_pred_ev']),
        ('ML_7p5_trades_day_EV', 'ML_Ranker', f"pred_ev >= {frozen_thresholds['req_7p5_per_day']['threshold_pred_ev']:.4f}",
         lambda df: df['pred_ev'] >= frozen_thresholds['req_7p5_per_day']['threshold_pred_ev']),
        ('ML_10_trades_day_EV', 'ML_Ranker', f"pred_ev >= {frozen_thresholds['req_10_per_day']['threshold_pred_ev']:.4f}",
         lambda df: df['pred_ev'] >= frozen_thresholds['req_10_per_day']['threshold_pred_ev']),
        ('ML_5_day_EV_LowCat', 'ML_RiskAdjusted', f"pred_ev >= {frozen_thresholds['req_5_per_day']['threshold_pred_ev']:.4f} & p_cat < {cat_med_th:.4f}",
         lambda df: (df['pred_ev'] >= frozen_thresholds['req_5_per_day']['threshold_pred_ev']) & (df['pred_p_cat'] < cat_med_th)),
        ('ML_10_day_EV_LowCat', 'ML_RiskAdjusted', f"pred_ev >= {frozen_thresholds['req_10_per_day']['threshold_pred_ev']:.4f} & p_cat < {cat_med_th:.4f}",
         lambda df: (df['pred_ev'] >= frozen_thresholds['req_10_per_day']['threshold_pred_ev']) & (df['pred_p_cat'] < cat_med_th)),
        (f"Interpretable_Leaf_{best_leaf_id}", 'Rule_Tree', f"Decision tree leaf {best_leaf_id}",
         lambda df: df['dt_leaf'] == best_leaf_id)
    ]
    
    master_matrix = []
    stress_tests = {}
    tail_tests = {}
    monthly_stability = {}
    baseline_comp = {}
    
    for c_name, c_type, c_rule, c_fn in candidate_defs:
        m23 = compute_metrics(df_2023[c_fn(df_2023)]['c1_net_pnl_atr'], df_2023[c_fn(df_2023)]['c1_net_pnl_dollars'], trading_days['2023'], len(df_2023))
        m24 = compute_metrics(df_2024[c_fn(df_2024)]['c1_net_pnl_atr'], df_2024[c_fn(df_2024)]['c1_net_pnl_dollars'], trading_days['2024'], len(df_2024))
        m25 = compute_metrics(df_2025[c_fn(df_2025)]['c1_net_pnl_atr'], df_2025[c_fn(df_2025)]['c1_net_pnl_dollars'], trading_days['2025_Q1'], len(df_2025))
        
        pnl24 = df_2024[c_fn(df_2024)]['c1_net_pnl_atr']
        tail_res = run_tail_stress_test(pnl24)
        tail_tests[c_name] = tail_res
        
        loss_res = run_loss_concentration_test(pnl24)
        stress_tests[c_name] = {
            'drawdown_metrics_2024': {
                'max_dd_atr': m24['max_dd_atr'],
                'max_dd_dollars': m24['max_dd_dollars'],
                'max_dd_trade_count': m24['max_dd_trade_count'],
                'longest_losing_streak': m24['longest_losing_streak'],
                'worst_20_trade_pnl': m24['worst_20_trade_pnl'],
                'worst_50_trade_pnl': m24['worst_50_trade_pnl'],
                'worst_100_trade_pnl': m24['worst_100_trade_pnl']
            },
            'loss_concentration_2024': loss_res
        }
        
        sub24 = df_2024[c_fn(df_2024)].copy()
        sub24['dt'] = pd.to_datetime(sub24['checkpoint_ts'], unit='ns', utc=True)
        sub24['month'] = sub24['dt'].dt.to_period('M').astype(str)
        
        m_breakdown = {}
        for m_str, m_df in sub24.groupby('month'):
            m_days = m_df['date'].nunique()
            m_breakdown[m_str] = compute_metrics(m_df['c1_net_pnl_atr'], m_df['c1_net_pnl_dollars'], m_days, len(m_df))
        monthly_stability[c_name] = m_breakdown
        
        c_class = 'NOT_USEFUL'
        if m24['mean_pnl_atr'] >= 0.30:
            c_class = 'STRONG'
        elif m24['mean_pnl_atr'] >= 0.20:
            c_class = 'PROMISING'
        elif m24['mean_pnl_atr'] >= 0.10:
            c_class = 'WEAK'
            
        row = {
            'candidate': c_name,
            'type': c_type,
            'features_rule': c_rule,
            'coverage_2024_pct': m24['coverage_pct'],
            'trades_per_day_2024': m24['trades_per_day'],
            '2023_OOF_EV': m23['mean_pnl_atr'],
            '2024_EV': m24['mean_pnl_atr'],
            '2025_Q1_EV': m25['mean_pnl_atr'],
            'classification_2024': c_class,
            'win_rate_2024': m24['win_rate'],
            'avg_win_2024': m24['avg_win'],
            'avg_loss_2024': m24['avg_loss'],
            'win_loss_ratio_2024': m24['win_loss_ratio'],
            'profit_factor_2024': m24['profit_factor'],
            'catastrophic_rate_2024': m24['catastrophic_rate'],
            'max_dd_atr_2024': m24['max_dd_atr'],
            'max_dd_dollars_2024': m24['max_dd_dollars'],
            'top_1pct_pnl_share_2024': tail_res.get('top_1pct_share_of_total_pnl', 0.0),
            'tail_dependent': tail_res.get('tail_dependent', False),
            'metrics_full_2023': m23,
            'metrics_full_2024': m24,
            'metrics_full_2025_q1': m25
        }
        master_matrix.append(row)
        baseline_comp[c_name] = {'2023': m23, '2024': m24, '2025_Q1': m25}
        
    with open(results_dir / 'candidate_subpopulation_matrix.json', 'w') as f:
        json.dump(master_matrix, f, indent=2)
    with open(results_dir / 'drawdown_stress_tests.json', 'w') as f:
        json.dump(stress_tests, f, indent=2)
    with open(results_dir / 'tail_dependence_tests.json', 'w') as f:
        json.dump(tail_tests, f, indent=2)
    with open(results_dir / 'monthly_stability.json', 'w') as f:
        json.dump(monthly_stability, f, indent=2)
    with open(results_dir / 'baseline_comparisons.json', 'w') as f:
        json.dump(baseline_comp, f, indent=2)
    with open(results_dir / '2025_q1_frozen_diagnostic.json', 'w') as f:
        json.dump({c['candidate']: c['metrics_full_2025_q1'] for c in master_matrix}, f, indent=2)

    print('\n--- 9. Saving Observation-Level Scored Parquet Ledger ---')
    scored_cols = ['trade_id', 'checkpoint_ts', 'year', 'split', 'direction_is_long',
                   'regime_age_sec__tf_1m', 'frozen_atr', 'c1_net_pnl_atr', 'c1_net_pnl_dollars',
                   'pred_ev', 'pred_p_cat', 'pred_p_win2', 'dt_leaf']
    df_scored = pd.concat([
        df_2023[scored_cols],
        df_2024[scored_cols],
        df_2025[scored_cols]
    ], ignore_index=True)
    df_scored.to_parquet(results_dir / 'h050_scored_observation_ledger.parquet', index=False)

    print('\n--- 10. Generating Study Metadata & Manifests ---')
    with open(results_dir / 'feature_manifest.json', 'w') as f:
        json.dump({'feature_count': len(feature_cols), 'feature_names': feature_cols}, f, indent=2)
        
    contract_json = {
        'target_frequency': '5-10 trades/day',
        'target_net_expectancy': '>= +0.30 ATR/trade net of slippage/costs',
        'cost_model': 'audited C1 execution model',
        'primary_split': {
            'discovery_fit_oof': '2023 (N=10,605)',
            'untouched_validation': '2024 (N=10,888)',
            'frozen_forward_diagnostic': '2025 Q1 (N=2,422)'
        },
        'kill_condition': 'If no candidate achieves >= +0.20 ATR/trade on untouched 2024 with ~5/day frequency and controlled DD, recommend STOP'
    }
    with open(results_dir / 'economic_target_contract.json', 'w') as f:
        json.dump(contract_json, f, indent=2)

    study_manifest = {
        'study_id': 'nq_h050_economic_subpopulation_mining',
        'timestamp_completed': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
        'total_observations': len(df_all),
        'observations_by_period': {
            '2023': len(df_2023),
            '2024': len(df_2024),
            '2025_Q1': len(df_2025)
        },
        'artifacts': [
            'population_frequency_summary.json',
            'economic_target_contract.json',
            'feature_manifest.json',
            'oof_model_manifest.json',
            'ev_rank_metrics.json',
            'left_tail_rank_metrics.json',
            'right_tail_rank_metrics.json',
            'coverage_band_results.json',
            'direction_age_matrix.json',
            'interpretable_rule_tree.json',
            'interpretable_rule_validation.json',
            'candidate_subpopulation_matrix.json',
            'drawdown_stress_tests.json',
            'tail_dependence_tests.json',
            'monthly_stability.json',
            'baseline_comparisons.json',
            '2025_q1_frozen_diagnostic.json',
            'h050_scored_observation_ledger.parquet'
        ]
    }
    with open(results_dir / 'study_manifest.json', 'w') as f:
        json.dump(study_manifest, f, indent=2)

    print('\nProcessing complete! All artifacts written successfully.')

if __name__ == '__main__':
    main()
