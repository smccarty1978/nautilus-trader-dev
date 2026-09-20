import sys
sys.path.insert(0, '.')
import time
import math
import numpy as np
import pandas as pd
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

# 1. Load checkpoints
ck = pd.read_parquet('studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet')
train_ck = ck[ck['split'] == 'TRAIN'].copy()
jan_ck = train_ck[(train_ck['checkpoint_ts'] >= 1672531200000000000) & 
                  (train_ck['checkpoint_ts'] < 1675209600000000000)].copy()

# 2. Read 1s data
df_1s = pd.read_parquet('data/raw/NQ_v0_1s_2023.parquet')
df_jan_1s = df_1s.loc['2023-01-01':'2023-01-31']

# 3. Resample & build trackers
tf_snapshots = {}
timeframes = [('30s', '30s'), ('1m', '1min'), ('5m', '5min'), ('1h', '1h')]

for tf_name, rule in timeframes:
    b = df_jan_1s.resample(rule).agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
    dur_ns = int(pd.Timedelta(rule).total_seconds() * 1e9)
    close_ts_arr = b.index.values.astype(np.int64) + dur_ns
    b['close_ts'] = close_ts_arr
    
    tracker = DualEmaRegimeTracker(timeframe=tf_name)
    snapshots = []
    
    cur_dir = 0
    start_ts = None
    start_price = None
    start_atr = 10.0
    mfe_price = None
    mfe_ts = None
    mae_price = None
    mae_ts = None
    new_ext_count = 0
    failed_attempts = 0
    in_approach = False
    prior_regime = None
    mfe_history = []
    
    for row_idx in range(len(b)):
        c_ts = close_ts_arr[row_idx]
        o = b['open'].values[row_idx]
        h = b['high'].values[row_idx]
        l = b['low'].values[row_idx]
        c = b['close'].values[row_idx]
        
        up = tracker.observe(h, l, c)
        cur_atr = up.atr if up.atr is not None and math.isfinite(up.atr) else 10.0
        
        if up.flipped:
            if cur_dir != 0 and start_ts is not None:
                dur_sec = max(0.0, (c_ts - start_ts) / 1e9)
                p_mfe_atr = max(0.0, cur_dir * (mfe_price - start_price) / max(start_atr, 1e-4))
                p_mae_atr = max(0.0, -cur_dir * (mae_price - start_price) / max(start_atr, 1e-4))
                prior_regime = {
                    'direction': cur_dir,
                    'start_ts': start_ts,
                    'end_ts': c_ts,
                    'start_price': start_price,
                    'end_close': c,
                    'mfe_price': mfe_price,
                    'mae_price': mae_price,
                    'start_atr': start_atr,
                    'max_mfe_atr': p_mfe_atr,
                    'max_mae_atr': p_mae_atr,
                    'duration_sec': dur_sec,
                    'total_range': abs(mfe_price - mae_price)
                }
            cur_dir = up.regime
            start_ts = c_ts
            start_price = o
            start_atr = cur_atr
            mfe_price = h if up.regime == 1 else l
            mfe_ts = c_ts
            mae_price = l if up.regime == 1 else h
            mae_ts = c_ts
            new_ext_count = 1
            failed_attempts = 0
            in_approach = False
            mfe_history = [(c_ts, mfe_price, c)]
        elif cur_dir != 0:
            is_new_mfe = False
            if cur_dir == 1:
                if h > mfe_price:
                    mfe_price = h
                    mfe_ts = c_ts
                    new_ext_count += 1
                    is_new_mfe = True
                if l < mae_price:
                    mae_price = l
                    mae_ts = c_ts
            else:
                if l < mfe_price:
                    mfe_price = l
                    mfe_ts = c_ts
                    new_ext_count += 1
                    is_new_mfe = True
                if h > mae_price:
                    mae_price = h
                    mae_ts = c_ts
                    
            dist_to_mfe = abs(c - mfe_price) / max(cur_atr, 1e-4)
            if dist_to_mfe <= 0.50 and not is_new_mfe:
                if not in_approach:
                    failed_attempts += 1
                    in_approach = True
            elif dist_to_mfe > 0.75:
                in_approach = False
                
            mfe_history.append((c_ts, mfe_price, c))
            if len(mfe_history) > 300:
                mfe_history.pop(0)
                
        snap = {
            'close_ts': c_ts,
            'direction': cur_dir,
            'start_ts': start_ts,
            'start_price': start_price,
            'start_atr': start_atr,
            'current_atr': cur_atr,
            'mfe_price': mfe_price,
            'mfe_ts': mfe_ts,
            'mae_price': mae_price,
            'mae_ts': mae_ts,
            'new_extreme_count': new_ext_count,
            'failed_new_extreme_attempt_count': failed_attempts,
            'prior_regime': prior_regime.copy() if prior_regime is not None else None,
            'mfe_history': list(mfe_history),
            'last_close_price': c,
        }
        snapshots.append(snap)
        
    tf_snapshots[tf_name] = (close_ts_arr, snapshots)

# 4. Feature Extraction Function for a single timeframe snapshot
def extract_tf_features(snap, tf, ck_ts, ck_price):
    d = snap['direction']
    atr = max(snap['current_atr'], 1e-4)
    start_p = snap['start_price'] if snap['start_price'] is not None else ck_price
    mfe_p = snap['mfe_price'] if snap['mfe_price'] is not None else ck_price
    mae_p = snap['mae_price'] if snap['mae_price'] is not None else ck_price
    s_ts = snap['start_ts'] if snap['start_ts'] is not None else ck_ts
    mfe_ts = snap['mfe_ts'] if snap['mfe_ts'] is not None else ck_ts
    mae_ts = snap['mae_ts'] if snap['mae_ts'] is not None else ck_ts
    
    # Family A
    age_sec = max(0.0, (ck_ts - s_ts) / 1e9)
    max_mfe_atr = max(0.0, d * (mfe_p - start_p) / atr)
    max_mae_atr = max(0.0, -d * (mae_p - start_p) / atr)
    total_range_atr = abs(mfe_p - mae_p) / atr
    cur_disp_atr = d * (ck_price - start_p) / atr
    dist_mfe_atr = abs(ck_price - mfe_p) / atr
    dist_mae_atr = abs(ck_price - mae_p) / atr
    time_since_mfe_sec = max(0.0, (ck_ts - mfe_ts) / 1e9)
    time_since_mae_sec = max(0.0, (ck_ts - mae_ts) / 1e9)
    new_ext_count = float(snap['new_extreme_count'])
    
    # Family B & C
    prior = snap['prior_regime']
    if prior is not None:
        p_dur_sec = prior['duration_sec']
        p_mfe_atr = prior['max_mfe_atr']
        p_mae_atr = prior['max_mae_atr']
        p_range_atr = abs(prior['mfe_price'] - prior['mae_price']) / atr
        p_mfe_mae_range_atr = p_range_atr
        
        start_from_p_mfe = d * (start_p - prior['mfe_price']) / atr
        start_from_p_mae = d * (start_p - prior['mae_price']) / atr
        price_from_p_mfe = d * (ck_price - prior['mfe_price']) / atr
        price_from_p_mae = d * (ck_price - prior['mae_price']) / atr
        cur_mfe_from_p_mfe = d * (mfe_p - prior['mfe_price']) / atr
        cur_mfe_from_p_mae = d * (mfe_p - prior['mae_price']) / atr
        
        p_range_pts = max(abs(prior['mfe_price'] - prior['mae_price']), 1e-4)
        reclaim_ratio = max(0.0, d * (mfe_p - prior['mfe_price'])) / p_range_pts
        
        p_hi = max(prior['mfe_price'], prior['mae_price'])
        p_lo = min(prior['mfe_price'], prior['mae_price'])
        c_hi = max(mfe_p, mae_p, start_p, ck_price)
        c_lo = min(mfe_p, mae_p, start_p, ck_price)
        overlap_pts = max(0.0, min(c_hi, p_hi) - max(c_lo, p_lo))
        overlap_ratio = min(1.0, max(0.0, overlap_pts / p_range_pts))
    else:
        p_dur_sec = 0.0
        p_mfe_atr = 0.0
        p_mae_atr = 0.0
        p_range_atr = 0.0
        p_mfe_mae_range_atr = 0.0
        start_from_p_mfe = 0.0
        start_from_p_mae = 0.0
        price_from_p_mfe = 0.0
        price_from_p_mae = 0.0
        cur_mfe_from_p_mfe = 0.0
        cur_mfe_from_p_mae = 0.0
        reclaim_ratio = 0.0
        overlap_ratio = 0.0
        
    # Family D
    hist = snap['mfe_history']
    def get_past_mfe(lb_sec):
        target_ts = ck_ts - int(lb_sec * 1e9)
        if target_ts < s_ts:
            return 0.0
        past_m = start_p
        for b_ts, b_mfe, b_c in hist:
            if b_ts <= target_ts:
                past_m = b_mfe
            else:
                break
        return max(0.0, d * (past_m - start_p) / atr)
        
    mfe_gain_30s = max(0.0, max_mfe_atr - get_past_mfe(30))
    mfe_gain_60s = max(0.0, max_mfe_atr - get_past_mfe(60))
    mfe_gain_180s = max(0.0, max_mfe_atr - get_past_mfe(180))
    
    exp_rate_min = max_mfe_atr / max(age_sec / 60.0, 1.0 / 60.0)
    recent_exp_30s = mfe_gain_30s / 0.5
    recent_exp_60s = mfe_gain_60s / 1.0
    recent_exp_180s = mfe_gain_180s / 3.0
    
    if len(hist) > 1:
        net_disp = abs(d * (snap['last_close_price'] - start_p))
        path_len = sum(abs(hist[i][2] - hist[i-1][2]) for i in range(1, len(hist)))
        prog_eff = min(1.0, max(0.0, net_disp / max(path_len, 1e-4)))
    else:
        prog_eff = 1.0
        
    def get_time_near(lb_sec):
        target_ts = ck_ts - int(lb_sec * 1e9)
        rel = [b for b in hist if b[0] >= target_ts]
        if not rel:
            return 1.0
        near = sum(1 for b in rel if abs(b[2] - b[1]) <= 0.25 * atr)
        return near / len(rel)
        
    t_near_60 = get_time_near(60)
    t_near_180 = get_time_near(180)
    t_near_300 = get_time_near(300)
    failed_att = float(snap['failed_new_extreme_attempt_count'])
    
    return {
        f'regime_age_sec__tf_{tf}': age_sec,
        f'regime_max_mfe_atr__tf_{tf}': max_mfe_atr,
        f'regime_max_mae_atr__tf_{tf}': max_mae_atr,
        f'regime_total_range_atr__tf_{tf}': total_range_atr,
        f'regime_current_displacement_atr__tf_{tf}': cur_disp_atr,
        f'regime_distance_from_mfe_atr__tf_{tf}': dist_mfe_atr,
        f'regime_distance_from_mae_atr__tf_{tf}': dist_mae_atr,
        f'regime_time_since_mfe_sec__tf_{tf}': time_since_mfe_sec,
        f'regime_time_since_mae_sec__tf_{tf}': time_since_mae_sec,
        f'regime_new_extreme_count__tf_{tf}': new_ext_count,
        
        f'prior_regime_duration_sec__tf_{tf}': p_dur_sec,
        f'prior_regime_max_mfe_atr__tf_{tf}': p_mfe_atr,
        f'prior_regime_max_mae_atr__tf_{tf}': p_mae_atr,
        f'prior_regime_total_range_atr__tf_{tf}': p_range_atr,
        f'prior_regime_mfe_to_mae_range_atr__tf_{tf}': p_mfe_mae_range_atr,
        
        f'current_regime_start_from_prior_mfe_atr__tf_{tf}': start_from_p_mfe,
        f'current_regime_start_from_prior_mae_atr__tf_{tf}': start_from_p_mae,
        f'current_price_from_prior_mfe_atr__tf_{tf}': price_from_p_mfe,
        f'current_price_from_prior_mae_atr__tf_{tf}': price_from_p_mae,
        f'current_max_mfe_from_prior_regime_mfe_atr__tf_{tf}': cur_mfe_from_p_mfe,
        f'current_max_mfe_from_prior_regime_mae_atr__tf_{tf}': cur_mfe_from_p_mae,
        f'prior_regime_range_reclaim_ratio__tf_{tf}': reclaim_ratio,
        f'prior_regime_range_overlap_ratio__tf_{tf}': overlap_ratio,
        
        f'regime_mfe_gain_30s_atr__tf_{tf}': mfe_gain_30s,
        f'regime_mfe_gain_60s_atr__tf_{tf}': mfe_gain_60s,
        f'regime_mfe_gain_180s_atr__tf_{tf}': mfe_gain_180s,
        f'regime_expansion_rate_atr_min__tf_{tf}': exp_rate_min,
        f'regime_recent_expansion_rate_30s_atr_min__tf_{tf}': recent_exp_30s,
        f'regime_recent_expansion_rate_60s_atr_min__tf_{tf}': recent_exp_60s,
        f'regime_recent_expansion_rate_180s_atr_min__tf_{tf}': recent_exp_180s,
        f'regime_progress_efficiency__tf_{tf}': prog_eff,
        f'time_near_regime_extreme_60s_ratio__tf_{tf}': t_near_60,
        f'time_near_regime_extreme_180s_ratio__tf_{tf}': t_near_180,
        f'time_near_regime_extreme_300s_ratio__tf_{tf}': t_near_300,
        f'failed_new_extreme_attempt_count__tf_{tf}': failed_att,
    }

# Benchmark extracting for all Jan checkpoints
t_start = time.time()
rows = []
for idx, r in jan_ck.iterrows():
    ck_ts = r['checkpoint_ts']
    ck_p = r['checkpoint_price']
    row_feat = {'checkpoint_ts': ck_ts, 'regime_id': r['regime_id']}
    
    tf_dirs = []
    tf_mfes = []
    tf_reclaims = []
    tf_disps = []
    
    for tf_name in ['30s', '1m', '5m', '1h']:
        c_ts_arr, snaps = tf_snapshots[tf_name]
        pos = np.searchsorted(c_ts_arr, ck_ts, side='right') - 1
        if pos >= 0:
            s = snaps[pos]
            feat = extract_tf_features(s, tf_name, ck_ts, ck_p)
            row_feat.update(feat)
            tf_dirs.append(s['direction'])
            tf_mfes.append(feat[f'regime_max_mfe_atr__tf_{tf_name}'])
            tf_reclaims.append(feat[f'prior_regime_range_reclaim_ratio__tf_{tf_name}'])
            tf_disps.append(1 if feat[f'current_price_from_prior_mfe_atr__tf_{tf_name}'] > 0 else 0)
        else:
            tf_dirs.append(0)
            tf_mfes.append(0.0)
            tf_reclaims.append(0.0)
            tf_disps.append(0)
            
    # Family F: MTF Structural Alignment
    h050_dir = r['direction']
    row_feat['mtf_regime_direction_agreement_count'] = float(sum(1 for d in tf_dirs if d == h050_dir))
    row_feat['mtf_regime_direction_signed_sum'] = float(sum(1 if d == h050_dir else -1 for d in tf_dirs))
    row_feat['mtf_prior_mfe_displacement_count'] = float(sum(tf_disps))
    row_feat['mtf_prior_range_reclaim_mean'] = float(np.mean(tf_reclaims))
    row_feat['mtf_current_regime_mfe_mean_atr'] = float(np.mean(tf_mfes))
    
    rows.append(row_feat)

print(f'Extracted MTF features for {len(rows)} checkpoints in {time.time()-t_start:.3f}s')
df_res = pd.DataFrame(rows)
print('Result shape:', df_res.shape)
print('Sample columns:', df_res.columns.tolist()[:15])
print('Sample values for first row:')
for col in df_res.columns[:10]:
    print(f'  {col}: {df_res[col].iloc[0]}')
