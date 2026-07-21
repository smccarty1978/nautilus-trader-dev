import numpy as np
import pandas as pd
from pathlib import Path
import json

def apply_policies(df: pd.DataFrame, threshold_fail_prob: float = 0.5) -> pd.DataFrame:
    """Evaluate and label each flip row with F0-F5 trade-eligibility flags."""
    df = df.copy()
    
    # Pre-fill flags (True means trade, False means skip/filter out)
    df['filter_F0_keep'] = True # Baseline
    
    # 1. F1: Median-center rotation filter
    # Skip only when centers compressed OR flat AND crossing rate high
    # compressed: ordering_state == 6 (spread < 0.1 ATR)
    # flat: absolute 5m/15m/30m slopes all small (< 0.001 ATR/s)
    # crossing rate high: crosses_per_minute >= 0.2
    sl_5m = np.abs(df['slope_5m_5m_aligned_atr'])
    sl_15m = np.abs(df['slope_15m_10m_aligned_atr'])
    sl_30m = np.abs(df['slope_30m_15m_aligned_atr'])
    flat = (sl_5m < 0.001) & (sl_15m < 0.001) & (sl_30m < 0.001)
    compressed = (df['ordering_state'] == 6) | flat
    high_cross = df['crosses_per_minute'] >= 0.2
    
    df['filter_F1_keep'] = ~(compressed & high_cross)
    
    # 2. F2: Regime-sequence rotation filter
    # Skip only when regime density high AND overlap high AND retracement high AND sequence efficiency low
    high_density = df['activity_regime_count_30m'] >= 5
    high_overlap = df['seq_5r_mean_overlap'] >= 0.5
    high_retrace = df['seq_5r_mean_retracement'] >= 0.5
    low_eff = df['seq_5r_efficiency'] < 0.2
    
    df['filter_F2_keep'] = ~(high_density & high_overlap & high_retrace & low_eff)
    
    # 3. F3: Combined rotation filter
    # Skip when BOTH F1 and F2 suggest skip
    df['filter_F3_keep'] = df['filter_F1_keep'] | df['filter_F2_keep']
    
    # 4. F4: Combined filter with directional exemption
    # Do not skip when one or more of the following hold:
    # - strong center migration: migration slope in dir > 0.005 ATR/r
    # - favorable regimes dominate: asym_duration > 1.5
    # - current price breaks sequence high/low (position_pct >= 0.9 or <= 0.1)
    strong_migration = df['seq_5r_center_migration_slope_atr'] > 0.005
    fav_dominate = df['seq_5r_asym_duration'] > 1.5
    breakout = (df['seq_5r_position_pct'] >= 0.9) | (df['seq_5r_position_pct'] <= 0.1)
    exemption = strong_migration | fav_dominate | breakout
    
    # F4 keep: keep if F3 says keep OR if exemption holds
    df['filter_F4_keep'] = df['filter_F3_keep'] | exemption
    
    # 5. F5: Model-based skip score
    # We will compute the skip score using predictions of model
    # Skip if probability of early failure exceeds threshold
    if 'ridge_log_fail_prob' in df.columns:
        df['filter_F5_keep'] = df['ridge_log_fail_prob'] < threshold_fail_prob
    else:
        df['filter_F5_keep'] = True
        
    return df


def calculate_policy_metrics(df_sub: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Calculate comprehensive performance metrics for a given subset (e.g. validation, test)
    across all policies F0-F5.
    """
    policies = ['F0', 'F1', 'F2', 'F3', 'F4', 'F5']
    results = []
    
    # Define runner thresholds based on pnl_base
    pnl_base = df_sub['pnl_base'].dropna().values
    if len(pnl_base) > 0:
        runner_90 = np.percentile(pnl_base, 90)
        runner_95 = np.percentile(pnl_base, 95)
    else:
        runner_90 = 0.0
        runner_95 = 0.0
        
    for p in policies:
        keep_col = f"filter_{p}_keep"
        if keep_col not in df_sub.columns:
            continue
            
        sub_p = df_sub[df_sub[keep_col] == True].copy()
        
        n_eligible = len(df_sub)
        n_traded = len(sub_p)
        retention_rate = n_traded / n_eligible if n_eligible > 0 else 0.0
        
        # PnL metrics
        pnls_base = sub_p['pnl_base'].dropna().values
        total_pnl = np.sum(pnls_base) if len(pnls_base) > 0 else 0.0
        ev_eligible = total_pnl / n_eligible if n_eligible > 0 else 0.0
        ev_traded = total_pnl / n_traded if n_traded > 0 else 0.0
        
        wins = pnls_base[pnls_base > 0]
        losses = pnls_base[pnls_base < 0]
        win_rate = len(wins) / len(pnls_base) if len(pnls_base) > 0 else 0.0
        profit_factor = np.sum(wins) / abs(np.sum(losses)) if len(losses) > 0 else (float('inf') if len(wins) > 0 else 0.0)
        
        # Max Drawdown
        if len(pnls_base) > 0:
            cum = np.cumsum(pnls_base)
            max_cum = np.maximum.accumulate(cum)
            drawdowns = max_cum - cum
            max_dd = drawdowns.max()
        else:
            max_dd = 0.0
            
        # Runner retention
        total_runners_90 = len(df_sub[df_sub['pnl_base'] >= runner_90])
        traded_runners_90 = len(sub_p[sub_p['pnl_base'] >= runner_90])
        retention_runners_90 = traded_runners_90 / total_runners_90 if total_runners_90 > 0 else 1.0
        
        total_runners_95 = len(df_sub[df_sub['pnl_base'] >= runner_95])
        traded_runners_95 = len(sub_p[sub_p['pnl_base'] >= runner_95])
        retention_runners_95 = traded_runners_95 / total_runners_95 if total_runners_95 > 0 else 1.0
        
        # Losing PnL removed vs Winning PnL removed
        skipped_df = df_sub[df_sub[keep_col] == False]
        losing_removed = skipped_df[skipped_df['pnl_base'] < 0]['pnl_base'].abs().sum()
        winning_removed = skipped_df[skipped_df['pnl_base'] > 0]['pnl_base'].sum()
        
        results.append({
            "subset": prefix,
            "policy": p,
            "eligible_episodes": n_eligible,
            "traded_episodes": n_traded,
            "retention_rate": retention_rate,
            "ev_per_eligible": ev_eligible,
            "ev_per_traded": ev_traded,
            "total_net_pnl": total_pnl,
            "profit_factor": profit_factor,
            "win_rate": win_rate,
            "max_drawdown": max_dd,
            "losing_pnl_removed": losing_removed,
            "winning_pnl_removed": winning_removed,
            "top_decile_runner_retention": retention_runners_90,
            "top_5pct_runner_retention": retention_runners_95
        })
        
    return pd.DataFrame(results)
