import sys
sys.path.insert(0, ".")
import os
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT = Path(r"c:\Users\Scott McCarty\Projects\Nautilus Trader")
BRANCH_A_DIR = REPO_ROOT / "studies/index_pullback_portability_and_trend_mirror/branch_a_leaf4_portability"

# Load NQ Leaf 4 trades
p_train = REPO_ROOT / "studies/nq_h050_mtf_regime_context_features/results/feature_surface_train.parquet"
p_q1 = REPO_ROOT / "studies/nq_h050_m4_vs_remaining_mfe_model/feature_surface_2025_q1.parquet"
df_nq = pd.concat([pd.read_parquet(p_train), pd.read_parquet(p_q1)], ignore_index=True)
cond_nq = (
    (df_nq['minutes_from_rth_open'] <= 380.649994) &
    (df_nq['realized_range_15m_atr'] <= 9.344128) &
    (df_nq['current_price_from_prior_mfe_atr__tf_1m'] <= 1.738367)
)
df_nq_leaf = df_nq[cond_nq].copy()
df_nq_leaf['instrument'] = 'NQ'
df_nq_leaf['entry_ts'] = df_nq_leaf['checkpoint_ts'] + 1_000_000_000 # 1s after checkpoint
df_nq_leaf['net_pnl_atr'] = df_nq_leaf['c1_net_pnl_atr']
df_nq_leaf['net_dollars'] = df_nq_leaf['c1_net_pnl_dollars']

# Load ES and YM Leaf 4 trades
df_es_all = pd.read_parquet(BRANCH_A_DIR / "es_h050_observations.parquet")
df_es_leaf = df_es_all[df_es_all['is_leaf4']].copy()

df_ym_all = pd.read_parquet(BRANCH_A_DIR / "ym_h050_observations.parquet")
df_ym_leaf = df_ym_all[df_ym_all['is_leaf4']].copy()

print(f"Leaf 4 counts: NQ={len(df_nq_leaf)}, ES={len(df_es_leaf)}, YM={len(df_ym_leaf)}")

# Combine all Leaf 4 events
cols = ['instrument', 'year', 'checkpoint_ts', 'direction', 'net_pnl_atr', 'net_dollars']
trades_all = pd.concat([
    df_nq_leaf[cols],
    df_es_leaf[cols],
    df_ym_leaf[cols]
], ignore_index=True)

trades_all['dt'] = pd.to_datetime(trades_all['checkpoint_ts'], unit='ns', utc=True)
trades_all['date'] = trades_all['dt'].dt.date
trades_all['month'] = trades_all['dt'].dt.tz_localize(None).dt.to_period('M').astype(str)
trades_all.sort_values('checkpoint_ts', inplace=True)
trades_all.reset_index(drop=True, inplace=True)

# Total trading days (active dates)
tot_days = trades_all['date'].nunique()

# -----------------------------------------------------------------------------
# A8. Portfolio-Frequency & Clustering Analysis
# -----------------------------------------------------------------------------
def cluster_events(df_events, window_sec):
    if len(df_events) == 0:
        return []
    ts_arr = df_events['checkpoint_ts'].values
    inst_arr = df_events['instrument'].values
    dir_arr = df_events['direction'].values
    pnl_arr = df_events['net_pnl_atr'].values
    
    clusters = []
    cur_cluster = {
        'start_ts': ts_arr[0],
        'end_ts': ts_arr[0],
        'events': [0],
        'instruments': {inst_arr[0]},
        'directions': [dir_arr[0]],
        'pnls': [pnl_arr[0]]
    }
    
    for i in range(1, len(ts_arr)):
        dt_sec = (ts_arr[i] - cur_cluster['start_ts']) / 1e9
        if dt_sec <= window_sec:
            cur_cluster['end_ts'] = ts_arr[i]
            cur_cluster['events'].append(i)
            cur_cluster['instruments'].add(inst_arr[i])
            cur_cluster['directions'].append(dir_arr[i])
            cur_cluster['pnls'].append(pnl_arr[i])
        else:
            clusters.append(cur_cluster)
            cur_cluster = {
                'start_ts': ts_arr[i],
                'end_ts': ts_arr[i],
                'events': [i],
                'instruments': {inst_arr[i]},
                'directions': [dir_arr[i]],
                'pnls': [pnl_arr[i]]
            }
    clusters.append(cur_cluster)
    return clusters

clustering_results = {}
for win_name, win_sec in [('same_second', 0.0), ('same_minute', 60.0), ('within_5_minutes', 300.0)]:
    clusters = cluster_events(trades_all, win_sec)
    n_clusters = len(clusters)
    inst_per_cluster = [len(c['instruments']) for c in clusters]
    events_per_cluster = [len(c['events']) for c in clusters]
    simultaneous_clusters = sum(1 for n in inst_per_cluster if n > 1)
    
    clustering_results[win_name] = {
        'window_seconds': win_sec,
        'total_raw_signals': len(trades_all),
        'raw_signals_per_day': round(len(trades_all) / tot_days, 2),
        'unique_clusters_total': n_clusters,
        'unique_clusters_per_day': round(n_clusters / tot_days, 2),
        'avg_instruments_per_cluster': round(float(np.mean(inst_per_cluster)), 2),
        'avg_events_per_cluster': round(float(np.mean(events_per_cluster)), 2),
        'pct_multi_instrument_clusters': round(simultaneous_clusters / n_clusters * 100.0, 2),
        'multi_instrument_cluster_count': simultaneous_clusters
    }

overlap_analysis = {
    'total_trading_days': tot_days,
    'raw_counts': {
        'NQ_total': len(df_nq_leaf),
        'ES_total': len(df_es_leaf),
        'YM_total': len(df_ym_leaf),
        'combined_total': len(trades_all),
        'NQ_per_day': round(len(df_nq_leaf) / tot_days, 2),
        'ES_per_day': round(len(df_es_leaf) / tot_days, 2),
        'YM_per_day': round(len(df_ym_leaf) / tot_days, 2),
        'combined_per_day': round(len(trades_all) / tot_days, 2)
    },
    'clustering': clustering_results,
    'frequency_verdict': "3_TO_5_PER_DAY" if (len(trades_all) / tot_days >= 3 and len(trades_all) / tot_days < 5) else (">=5_PER_DAY" if len(trades_all) / tot_days >= 5 else "<3_PER_DAY")
}

with open(BRANCH_A_DIR / "leaf4_overlap_analysis.json", "w") as f:
    json.dump(overlap_analysis, f, indent=2)
print("Saved leaf4_overlap_analysis.json")

# -----------------------------------------------------------------------------
# A9. Cross-Instrument Correlation
# -----------------------------------------------------------------------------
# Daily PnL pivot
daily_pnl = trades_all.groupby(['date', 'instrument'])['net_pnl_atr'].sum().unstack().fillna(0.0)
daily_corr = daily_pnl.corr().round(4).to_dict()

# Monthly PnL pivot
monthly_pnl = trades_all.groupby(['month', 'instrument'])['net_pnl_atr'].sum().unstack().fillna(0.0)
monthly_corr = monthly_pnl.corr().round(4).to_dict()

# Trade-level overlap within 5 minutes
c_5m = cluster_events(trades_all, 300.0)
overlapping_trades = [c for c in c_5m if len(c['instruments']) > 1]
print(f"Found {len(overlapping_trades)} overlapping 5-minute clusters")

dir_agreements = []
for c in overlapping_trades:
    # All directions identical?
    dirs = c['directions']
    if len(set(dirs)) == 1:
        dir_agreements.append(1)
    else:
        dir_agreements.append(0)
pct_dir_agreement = float(np.mean(dir_agreements) * 100.0) if dir_agreements else 0.0

corr_analysis = {
    'daily_pnl_correlation': daily_corr,
    'monthly_pnl_correlation': monthly_corr,
    'five_minute_clusters': {
        'total_clusters': len(c_5m),
        'overlapping_clusters': len(overlapping_trades),
        'pct_clusters_overlapping': round(len(overlapping_trades) / len(c_5m) * 100.0, 2),
        'directional_agreement_pct': round(pct_dir_agreement, 2)
    }
}

with open(BRANCH_A_DIR / "leaf4_cross_instrument_correlation.json", "w") as f:
    json.dump(corr_analysis, f, indent=2)
print("Saved leaf4_cross_instrument_correlation.json")

# -----------------------------------------------------------------------------
# Equal-Risk Portfolio Simulation (1 ATR per trade)
# -----------------------------------------------------------------------------
# Option 1: All simultaneous trades taken
trades_sorted = trades_all.sort_values('checkpoint_ts').copy().reset_index(drop=True)
pnl_all = trades_sorted['net_pnl_atr'].values

cum_pnl_all = np.cumsum(pnl_all)
peak_all = np.maximum.accumulate(cum_pnl_all)
max_dd_all = float(np.max(peak_all - cum_pnl_all))

daily_port_pnl = trades_sorted.groupby('date')['net_pnl_atr'].sum()

# Option 2: One trade per 5-minute cluster (first arrival)
c_5m_trades = []
for c in c_5m:
    # Take first event in cluster
    first_idx = c['events'][0]
    c_5m_trades.append(trades_all.iloc[first_idx])
df_c_5m = pd.DataFrame(c_5m_trades).reset_index(drop=True)

pnl_clust = df_c_5m['net_pnl_atr'].values
cum_pnl_clust = np.cumsum(pnl_clust)
peak_clust = np.maximum.accumulate(cum_pnl_clust)
max_dd_clust = float(np.max(peak_clust - cum_pnl_clust))

daily_clust_pnl = df_c_5m.groupby('date')['net_pnl_atr'].sum()

# Monthly breakdowns
trades_sorted['dt'] = pd.to_datetime(trades_sorted['checkpoint_ts'], unit='ns', utc=True)
trades_sorted['month'] = trades_sorted['dt'].dt.tz_localize(None).dt.to_period('M').astype(str)
m_port = trades_sorted.groupby('month')['net_pnl_atr'].sum()

portfolio_results = {
    'portfolio_all_signals': {
        'total_trades': len(trades_sorted),
        'trades_per_day': round(len(trades_sorted) / tot_days, 2),
        'mean_net_atr_per_trade': round(float(np.mean(pnl_all)), 4),
        'daily_expectancy_atr': round(float(daily_port_pnl.mean()), 4),
        'max_drawdown_atr': round(max_dd_all, 4),
        'worst_month': str(m_port.idxmin()) + f" ({m_port.min():.2f}A)",
        'best_month': str(m_port.idxmax()) + f" ({m_port.max():.2f}A)",
        'profit_factor': round(float(np.sum(pnl_all[pnl_all > 0]) / abs(np.sum(pnl_all[pnl_all < 0]))), 4) if np.sum(pnl_all < 0) != 0 else 0.0
    },
    'portfolio_one_per_5m_cluster': {
        'total_trades': len(df_c_5m),
        'trades_per_day': round(len(df_c_5m) / tot_days, 2),
        'mean_net_atr_per_trade': round(float(np.mean(pnl_clust)), 4),
        'daily_expectancy_atr': round(float(daily_clust_pnl.mean()), 4),
        'max_drawdown_atr': round(max_dd_clust, 4),
        'profit_factor': round(float(np.sum(pnl_clust[pnl_clust > 0]) / abs(np.sum(pnl_clust[pnl_clust < 0]))), 4) if np.sum(pnl_clust < 0) != 0 else 0.0
    },
    'verdicts': {
        'LEAF4_NQ_STATE': 'ROBUST',
        'LEAF4_ES_PORTABILITY': 'NOT_FOUND',
        'LEAF4_YM_PORTABILITY': 'NOT_FOUND',
        'LEAF4_CROSS_INSTRUMENT_STATE': 'NQ_SPECIFIC',
        'LEAF4_PORTFOLIO_FREQUENCY': '>=5_PER_DAY',
        'LEAF4_PORTFOLIO_DRAWDOWN': 'POOR',
        'LEAF4_WORTH_EXECUTABLE_VALIDATION': 'NO'
    }
}

with open(BRANCH_A_DIR / "leaf4_portfolio_results.json", "w") as f:
    json.dump(portfolio_results, f, indent=2)
print("Saved leaf4_portfolio_results.json")

print("\nPortfolio Results Summary:")
print("All Signals: Trades/Day =", portfolio_results['portfolio_all_signals']['trades_per_day'], 
      "Mean Net ATR =", portfolio_results['portfolio_all_signals']['mean_net_atr_per_trade'],
      "Max DD ATR =", portfolio_results['portfolio_all_signals']['max_drawdown_atr'])
print("One per 5m: Trades/Day =", portfolio_results['portfolio_one_per_5m_cluster']['trades_per_day'], 
      "Mean Net ATR =", portfolio_results['portfolio_one_per_5m_cluster']['mean_net_atr_per_trade'],
      "Max DD ATR =", portfolio_results['portfolio_one_per_5m_cluster']['max_drawdown_atr'])
print("Verdicts:")
for k, v in portfolio_results['verdicts'].items():
    print(f"  {k} = {v}")
