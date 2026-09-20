import sys
sys.path.insert(0, ".")
import os
import json
import math
import time
from pathlib import Path
import numpy as np
import pandas as pd
from features.trackers.regime_dual_ema import DualEmaRegimeTracker

REPO_ROOT = Path(r"c:\Users\Scott McCarty\Projects\Nautilus Trader")
OUTPUT_DIR = REPO_ROOT / "studies/index_pullback_portability_and_trend_mirror/branch_a_leaf4_portability"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

spec = {
    'point_value': 5.0,
    'tick_size': 1.0,
    'commission_rt': 5.0,
    'slippage_rt_ticks': 2,
    'total_friction_pts': 2.0 + 1.0, # 2 ticks (2.0) + $5 comm (1.0 pt) = 3.0 pts ($15)
    'total_friction_dollars': 15.0,
}

YEARS = ['2023', '2024', '2025']
inst_name = 'YM'

print(f"=======================================================")
print(f"PROCESSING INSTRUMENT: {inst_name} (OPTIMIZED FAST)")
print(f"=======================================================")

all_checkpoints = []
trading_days = {}

for year in YEARS:
    p_yr_key = year if year != '2025' else '2025_Q1'
    p_1s = REPO_ROOT / f"data/raw/{inst_name}_v0_1s_{year}.parquet"
    if not p_1s.exists():
        print(f"File {p_1s} not found, skipping...")
        continue
        
    print(f"\n--- Loading {inst_name} {p_yr_key} ---")
    t0 = time.time()
    df_1s = pd.read_parquet(p_1s, columns=['open', 'high', 'low', 'close'])
    if year == '2025':
        df_1s = df_1s.loc[:'2025-03-31 23:59:59']
    print(f"Loaded {len(df_1s):,} 1s bars in {time.time()-t0:.2f}s")
    
    # Resample to 1m
    t_1m = time.time()
    df_1m = df_1s.resample('1min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    print(f"Resampled to {len(df_1m):,} 1m bars in {time.time()-t_1m:.2f}s")
    
    # Rolling 15m range on 1m completed bars
    df_1m['roll_15m_high'] = df_1m['high'].rolling(15, min_periods=1).max()
    df_1m['roll_15m_low'] = df_1m['low'].rolling(15, min_periods=1).min()
    df_1m['roll_15m_range'] = df_1m['roll_15m_high'] - df_1m['roll_15m_low']
    
    # Dual EMA tracker on 1m
    tracker = DualEmaRegimeTracker(timeframe='1m')
    df_1m_ts = df_1m.index.values.astype(np.int64)
    df_1m_high = df_1m['high'].values
    df_1m_low = df_1m['low'].values
    df_1m_close = df_1m['close'].values
    df_1m_open = df_1m['open'].values
    df_1m_r15 = df_1m['roll_15m_range'].values
    
    print("Running regime tracker on 1m completed bars...")
    t_trk = time.time()
    atrs_1m = []
    regimes = []
    cur_reg = None
    prior_reg = None
    
    for i in range(len(df_1m)):
        up = tracker.observe(df_1m_high[i], df_1m_low[i], df_1m_close[i])
        atrs_1m.append(up.atr if up.atr is not None else 1.0)
        
        if up.flipped:
            if cur_reg is not None:
                cur_reg['end_ts'] = df_1m_ts[i]
                cur_reg['end_close'] = df_1m_close[i]
                prior_reg = cur_reg.copy()
                regimes.append(cur_reg)
            cur_reg = {
                'regime_id': df_1m_ts[i],
                'direction': up.regime,
                'start_ts': df_1m_ts[i],
                'start_price': df_1m_open[i],
                'start_atr': up.atr if up.atr is not None else 1.0,
                'prior_mfe_price': prior_reg['mfe_price'] if prior_reg is not None else df_1m_open[i],
                'mfe_price': df_1m_high[i] if up.regime == 1 else df_1m_low[i]
            }
        elif cur_reg is not None:
            if cur_reg['direction'] == 1:
                cur_reg['mfe_price'] = max(cur_reg['mfe_price'], df_1m_high[i])
            else:
                cur_reg['mfe_price'] = min(cur_reg['mfe_price'], df_1m_low[i])
                
    if cur_reg is not None and 'end_ts' not in cur_reg:
        cur_reg['end_ts'] = df_1m_ts[-1]
        regimes.append(cur_reg)
        
    print(f"Tracked {len(regimes):,} regimes in {time.time()-t_trk:.2f}s")
    
    df_1m_atrs = np.array(atrs_1m)
    idx_1s_ts = df_1s.index.values.astype(np.int64)
    opens_1s = df_1s['open'].values
    highs_1s = df_1s['high'].values
    lows_1s = df_1s['low'].values
    closes_1s = df_1s['close'].values
    
    idx_ct = df_1s.index.tz_convert('America/Chicago')
    ct_hours = idx_ct.hour.values
    ct_mins = idx_ct.minute.values
    ct_secs = idx_ct.second.values
    ct_tot_mins = ct_hours * 60 + ct_mins
    
    rth_mask = (ct_tot_mins >= 510) & (ct_tot_mins < 915)
    rth_dates = pd.Series(idx_ct[rth_mask].date).nunique()
    trading_days[p_yr_key] = rth_dates
    
    print("Detecting H050 pullback checkpoints during RTH...")
    t_ck = time.time()
    reg_df = pd.DataFrame(regimes)
    year_ck_list = []
    
    for _, reg in reg_df.iterrows():
        r_start = reg['start_ts']
        r_end = reg['end_ts']
        d = int(reg['direction'])
        frozen_atr = max(float(reg['start_atr']), 1e-4)
        prior_mfe = float(reg['prior_mfe_price'])
        
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
            else:
                if l_k < running_mfe_px:
                    running_mfe_px = l_k
                    in_pullback = False
                    
            if d == 1:
                pb_dist = running_mfe_px - c_k
            else:
                pb_dist = c_k - running_mfe_px
                
            pb_depth_atr = pb_dist / frozen_atr
            
            if (not in_pullback) and (pb_depth_atr >= 0.50):
                in_pullback = True
                
                if r_rth[k]:
                    min_from_rth_open = float(r_ct_m[k] - 510 + r_ct_s[k] / 60.0)
                    pos_1m = np.searchsorted(df_1m_ts, ts_k, side='right') - 1
                    if pos_1m >= 0:
                        cur_1m_atr = max(df_1m_atrs[pos_1m], 1e-4)
                        cur_1m_r15 = df_1m_r15[pos_1m]
                        realized_range_15m_atr = cur_1m_r15 / cur_1m_atr
                    else:
                        cur_1m_atr = frozen_atr
                        realized_range_15m_atr = 2.0
                        
                    dist_prior_mfe_atr = (d * (c_k - prior_mfe)) / cur_1m_atr
                    is_leaf4 = (
                        (min_from_rth_open <= 380.649994) and
                        (realized_range_15m_atr <= 9.344128) and
                        (dist_prior_mfe_atr <= 1.738367)
                    )
                    
                    year_ck_list.append({
                        'instrument': inst_name,
                        'year': p_yr_key,
                        'regime_id': int(reg['regime_id']),
                        'regime_exit_ts': int(r_end),
                        'checkpoint_ts': int(ts_k),
                        'checkpoint_price': float(c_k),
                        'direction': d,
                        'direction_name': 'Bull' if d == 1 else 'Bear',
                        'frozen_atr': float(frozen_atr),
                        'cur_1m_atr': float(cur_1m_atr),
                        'minutes_from_rth_open': round(min_from_rth_open, 4),
                        'realized_range_15m_atr': round(float(realized_range_15m_atr), 4),
                        'current_price_from_prior_mfe_atr__tf_1m': round(float(dist_prior_mfe_atr), 4),
                        'is_leaf4': bool(is_leaf4),
                        '1s_pos': p_start + k
                    })
                    
    print(f"Emitted {len(year_ck_list):,} RTH H050 checkpoints ({sum(1 for c in year_ck_list if c['is_leaf4']):,} Leaf 4) in {time.time()-t_ck:.2f}s")
    
    print("Simulating counter-regime C1 trade outcomes (Fast)...")
    t_trade = time.time()
    year_ck_list.sort(key=lambda x: x['checkpoint_ts'])
    
    n_ck = len(year_ck_list)
    for idx_ck in range(n_ck):
        ck_item = year_ck_list[idx_ck]
        pos_1s = ck_item['1s_pos']
        ck_ts = ck_item['checkpoint_ts']
        reg_exit = ck_item['regime_exit_ts']
        d = ck_item['direction']
        c_dir = -d
        atr = ck_item['frozen_atr']
        
        if pos_1s + 1 < len(idx_1s_ts):
            entry_fill_gross = opens_1s[pos_1s + 1]
            entry_ts = idx_1s_ts[pos_1s + 1]
        else:
            continue
            
        opposing_ts = None
        for j in range(idx_ck + 1, n_ck):
            next_ck = year_ck_list[j]
            if next_ck['checkpoint_ts'] > reg_exit:
                break
            if next_ck['direction'] == -d:
                opposing_ts = next_ck['checkpoint_ts']
                break
                
        exit_target_ts = opposing_ts if opposing_ts is not None else reg_exit
        pos_exit = np.searchsorted(idx_1s_ts, exit_target_ts, side='right')
        if pos_exit < len(idx_1s_ts):
            exit_fill_gross = opens_1s[pos_exit]
            exit_ts = idx_1s_ts[pos_exit]
        else:
            exit_fill_gross = closes_1s[-1]
            exit_ts = idx_1s_ts[-1]
            
        gross_pts = c_dir * (exit_fill_gross - entry_fill_gross)
        net_pts = gross_pts - spec['total_friction_pts']
        gross_dol = gross_pts * spec['point_value']
        net_dol = net_pts * spec['point_value']
        gross_atr = gross_pts / atr
        net_atr = net_pts / atr
        
        ck_item['entry_ts'] = int(entry_ts)
        ck_item['exit_ts'] = int(exit_ts)
        ck_item['entry_price'] = float(entry_fill_gross)
        ck_item['exit_price'] = float(exit_fill_gross)
        ck_item['gross_pts'] = round(float(gross_pts), 4)
        ck_item['net_pts'] = round(float(net_pts), 4)
        ck_item['gross_dollars'] = round(float(gross_dol), 2)
        ck_item['net_dollars'] = round(float(net_dol), 2)
        ck_item['gross_pnl_atr'] = round(float(gross_atr), 4)
        ck_item['net_pnl_atr'] = round(float(net_atr), 4)
        ck_item['is_win_net'] = net_pts > 0
        
        all_checkpoints.append(ck_item)
        
    print(f"Completed trade simulation in {time.time()-t_trade:.2f}s")

df_all_ck = pd.DataFrame(all_checkpoints)
df_all_ck.to_parquet(OUTPUT_DIR / f"{inst_name.lower()}_h050_observations.parquet")
print(f"\nSaved {inst_name.lower()}_h050_observations.parquet ({len(df_all_ck):,} rows)")

def compute_leaf4_metrics(df_sub, n_days, total_pop):
    n = len(df_sub)
    if n == 0:
        return {'N': 0, 'trades_per_day': 0.0, 'coverage_pct': 0.0, 'mean_pnl_atr': 0.0}
    pnl = df_sub['net_pnl_atr'].values
    pnl_dol = df_sub['net_dollars'].values
    t_day = n / n_days if n_days > 0 else 0.0
    cov = n / total_pop * 100.0 if total_pop > 0 else 0.0
    mean_atr = float(np.mean(pnl))
    median_atr = float(np.median(pnl))
    std_atr = float(np.std(pnl, ddof=1)) if n > 1 else 0.0
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    wr = float(len(wins) / n)
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
    sorted_pnl = np.sort(pnl)
    top1_n = max(1, int(math.ceil(0.01 * n)))
    pnl_ex_top1 = sorted_pnl[:-top1_n] if n > top1_n else sorted_pnl
    mean_ex_top1 = float(np.mean(pnl_ex_top1))
    top1_sum = float(np.sum(sorted_pnl[-top1_n:]))
    tot_sum = float(np.sum(pnl))
    top1_share = float(top1_sum / tot_sum) if tot_sum > 0 else 999.0
    
    df_sub['dt'] = pd.to_datetime(df_sub['entry_ts'], unit='ns', utc=True)
    df_sub['month'] = df_sub['dt'].dt.tz_localize(None).dt.to_period('M').astype(str)
    m_atr = df_sub.groupby('month')['net_pnl_atr'].sum()
    worst_m = str(m_atr.idxmin()) + f" ({m_atr.min():.2f}A)" if len(m_atr) > 0 else "N/A"
    best_m = str(m_atr.idxmax()) + f" ({m_atr.max():.2f}A)" if len(m_atr) > 0 else "N/A"

    return {
        'candidate_opportunities_per_day': round(total_pop / n_days, 2) if n_days > 0 else 0.0,
        'leaf4_trades_per_day': round(t_day, 2),
        'coverage_pct': round(cov, 2),
        'N': int(n),
        'mean_pnl_atr': round(mean_atr, 4),
        'median_pnl_atr': round(median_atr, 4),
        'std_pnl_atr': round(std_atr, 4),
        'net_dollars_per_trade': round(float(np.mean(pnl_dol)), 2),
        'total_pnl_dollars': round(float(np.sum(pnl_dol)), 2),
        'win_rate': round(wr, 4),
        'avg_win_atr': round(avg_win, 4),
        'avg_loss_atr': round(avg_loss, 4),
        'win_loss_ratio': round(wl_ratio, 4),
        'profit_factor': round(pf, 4),
        'catastrophic_rate': round(cat_rate, 4),
        'winner_gte_1a_rate': round(w1_rate, 4),
        'winner_gte_2a_rate': round(w2_rate, 4),
        'winner_gte_3a_rate': round(w3_rate, 4),
        'max_dd_atr': round(max_dd_atr, 4),
        'max_dd_dollars': round(max_dd_dol, 2),
        'longest_losing_streak': int(longest_loss_streak),
        'ex_top_1pct_expectancy_atr': round(mean_ex_top1, 4),
        'top_1pct_pnl_share': round(top1_share, 4),
        'worst_month': worst_m,
        'best_month': best_m
    }

results = {}
for period in ['2023', '2024', '2025_Q1']:
    df_p = df_all_ck[df_all_ck['year'] == period]
    df_leaf = df_p[df_p['is_leaf4']].copy()
    results[period] = compute_leaf4_metrics(df_leaf, trading_days.get(period, 1), len(df_p))
    
df_train_all = df_all_ck[df_all_ck['year'].isin(['2023', '2024'])]
df_train_leaf = df_train_all[df_train_all['is_leaf4']].copy()
results['pooled_2023_2024'] = compute_leaf4_metrics(
    df_train_leaf, trading_days.get('2023', 0) + trading_days.get('2024', 0), len(df_train_all)
)

with open(OUTPUT_DIR / f"leaf4_{inst_name.lower()}_results.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"Saved leaf4_{inst_name.lower()}_results.json")

print(f"\n{inst_name} Leaf 4 Summary:")
print("  2023: N =", results['2023']['N'], "Trades/Day =", results['2023']['leaf4_trades_per_day'], "Mean ATR =", results['2023']['mean_pnl_atr'], "PF =", results['2023']['profit_factor'])
print("  2024: N =", results['2024']['N'], "Trades/Day =", results['2024']['leaf4_trades_per_day'], "Mean ATR =", results['2024']['mean_pnl_atr'], "PF =", results['2024']['profit_factor'])
print("  2025 Q1: N =", results['2025_Q1']['N'], "Trades/Day =", results['2025_Q1']['leaf4_trades_per_day'], "Mean ATR =", results['2025_Q1']['mean_pnl_atr'], "PF =", results['2025_Q1']['profit_factor'])
