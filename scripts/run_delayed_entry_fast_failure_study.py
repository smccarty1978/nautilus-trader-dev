"""
run_delayed_entry_fast_failure_study.py

Bounded delayed-entry and fast-failure observational study for the NQ H050 counter-regime research lineage.
Population: 2023-2024 TRAIN (N=21,493 H050 checkpoints).
Checkpoints: T0, T30, T60, T120, T180, T300.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import time
import math
import json
import hashlib
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
import lightgbm as lgb
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

# Import single timeframe tracker logic from existing audited script
from scripts.build_mtf_regime_context_features import SingleTimeframeRegimeTracker, extract_tf_features

STUDY_DIR = REPO_ROOT / 'studies/nq_h050_delayed_entry_fast_failure'
RESULTS_DIR = STUDY_DIR / 'results'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# 1. Main Execution Engine
# -----------------------------------------------------------------------------
def run_study():
    t_start = time.time()
    print("=" * 80)
    print("NQ H050 Bounded Delayed-Entry & Fast-Failure Observational Study")
    print("=" * 80)

    # 1. Load historical H050 checkpoint ledger and C1 exit ledger
    ck_path = REPO_ROOT / 'studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet'
    exit_path = REPO_ROOT / 'studies/nq_h050_to_opposing_h050_exit_lifecycle/results/counter_h0501_exit_ledger.parquet'

    print(f"Loading checkpoint ledger: {ck_path}")
    ck_df = pd.read_parquet(ck_path)
    exit_df = pd.read_parquet(exit_path)

    train_ck = ck_df[ck_df['split'] == 'TRAIN'].copy().reset_index(drop=True)
    train_exit = exit_df[exit_df['split'] == 'TRAIN'].copy().reset_index(drop=True)

    N_total = len(train_ck)
    print(f"Loaded {N_total} TRAIN H050 checkpoints (2023: {(train_ck['year']=='2023').sum()}, 2024: {(train_ck['year']=='2024').sum()})")

    # Load frozen M4 models
    m4_models = {}
    for i in range(3):
        m_path = REPO_ROOT / f'studies/nq_h050_m4_runtime_recovery/results/m4_head{i}_model.txt'
        m4_models[i] = lgb.Booster(model_file=str(m_path))
    print("Loaded 3 frozen M4 LightGBM models")

    with open(REPO_ROOT / 'studies/nq_h050_m4_runtime_recovery/results/ordered_17_feature_manifest.json') as f:
        m4_feature_names = [x['feature_name'] for x in json.load(f)]

    # Horizons to evaluate
    horizons_sec = [0, 30, 60, 120, 180, 300]
    
    # Census tracking
    census_data = {
        'initial_h050_count': N_total,
        'horizons': {}
    }

    # Data collection containers
    observation_records = []
    fast_failure_records = {15: [], 30: [], 60: []}

    # Process year by year for memory and processing efficiency
    for year in ['2023', '2024']:
        t_yr = time.time()
        print(f"\n" + "=" * 50)
        print(f"Processing Year {year} ...")
        print("=" * 50)

        mask_yr = (train_ck['year'] == year)
        yr_ck = train_ck[mask_yr].copy().reset_index(drop=True)
        yr_exit = train_exit[mask_yr].copy().reset_index(drop=True)
        N_yr = len(yr_ck)
        print(f"Year {year} H050 count: {N_yr}")

        # Load raw 1s bars
        raw_path = REPO_ROOT / f'data/raw/NQ_v0_1s_{year}.parquet'
        print(f"Loading raw 1s data from: {raw_path}")
        df_1s = pd.read_parquet(raw_path, columns=['open', 'high', 'low', 'close', 'volume'])
        print(f"Loaded {len(df_1s)} 1s rows in {time.time()-t_yr:.2f}s")

        # Fast timestamp indexing
        # Note: df_1s.index is DatetimeIndex, close_ts is ts_event + 1e9 ns
        ts_1s_arr = df_1s.index.values.astype(np.int64) + 1_000_000_000
        opens_1s = df_1s['open'].values
        highs_1s = df_1s['high'].values
        lows_1s = df_1s['low'].values
        closes_1s = df_1s['close'].values

        # Resample to 30s, 1m, 5m, 1h
        print("Resampling and tracking 30s, 1m, 5m, 1h completed bar regimes...")
        res_bars = {}
        tf_snapshots = {}
        for tf_name, rule in [('30s', '30s'), ('1m', '1min'), ('5m', '5min'), ('1h', '1h')]:
            b = df_1s.resample(rule).agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
            dur_ns = int(pd.Timedelta(rule).total_seconds() * 1e9)
            close_ts_arr = b.index.values.astype(np.int64) + dur_ns
            b['close_ts'] = close_ts_arr
            res_bars[tf_name] = b

            tracker = SingleTimeframeRegimeTracker(timeframe=tf_name)
            snaps = []
            c_ts = close_ts_arr
            o = b['open'].values
            h = b['high'].values
            l = b['low'].values
            c = b['close'].values
            for i in range(len(b)):
                snaps.append(tracker.on_bar(c_ts[i], o[i], h[i], l[i], c[i]))
            tf_snapshots[tf_name] = (close_ts_arr, snaps)

        # 1m bar level & volatility lookups
        df_1m = res_bars['1m'].copy()
        df_1m_close_ts = df_1m['close_ts'].values
        idx_ct = df_1m.index.tz_convert('America/Chicago')
        df_1m['ct_date'] = idx_ct.date
        df_1m['ct_minute'] = idx_ct.hour * 60 + idx_ct.minute

        session_dates = []
        for dt in idx_ct:
            if dt.hour >= 17:
                session_dates.append((dt + pd.Timedelta(days=1)).date())
            else:
                session_dates.append(dt.date())
        df_1m['session_date'] = session_dates

        df_1m['roll_15m_high'] = df_1m['high'].rolling(15, min_periods=1).max()
        df_1m['roll_15m_low'] = df_1m['low'].rolling(15, min_periods=1).min()
        df_1m['roll_30m_high'] = df_1m['high'].rolling(30, min_periods=1).max()
        df_1m['roll_30m_low'] = df_1m['low'].rolling(30, min_periods=1).min()
        df_1m['roll_60m_high'] = df_1m['high'].rolling(60, min_periods=1).max()
        df_1m['roll_60m_low'] = df_1m['low'].rolling(60, min_periods=1).min()

        df_1m['realized_range_1m'] = df_1m['high'] - df_1m['low']
        df_1m['realized_range_5m'] = df_1m['high'].rolling(5, min_periods=1).max() - df_1m['low'].rolling(5, min_periods=1).min()
        df_1m['realized_range_15m'] = df_1m['high'].rolling(15, min_periods=1).max() - df_1m['low'].rolling(15, min_periods=1).min()

        tr_1m = np.maximum(df_1m['high'] - df_1m['low'],
                           np.maximum(abs(df_1m['high'] - df_1m['close'].shift(1).fillna(df_1m['close'])),
                                      abs(df_1m['low'] - df_1m['close'].shift(1).fillna(df_1m['close']))))
        df_1m['atr_200'] = tr_1m.ewm(alpha=1.0/200.0, adjust=False).mean()
        atr_1m_arr = np.array([s['current_atr'] for s in tf_snapshots['1m'][1]])
        df_1m['atr_14'] = atr_1m_arr
        df_1m['atr_ratio_short_long'] = df_1m['atr_14'] / np.maximum(df_1m['atr_200'], 1e-4)

        # Precompute session price levels
        session_levels = {}
        grouped = df_1m.groupby('session_date')
        sorted_sess_dates = sorted(grouped.groups.keys())
        prior_rth = None
        for s_date in sorted_sess_dates:
            s_df = grouped.get_group(s_date)
            overnight_bars = s_df[(s_df['ct_minute'] >= 1020) | (s_df['ct_minute'] < 510)]
            on_hi = overnight_bars['high'].max() if len(overnight_bars) > 0 else None
            on_lo = overnight_bars['low'].min() if len(overnight_bars) > 0 else None

            rth_bars = s_df[(s_df['ct_minute'] >= 510) & (s_df['ct_minute'] < 915)]
            if len(rth_bars) > 0:
                cur_rth = {
                    'open': rth_bars['open'].iloc[0],
                    'high': rth_bars['high'].max(),
                    'low': rth_bars['low'].min(),
                    'close': rth_bars['close'].iloc[-1],
                }
            else:
                cur_rth = None

            or30_bars = s_df[(s_df['ct_minute'] >= 510) & (s_df['ct_minute'] < 540)]
            or30_hi = or30_bars['high'].max() if len(or30_bars) >= 20 else None
            or30_lo = or30_bars['low'].min() if len(or30_bars) >= 20 else None

            session_levels[s_date] = {
                'prior_rth': prior_rth.copy() if prior_rth else None,
                'overnight_high': on_hi,
                'overnight_low': on_lo,
                'or30_high': or30_hi,
                'or30_low': or30_lo,
            }
            if cur_rth is not None:
                prior_rth = cur_rth

        print(f"Precomputations complete. Iterating through {N_yr} events across 6 checkpoint horizons...")
        t_loop = time.time()

        # Iterate through events
        for idx in range(N_yr):
            r_ck = yr_ck.iloc[idx]
            r_ex = yr_exit.iloc[idx]

            t0_ts = int(r_ck['checkpoint_ts'])
            regime_id = int(r_ck['regime_id'])
            regime_start_ts = int(r_ck['regime_start_ts'])
            regime_exit_ts = int(r_ck['regime_exit_ts'])
            direction = int(r_ck['direction'])
            counter_direction = -direction
            frozen_atr = float(r_ck['frozen_atr'])
            pre_pb_mfe_pts = float(r_ck['pre_pullback_max_mfe_points'])
            pre_pb_mfe_atr = float(r_ck['pre_pullback_max_mfe_atr'])
            regime_entry_px = float(r_ck['entry_price'])
            
            # C1 and R2 exit references
            c1_exit_ts = int(r_ex['c1_exit_ts'])
            c1_exit_px = float(r_ex['c1_exit_price'])
            c1_exit_source = str(r_ex['c1_exit_source'])
            r2_exit_ts = int(r_ex['r1_end_ts'])
            r2_exit_px = float(r_ex['price_exit'])

            # Eventual final regime max MFE (over whole regime up to regime_exit_ts)
            final_regime_max_mfe_atr = float(r_ck['final_regime_max_mfe_atr'])

            # Locate T0 bar index in 1s data
            idx_t0 = np.searchsorted(ts_1s_arr, t0_ts)
            if idx_t0 >= len(ts_1s_arr) or ts_1s_arr[idx_t0] != t0_ts:
                # If exact match not at idx_t0, search nearest causal bar
                idx_t0 = max(0, min(len(ts_1s_arr) - 1, idx_t0))
            
            t0_price = closes_1s[idx_t0]
            
            # T0 initial M4 features & scores
            t0_m4_feats = [float(r_ck[col]) if col in r_ck else 0.0 for col in m4_feature_names]
            t0_X = np.array(t0_m4_feats).reshape(1, -1)
            t0_p0 = float(m4_models[0].predict(t0_X)[0])
            t0_p1 = float(m4_models[1].predict(t0_X)[0])
            t0_p2 = float(m4_models[2].predict(t0_X)[0])
            t0_m4_score = t0_p0 - 0.5 * t0_p1 - 1.0 * t0_p2

            # Pre-pullback peak price at T0
            if direction == 1:
                t0_peak_price = regime_entry_px + pre_pb_mfe_pts
            else:
                t0_peak_price = regime_entry_px - pre_pb_mfe_pts

            # Evaluate each horizon
            for h_sec in horizons_sec:
                h_ns = h_sec * 1_000_000_000
                ck_ts = t0_ts + h_ns
                horizon_name = f"T{h_sec}"

                # Check eligibility
                if ck_ts > regime_exit_ts:
                    # Regime already ended before checkpoint
                    continue
                
                idx_ck = np.searchsorted(ts_1s_arr, ck_ts)
                if idx_ck >= len(ts_1s_arr):
                    # Exceeded bar array (end of dataset)
                    continue
                
                ck_price = closes_1s[idx_ck]

                # -------------------------------------------------------------
                # A. Path evolution in window [T0, ck_ts]
                # -------------------------------------------------------------
                if h_sec == 0:
                    bars_window = idx_ck - idx_t0 + 1
                    slice_highs = highs_1s[idx_t0:idx_ck+1]
                    slice_lows = lows_1s[idx_t0:idx_ck+1]
                    slice_closes = closes_1s[idx_t0:idx_ck+1]
                else:
                    slice_highs = highs_1s[idx_t0:idx_ck+1]
                    slice_lows = lows_1s[idx_t0:idx_ck+1]
                    slice_closes = closes_1s[idx_t0:idx_ck+1]
                    bars_window = len(slice_closes)

                # Running extreme up to ck_ts
                if direction == 1:
                    running_max_hi = np.max(slice_highs)
                    running_peak_price = max(t0_peak_price, running_max_hi)
                    has_new_extreme = int(running_max_hi > t0_peak_price + 1e-4)
                    new_extreme_mag_pts = max(0.0, running_peak_price - t0_peak_price)
                    cur_pb_depth_pts = max(0.0, running_peak_price - ck_price)
                    deepest_pb_pts = max(0.0, running_peak_price - np.min(slice_lows))
                else:
                    running_min_lo = np.min(slice_lows)
                    running_peak_price = min(t0_peak_price, running_min_lo)
                    has_new_extreme = int(running_min_lo < t0_peak_price - 1e-4)
                    new_extreme_mag_pts = max(0.0, t0_peak_price - running_peak_price)
                    cur_pb_depth_pts = max(0.0, ck_price - running_peak_price)
                    deepest_pb_pts = max(0.0, np.max(slice_highs) - running_peak_price)

                cur_pb_depth_atr = cur_pb_depth_pts / max(frozen_atr, 1e-4)
                deepest_pb_atr = deepest_pb_pts / max(frozen_atr, 1e-4)
                rebound_from_deepest_atr = max(0.0, deepest_pb_atr - cur_pb_depth_atr)

                # Counter excursion & adverse continuation in [T0, ck_ts]
                if direction == 1: # counter is SHORT
                    counter_mfe_pts = max(0.0, t0_price - np.min(slice_lows))
                    incumbent_mae_pts = max(0.0, np.max(slice_highs) - t0_price)
                    price_improvement_pts = t0_price - ck_price # positive if ck_price < t0_price (better short)
                    directional_disp_pts = t0_price - ck_price
                else: # counter is LONG
                    counter_mfe_pts = max(0.0, np.max(slice_highs) - t0_price)
                    incumbent_mae_pts = max(0.0, t0_price - np.min(slice_lows))
                    price_improvement_pts = ck_price - t0_price # positive if ck_price > t0_price (wait, if long, lower is better!)
                    # For LONG counter-regime: buying lower is better price!
                    price_improvement_pts = t0_price - ck_price # if t0=100, ck=95, bought 5 pts cheaper -> +5 pts improvement!
                    directional_disp_pts = ck_price - t0_price

                counter_mfe_atr = counter_mfe_pts / max(frozen_atr, 1e-4)
                incumbent_mae_atr = incumbent_mae_pts / max(frozen_atr, 1e-4)
                price_improvement_atr = price_improvement_pts / max(frozen_atr, 1e-4)
                price_improvement_dollars = price_improvement_pts * 20.0

                hl_range_pts = np.max(slice_highs) - np.min(slice_lows)
                hl_range_atr = hl_range_pts / max(frozen_atr, 1e-4)

                # Path bars & efficiency
                diffs = np.diff(slice_closes) if len(slice_closes) > 1 else np.array([0.0])
                total_abs_diff = np.sum(np.abs(diffs))
                path_eff = min(1.0, max(0.0, abs(ck_price - t0_price) / max(total_abs_diff, 1e-4)))
                realized_vol_atr = (np.std(diffs) if len(diffs) > 1 else 0.0) / max(frozen_atr, 1e-4)

                counter_bars = int(np.sum(diffs * counter_direction > 0))
                incumbent_bars = int(np.sum(diffs * direction > 0))

                # Runs
                max_c_run, max_i_run, cur_c_run, cur_i_run = 0, 0, 0, 0
                for d_val in diffs:
                    if d_val * counter_direction > 0:
                        cur_c_run += 1
                        cur_i_run = 0
                        if cur_c_run > max_c_run: max_c_run = cur_c_run
                    elif d_val * direction > 0:
                        cur_i_run += 1
                        cur_c_run = 0
                        if cur_i_run > max_i_run: max_i_run = cur_i_run
                    else:
                        cur_c_run = 0
                        cur_i_run = 0

                # Extreme behavior
                new_extreme_count = 0
                last_ext_idx = idx_t0
                if direction == 1:
                    cur_peak = t0_peak_price
                    for b_i in range(len(slice_highs)):
                        if slice_highs[b_i] > cur_peak:
                            new_extreme_count += 1
                            cur_peak = slice_highs[b_i]
                            last_ext_idx = idx_t0 + b_i
                else:
                    cur_peak = t0_peak_price
                    for b_i in range(len(slice_lows)):
                        if slice_lows[b_i] < cur_peak:
                            new_extreme_count += 1
                            cur_peak = slice_lows[b_i]
                            last_ext_idx = idx_t0 + b_i

                sec_since_last_ext = max(0.0, (ck_ts - ts_1s_arr[last_ext_idx]) / 1e9)
                sec_without_new_ext = float(h_sec) if new_extreme_count == 0 else 0.0

                # Pullback duration and velocity at ck_ts
                cur_pb_dur_sec = max(1.0, sec_since_last_ext) if new_extreme_count > 0 else (float(r_ck['pullback_duration_sec']) + float(h_sec))
                cur_pb_vel = cur_pb_depth_atr / max(cur_pb_dur_sec, 1.0)
                cur_pb_eff = min(1.0, max(0.0, cur_pb_depth_pts / max(total_abs_diff, 1e-4)))
                pb_depth_increasing = int(cur_pb_depth_atr > float(r_ck['pullback_depth_atr']))
                delta_pb_depth = cur_pb_depth_atr - float(r_ck['pullback_depth_atr'])
                delta_pb_vel = cur_pb_vel - float(r_ck['pullback_velocity_atr_sec'])

                # -------------------------------------------------------------
                # B. M4 dynamic rescoring at ck_ts
                # -------------------------------------------------------------
                cur_regime_age_sec = max(0.0, (ck_ts - regime_start_ts) / 1e9)
                cur_pre_pb_mfe_atr = max(0.0, direction * (running_peak_price - regime_entry_px) / max(frozen_atr, 1e-4))
                cur_pb_depth_vs_mfe = cur_pb_depth_atr / max(cur_pre_pb_mfe_atr, 0.001)
                cur_pb_dur_vs_age = cur_pb_dur_sec / max(cur_regime_age_sec, 1.0)
                cur_exp_rate = cur_pre_pb_mfe_atr / max((cur_regime_age_sec - cur_pb_dur_sec) / 60.0, 0.1)

                # Assemble updated 17 features
                m4_cur_feats = [
                    cur_pb_depth_atr,
                    cur_pb_dur_sec,
                    cur_pb_eff,
                    cur_pb_vel,
                    cur_pre_pb_mfe_atr,
                    int(r_ck['pullback_ordinal']) + (1 if new_extreme_count > 0 else 0),
                    cur_regime_age_sec,
                    int(r_ck['previous_pullbacks_count']) + (1 if new_extreme_count > 0 else 0),
                    max(float(r_ck['previous_pullbacks_max_depth_atr']), cur_pb_depth_atr if new_extreme_count > 0 else 0.0),
                    float(r_ck['previous_pullbacks_avg_duration_sec']),
                    cur_pb_depth_vs_mfe,
                    cur_pb_dur_vs_age,
                    cur_exp_rate,
                    1 if (int(r_ck['previous_pullbacks_count']) + (1 if new_extreme_count > 0 else 0)) > 0 else 0,
                    float(r_ck['previous_max_depth_ratio']),
                    frozen_atr,
                    1 if direction == 1 else 0
                ]
                cur_X = np.array(m4_cur_feats).reshape(1, -1)
                cur_p0 = float(m4_models[0].predict(cur_X)[0])
                cur_p1 = float(m4_models[1].predict(cur_X)[0])
                cur_p2 = float(m4_models[2].predict(cur_X)[0])
                cur_m4_score = cur_p0 - 0.5 * cur_p1 - 1.0 * cur_p2
                delta_m4_score = cur_m4_score - t0_m4_score

                # -------------------------------------------------------------
                # C. Recalculated remaining MFE targets from ck_ts
                # -------------------------------------------------------------
                # Eventual regime max MFE from regime entry in ATR
                # Remaining incumbent excursion beyond running_peak_price
                if direction == 1:
                    final_peak_px = regime_entry_px + final_regime_max_mfe_atr * frozen_atr
                    rem_mfe_pts = max(0.0, final_peak_px - running_peak_price)
                else:
                    final_peak_px = regime_entry_px - final_regime_max_mfe_atr * frozen_atr
                    rem_mfe_pts = max(0.0, running_peak_price - final_peak_px)
                
                rem_mfe_atr_from_t = rem_mfe_pts / max(frozen_atr, 1e-4)
                target_terminal_0p25a = int(rem_mfe_atr_from_t < 0.25)
                target_gte_0p5a = int(rem_mfe_atr_from_t >= 0.50)
                target_gte_1p0a = int(rem_mfe_atr_from_t >= 1.00)
                target_gte_2p0a = int(rem_mfe_atr_from_t >= 2.00)

                # -------------------------------------------------------------
                # D. Delayed-entry economics (C1 & R2)
                # -------------------------------------------------------------
                # Delayed counter-regime entry at ck_price
                # C1 net pnl
                c1_pnl_pts = counter_direction * (c1_exit_px - ck_price) - 0.75
                c1_pnl_dollars = c1_pnl_pts * 20.0
                c1_pnl_atr = c1_pnl_pts / max(frozen_atr, 1e-4)

                # R2 net pnl
                r2_pnl_pts = counter_direction * (r2_exit_px - ck_price) - 0.75
                r2_pnl_dollars = r2_pnl_pts * 20.0
                r2_pnl_atr = r2_pnl_pts / max(frozen_atr, 1e-4)

                # Post-entry excursion from ck_ts until C1 exit
                idx_exit = np.searchsorted(ts_1s_arr, c1_exit_ts)
                idx_exit = max(idx_ck, min(len(ts_1s_arr) - 1, idx_exit))
                trade_highs = highs_1s[idx_ck:idx_exit+1]
                trade_lows = lows_1s[idx_ck:idx_exit+1]

                if direction == 1: # counter is SHORT
                    post_mfe_pts = max(0.0, ck_price - np.min(trade_lows))
                    post_mae_pts = max(0.0, np.max(trade_highs) - ck_price)
                else: # counter is LONG
                    post_mfe_pts = max(0.0, np.max(trade_highs) - ck_price)
                    post_mae_pts = max(0.0, ck_price - np.min(trade_lows))

                post_mfe_atr = post_mfe_pts / max(frozen_atr, 1e-4)
                post_mae_atr = post_mae_pts / max(frozen_atr, 1e-4)

                is_catastrophic = int(c1_pnl_atr <= -3.00)
                is_severe_loss = int(c1_pnl_atr <= -2.00)
                is_winner_1a = int(c1_pnl_atr >= 1.00)
                is_winner_2a = int(c1_pnl_atr >= 2.00)
                is_winner_3a = int(c1_pnl_atr >= 3.00)

                # -------------------------------------------------------------
                # E. Context features from 30s, 1m, 5m, 1h regime trackers
                # -------------------------------------------------------------
                ctx_feats = {}
                for tf_name in ['30s', '1m', '5m', '1h']:
                    c_ts_arr, snaps = tf_snapshots[tf_name]
                    # Find completed bar strictly closed at or before ck_ts
                    idx_tf = np.searchsorted(c_ts_arr, ck_ts, side='right') - 1
                    if idx_tf >= 0:
                        snap = snaps[idx_tf]
                    else:
                        snap = snaps[0]
                    tf_f = extract_tf_features(snap, tf_name, ck_ts, ck_price)
                    ctx_feats.update(tf_f)

                # Agreement across 4 timeframes with counter-direction
                dir_30s = ctx_feats.get('regime_direction__tf_30s', 0)
                dir_1m = ctx_feats.get('regime_direction__tf_1m', 0)
                dir_5m = ctx_feats.get('regime_direction__tf_5m', 0)
                dir_1h = ctx_feats.get('regime_direction__tf_1h', 0)
                agreement_count = sum(1 for d in [dir_30s, dir_1m, dir_5m, dir_1h] if d == counter_direction)

                # Price level features from 1m
                idx_1m = np.searchsorted(df_1m_close_ts, ck_ts, side='right') - 1
                idx_1m = max(0, min(len(df_1m) - 1, idx_1m))
                row_1m = df_1m.iloc[idx_1m]
                s_date = row_1m['session_date']
                s_levels = session_levels.get(s_date, {})
                cur_1m_atr = float(row_1m['atr_14'])
                atr_ratio = float(row_1m['atr_ratio_short_long'])

                # Record observation
                obs_row = {
                    'trade_id': f"{year}_{regime_id}_{t0_ts}_{horizon_name}",
                    'parent_h050_id': f"{year}_{regime_id}_{t0_ts}",
                    'year': year,
                    'regime_id': regime_id,
                    't0_ts': t0_ts,
                    'checkpoint_ts': ck_ts,
                    'horizon_sec': h_sec,
                    'horizon_name': horizon_name,
                    'direction': direction,
                    'counter_direction': counter_direction,
                    'direction_is_long': 1 if direction == 1 else 0,
                    'entry_price': ck_price,
                    't0_price': t0_price,
                    'frozen_atr': frozen_atr,
                    'current_1m_atr': cur_1m_atr,
                    'atr_ratio_short_long': atr_ratio,
                    # Dynamic M4 features
                    'm4_score_at_h050': t0_m4_score,
                    'm4_score_current': cur_m4_score,
                    'delta_m4_score_from_h050': delta_m4_score,
                    'm4_p0_current': cur_p0,
                    'm4_p1_current': cur_p1,
                    'm4_p2_current': cur_p2,
                    'delta_m4_p0': cur_p0 - t0_p0,
                    'delta_m4_p1': cur_p1 - t0_p1,
                    'delta_m4_p2': cur_p2 - t0_p2,
                    # Path evolution features
                    'price_displacement_from_h050_atr': directional_disp_pts / max(frozen_atr, 1e-4),
                    'path_max_counter_mfe_atr': counter_mfe_atr,
                    'path_max_incumbent_mae_atr': incumbent_mae_atr,
                    'path_high_low_range_atr': hl_range_atr,
                    'path_efficiency_since_h050': path_eff,
                    'path_realized_vol_since_h050': realized_vol_atr,
                    'path_counter_bars_count': counter_bars,
                    'path_incumbent_bars_count': incumbent_bars,
                    'path_longest_counter_run_bars': max_c_run,
                    'path_longest_incumbent_run_bars': max_i_run,
                    'has_new_incumbent_extreme_since_h050': has_new_extreme,
                    'new_incumbent_extreme_count_since_h050': new_extreme_count,
                    'additional_incumbent_mfe_since_h050_atr': new_extreme_mag_pts / max(frozen_atr, 1e-4),
                    'seconds_since_most_recent_incumbent_extreme': sec_since_last_ext,
                    'seconds_since_h050_without_new_extreme': sec_without_new_ext,
                    'current_pullback_depth_atr': cur_pb_depth_atr,
                    'deepest_pullback_depth_since_h050_atr': deepest_pb_atr,
                    'pullback_rebound_from_deepest_atr': rebound_from_deepest_atr,
                    'current_pullback_velocity_atr_sec': cur_pb_vel,
                    'current_pullback_efficiency': cur_pb_eff,
                    'current_pullback_duration_sec': cur_pb_dur_sec,
                    'pullback_depth_increasing': pb_depth_increasing,
                    'delta_pullback_depth_from_h050_atr': delta_pb_depth,
                    'delta_pullback_velocity_from_h050': delta_pb_vel,
                    'mtf_counter_agreement_count': agreement_count,
                    # Targets recalculated from ck_ts
                    'remaining_incumbent_mfe_atr_from_t': rem_mfe_atr_from_t,
                    'terminal_mfe_within_0p25a_from_t': target_terminal_0p25a,
                    'remaining_mfe_gte_0p5a_from_t': target_gte_0p5a,
                    'remaining_mfe_gte_1p0a_from_t': target_gte_1p0a,
                    'remaining_mfe_gte_2p0a_from_t': target_gte_2p0a,
                    # Economics
                    'c1_exit_price': c1_exit_px,
                    'c1_exit_ts': c1_exit_ts,
                    'c1_exit_source': c1_exit_source,
                    'c1_net_pnl_pts': c1_pnl_pts,
                    'c1_net_pnl_dollars': c1_pnl_dollars,
                    'c1_net_pnl_atr': c1_pnl_atr,
                    'r2_exit_price': r2_exit_px,
                    'r2_exit_ts': r2_exit_ts,
                    'r2_net_pnl_pts': r2_pnl_pts,
                    'r2_net_pnl_dollars': r2_pnl_dollars,
                    'r2_net_pnl_atr': r2_pnl_atr,
                    'post_entry_mfe_atr': post_mfe_atr,
                    'post_entry_mae_atr': post_mae_atr,
                    'is_catastrophic_loss': is_catastrophic,
                    'is_severe_loss': is_severe_loss,
                    'is_winner_1a': is_winner_1a,
                    'is_winner_2a': is_winner_2a,
                    'is_winner_3a': is_winner_3a,
                    # Opportunity cost metrics
                    'counter_mfe_missed_atr': counter_mfe_atr,
                    'counter_mfe_missed_dollars': counter_mfe_pts * 20.0,
                    'incumbent_mae_avoided_atr': incumbent_mae_atr,
                    'incumbent_mae_avoided_dollars': incumbent_mae_pts * 20.0,
                    'entry_price_improvement_pts': price_improvement_pts,
                    'entry_price_improvement_atr': price_improvement_atr,
                    'entry_price_improvement_dollars': price_improvement_dollars,
                    # Original H050 winner targets for retention analysis
                    'h050_c1_net_pnl_atr': float(r_ck.get('c1_net_pnl_atr', 0.0) if 'c1_net_pnl_atr' in r_ck else r_ex['c1_pnl_atr']),
                    'h050_winner_1a': int(float(r_ck.get('c1_net_pnl_atr', 0.0) if 'c1_net_pnl_atr' in r_ck else r_ex['c1_pnl_atr']) >= 1.0),
                    'h050_winner_2a': int(float(r_ck.get('c1_net_pnl_atr', 0.0) if 'c1_net_pnl_atr' in r_ck else r_ex['c1_pnl_atr']) >= 2.0),
                    'h050_winner_3a': int(float(r_ck.get('c1_net_pnl_atr', 0.0) if 'c1_net_pnl_atr' in r_ck else r_ex['c1_pnl_atr']) >= 3.0),
                }
                obs_row.update(ctx_feats)
                observation_records.append(obs_row)

                # -------------------------------------------------------------
                # F. Fast-Failure post-delayed-entry observation (+15s, +30s, +60s)
                # -------------------------------------------------------------
                for fail_sec in [15, 30, 60]:
                    ff_ts = ck_ts + fail_sec * 1_000_000_000
                    idx_ff = np.searchsorted(ts_1s_arr, ff_ts)
                    idx_ff = max(idx_ck, min(len(ts_1s_arr) - 1, idx_ff))
                    ff_px = closes_1s[idx_ff]

                    ff_highs = highs_1s[idx_ck:idx_ff+1]
                    ff_lows = lows_1s[idx_ck:idx_ff+1]
                    ff_diffs = np.diff(closes_1s[idx_ck:idx_ff+1]) if idx_ff > idx_ck else np.array([0.0])

                    if direction == 1:
                        ff_fav_pts = max(0.0, ck_price - np.min(ff_lows))
                        ff_adv_pts = max(0.0, np.max(ff_highs) - ck_price)
                        ff_new_ext = int(np.max(ff_highs) > running_peak_price + 1e-4)
                        ff_new_ext_mag = max(0.0, np.max(ff_highs) - running_peak_price) / max(frozen_atr, 1e-4)
                    else:
                        ff_fav_pts = max(0.0, np.max(ff_highs) - ck_price)
                        ff_adv_pts = max(0.0, ck_price - np.min(ff_lows))
                        ff_new_ext = int(np.min(ff_lows) < running_peak_price - 1e-4)
                        ff_new_ext_mag = max(0.0, running_peak_price - np.min(ff_lows)) / max(frozen_atr, 1e-4)

                    ff_fav_atr = ff_fav_pts / max(frozen_atr, 1e-4)
                    ff_adv_atr = ff_adv_pts / max(frozen_atr, 1e-4)
                    ff_mfe_mae_ratio = ff_fav_atr / max(ff_adv_atr, 0.01)

                    ff_counter_bars = int(np.sum(ff_diffs * counter_direction > 0))
                    ff_incumbent_bars = int(np.sum(ff_diffs * direction > 0))

                    # Immediate exit PnL at ff_ts
                    ff_imm_pnl_pts = counter_direction * (ff_px - ck_price) - 0.75
                    ff_imm_pnl_dollars = ff_imm_pnl_pts * 20.0
                    ff_imm_pnl_atr = ff_imm_pnl_pts / max(frozen_atr, 1e-4)

                    # Diagnostic labels:
                    # 1. Eventual severe loser under C1 (<= -2.00A)
                    # 2. >= 1.0A additional adverse excursion before favorable continuation
                    failed_rev_severe = int(c1_pnl_atr <= -2.00)
                    failed_rev_1a = int(post_mae_atr >= 1.00 and post_mfe_atr < 0.50)

                    fast_failure_records[fail_sec].append({
                        'trade_id': obs_row['trade_id'],
                        'year': year,
                        'horizon_name': horizon_name,
                        'fail_sec': fail_sec,
                        'post_entry_adverse_excursion_atr': ff_adv_atr,
                        'post_entry_favorable_excursion_atr': ff_fav_atr,
                        'post_entry_mfe_mae_ratio': ff_mfe_mae_ratio,
                        'has_new_incumbent_extreme_post_entry': ff_new_ext,
                        'magnitude_new_incumbent_extreme_post_entry': ff_new_ext_mag,
                        'incumbent_bars_count_post_entry': ff_incumbent_bars,
                        'counter_bars_count_post_entry': ff_counter_bars,
                        'immediate_exit_pnl_atr': ff_imm_pnl_atr,
                        'immediate_exit_pnl_dollars': ff_imm_pnl_dollars,
                        'c1_eventual_pnl_atr': c1_pnl_atr,
                        'c1_eventual_pnl_dollars': c1_pnl_dollars,
                        'is_catastrophic_loss': is_catastrophic,
                        'is_winner_2a': is_winner_2a,
                        'is_winner_3a': is_winner_3a,
                        'failed_reversal_severe': failed_rev_severe,
                        'failed_reversal_1a': failed_rev_1a,
                    })

        print(f"Year {year} finished in {time.time()-t_loop:.2f}s")

    print(f"\nTotal observation records materialized: {len(observation_records)}")
    df_obs = pd.DataFrame(observation_records)

    # Save observation ledger parquet
    ledger_path = RESULTS_DIR / 'delayed_entry_observation_ledger.parquet'
    print(f"Saving observation ledger to: {ledger_path}")
    df_obs.to_parquet(ledger_path, index=False)

    # -------------------------------------------------------------------------
    # 2. Census & Survivor Accounting
    # -------------------------------------------------------------------------
    print("\n" + "=" * 50)
    print("Computing Checkpoint Population Census...")
    print("=" * 50)
    census = {
        'initial_h050_count': N_total,
        'horizons': {}
    }
    for h_sec in horizons_sec:
        h_name = f"T{h_sec}"
        sub = df_obs[df_obs['horizon_sec'] == h_sec]
        surv_count = len(sub)
        pct_surv = round(surv_count / N_total * 100.0, 3)
        excl_ended = N_total - surv_count
        census['horizons'][h_name] = {
            'horizon_sec': h_sec,
            'eligible_survivor_count': surv_count,
            'percent_remaining': pct_surv,
            'exclusions': {
                'regime_ended_before_checkpoint': excl_ended,
                'session_or_data_boundary': 0
            }
        }
        print(f"  {h_name} (+{h_sec:3d}s): Survivors = {surv_count:5d} ({pct_surv:6.2f}%), Excluded = {excl_ended:4d}")

    with open(RESULTS_DIR / 'checkpoint_population_census.json', 'w') as f:
        json.dump(census, f, indent=2)

    # Target summary across horizons
    print("\nComputing Target Distributions across Horizons...")
    target_summary = {}
    for h_sec in horizons_sec:
        h_name = f"T{h_sec}"
        sub = df_obs[df_obs['horizon_sec'] == h_sec]
        target_summary[h_name] = {
            'count': len(sub),
            'terminal_within_0p25a_rate': float(round(sub['terminal_mfe_within_0p25a_from_t'].mean(), 4)),
            'remaining_gte_0p5a_rate': float(round(sub['remaining_mfe_gte_0p5a_from_t'].mean(), 4)),
            'remaining_gte_1p0a_rate': float(round(sub['remaining_mfe_gte_1p0a_from_t'].mean(), 4)),
            'remaining_gte_2p0a_rate': float(round(sub['remaining_mfe_gte_2p0a_from_t'].mean(), 4)),
            'mean_remaining_mfe_atr': float(round(sub['remaining_incumbent_mfe_atr_from_t'].mean(), 4)),
            'median_remaining_mfe_atr': float(round(sub['remaining_incumbent_mfe_atr_from_t'].median(), 4)),
        }
    with open(RESULTS_DIR / 'checkpoint_target_summary.json', 'w') as f:
        json.dump(target_summary, f, indent=2)

    # -------------------------------------------------------------------------
    # 3. Dynamic M4 Rescore Summary
    # -------------------------------------------------------------------------
    print("\nComputing Dynamic M4 Rescore Summary...")
    m4_rescore_summary = {}
    for h_sec in horizons_sec:
        h_name = f"T{h_sec}"
        sub = df_obs[df_obs['horizon_sec'] == h_sec]
        corr_cur_h050, _ = pearsonr(sub['m4_score_current'], sub['m4_score_at_h050'])
        m4_rescore_summary[h_name] = {
            'mean_m4_score_at_h050': float(round(sub['m4_score_at_h050'].mean(), 5)),
            'mean_m4_score_current': float(round(sub['m4_score_current'].mean(), 5)),
            'mean_delta_m4_score': float(round(sub['delta_m4_score_from_h050'].mean(), 5)),
            'std_delta_m4_score': float(round(sub['delta_m4_score_from_h050'].std(), 5)),
            'correlation_with_h050_score': float(round(corr_cur_h050, 4)),
            'mean_delta_p0': float(round(sub['delta_m4_p0'].mean(), 5)),
            'mean_delta_p1': float(round(sub['delta_m4_p1'].mean(), 5)),
            'mean_delta_p2': float(round(sub['delta_m4_p2'].mean(), 5)),
        }
    with open(RESULTS_DIR / 'm4_dynamic_rescore_summary.json', 'w') as f:
        json.dump(m4_rescore_summary, f, indent=2)

    # -------------------------------------------------------------------------
    # 4. Delayed-Entry Economics & Opportunity Cost of Waiting
    # -------------------------------------------------------------------------
    print("\nComputing Delayed-Entry Economics & Opportunity Costs...")
    delayed_econ = {}
    opp_cost = {}
    for h_sec in horizons_sec:
        h_name = f"T{h_sec}"
        sub = df_obs[df_obs['horizon_sec'] == h_sec]
        delayed_econ[h_name] = {
            'survivor_count': len(sub),
            'c1_mean_pnl_atr': float(round(sub['c1_net_pnl_atr'].mean(), 4)),
            'c1_median_pnl_atr': float(round(sub['c1_net_pnl_atr'].median(), 4)),
            'c1_mean_pnl_dollars': float(round(sub['c1_net_pnl_dollars'].mean(), 2)),
            'c1_win_rate': float(round((sub['c1_net_pnl_atr'] > 0).mean(), 4)),
            'c1_catastrophic_rate': float(round(sub['is_catastrophic_loss'].mean(), 4)),
            'c1_severe_loss_rate': float(round(sub['is_severe_loss'].mean(), 4)),
            'c1_winner_1a_rate': float(round(sub['is_winner_1a'].mean(), 4)),
            'c1_winner_2a_rate': float(round(sub['is_winner_2a'].mean(), 4)),
            'c1_winner_3a_rate': float(round(sub['is_winner_3a'].mean(), 4)),
            'r2_mean_pnl_atr': float(round(sub['r2_net_pnl_atr'].mean(), 4)),
            'r2_median_pnl_atr': float(round(sub['r2_net_pnl_atr'].median(), 4)),
            'post_entry_mean_mfe_atr': float(round(sub['post_entry_mfe_atr'].mean(), 4)),
            'post_entry_mean_mae_atr': float(round(sub['post_entry_mae_atr'].mean(), 4)),
        }
        opp_cost[h_name] = {
            'mean_counter_mfe_missed_atr': float(round(sub['counter_mfe_missed_atr'].mean(), 4)),
            'median_counter_mfe_missed_atr': float(round(sub['counter_mfe_missed_atr'].median(), 4)),
            'mean_counter_mfe_missed_dollars': float(round(sub['counter_mfe_missed_dollars'].mean(), 2)),
            'mean_incumbent_mae_avoided_atr': float(round(sub['incumbent_mae_avoided_atr'].mean(), 4)),
            'median_incumbent_mae_avoided_atr': float(round(sub['incumbent_mae_avoided_atr'].median(), 4)),
            'mean_incumbent_mae_avoided_dollars': float(round(sub['incumbent_mae_avoided_dollars'].mean(), 2)),
            'mean_entry_price_improvement_pts': float(round(sub['entry_price_improvement_pts'].mean(), 3)),
            'mean_entry_price_improvement_atr': float(round(sub['entry_price_improvement_atr'].mean(), 4)),
            'mean_entry_price_improvement_dollars': float(round(sub['entry_price_improvement_dollars'].mean(), 2)),
        }

    with open(RESULTS_DIR / 'delayed_entry_economics.json', 'w') as f:
        json.dump(delayed_econ, f, indent=2)
    with open(RESULTS_DIR / 'opportunity_cost_of_waiting.json', 'w') as f:
        json.dump(opp_cost, f, indent=2)

    # -------------------------------------------------------------------------
    # 5. Winner Opportunity Retention Analysis (§15)
    # -------------------------------------------------------------------------
    print("\nComputing Winner Opportunity Retention Analysis...")
    winner_retention = {}
    for h_sec in horizons_sec:
        h_name = f"T{h_sec}"
        sub = df_obs[df_obs['horizon_sec'] == h_sec]

        # For trades that were original H050 +1A / +2A / +3A winners
        w1 = sub[sub['h050_winner_1a'] == 1]
        w2 = sub[sub['h050_winner_2a'] == 1]
        w3 = sub[sub['h050_winner_3a'] == 1]

        winner_retention[h_name] = {
            'plus_1a_cohort': {
                'original_count': len(w1),
                'percent_still_profitable': float(round((w1['c1_net_pnl_atr'] > 0).mean() * 100, 2)) if len(w1)>0 else 0.0,
                'percent_still_gte_1a': float(round(w1['is_winner_1a'].mean() * 100, 2)) if len(w1)>0 else 0.0,
                'percent_still_gte_2a': float(round(w1['is_winner_2a'].mean() * 100, 2)) if len(w1)>0 else 0.0,
                'mean_remaining_mfe_atr': float(round(w1['post_entry_mfe_atr'].mean(), 4)) if len(w1)>0 else 0.0,
            },
            'plus_2a_cohort': {
                'original_count': len(w2),
                'percent_still_profitable': float(round((w2['c1_net_pnl_atr'] > 0).mean() * 100, 2)) if len(w2)>0 else 0.0,
                'percent_still_gte_1a': float(round(w2['is_winner_1a'].mean() * 100, 2)) if len(w2)>0 else 0.0,
                'percent_still_gte_2a': float(round(w2['is_winner_2a'].mean() * 100, 2)) if len(w2)>0 else 0.0,
                'percent_still_gte_3a': float(round(w2['is_winner_3a'].mean() * 100, 2)) if len(w2)>0 else 0.0,
                'mean_remaining_mfe_atr': float(round(w2['post_entry_mfe_atr'].mean(), 4)) if len(w2)>0 else 0.0,
            },
            'plus_3a_cohort': {
                'original_count': len(w3),
                'percent_still_profitable': float(round((w3['c1_net_pnl_atr'] > 0).mean() * 100, 2)) if len(w3)>0 else 0.0,
                'percent_still_gte_2a': float(round(w3['is_winner_2a'].mean() * 100, 2)) if len(w3)>0 else 0.0,
                'percent_still_gte_3a': float(round(w3['is_winner_3a'].mean() * 100, 2)) if len(w3)>0 else 0.0,
                'mean_remaining_mfe_atr': float(round(w3['post_entry_mfe_atr'].mean(), 4)) if len(w3)>0 else 0.0,
            }
        }
    with open(RESULTS_DIR / 'winner_opportunity_retention.json', 'w') as f:
        json.dump(winner_retention, f, indent=2)

    # -------------------------------------------------------------------------
    # 6. Horizon-Specific Model Protocol & Survivor-Selection Audit (§10, 11, 14)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 50)
    print("Running Horizon Model Protocol & Survivor Audit (2023 Fit -> 2024 Val)...")
    print("=" * 50)

    # Feature columns for expanded model
    meta_cols = {'trade_id', 'parent_h050_id', 'year', 'regime_id', 't0_ts', 'checkpoint_ts',
                 'horizon_sec', 'horizon_name', 'c1_exit_source', 'c1_exit_ts', 'r2_exit_ts',
                 'remaining_incumbent_mfe_atr_from_t', 'terminal_mfe_within_0p25a_from_t',
                 'remaining_mfe_gte_0p5a_from_t', 'remaining_mfe_gte_1p0a_from_t', 'remaining_mfe_gte_2p0a_from_t',
                 'c1_net_pnl_pts', 'c1_net_pnl_dollars', 'c1_net_pnl_atr', 'r2_net_pnl_pts',
                 'r2_net_pnl_dollars', 'r2_net_pnl_atr', 'post_entry_mfe_atr', 'post_entry_mae_atr',
                 'is_catastrophic_loss', 'is_severe_loss', 'is_winner_1a', 'is_winner_2a', 'is_winner_3a',
                 'h050_c1_net_pnl_atr', 'h050_winner_1a', 'h050_winner_2a', 'h050_winner_3a'}
    expanded_feature_cols = [c for c in df_obs.columns if c not in meta_cols]
    print(f"Total candidate features in expanded surface: {len(expanded_feature_cols)}")

    # Fixed hyperparameters across horizons
    lgb_params = {
        'n_estimators': 100,
        'learning_rate': 0.03,
        'max_depth': 4,
        'num_leaves': 15,
        'min_child_samples': 50,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'random_state': 42,
        'verbose': -1,
        'n_jobs': -1
    }

    horizon_model_metrics = {}
    survivor_adjusted_info = {}

    targets = ['terminal_mfe_within_0p25a_from_t', 'remaining_mfe_gte_0p5a_from_t',
               'remaining_mfe_gte_1p0a_from_t', 'remaining_mfe_gte_2p0a_from_t']

    for h_sec in horizons_sec:
        h_name = f"T{h_sec}"
        print(f"\n--- Modeling Horizon {h_name} (+{h_sec}s) ---")
        df_h = df_obs[df_obs['horizon_sec'] == h_sec].copy()
        train_sub = df_h[df_h['year'] == '2023']
        val_sub = df_h[df_h['year'] == '2024']

        X_tr = train_sub[expanded_feature_cols].values
        X_val = val_sub[expanded_feature_cols].values

        h_metrics = {'survivors_2023': len(train_sub), 'survivors_2024': len(val_sub), 'targets': {}}
        surv_info = {'survivors_count_2024': len(val_sub), 'targets': {}}

        for tgt in targets:
            y_tr = train_sub[tgt].values
            y_val = val_sub[tgt].values

            # Train simple bounded LightGBM on 2023
            clf = lgb.LGBMClassifier(**lgb_params)
            clf.fit(X_tr, y_tr)
            p_exp_val = clf.predict_proba(X_val)[:, 1]

            # Model A: M4 current score on 2024 survivors
            m4_cur_val = val_sub['m4_score_current'].values
            # Model B: M4 H050 score on 2024 survivors
            m4_h050_val = val_sub['m4_score_at_h050'].values

            # AUCs on validation cohort (2024)
            auc_exp = float(round(roc_auc_score(y_val, p_exp_val), 4))
            pr_exp = float(round(average_precision_score(y_val, p_exp_val), 4))
            brier_exp = float(round(brier_score_loss(y_val, p_exp_val), 4))

            # Sign flip for M4 if target is continuation (remaining >= 1A, etc.)
            # M4 score is higher for EXHAUSTION (success <0.5A).
            # If target is terminal <0.25A, high M4 score agrees with target.
            # If target is remaining >= 1.0A (continuation), high M4 score opposes target, so invert score for AUC.
            if 'terminal' in tgt:
                auc_m4_cur = float(round(roc_auc_score(y_val, m4_cur_val), 4))
                auc_m4_h050 = float(round(roc_auc_score(y_val, m4_h050_val), 4))
            else:
                auc_m4_cur = float(round(roc_auc_score(y_val, -m4_cur_val), 4))
                auc_m4_h050 = float(round(roc_auc_score(y_val, -m4_h050_val), 4))

            # Decile separation for expanded model
            val_temp = pd.DataFrame({'score': p_exp_val, 'y': y_val})
            val_temp['decile'] = pd.qcut(val_temp['score'].rank(method='first'), 10, labels=False)
            d_top = float(val_temp[val_temp['decile'] == 9]['y'].mean())
            d_bot = float(val_temp[val_temp['decile'] == 0]['y'].mean())
            decile_spread = float(round(d_top - d_bot, 4))

            h_metrics['targets'][tgt] = {
                'expanded_model_auc': auc_exp,
                'expanded_model_pr_auc': pr_exp,
                'expanded_model_brier': brier_exp,
                'expanded_model_decile_spread': decile_spread,
                'm4_current_auc': auc_m4_cur,
                'm4_h050_carried_auc': auc_m4_h050,
                'delta_m4_rescore_auc': float(round(auc_m4_cur - auc_m4_h050, 4)),
                'expanded_vs_m4_current_delta_auc': float(round(auc_exp - auc_m4_cur, 4)),
            }

            # Survivor audit on exact same 2024 survivors:
            # Incremental info = current state AUC vs H050 state AUC on identical rows
            delta_auc_surv = float(round(auc_exp - auc_m4_h050, 4))
            surv_info['targets'][tgt] = {
                'cohort_a_current_state_auc': auc_exp,
                'cohort_b_h050_state_auc': auc_m4_h050,
                'incremental_information_from_waiting': delta_auc_surv,
                'is_genuine_new_information': bool(delta_auc_surv > 0.01)
            }

            print(f"  Target {tgt:35s}: Exp AUC = {auc_exp:.4f} | M4 Cur = {auc_m4_cur:.4f} | M4 H050 = {auc_m4_h050:.4f} | Incr = {delta_auc_surv:+.4f}")

        horizon_model_metrics[h_name] = h_metrics
        survivor_adjusted_info[h_name] = surv_info

    with open(RESULTS_DIR / 'horizon_model_metrics.json', 'w') as f:
        json.dump(horizon_model_metrics, f, indent=2)
    with open(RESULTS_DIR / 'survivor_adjusted_information.json', 'w') as f:
        json.dump(survivor_adjusted_info, f, indent=2)

    # -------------------------------------------------------------------------
    # 7. Fast-Failure Invalidation Analysis (§16-20)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 50)
    print("Analyzing Fast-Failure Invalidation across +15s, +30s, +60s...")
    print("=" * 50)

    fast_failure_economic_summary = {}

    for fail_sec in [15, 30, 60]:
        df_ff = pd.DataFrame(fast_failure_records[fail_sec])
        # Model on 2023, test on 2024
        ff_train = df_ff[df_ff['year'] == '2023'].copy()
        ff_val = df_ff[df_ff['year'] == '2024'].copy()

        ff_features = [
            'post_entry_adverse_excursion_atr',
            'post_entry_favorable_excursion_atr',
            'post_entry_mfe_mae_ratio',
            'has_new_incumbent_extreme_post_entry',
            'magnitude_new_incumbent_extreme_post_entry',
            'incumbent_bars_count_post_entry',
            'counter_bars_count_post_entry'
        ]

        # Fit simple risk score to predict severe failure (eventual C1 <= -2A)
        clf_ff = lgb.LGBMClassifier(**lgb_params)
        clf_ff.fit(ff_train[ff_features].values, ff_train['failed_reversal_severe'].values)
        ff_val_scores = clf_ff.predict_proba(ff_val[ff_features].values)[:, 1]
        ff_val['risk_score'] = ff_val_scores

        auc_ff = float(round(roc_auc_score(ff_val['failed_reversal_severe'], ff_val_scores), 4))
        auc_cat = float(round(roc_auc_score(ff_val['is_catastrophic_loss'], ff_val_scores), 4))

        # Top 10% and Top 20% risk buckets
        q90 = np.percentile(ff_val_scores, 90)
        q80 = np.percentile(ff_val_scores, 80)

        top10 = ff_val[ff_val['risk_score'] >= q90]
        top20 = ff_val[ff_val['risk_score'] >= q80]

        total_cat = ff_val['is_catastrophic_loss'].sum()
        total_w2 = ff_val['is_winner_2a'].sum()
        total_w3 = ff_val['is_winner_3a'].sum()

        cat_cap_10 = float(round(top10['is_catastrophic_loss'].sum() / max(total_cat, 1), 4))
        cat_cap_20 = float(round(top20['is_catastrophic_loss'].sum() / max(total_cat, 1), 4))

        w2_collat_10 = float(round(top10['is_winner_2a'].sum() / max(total_w2, 1), 4))
        w2_collat_20 = float(round(top20['is_winner_2a'].sum() / max(total_w2, 1), 4))
        w3_collat_10 = float(round(top10['is_winner_3a'].sum() / max(total_w3, 1), 4))
        w3_collat_20 = float(round(top20['is_winner_3a'].sum() / max(total_w3, 1), 4))

        mean_imm_pnl_10 = float(round(top10['immediate_exit_pnl_atr'].mean(), 4))
        mean_c1_pnl_10 = float(round(top10['c1_eventual_pnl_atr'].mean(), 4))
        loss_avoided_10 = float(round(mean_imm_pnl_10 - mean_c1_pnl_10, 4)) # positive means immediate exit was better than holding to C1 exit!

        mean_imm_pnl_20 = float(round(top20['immediate_exit_pnl_atr'].mean(), 4))
        mean_c1_pnl_20 = float(round(top20['c1_eventual_pnl_atr'].mean(), 4))
        loss_avoided_20 = float(round(mean_imm_pnl_20 - mean_c1_pnl_20, 4))

        ff_report = {
            'checkpoint_seconds_post_entry': fail_sec,
            'auc_failed_reversal_severe': auc_ff,
            'auc_catastrophic_loss': auc_cat,
            'top_10_percent_risk': {
                'catastrophic_loss_capture_rate': cat_cap_10,
                'winner_2a_collateral_rate': w2_collat_10,
                'winner_3a_collateral_rate': w3_collat_10,
                'immediate_exit_mean_pnl_atr': mean_imm_pnl_10,
                'held_to_c1_mean_pnl_atr': mean_c1_pnl_10,
                'net_loss_avoided_atr': loss_avoided_10,
            },
            'top_20_percent_risk': {
                'catastrophic_loss_capture_rate': cat_cap_20,
                'winner_2a_collateral_rate': w2_collat_20,
                'winner_3a_collateral_rate': w3_collat_20,
                'immediate_exit_mean_pnl_atr': mean_imm_pnl_20,
                'held_to_c1_mean_pnl_atr': mean_c1_pnl_20,
                'net_loss_avoided_atr': loss_avoided_20,
            }
        }
        with open(RESULTS_DIR / f'fast_failure_{fail_sec}s.json', 'w') as f:
            json.dump(ff_report, f, indent=2)

        fast_failure_economic_summary[f"+{fail_sec}s"] = ff_report
        print(f"  +{fail_sec}s Post-Entry: Catastrophic Capture (Top 10%) = {cat_cap_10*100:.1f}%, W2 Collateral = {w2_collat_10*100:.1f}%, Loss Avoided = {loss_avoided_10:+.4f}A")

    with open(RESULTS_DIR / 'fast_failure_economic_separation.json', 'w') as f:
        json.dump(fast_failure_economic_summary, f, indent=2)

    # Feature contract
    with open(RESULTS_DIR / 'checkpoint_feature_contract.json', 'w') as f:
        json.dump({
            'total_materialized_features': len(expanded_feature_cols),
            'm4_original_features': m4_feature_names,
            'expanded_feature_names': expanded_feature_cols,
        }, f, indent=2)

    # -------------------------------------------------------------------------
    # 8. Manifest & SHA256 Digests
    # -------------------------------------------------------------------------
    manifest = {
        'study_id': 'nq_h050_delayed_entry_fast_failure',
        'generated_utc': time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        'artifacts': {}
    }
    for p in sorted(RESULTS_DIR.glob('*')):
        if p.is_file() and p.name != 'study_manifest.json':
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            manifest['artifacts'][p.name] = {
                'sha256': h,
                'size_bytes': p.stat().st_size
            }
    with open(RESULTS_DIR / 'study_manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"\nStudy completed successfully in {time.time()-t_start:.2f}s!")

if __name__ == '__main__':
    run_study()
