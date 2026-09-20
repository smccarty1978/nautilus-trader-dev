import os
import sys
import time
import math
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT = Path(r'c:/Users/Scott McCarty/Projects/Nautilus Trader')
sys.path.insert(0, str(REPO_ROOT))

from features.trackers.regime_dual_ema import DualEmaRegimeTracker

def process_year(year_label, raw_parquet_path):
    print(f"\n==========================================")
    print(f"Processing Year: {year_label}")
    print(f"Reading: {raw_parquet_path}")
    print(f"==========================================")
    t0 = time.time()
    
    df_1s = pd.read_parquet(raw_parquet_path, columns=['open', 'high', 'low', 'close', 'volume'])
    print(f"Loaded {len(df_1s):,} 1s bars in {time.time()-t0:.2f}s")
    
    # Resample to 1m
    t_res = time.time()
    b_1m = df_1s.resample('1min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    dur_ns = int(60 * 1e9)
    close_ts_arr = b_1m.index.values.astype(np.int64) + dur_ns
    b_1m['close_ts'] = close_ts_arr
    print(f"Resampled to {len(b_1m):,} 1m bars in {time.time()-t_res:.2f}s")
    
    # Run 1m regime tracker
    t_trk = time.time()
    tracker = DualEmaRegimeTracker(timeframe='1m')
    regimes = []
    snapshots = []
    
    opens_1m = b_1m['open'].values
    highs_1m = b_1m['high'].values
    lows_1m = b_1m['low'].values
    closes_1m = b_1m['close'].values
    
    cur_reg = None
    prior_reg = None
    
    for i in range(len(b_1m)):
        c_ts = close_ts_arr[i]
        o = opens_1m[i]
        h = highs_1m[i]
        l = lows_1m[i]
        c = closes_1m[i]
        
        up = tracker.observe(h, l, c)
        cur_atr = up.atr if up.atr is not None and math.isfinite(up.atr) else 10.0
        
        if up.flipped:
            if cur_reg is not None:
                cur_reg['end_ts'] = c_ts
                cur_reg['end_close'] = c
                regimes.append(cur_reg)
                prior_reg = cur_reg.copy()
            cur_reg = {
                'regime_id': c_ts,
                'direction': up.regime,
                'start_ts': c_ts,
                'start_price': o,
                'start_atr': cur_atr,
                'mfe_price': h if up.regime == 1 else l,
                'mae_price': l if up.regime == 1 else h,
                'prior_regime': prior_reg
            }
        elif cur_reg is not None:
            if cur_reg['direction'] == 1:
                cur_reg['mfe_price'] = max(cur_reg['mfe_price'], h)
                cur_reg['mae_price'] = min(cur_reg['mae_price'], l)
            else:
                cur_reg['mfe_price'] = min(cur_reg['mfe_price'], l)
                cur_reg['mae_price'] = max(cur_reg['mae_price'], h)
                
        snap = {
            'close_ts': c_ts,
            'direction': cur_reg['direction'] if cur_reg is not None else 0,
            'start_ts': cur_reg['start_ts'] if cur_reg is not None else c_ts,
            'start_price': cur_reg['start_price'] if cur_reg is not None else c,
            'mfe_price': cur_reg['mfe_price'] if cur_reg is not None else c,
            'current_atr': cur_atr,
            'prior_regime': prior_reg.copy() if prior_reg is not None else None
        }
        snapshots.append(snap)
        
    if cur_reg is not None and 'end_ts' not in cur_reg:
        cur_reg['end_ts'] = close_ts_arr[-1]
        regimes.append(cur_reg)
        
    print(f"Tracked {len(regimes):,} regimes in {time.time()-t_trk:.2f}s")
    
    # 1m Rolling levels & ATR
    b_1m['roll_15m_high'] = b_1m['high'].rolling(15, min_periods=1).max()
    b_1m['roll_15m_low'] = b_1m['low'].rolling(15, min_periods=1).min()
    b_1m['realized_range_15m'] = b_1m['roll_15m_high'] - b_1m['roll_15m_low']
    b_1m['atr_14'] = [s['current_atr'] for s in snapshots]
    
    # Chicago time on 1s data
    idx_1s_ts = df_1s.index.values.astype(np.int64)
    opens_1s = df_1s['open'].values
    highs_1s = df_1s['high'].values
    lows_1s = df_1s['low'].values
    closes_1s = df_1s['close'].values
    
    idx_ct = df_1s.index.tz_convert('America/Chicago')
    ct_tot_mins = idx_ct.hour.values * 60 + idx_ct.minute.values
    ct_secs = idx_ct.second.values
    rth_mask = (ct_tot_mins >= 510) & (ct_tot_mins < 915)
    
    # Identify H050 checkpoints
    print("Detecting H050 checkpoints and extracting Leaf 4 features...")
    t_ck = time.time()
    h050_checkpoints = []
    
    df_1m_close_ts = b_1m['close_ts'].values
    df_1m_r15 = b_1m['realized_range_15m'].values
    df_1m_atr = b_1m['atr_14'].values
    
    reg_df = pd.DataFrame(regimes)
    for r_idx, reg in reg_df.iterrows():
        r_start = reg['start_ts']
        r_end = reg['end_ts']
        d = int(reg['direction'])
        frozen_atr = max(float(reg['start_atr']), 1e-4)
        p_prior = reg['prior_regime']
        prior_mfe_px = float(p_prior['mfe_price']) if p_prior is not None else float(reg['start_price'])
        
        p_start = np.searchsorted(idx_1s_ts, r_start, side='left')
        p_end = np.searchsorted(idx_1s_ts, r_end, side='right')
        if p_start >= p_end:
            continue
            
        r_ts = idx_1s_ts[p_start:p_end]
        r_h = highs_1s[p_start:p_end]
        r_l = lows_1s[p_start:p_end]
        r_c = closes_1s[p_start:p_end]
        r_rth = rth_mask[p_start:p_end]
        r_ct_m = ct_tot_mins[p_start:p_end]
        r_ct_s = ct_secs[p_start:p_end]
        
        running_mfe_px = r_h[0] if d == 1 else r_l[0]
        in_pullback = False
        
        for k in range(len(r_ts)):
            h_k = r_h[k]
            l_k = r_l[k]
            c_k = r_c[k]
            ts_k = r_ts[k]
            
            if d == 1:
                if h_k > running_mfe_px:
                    running_mfe_px = h_k
                    in_pullback = False
                pb_dist = running_mfe_px - c_k
            else:
                if l_k < running_mfe_px:
                    running_mfe_px = l_k
                    in_pullback = False
                pb_dist = c_k - running_mfe_px
                
            pb_depth_atr = pb_dist / frozen_atr
            if (not in_pullback) and (pb_depth_atr >= 0.50):
                in_pullback = True
                
                # Checkpoint emitted!
                # Check RTH
                if r_rth[k]:
                    min_from_rth_open = float(r_ct_m[k] - 510.0 + r_ct_s[k] / 60.0)
                    
                    # 1m bar lookup
                    p1m = np.searchsorted(df_1m_close_ts, ts_k, side='right') - 1
                    if p1m >= 0:
                        cur_1m_atr = max(df_1m_atr[p1m], 1e-4)
                        r15_val = df_1m_r15[p1m]
                        realized_range_15m_atr = r15_val / frozen_atr
                    else:
                        cur_1m_atr = frozen_atr
                        realized_range_15m_atr = 2.0
                        
                    # Distance from prior MFE
                    current_price_from_prior_mfe_atr__tf_1m = (d * (c_k - prior_mfe_px)) / cur_1m_atr
                    
                    # Leaf 4 conditions
                    c1_rth = min_from_rth_open <= 380.649994
                    c2_rr = realized_range_15m_atr <= 9.344128
                    c3_mfe = current_price_from_prior_mfe_atr__tf_1m <= 1.738367
                    is_leaf4 = c1_rth and c2_rr and c3_mfe
                    
                    h050_checkpoints.append({
                        'year': year_label,
                        'regime_id': int(reg['regime_id']),
                        'regime_start_ts': int(r_start),
                        'regime_exit_ts': int(r_end),
                        'direction': d,
                        'counter_direction': -d,
                        'checkpoint_ts': int(ts_k),
                        'checkpoint_price': float(c_k),
                        'frozen_atr': float(frozen_atr),
                        'cur_1m_atr': float(cur_1m_atr),
                        'minutes_from_rth_open': float(min_from_rth_open),
                        'realized_range_15m_atr': float(realized_range_15m_atr),
                        'current_price_from_prior_mfe_atr__tf_1m': float(current_price_from_prior_mfe_atr__tf_1m),
                        'is_leaf4': bool(is_leaf4),
                        '1s_pos': p_start + k
                    })
                    
    df_ck = pd.DataFrame(h050_checkpoints)
    print(f"Extracted {len(df_ck):,} H050 RTH checkpoints ({df_ck['is_leaf4'].sum():,} Leaf 4) in {time.time()-t_ck:.2f}s")
    return df_ck

if __name__ == '__main__':
    df_2025 = process_year('2025', REPO_ROOT / 'data/raw/NQ_v0_1s_2025.parquet')
    df_2025['dt'] = pd.to_datetime(df_2025['checkpoint_ts'], unit='ns', utc=True)
    q1_sub = df_2025[(df_2025['dt'] >= '2025-01-01') & (df_2025['dt'] < '2025-04-01') & df_2025['is_leaf4']]
    print(f"\n[Validation] Extracted Leaf 4 trades in 2025 Q1: {len(q1_sub)}")
    
    p_auth = REPO_ROOT / 'studies/nq_leaf4_runtime_validation_and_distribution_diagnostic/runtime_trade_ledger.parquet'
    df_auth = pd.read_parquet(p_auth)
    df_auth['dt'] = pd.to_datetime(df_auth['checkpoint_ts'], unit='ns', utc=True)
    auth_q1 = df_auth[(df_auth['dt'] >= '2025-01-01') & (df_auth['dt'] < '2025-04-01')]
    print(f"[Validation] Authoritative Leaf 4 trades in 2025 Q1: {len(auth_q1)}")
    matches = q1_sub['checkpoint_ts'].isin(auth_q1['checkpoint_ts']).sum()
    print(f"[Validation] Checkpoint TS matches: {matches} / {len(auth_q1)}")
