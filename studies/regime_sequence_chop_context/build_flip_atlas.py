import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from reproduce_regimes import aggregate_and_run_regimes
from build_median_centers import build_median_centers_df
from build_regime_history import build_completed_regimes, get_session_start
from build_regime_sequence import compute_sequence_features

NQ_MULTIPLIER = 20.0
NQ_TICK_SIZE = 0.25
CAT_STOP_ATR = 1.50

def get_contemporaneous_row(df: pd.DataFrame, ts: int) -> dict:
    """Return the nearest prior row in df for the given timestamp ts in a safe, causal manner."""
    idx = df.index.get_indexer([ts], method='pad')[0]
    if idx < 0:
        row = df.iloc[0]
    else:
        row = df.iloc[idx]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[-1]
    return dict(row)

def simulate_trade_replay(
    direction: int,
    entry_ts_target: int,
    stop_px: float,
    ep_end_ts: int,
    df_1s_fwd: pd.DataFrame, # slice of 1s bars starting from entry_ts_target
    slip_entry_pts: float,
    slip_stop_pts: float,
) -> dict:
    """Simulate a single trade using the exact-replay logic.
    
    Returns entry_px, exit_px, exit_ts, exit_type, and net PnL in points.
    """
    if len(df_1s_fwd) == 0:
        return {
            "entry_px": np.nan, "exit_px": np.nan, "exit_ts": 0,
            "exit_type": "censored", "pnl_pts": np.nan
        }
        
    # Get arrays
    opens = df_1s_fwd['open'].values
    highs = df_1s_fwd['high'].values
    lows = df_1s_fwd['low'].values
    closes = df_1s_fwd['close'].values
    timestamps = df_1s_fwd.index.values.view(np.int64)
    
    entry_ts = int(timestamps[0])
    entry_px = float(opens[0])
    eff_entry = entry_px + direction * slip_entry_pts
    eff_stop = stop_px - direction * slip_stop_pts
    
    exit_px = np.nan
    exit_ts = 0
    exit_type = "censored"
    
    # Iterate through forward 1s bars
    for idx in range(1, len(opens)):
        ts_ns = int(timestamps[idx])
        o = float(opens[idx])
        h = float(highs[idx])
        l = float(lows[idx])
        c = float(closes[idx])
        
        # Check catastrophic stop
        if direction == 1:
            gapped = o <= eff_stop
            touched = l <= eff_stop
        else:
            gapped = o >= eff_stop
            touched = h >= eff_stop
            
        if gapped or touched:
            exit_ts = ts_ns
            exit_type = "stop"
            exit_px = o if gapped else eff_stop
            break
            
        # Check regime end (opposing flip or timeout)
        if ts_ns >= ep_end_ts:
            exit_ts = ep_end_ts
            exit_type = "regime_exit" if ep_end_ts < entry_ts + 1800 * 1e9 else "timeout"
            exit_px = o # exit filled at next available 1s open
            break
            
    if np.isnan(exit_px):
        # Censored at the end of the data slice
        exit_ts = int(timestamps[-1])
        exit_type = "censored"
        exit_px = float(closes[-1])
        
    pnl_pts = direction * (exit_px - eff_entry)
    
    return {
        "entry_px": entry_px,
        "exit_px": exit_px,
        "exit_ts": exit_ts,
        "exit_type": exit_type,
        "pnl_pts": pnl_pts
    }


def build_flip_atlas(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load raw 1s data for a year, build features, extract flips, and compute outcomes."""
    print(f"Processing year {year}...")
    f_path = f"data/raw/NQ_v0_1s_{year}.parquet"
    if not os.path.exists(f_path) and year == 2026:
        f_path = f"data/raw/NQ_v0_1s_{year}_ytd.parquet"
    df_1s = pd.read_parquet(f_path)
    
    # 1. Aggregate to 1m and run regime engine
    print("  Running 1m regime engine...")
    df_1m = aggregate_and_run_regimes(df_1s, "1m")
    
    # Merge 1m ATR and regime onto 1s
    print("  Merging 1m states onto 1s data...")
    df_1s_ns = df_1s.copy()
    df_1s_ns['ts_ns'] = df_1s_ns.index.view(np.int64)
    df_1s_ns = df_1s_ns.sort_values('ts_ns')
    
    df_1m_sorted = df_1m.sort_values('close_ts')
    
    merged = pd.merge_asof(
        df_1s_ns,
        df_1m_sorted[['close_ts', 'atr', 'regime']],
        left_on='ts_ns',
        right_on='close_ts',
        direction='backward'
    )
    merged.index = pd.to_datetime(merged['ts_ns'], unit='ns', utc=True)
    merged.index.name = 'ts_event'
    df_1s = merged.drop(columns=['ts_ns', 'close_ts'])
    
    # 2. Build median center features
    df_1s_feats = build_median_centers_df(df_1s)
    
    # 3. Build completed regimes
    print("  Extracting completed regimes...")
    df_regimes = build_completed_regimes(df_1m, df_1s)
    
    # Find all flips (Population F1)
    df_1m['prev_regime'] = df_1m['regime'].shift(1).fillna(0).astype(int)
    flips_1m = df_1m[(df_1m['regime'] != 0) & (df_1m['prev_regime'] != 0) & (df_1m['regime'] != df_1m['prev_regime'])].copy()
    
    print(f"  Found {len(flips_1m)} flips (F1 population).")
    
    # Collect causal context and outcomes for flips
    f1_records = []
    f2_records = []
    
    # Index 1s by nanosecond integer for fast lookups
    df_1s_feats_ns = df_1s_feats.copy()
    df_1s_feats_ns.index = df_1s_feats_ns.index.view(np.int64)
    
    # Pre-build regime lookup list
    regimes_list = list(df_regimes.itertuples(index=False))
    
    # For F2 entries: V_A confirmation bar+1
    # We iterate over df_1m rows to find flips and then check the confirmation bar
    df_1m_list = list(df_1m.itertuples())
    
    for idx in range(1, len(df_1m_list) - 1):
        r_curr = df_1m_list[idx]
        r_prev = df_1m_list[idx - 1]
        
        if r_curr.regime != 0 and r_prev.regime != 0 and r_curr.regime != r_prev.regime:
            # Flip detected at close of r_curr bar!
            # F1 flip is at r_curr.close_ts
            flip_ts = int(r_curr.close_ts)
            direction = int(r_curr.regime)
            atr_val = float(r_curr.atr)
            
            if np.isnan(atr_val) or atr_val <= 0:
                continue
                
            # contemporaneous 1s close
            flip_close = float(r_curr.close)
            
            # Find the opposing flip timestamp (end of this regime)
            opp_flip_ts = 0
            for r_fwd in df_1m_list[idx+1:]:
                if r_fwd.regime == -direction:
                    opp_flip_ts = int(r_fwd.close_ts)
                    break
            if opp_flip_ts == 0:
                opp_flip_ts = int(df_1m_list[-1].close_ts)
                
            # Timeout is 30 minutes
            timeout_ts = flip_ts + 1800 * 1_000_000_000
            ep_end_ts = min(opp_flip_ts, timeout_ts)
            
            # Slice 1s bars for outcomes
            df_1s_fwd = df_1s_feats_ns.loc[flip_ts : ep_end_ts + 60 * 1_000_000_000]
            
            context = get_contemporaneous_row(df_1s_feats_ns, flip_ts)
            context["observation_time"] = flip_ts
            context["direction"] = direction
            
            # completed regime activity at flip_ts
            end_times_reg = df_regimes['end_time'].values
            idx_right = np.searchsorted(end_times_reg, flip_ts, side='right')
            
            activity_feats = {}
            for W_min in (5, 15, 30, 60, 120):
                W_ns = W_min * 60 * 1_000_000_000
                idx_left = np.searchsorted(end_times_reg, flip_ts - W_ns, side='right')
                count_reg = idx_right - idx_left
                activity_feats[f"activity_regime_count_{W_min}m"] = count_reg
                activity_feats[f"activity_flip_count_{W_min}m"] = count_reg
                if count_reg > 0:
                    activity_feats[f"activity_duration_median_{W_min}m"] = float(np.median(df_regimes['duration'].values[idx_left : idx_right]))
                else:
                    activity_feats[f"activity_duration_median_{W_min}m"] = np.nan
                    
            sess_start = get_session_start(pd.Timestamp(flip_ts, unit='ns', tz='UTC'))
            idx_sess = np.searchsorted(end_times_reg, sess_start.value, side='left')
            activity_feats["activity_regime_count_std"] = max(0, idx_right - idx_sess)
            
            if idx_right >= 3:
                activity_feats["duration_median_last_3"] = float(np.median(df_regimes['duration'].values[idx_right-3 : idx_right]))
            else:
                activity_feats["duration_median_last_3"] = np.nan
            if idx_right >= 5:
                activity_feats["duration_median_last_5"] = float(np.median(df_regimes['duration'].values[idx_right-5 : idx_right]))
            else:
                activity_feats["duration_median_last_5"] = np.nan
            if idx_right >= 10:
                activity_feats["duration_median_last_10"] = float(np.median(df_regimes['duration'].values[idx_right-10 : idx_right]))
            else:
                activity_feats["duration_median_last_10"] = np.nan
                
            activity_feats["duration_ratio_3_vs_10"] = activity_feats["duration_median_last_3"] / (activity_feats["duration_median_last_10"] + 1e-8)
            activity_feats["duration_ratio_5_vs_10"] = activity_feats["duration_median_last_5"] / (activity_feats["duration_median_last_10"] + 1e-8)
            
            context.update(activity_feats)
            
            # sequence features
            seq_feats = compute_sequence_features(flip_ts, flip_close, direction, atr_val, df_regimes)
            context.update(seq_feats)
            
            # Cross-family context
            cross_family = {
                "cross_family_spread_vs_reg_count": context.get("center_spread_5m_30m", 0) / max(context.get("activity_regime_count_30m", 0), 1),
                "cross_family_slope_vs_reg_count": context.get("slope_30m_15m_aligned_atr", 0) / max(context.get("activity_regime_count_30m", 0), 1),
            }
            context.update(cross_family)
            
            # Simulate replay outcomes for F1
            stop_px = flip_close - direction * CAT_STOP_ATR * atr_val
            
            out_base = simulate_trade_replay(direction, flip_ts, stop_px, ep_end_ts, df_1s_fwd, 0.0, 0.0)
            out_1t = simulate_trade_replay(direction, flip_ts, stop_px, ep_end_ts, df_1s_fwd, NQ_TICK_SIZE, NQ_TICK_SIZE)
            out_2t = simulate_trade_replay(direction, flip_ts, stop_px, ep_end_ts, df_1s_fwd, 2.0 * NQ_TICK_SIZE, 2.0 * NQ_TICK_SIZE)
            
            # Add outcomes
            context.update({
                "ep_end_time": ep_end_ts,
                "opposing_flip_time": opp_flip_ts,
                "regime_duration": out_base['exit_ts'] - flip_ts,
                "pnl_base": out_base['pnl_pts'] * NQ_MULTIPLIER - 5.0,
                "pnl_plus_1t": out_1t['pnl_pts'] * NQ_MULTIPLIER - 5.0,
                "pnl_plus_2t": out_2t['pnl_pts'] * NQ_MULTIPLIER - 5.0,
                "exit_type": out_base['exit_type'],
                "exit_price": out_base['exit_px'],
                "entry_price": out_base['entry_px'],
            })
            
            # Retrospective outcome metrics
            # Let's just find the close at opp_flip_ts
            opp_bar_match = df_1m[df_1m['close_ts'] == opp_flip_ts]
            opp_close = float(opp_bar_match.iloc[0]['close']) if len(opp_bar_match) > 0 else flip_close
            context["E0_regime_exit_pnl"] = direction * (opp_close - flip_close) * NQ_MULTIPLIER - 5.0
            
            # MFE, MAE from trade path
            closes_fwd = df_1s_fwd['close'].values
            highs_fwd = df_1s_fwd['high'].values
            lows_fwd = df_1s_fwd['low'].values
            
            if len(highs_fwd) > 0:
                mfe_fwd = float(np.max(highs_fwd - flip_close) if direction == 1 else np.max(flip_close - lows_fwd))
                mae_fwd = float(np.max(flip_close - lows_fwd) if direction == 1 else np.max(highs_fwd - flip_close))
            else:
                mfe_fwd = 0.0
                mae_fwd = 0.0
            
            context["MFE"] = mfe_fwd
            context["MAE"] = mae_fwd
            context["MFE_atr"] = mfe_fwd / atr_val
            context["MAE_atr"] = mae_fwd / atr_val
            
            # Outcome classes
            early_fail = (out_base['exit_type'] == 'stop' and mfe_fwd / atr_val < 0.5) or (opp_flip_ts - flip_ts < 60 * 1e9)
            low_progress = (opp_flip_ts - flip_ts <= 300 * 1e9) and (mfe_fwd / atr_val < 0.5)
            large_runner = (mfe_fwd / atr_val >= 2.0)
            productive_ord = (mfe_fwd / atr_val >= 0.5) and not large_runner
            
            if early_fail:
                out_class = "EARLY_ROTATIONAL_FAILURE"
            elif low_progress:
                out_class = "LOW_PROGRESS_REGIME"
            elif large_runner:
                out_class = "LARGE_RUNNER"
            elif productive_ord:
                out_class = "PRODUCTIVE_ORDINARY_REGIME"
            else:
                out_class = "AMBIGUOUS"
                
            context["outcome_class"] = out_class
            f1_records.append(context)
            
            # Check confirmation bar (idx + 1) for F2 population
            r_conf = df_1m_list[idx + 1]
            if direction == 1:
                hhll_ok = r_conf.high > r_curr.high
                mom_ok = r_conf.close > r_conf.open
            else:
                hhll_ok = r_conf.low < r_curr.low
                mom_ok = r_conf.close < r_conf.open
                
            if hhll_ok and mom_ok:
                # F2 entry confirmed!
                # Decision timestamp is the close of the confirmation bar
                conf_ts = int(r_conf.close_ts)
                
                context_c = get_contemporaneous_row(df_1s_feats_ns, conf_ts)
                context_c["observation_time"] = conf_ts
                context_c["direction"] = direction
                
                # Activity & sequence features at conf_ts
                idx_right_c = np.searchsorted(end_times_reg, conf_ts, side='right')
                
                activity_feats_c = {}
                for W_min in (5, 15, 30, 60, 120):
                    W_ns = W_min * 60 * 1_000_000_000
                    idx_left_c = np.searchsorted(end_times_reg, conf_ts - W_ns, side='right')
                    count_reg_c = idx_right_c - idx_left_c
                    activity_feats_c[f"activity_regime_count_{W_min}m"] = count_reg_c
                    activity_feats_c[f"activity_flip_count_{W_min}m"] = count_reg_c
                    if count_reg_c > 0:
                        activity_feats_c[f"activity_duration_median_{W_min}m"] = float(np.median(df_regimes['duration'].values[idx_left_c : idx_right_c]))
                    else:
                        activity_feats_c[f"activity_duration_median_{W_min}m"] = np.nan
                        
                sess_start_c = get_session_start(pd.Timestamp(conf_ts, unit='ns', tz='UTC'))
                idx_sess_c = np.searchsorted(end_times_reg, sess_start_c.value, side='left')
                activity_feats_c["activity_regime_count_std"] = max(0, idx_right_c - idx_sess_c)
                
                if idx_right_c >= 3:
                    activity_feats_c["duration_median_last_3"] = float(np.median(df_regimes['duration'].values[idx_right_c-3 : idx_right_c]))
                else:
                    activity_feats_c["duration_median_last_3"] = np.nan
                if idx_right_c >= 5:
                    activity_feats_c["duration_median_last_5"] = float(np.median(df_regimes['duration'].values[idx_right_c-5 : idx_right_c]))
                else:
                    activity_feats_c["duration_median_last_5"] = np.nan
                if idx_right_c >= 10:
                    activity_feats_c["duration_median_last_10"] = float(np.median(df_regimes['duration'].values[idx_right_c-10 : idx_right_c]))
                else:
                    activity_feats_c["duration_median_last_10"] = np.nan
                    
                activity_feats_c["duration_ratio_3_vs_10"] = activity_feats_c["duration_median_last_3"] / (activity_feats_c["duration_median_last_10"] + 1e-8)
                activity_feats_c["duration_ratio_5_vs_10"] = activity_feats_c["duration_median_last_5"] / (activity_feats_c["duration_median_last_10"] + 1e-8)
                
                context_c.update(activity_feats_c)
                
                # sequence features at conf_ts (using confirmation price)
                seq_feats_c = compute_sequence_features(conf_ts, float(r_conf.close), direction, atr_val, df_regimes)
                context_c.update(seq_feats_c)
                
                # Cross-family
                cross_family_c = {
                    "cross_family_spread_vs_reg_count": context_c.get("center_spread_5m_30m", 0) / max(context_c.get("activity_regime_count_30m", 0), 1),
                    "cross_family_slope_vs_reg_count": context_c.get("slope_30m_15m_aligned_atr", 0) / max(context_c.get("activity_regime_count_30m", 0), 1),
                }
                context_c.update(cross_family_c)
                
                # Slice 1s bars starting from conf_ts
                df_1s_fwd_c = df_1s_feats_ns.loc[conf_ts : ep_end_ts + 60 * 1_000_000_000]
                
                # Simulate replay outcomes for F2
                out_base_c = simulate_trade_replay(direction, conf_ts, stop_px, ep_end_ts, df_1s_fwd_c, 0.0, 0.0)
                out_1t_c = simulate_trade_replay(direction, conf_ts, stop_px, ep_end_ts, df_1s_fwd_c, NQ_TICK_SIZE, NQ_TICK_SIZE)
                out_2t_c = simulate_trade_replay(direction, conf_ts, stop_px, ep_end_ts, df_1s_fwd_c, 2.0 * NQ_TICK_SIZE, 2.0 * NQ_TICK_SIZE)
                
                context_c.update({
                    "ep_end_time": ep_end_ts,
                    "opposing_flip_time": opp_flip_ts,
                    "regime_duration": out_base_c['exit_ts'] - conf_ts,
                    "pnl_base": out_base_c['pnl_pts'] * NQ_MULTIPLIER - 5.0,
                    "pnl_plus_1t": out_1t_c['pnl_pts'] * NQ_MULTIPLIER - 5.0,
                    "pnl_plus_2t": out_2t_c['pnl_pts'] * NQ_MULTIPLIER - 5.0,
                    "exit_type": out_base_c['exit_type'],
                    "exit_price": out_base_c['exit_px'],
                    "entry_price": out_base_c['entry_px'],
                })
                
                context_c["E0_regime_exit_pnl"] = direction * (opp_close - float(r_conf.close)) * NQ_MULTIPLIER - 5.0
                
                # MFE, MAE from confirmation close
                closes_fwd_c = df_1s_fwd_c['close'].values
                highs_fwd_c = df_1s_fwd_c['high'].values
                lows_fwd_c = df_1s_fwd_c['low'].values
                
                if len(highs_fwd_c) > 0:
                    mfe_fwd_c = float(np.max(highs_fwd_c - float(r_conf.close)) if direction == 1 else np.max(float(r_conf.close) - lows_fwd_c))
                    mae_fwd_c = float(np.max(float(r_conf.close) - lows_fwd_c) if direction == 1 else np.max(highs_fwd_c - float(r_conf.close)))
                else:
                    mfe_fwd_c = 0.0
                    mae_fwd_c = 0.0
                
                context_c["MFE"] = mfe_fwd_c
                context_c["MAE"] = mae_fwd_c
                context_c["MFE_atr"] = mfe_fwd_c / atr_val
                context_c["MAE_atr"] = mae_fwd_c / atr_val
                
                early_fail_c = (out_base_c['exit_type'] == 'stop' and mfe_fwd_c / atr_val < 0.5) or (opp_flip_ts - conf_ts < 60 * 1e9)
                low_progress_c = (opp_flip_ts - conf_ts <= 300 * 1e9) and (mfe_fwd_c / atr_val < 0.5)
                large_runner_c = (mfe_fwd_c / atr_val >= 2.0)
                productive_ord_c = (mfe_fwd_c / atr_val >= 0.5) and not large_runner_c
                
                if early_fail_c:
                    out_class_c = "EARLY_ROTATIONAL_FAILURE"
                elif low_progress_c:
                    out_class_c = "LOW_PROGRESS_REGIME"
                elif large_runner_c:
                    out_class_c = "LARGE_RUNNER"
                elif productive_ord_c:
                    out_class_c = "PRODUCTIVE_ORDINARY_REGIME"
                else:
                    out_class_c = "AMBIGUOUS"
                    
                context_c["outcome_class"] = out_class_c
                f2_records.append(context_c)
                
    df_f1 = pd.DataFrame(f1_records)
    df_f2 = pd.DataFrame(f2_records)
    return df_f1, df_f2
