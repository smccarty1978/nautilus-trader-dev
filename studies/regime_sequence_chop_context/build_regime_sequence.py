import numpy as np
import pandas as pd
from typing import Optional

def compute_sequence_features(
    checkpoint_ts: int,
    current_price: float,
    direction: int,
    atr: float,
    df_regimes: pd.DataFrame, # all completed regimes sorted by end_time
) -> dict:
    """Compute K-regime sequence features at a checkpoint_ts.
    
    Only regimes with end_time <= checkpoint_ts are completed.
    We calculate sequence features for K = 3, 5, 8, 12.
    """
    feats = {}
    if df_regimes.empty:
        return feats

    end_times = df_regimes['end_time'].values
    idx = np.searchsorted(end_times, checkpoint_ts, side='right')
    if idx == 0:
        return feats

    n_reg = idx
    completed_slice = df_regimes.iloc[max(0, idx - 12) : idx]
    completed_list = completed_slice.to_dict('records')

    for K in (3, 5, 8, 12):
        prefix = f"seq_{K}r_"
        if n_reg < K:
            # Not enough regimes, pad with defaults or nans
            feats[f"{prefix}available"] = False
            continue
            
        feats[f"{prefix}available"] = True
        sub = completed_list[-K:]
        
        # 1. Alternation
        dirs = [int(r['direction']) for r in sub]
        changes = sum(1 for i in range(K - 1) if dirs[i] != dirs[i+1])
        feats[f"{prefix}alternation_rate"] = changes / (K - 1)
        feats[f"{prefix}perfect_alternation"] = int(changes == (K - 1))
        
        # 2. Sequence Efficiency
        seq_start_price = sub[0]['start_price']
        total_abs_net_move = sum(abs(float(r['net_aligned_move'])) for r in sub)
        net_disp = current_price - seq_start_price
        feats[f"{prefix}efficiency"] = abs(net_disp) / (total_abs_net_move + 1e-8)
        feats[f"{prefix}disp_atr"] = (direction * net_disp) / (atr + 1e-8)

        # 3. Range Overlap
        overlaps = []
        for i in range(K - 1):
            r1 = sub[i]
            r2 = sub[i+1]
            
            # Reconstruction ranges
            if r1['direction'] == 1:
                high1 = r1['start_price'] + r1['MFE']
                low1 = r1['start_price'] - r1['MAE']
            else:
                high1 = r1['start_price'] + r1['MAE']
                low1 = r1['start_price'] - r1['MFE']
                
            if r2['direction'] == 1:
                high2 = r2['start_price'] + r2['MFE']
                low2 = r2['start_price'] - r2['MAE']
            else:
                high2 = r2['start_price'] + r2['MAE']
                low2 = r2['start_price'] - r2['MFE']
                
            inter = max(0.0, min(high1, high2) - max(low1, low2))
            min_rng = min(high1 - low1, high2 - low2)
            overlaps.append(inter / (min_rng + 1e-8))
            
        n_over = len(overlaps)
        mean_overlap = sum(overlaps) / n_over if n_over > 0 else 0.0
        max_overlap = max(overlaps) if overlaps else 0.0
        
        if overlaps:
            sorted_over = sorted(overlaps)
            if n_over % 2 == 1:
                median_overlap = float(sorted_over[n_over // 2])
            else:
                median_overlap = float((sorted_over[n_over // 2 - 1] + sorted_over[n_over // 2]) / 2.0)
        else:
            median_overlap = 0.0
            
        overlap_above_50 = sum(1.0 for o in overlaps if o > 0.5) / n_over if n_over > 0 else 0.0
        overlap_above_75 = sum(1.0 for o in overlaps if o > 0.75) / n_over if n_over > 0 else 0.0
        
        feats[f"{prefix}mean_overlap"] = mean_overlap
        feats[f"{prefix}median_overlap"] = median_overlap
        feats[f"{prefix}max_overlap"] = max_overlap
        feats[f"{prefix}overlap_above_50"] = overlap_above_50
        feats[f"{prefix}overlap_above_75"] = overlap_above_75

        # 4. Retracement Behavior
        retracements = []
        retracements_mfe = []
        reclaim_count = 0
        for i in range(K - 1):
            r1 = sub[i]
            r2 = sub[i+1]
            if r1['direction'] != r2['direction']:
                p_net = abs(r1['net_aligned_move'])
                o_net = abs(r2['net_aligned_move'])
                retracements.append(o_net / (p_net + 1e-8))
                
                p_mfe = r1['MFE']
                retracements_mfe.append(o_net / (p_mfe + 1e-8))
                
                r1_start = r1['start_price']
                if r2['direction'] == 1:
                    r2_high = r2['start_price'] + r2['MFE']
                    r2_low = r2['start_price'] - r2['MAE']
                else:
                    r2_high = r2['start_price'] + r2['MAE']
                    r2_low = r2['start_price'] - r2['MFE']
                    
                if r1['direction'] == 1:
                    if r2_low <= r1_start:
                        reclaim_count += 1
                else:
                    if r2_high >= r1_start:
                        reclaim_count += 1
                        
        feats[f"{prefix}mean_retracement"] = sum(retracements) / len(retracements) if retracements else 0.0
        feats[f"{prefix}mean_retracement_mfe"] = sum(retracements_mfe) / len(retracements_mfe) if retracements_mfe else 0.0
        feats[f"{prefix}reclaim_rate"] = reclaim_count / max(1, len(retracements))

        # 5. Envelope Expansion
        highs = []
        lows = []
        for r in sub:
            highs.append(r['start_price'] + r['MFE'] if r['direction'] == 1 else r['start_price'] + r['MAE'])
            lows.append(r['start_price'] - r['MAE'] if r['direction'] == 1 else r['start_price'] - r['MFE'])
            
        seq_high = max(highs)
        seq_low = min(lows)
        seq_rng = seq_high - seq_low
        feats[f"{prefix}range_atr"] = seq_rng / (atr + 1e-8)
        
        # Position of current price in sequence range
        if seq_rng > 1e-8:
            pos_pct = (current_price - seq_low) / seq_rng
        else:
            pos_pct = 0.5
        feats[f"{prefix}position_pct"] = direction * (pos_pct - 0.5) + 0.5
        feats[f"{prefix}dist_to_high_atr"] = (direction * (seq_high - current_price)) / (atr + 1e-8)
        feats[f"{prefix}dist_to_low_atr"] = (direction * (current_price - seq_low)) / (atr + 1e-8)

        # 6. Regime-Center Migration
        centers = [r['regime_center'] for r in sub]
        sum_y = sum(centers)
        mean_y = sum_y / K
        sum_xy = sum(i * centers[i] for i in range(K))
        sum_x = K * (K - 1) / 2.0
        ss_xx = K * (K ** 2 - 1) / 12.0
        ss_xy = sum_xy - sum_x * mean_y
        
        slope = ss_xy / ss_xx
        feats[f"{prefix}center_migration_slope_atr"] = slope / (atr + 1e-8)
        
        ss_yy = sum((y - mean_y) ** 2 for y in centers)
        if ss_yy > 1e-8:
            r2 = (ss_xy ** 2) / (ss_xx * ss_yy)
        else:
            r2 = 0.0
        feats[f"{prefix}center_migration_r2"] = r2
        
        center_diffs = [centers[i+1] - centers[i] for i in range(K - 1)]
        favorable_changes = sum(1 for d in center_diffs if d * direction > 0)
        reversals = sum(1 for i in range(len(center_diffs) - 1) if center_diffs[i] * center_diffs[i+1] < 0)
        feats[f"{prefix}center_dir_consistency"] = favorable_changes / max(1, len(center_diffs))
        feats[f"{prefix}center_reversal_count"] = reversals

        # 7. Directional Asymmetry
        fav_regs = [r for r in sub if r['direction'] == direction]
        adv_regs = [r for r in sub if r['direction'] == -direction]
        
        def safe_ratio(fav_val, adv_val):
            if adv_val == 0:
                return 1.0 if fav_val == 0 else 5.0
            return fav_val / adv_val
            
        mean_dur_fav = sum(r['duration'] for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
        mean_dur_adv = sum(r['duration'] for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
        feats[f"{prefix}asym_duration"] = safe_ratio(mean_dur_fav, mean_dur_adv)
        
        mean_mfe_fav = sum(r['MFE'] for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
        mean_mfe_adv = sum(r['MFE'] for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
        feats[f"{prefix}asym_mfe"] = safe_ratio(mean_mfe_fav, mean_mfe_adv)
        
        mean_net_fav = sum(abs(r['net_aligned_move']) for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
        mean_net_adv = sum(abs(r['net_aligned_move']) for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
        feats[f"{prefix}asym_net_move"] = safe_ratio(mean_net_fav, mean_net_adv)
        
        mean_eff_fav = sum(abs(r['directional_efficiency']) for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
        mean_eff_adv = sum(abs(r['directional_efficiency']) for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
        feats[f"{prefix}asym_efficiency"] = safe_ratio(mean_eff_fav, mean_eff_adv)
        
        mean_vol_fav = sum(r['volume'] for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
        mean_vol_adv = sum(r['volume'] for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
        feats[f"{prefix}asym_volume"] = safe_ratio(mean_vol_fav, mean_vol_adv)

    return feats
