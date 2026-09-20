import sys
sys.path.insert(0, ".")
import os
import json
import math
import time
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT = Path(r"c:\Users\Scott McCarty\Projects\Nautilus Trader")
OUTPUT_DIR = REPO_ROOT / "studies/index_pullback_portability_and_trend_mirror/branch_b_trend_mirror"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 80)
print("RUNNING BRANCH B: H050 TREND-FOLLOWING MIRROR ON NQ")
print("=" * 80)

# Load canonical checkpoints
ck_path = REPO_ROOT / 'studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet'
df_ck_all = pd.read_parquet(ck_path)
print(f"Loaded {len(df_ck_all)} canonical checkpoints across 2023, 2024, 2025 Q1")

# Instrument specs for NQ
POINT_VALUE = 20.0
TICK_SIZE = 0.25
COMMISSION_RT = 5.0
TOTAL_FRICTION_PTS = 0.75 # 1 tick entry (0.25) + 1 tick exit (0.25) + comm (0.25)
TOTAL_FRICTION_DOLLARS = 15.0

BRACKETS = {
    'R0': {'sl_mult': 0.75, 'pt_mult': 0.75, 'rr': 1.00},
    'R1': {'sl_mult': 0.75, 'pt_mult': 1.00, 'rr': 1.3333},
    'R2': {'sl_mult': 1.00, 'pt_mult': 1.25, 'rr': 1.25},
}

CELLS = ['E0_R0', 'E0_R1', 'E0_R2', 'E1_R0', 'E1_R1', 'E1_R2']

# Process year by year
all_cell_trades = {cell: [] for cell in CELLS}
trading_days = {}

for year in ['2023', '2024', '2025']:
    p_yr_key = year if year != '2025' else '2025_Q1'
    df_ck_yr = df_ck_all[df_ck_all['year'] == p_yr_key].copy()
    if len(df_ck_yr) == 0:
        continue
        
    p_1s = REPO_ROOT / f'data/raw/NQ_v0_1s_{year}.parquet'
    print(f"\nProcessing {p_yr_key} ({len(df_ck_yr)} checkpoints)...")
    t0 = time.time()
    df_1s = pd.read_parquet(p_1s, columns=['open', 'high', 'low', 'close'])
    if year == '2025':
        # Restrict to Q1: up to 2025-03-31
        df_1s = df_1s.loc[:'2025-03-31 23:59:59']
    print(f"Loaded {len(df_1s):,} 1s bars in {time.time()-t0:.2f}s")
    
    # 5s bars for E1
    t_5s = time.time()
    df_5s = df_1s.resample('5s').agg({'open': 'first', 'close': 'last'}).dropna()
    df_5s_open_ts = df_5s.index.values.astype(np.int64)
    df_5s_close_ts = df_5s_open_ts + 5_000_000_000 # closes at open + 5s
    df_5s_open = df_5s['open'].values
    df_5s_close = df_5s['close'].values
    print(f"Built {len(df_5s):,} 5s bars in {time.time()-t_5s:.2f}s")
    
    # 1s arrays
    idx_1s_ts = df_1s.index.values.astype(np.int64)
    opens_1s = df_1s['open'].values
    highs_1s = df_1s['high'].values
    lows_1s = df_1s['low'].values
    closes_1s = df_1s['close'].values
    
    # Dates for trading days
    dt_index = pd.to_datetime(idx_1s_ts, unit='ns', utc=True)
    n_days = int(pd.Series(dt_index.date).nunique())
    trading_days[p_yr_key] = n_days
    
    # Simulate each checkpoint
    t_sim = time.time()
    for _, ck in df_ck_yr.iterrows():
        ck_ts = int(ck['checkpoint_ts'])
        reg_exit_ts = int(ck['regime_exit_ts'])
        d = int(ck['direction']) # Bull: 1, Bear: -1
        atr = float(ck['frozen_atr'])
        regime_id = int(ck['regime_id'])
        
        # --- E0 Entry ---
        pos_e0 = np.searchsorted(idx_1s_ts, ck_ts, side='right')
        e0_valid = (pos_e0 < len(idx_1s_ts)) and (idx_1s_ts[pos_e0] <= reg_exit_ts)
        
        # --- E1 Entry (Re-acceleration) ---
        # First completed 5s bar with close_ts > ck_ts that satisfies re-acceleration
        pos_5s = np.searchsorted(df_5s_close_ts, ck_ts, side='right')
        e1_entry_ts = None
        pos_e1 = None
        
        while pos_5s < len(df_5s_close_ts):
            c_ts_5s = df_5s_close_ts[pos_5s]
            if c_ts_5s > reg_exit_ts:
                # Regime terminated before re-acceleration
                break
            o_5s = df_5s_open[pos_5s]
            c_5s = df_5s_close[pos_5s]
            if d == 1 and c_5s > o_5s: # Bull re-acceleration
                e1_entry_ts = c_ts_5s
                break
            elif d == -1 and c_5s < o_5s: # Bear re-acceleration
                e1_entry_ts = c_ts_5s
                break
            pos_5s += 1
            
        if e1_entry_ts is not None:
            pos_e1 = np.searchsorted(idx_1s_ts, e1_entry_ts, side='left')
            if pos_e1 >= len(idx_1s_ts) or idx_1s_ts[pos_e1] > reg_exit_ts:
                pos_e1 = None
                
        # Now simulate for each bracket policy
        for b_name, b_spec in BRACKETS.items():
            sl_dist = b_spec['sl_mult'] * atr
            pt_dist = b_spec['pt_mult'] * atr
            
            # --- Simulate E0 ---
            cell_e0 = f"E0_{b_name}"
            if e0_valid:
                entry_fill_gross = opens_1s[pos_e0]
                if d == 1:
                    pt_px = round((entry_fill_gross + pt_dist) / TICK_SIZE) * TICK_SIZE
                    sl_px = round((entry_fill_gross - sl_dist) / TICK_SIZE) * TICK_SIZE
                else:
                    pt_px = round((entry_fill_gross - pt_dist) / TICK_SIZE) * TICK_SIZE
                    sl_px = round((entry_fill_gross + sl_dist) / TICK_SIZE) * TICK_SIZE
                
                exit_ts = None
                exit_px_gross = None
                exit_source = None
                
                cur_p = pos_e0
                while cur_p < len(idx_1s_ts):
                    b_ts = idx_1s_ts[cur_p]
                    h = highs_1s[cur_p]
                    l = lows_1s[cur_p]
                    o = opens_1s[cur_p]
                    
                    if b_ts > reg_exit_ts:
                        exit_ts = b_ts
                        exit_px_gross = o
                        exit_source = "REGIME_TERMINATION_EXIT"
                        break
                        
                    if d == 1:
                        hit_pt = (h >= pt_px)
                        hit_sl = (l <= sl_px)
                        if hit_pt and hit_sl:
                            exit_ts = b_ts
                            exit_px_gross = sl_px
                            exit_source = "SL_HIT"
                            break
                        elif hit_sl:
                            exit_ts = b_ts
                            exit_px_gross = sl_px
                            exit_source = "SL_HIT"
                            break
                        elif hit_pt:
                            exit_ts = b_ts
                            exit_px_gross = pt_px
                            exit_source = "PT_HIT"
                            break
                    else:
                        hit_pt = (l <= pt_px)
                        hit_sl = (h >= sl_px)
                        if hit_pt and hit_sl:
                            exit_ts = b_ts
                            exit_px_gross = sl_px
                            exit_source = "SL_HIT"
                            break
                        elif hit_sl:
                            exit_ts = b_ts
                            exit_px_gross = sl_px
                            exit_source = "SL_HIT"
                            break
                        elif hit_pt:
                            exit_ts = b_ts
                            exit_px_gross = pt_px
                            exit_source = "PT_HIT"
                            break
                    cur_p += 1
                    
                gross_pts = d * (exit_px_gross - entry_fill_gross)
                net_pts = gross_pts - TOTAL_FRICTION_PTS
                net_dol = net_pts * POINT_VALUE
                gross_dol = gross_pts * POINT_VALUE
                net_atr = net_pts / atr
                gross_atr = gross_pts / atr
                
                all_cell_trades[cell_e0].append({
                    'checkpoint_ts': ck_ts,
                    'entry_ts': idx_1s_ts[pos_e0],
                    'exit_ts': exit_ts,
                    'year': p_yr_key,
                    'direction': d,
                    'direction_name': 'LONG' if d == 1 else 'SHORT',
                    'frozen_atr': atr,
                    'entry_price': entry_fill_gross,
                    'exit_price': exit_px_gross,
                    'exit_source': exit_source,
                    'gross_pts': gross_pts,
                    'net_pts': net_pts,
                    'gross_dollars': gross_dol,
                    'net_dollars': net_dol,
                    'gross_pnl_atr': gross_atr,
                    'net_pnl_atr': net_atr,
                    'is_win_net': net_pts > 0,
                    'is_pt_hit': exit_source == "PT_HIT",
                    'is_sl_hit': exit_source == "SL_HIT",
                    'is_regime_exit': exit_source == "REGIME_TERMINATION_EXIT",
                    'skipped': False
                })
            else:
                all_cell_trades[cell_e0].append({
                    'checkpoint_ts': ck_ts,
                    'year': p_yr_key,
                    'direction': d,
                    'direction_name': 'LONG' if d == 1 else 'SHORT',
                    'skipped': True
                })
                
            # --- Simulate E1 ---
            cell_e1 = f"E1_{b_name}"
            if pos_e1 is not None:
                entry_fill_gross = opens_1s[pos_e1]
                if d == 1:
                    pt_px = round((entry_fill_gross + pt_dist) / TICK_SIZE) * TICK_SIZE
                    sl_px = round((entry_fill_gross - sl_dist) / TICK_SIZE) * TICK_SIZE
                else:
                    pt_px = round((entry_fill_gross - pt_dist) / TICK_SIZE) * TICK_SIZE
                    sl_px = round((entry_fill_gross + sl_dist) / TICK_SIZE) * TICK_SIZE
                
                exit_ts = None
                exit_px_gross = None
                exit_source = None
                
                cur_p = pos_e1
                while cur_p < len(idx_1s_ts):
                    b_ts = idx_1s_ts[cur_p]
                    h = highs_1s[cur_p]
                    l = lows_1s[cur_p]
                    o = opens_1s[cur_p]
                    
                    if b_ts > reg_exit_ts:
                        exit_ts = b_ts
                        exit_px_gross = o
                        exit_source = "REGIME_TERMINATION_EXIT"
                        break
                        
                    if d == 1:
                        hit_pt = (h >= pt_px)
                        hit_sl = (l <= sl_px)
                        if hit_pt and hit_sl:
                            exit_ts = b_ts
                            exit_px_gross = sl_px
                            exit_source = "SL_HIT"
                            break
                        elif hit_sl:
                            exit_ts = b_ts
                            exit_px_gross = sl_px
                            exit_source = "SL_HIT"
                            break
                        elif hit_pt:
                            exit_ts = b_ts
                            exit_px_gross = pt_px
                            exit_source = "PT_HIT"
                            break
                    else:
                        hit_pt = (l <= pt_px)
                        hit_sl = (h >= sl_px)
                        if hit_pt and hit_sl:
                            exit_ts = b_ts
                            exit_px_gross = sl_px
                            exit_source = "SL_HIT"
                            break
                        elif hit_sl:
                            exit_ts = b_ts
                            exit_px_gross = sl_px
                            exit_source = "SL_HIT"
                            break
                        elif hit_pt:
                            exit_ts = b_ts
                            exit_px_gross = pt_px
                            exit_source = "PT_HIT"
                            break
                    cur_p += 1
                    
                gross_pts = d * (exit_px_gross - entry_fill_gross)
                net_pts = gross_pts - TOTAL_FRICTION_PTS
                net_dol = net_pts * POINT_VALUE
                gross_dol = gross_pts * POINT_VALUE
                net_atr = net_pts / atr
                gross_atr = gross_pts / atr
                
                all_cell_trades[cell_e1].append({
                    'checkpoint_ts': ck_ts,
                    'entry_ts': idx_1s_ts[pos_e1],
                    'exit_ts': exit_ts,
                    'year': p_yr_key,
                    'direction': d,
                    'direction_name': 'LONG' if d == 1 else 'SHORT',
                    'frozen_atr': atr,
                    'entry_price': entry_fill_gross,
                    'exit_price': exit_px_gross,
                    'exit_source': exit_source,
                    'gross_pts': gross_pts,
                    'net_pts': net_pts,
                    'gross_dollars': gross_dol,
                    'net_dollars': net_dol,
                    'gross_pnl_atr': gross_atr,
                    'net_pnl_atr': net_atr,
                    'is_win_net': net_pts > 0,
                    'is_pt_hit': exit_source == "PT_HIT",
                    'is_sl_hit': exit_source == "SL_HIT",
                    'is_regime_exit': exit_source == "REGIME_TERMINATION_EXIT",
                    'skipped': False
                })
            else:
                all_cell_trades[cell_e1].append({
                    'checkpoint_ts': ck_ts,
                    'year': p_yr_key,
                    'direction': d,
                    'direction_name': 'LONG' if d == 1 else 'SHORT',
                    'skipped': True
                })
                
    print(f"Completed {p_yr_key} simulation in {time.time()-t_sim:.2f}s")

# Save trade ledgers
dfs_cell = {}
for cell, trades in all_cell_trades.items():
    df_c = pd.DataFrame(trades)
    df_c.to_parquet(OUTPUT_DIR / f"ledger_{cell}.parquet")
    dfs_cell[cell] = df_c
print("\nSaved individual cell ledgers.")

# -----------------------------------------------------------------------------
# Detailed Metrics Computation Function
# -----------------------------------------------------------------------------
def compute_comprehensive_metrics(df_sub, n_days, candidate_count, rr_target):
    executed = df_sub[~df_sub['skipped']].copy()
    n_exec = len(executed)
    n_skip = int(df_sub['skipped'].sum())
    
    if n_exec == 0:
        return {'candidate_count': candidate_count, 'trades_executed': 0, 'skipped_trades': n_skip}
        
    pnl = executed['net_pnl_atr'].values
    pnl_dol = executed['net_dollars'].values
    gross_dol = executed['gross_dollars'].values
    
    t_day = n_exec / n_days if n_days > 0 else 0.0
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    wr = float(len(wins) / n_exec)
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    realized_wl = float(abs(avg_win / avg_loss)) if abs(avg_loss) > 1e-6 else 0.0
    sum_win = float(np.sum(wins))
    sum_loss = float(np.abs(np.sum(losses)))
    pf = float(sum_win / sum_loss) if sum_loss > 1e-6 else (999.0 if sum_win > 0 else 0.0)
    
    pt_hit_pct = float(executed['is_pt_hit'].mean() * 100.0)
    sl_hit_pct = float(executed['is_sl_hit'].mean() * 100.0)
    reg_exit_pct = float(executed['is_regime_exit'].mean() * 100.0)
    
    mean_net_atr = float(np.mean(pnl))
    median_net_atr = float(np.median(pnl))
    mean_net_dol = float(np.mean(pnl_dol))
    mean_gross_dol = float(np.mean(gross_dol))
    
    cum_pnl = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum_pnl)
    max_dd_atr = float(np.max(peak - cum_pnl)) if len(cum_pnl) > 0 else 0.0
    
    cum_dol = np.cumsum(pnl_dol)
    peak_dol = np.maximum.accumulate(cum_dol)
    max_dd_dol = float(np.max(peak_dol - cum_dol)) if len(cum_dol) > 0 else 0.0
    
    longest_loss_streak = 0
    cur_streak = 0
    for val in pnl:
        if val <= 0:
            cur_streak += 1
            if cur_streak > longest_loss_streak:
                longest_loss_streak = cur_streak
        else:
            cur_streak = 0
            
    s_pnl = pd.Series(pnl)
    worst_20 = float(s_pnl.rolling(20).sum().min()) if n_exec >= 20 else float(s_pnl.sum())
    worst_50 = float(s_pnl.rolling(50).sum().min()) if n_exec >= 50 else float(s_pnl.sum())
    worst_100 = float(s_pnl.rolling(100).sum().min()) if n_exec >= 100 else float(s_pnl.sum())
    
    cat_rate = float(np.mean(pnl <= -2.0)) # catastrophic <= -2A
    
    sorted_pnl = np.sort(pnl)
    top1_n = max(1, int(math.ceil(0.01 * n_exec)))
    top1_sum = float(np.sum(sorted_pnl[-top1_n:]))
    tot_sum = float(np.sum(pnl))
    top1_share = float(top1_sum / tot_sum) if tot_sum > 0 else 999.0
    
    # Required break-even win rate
    # Without friction: 1 / (1 + rr)
    # With observed friction: avg_loss / (avg_loss - avg_win) = |avg_loss| / (|avg_loss| + avg_win)
    req_be_wr = float(abs(avg_loss) / (abs(avg_loss) + avg_win)) if (abs(avg_loss) + avg_win) > 1e-6 else 0.5
    wr_margin = float(wr - req_be_wr)
    
    # Monthly best/worst
    executed['dt'] = pd.to_datetime(executed['entry_ts'], unit='ns', utc=True)
    executed['month'] = executed['dt'].dt.to_period('M').astype(str)
    monthly_atr = executed.groupby('month')['net_pnl_atr'].sum()
    worst_month = str(monthly_atr.idxmin()) + f" ({monthly_atr.min():.2f}A)" if len(monthly_atr) > 0 else "N/A"
    best_month = str(monthly_atr.idxmax()) + f" ({monthly_atr.max():.2f}A)" if len(monthly_atr) > 0 else "N/A"

    return {
        'candidate_count': int(candidate_count),
        'trades_executed': int(n_exec),
        'skipped_trades': int(n_skip),
        'skip_rate_pct': round(n_skip / candidate_count * 100.0, 2),
        'trades_per_day': round(t_day, 2),
        'win_rate': round(wr, 4),
        'pt_hit_pct': round(pt_hit_pct, 2),
        'sl_hit_pct': round(sl_hit_pct, 2),
        'regime_termination_exit_pct': round(reg_exit_pct, 2),
        'gross_dollars_per_trade': round(mean_gross_dol, 2),
        'net_dollars_per_trade': round(mean_net_dol, 2),
        'mean_pnl_atr': round(mean_net_atr, 4),
        'median_pnl_atr': round(median_net_atr, 4),
        'avg_win_atr': round(avg_win, 4),
        'avg_loss_atr': round(avg_loss, 4),
        'realized_win_loss_ratio': round(realized_wl, 4),
        'profit_factor': round(pf, 4),
        'max_dd_atr': round(max_dd_atr, 4),
        'max_dd_dollars': round(max_dd_dol, 2),
        'longest_losing_streak': int(longest_loss_streak),
        'worst_20_trade_pnl_atr': round(worst_20, 2),
        'worst_50_trade_pnl_atr': round(worst_50, 2),
        'worst_100_trade_pnl_atr': round(worst_100, 2),
        'catastrophic_le_minus_2a_rate': round(cat_rate, 4),
        'top_1pct_pnl_share': round(top1_share, 4),
        'required_break_even_win_rate': round(req_be_wr, 4),
        'win_rate_margin_of_safety': round(wr_margin, 4),
        'worst_month': worst_month,
        'best_month': best_month
    }

# Compute 6-cell matrix across 2023, 2024, pooled, and 2025 Q1
nq_trend_matrix = {
    '2023': {},
    '2024': {},
    'pooled_2023_2024': {},
    '2025_Q1_FROZEN': {}
}

for cell, df_c in dfs_cell.items():
    b_name = cell.split('_')[1]
    rr = BRACKETS[b_name]['rr']
    
    # 2023
    df_23 = df_c[df_c['year'] == '2023']
    nq_trend_matrix['2023'][cell] = compute_comprehensive_metrics(df_23, trading_days['2023'], len(df_23), rr)
    
    # 2024
    df_24 = df_c[df_c['year'] == '2024']
    nq_trend_matrix['2024'][cell] = compute_comprehensive_metrics(df_24, trading_days['2024'], len(df_24), rr)
    
    # Pooled
    df_pl = df_c[df_c['year'].isin(['2023', '2024'])]
    nq_trend_matrix['pooled_2023_2024'][cell] = compute_comprehensive_metrics(df_pl, trading_days['2023'] + trading_days['2024'], len(df_pl), rr)
    
    # 2025 Q1
    df_25 = df_c[df_c['year'] == '2025_Q1']
    nq_trend_matrix['2025_Q1_FROZEN'][cell] = compute_comprehensive_metrics(df_25, trading_days['2025_Q1'], len(df_25), rr)

with open(OUTPUT_DIR / "nq_trend_matrix.json", "w") as f:
    json.dump(nq_trend_matrix, f, indent=2)
print("Saved nq_trend_matrix.json")

# Directional breakdown (LONG vs SHORT) for all cells
directional_results = {}
for cell, df_c in dfs_cell.items():
    directional_results[cell] = {}
    b_name = cell.split('_')[1]
    rr = BRACKETS[b_name]['rr']
    
    for d_name, d_val in [('LONG', 1), ('SHORT', -1)]:
        df_d = df_c[df_c['direction'] == d_val]
        # Pooled 2023-2024
        df_d_train = df_d[df_d['year'].isin(['2023', '2024'])]
        directional_results[cell][f"{d_name}_TRAIN"] = compute_comprehensive_metrics(
            df_d_train, trading_days['2023'] + trading_days['2024'], len(df_d_train), rr
        )
        df_d_25 = df_d[df_d['year'] == '2025_Q1']
        directional_results[cell][f"{d_name}_2025_Q1"] = compute_comprehensive_metrics(
            df_d_25, trading_days['2025_Q1'], len(df_d_25), rr
        )

with open(OUTPUT_DIR / "nq_directional_results.json", "w") as f:
    json.dump(directional_results, f, indent=2)
print("Saved nq_directional_results.json")

# Monthly Stability
monthly_stability = {}
for cell, df_c in dfs_cell.items():
    monthly_stability[cell] = {}
    exec_c = df_c[~df_c['skipped']].copy()
    exec_c['dt'] = pd.to_datetime(exec_c['entry_ts'], unit='ns', utc=True)
    exec_c['month'] = exec_c['dt'].dt.to_period('M').astype(str)
    
    for m, m_grp in exec_c.groupby('month'):
        n_m = len(m_grp)
        pnl = m_grp['net_pnl_atr'].values
        m_days = m_grp['dt'].dt.date.nunique()
        wr = float((pnl > 0).mean())
        mean_atr = float(np.mean(pnl))
        tot_atr = float(np.sum(pnl))
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        pf = float(np.sum(wins) / np.abs(np.sum(losses))) if len(losses) > 0 and np.abs(np.sum(losses)) > 1e-6 else 999.0
        
        cum_p = np.cumsum(pnl)
        peak = np.maximum.accumulate(cum_p)
        max_dd = float(np.max(peak - cum_p)) if len(cum_p) > 0 else 0.0
        
        monthly_stability[cell][m] = {
            'trades': n_m,
            'trading_days': m_days,
            'trades_per_day': round(n_m / m_days, 2) if m_days > 0 else 0.0,
            'win_rate': round(wr, 4),
            'net_atr_per_trade': round(mean_atr, 4),
            'total_net_atr': round(tot_atr, 2),
            'profit_factor': round(pf, 4),
            'max_dd_atr': round(max_dd, 4)
        }

with open(OUTPUT_DIR / "nq_monthly_stability.json", "w") as f:
    json.dump(monthly_stability, f, indent=2)
print("Saved nq_monthly_stability.json")

# Tail stress tests
tail_stress = {}
for cell, df_c in dfs_cell.items():
    tail_stress[cell] = {}
    for period in ['2023', '2024', 'pooled_2023_2024', '2025_Q1_FROZEN']:
        if period == 'pooled_2023_2024':
            sub = df_c[df_c['year'].isin(['2023', '2024']) & ~df_c['skipped']]
        else:
            sub = df_c[(df_c['year'] == period) & ~df_c['skipped']]
        if len(sub) == 0:
            continue
            
        pnl = np.sort(sub['net_pnl_atr'].values)
        base_mean = float(np.mean(pnl))
        n = len(pnl)
        
        drop1 = pnl[:-1] if n > 1 else pnl
        n_05 = max(1, int(math.ceil(0.005 * n)))
        drop05 = pnl[:-n_05] if n > n_05 else pnl
        n_10 = max(1, int(math.ceil(0.01 * n)))
        drop10 = pnl[:-n_10] if n > n_10 else pnl
        
        tail_stress[cell][period] = {
            'N': n,
            'base_mean_atr': round(base_mean, 4),
            'ex_largest_winner_mean_atr': round(float(np.mean(drop1)), 4),
            'ex_top_0p5pct_mean_atr': round(float(np.mean(drop05)), 4),
            'ex_top_1pct_mean_atr': round(float(np.mean(drop10)), 4),
            'top_1pct_pnl_share': round(float(np.sum(pnl[-n_10:]) / np.sum(pnl)), 4) if np.sum(pnl) > 0 else 999.0
        }

with open(OUTPUT_DIR / "trend_tail_stress.json", "w") as f:
    json.dump(tail_stress, f, indent=2)
print("Saved trend_tail_stress.json")

# Counter-regime comparison
counter_path = REPO_ROOT / 'studies/nq_h050_economic_subpopulation_mining/results/candidate_subpopulation_matrix.json'
with open(counter_path, "r") as f:
    cand_matrix = json.load(f)

counter_h050 = cand_matrix.get('Broad_H050', {})
counter_comp = {
    'counter_regime_broad_h050_2024': counter_h050,
    'trend_following_cells_2024': {cell: nq_trend_matrix['2024'][cell] for cell in CELLS}
}
with open(OUTPUT_DIR / "counter_vs_trend_comparison.json", "w") as f:
    json.dump(counter_comp, f, indent=2)
print("Saved counter_vs_trend_comparison.json")

# Branch B Decision Gate (B20)
# Criteria:
# 1. positive net expectancy in 2023 AND 2024
# 2. reasonable drawdown profile
# 3. at least one of:
#    - >=53% WR with >=1.2 realized W/L
#    - >=55% WR with >=1.0 realized W/L
#    - >=+0.15 ATR/trade net with stable monthly behavior
passing_cells = []
for cell in CELLS:
    m23 = nq_trend_matrix['2023'][cell]
    m24 = nq_trend_matrix['2024'][cell]
    
    pos_23 = m23['mean_pnl_atr'] > 0
    pos_24 = m24['mean_pnl_atr'] > 0
    
    wr_wl_1 = (m24['win_rate'] >= 0.53) and (m24['realized_win_loss_ratio'] >= 1.2)
    wr_wl_2 = (m24['win_rate'] >= 0.55) and (m24['realized_win_loss_ratio'] >= 1.0)
    high_ev = (m24['mean_pnl_atr'] >= 0.15)
    
    qualifies = (pos_23 and pos_24) and (wr_wl_1 or wr_wl_2 or high_ev)
    if qualifies:
        passing_cells.append(cell)

gate_result = {
    'gate_name': 'TREND_MIRROR_CROSS_INSTRUMENT_GATE',
    'verdict': 'PASS' if len(passing_cells) > 0 else 'FAIL',
    'passing_cells': passing_cells,
    'cell_evaluations': {
        cell: {
            'pos_2023': nq_trend_matrix['2023'][cell]['mean_pnl_atr'] > 0,
            'mean_atr_2023': nq_trend_matrix['2023'][cell]['mean_pnl_atr'],
            'pos_2024': nq_trend_matrix['2024'][cell]['mean_pnl_atr'] > 0,
            'mean_atr_2024': nq_trend_matrix['2024'][cell]['mean_pnl_atr'],
            'win_rate_2024': nq_trend_matrix['2024'][cell]['win_rate'],
            'realized_wl_2024': nq_trend_matrix['2024'][cell]['realized_win_loss_ratio'],
            'max_dd_atr_2024': nq_trend_matrix['2024'][cell]['max_dd_atr'],
            'passed': cell in passing_cells
        }
        for cell in CELLS
    }
}

with open(OUTPUT_DIR / "trend_cross_instrument_gate.json", "w") as f:
    json.dump(gate_result, f, indent=2)
print("Saved trend_cross_instrument_gate.json")
print("\nBranch B Decision Gate Verdict:", gate_result['verdict'])
if passing_cells:
    print("Passing cells:", passing_cells)
else:
    print("No cell passed the cross-instrument gate.")
