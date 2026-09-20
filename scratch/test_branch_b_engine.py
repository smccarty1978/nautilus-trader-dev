import sys
sys.path.insert(0, ".")
import time
import numpy as np
import pandas as pd

# Load checkpoints
ck_path = 'studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet'
df_ck = pd.read_parquet(ck_path)
print("Total checkpoints:", len(df_ck))
print("2023 checkpoints:", len(df_ck[df_ck['year'] == '2023']))

# Load 1s data for 2023
p_1s = 'data/raw/NQ_v0_1s_2023.parquet'
t0 = time.time()
df_1s = pd.read_parquet(p_1s, columns=['open', 'high', 'low', 'close'])
print(f"Loaded 1s data in {time.time()-t0:.2f}s")

# Test first 100 checkpoints
sub_ck = df_ck[df_ck['year'] == '2023'].head(100).copy()

# Fast index on 1s
idx_ts = df_1s.index.values.astype(np.int64)
opens = df_1s['open'].values
highs = df_1s['high'].values
lows = df_1s['low'].values
closes = df_1s['close'].values

print("Running E0 simulation on 100 checkpoints...")
t1 = time.time()
results = []
for _, r in sub_ck.iterrows():
    ck_ts = int(r['checkpoint_ts'])
    reg_exit_ts = int(r['regime_exit_ts'])
    d = int(r['direction']) # Bull: 1, Bear: -1
    atr = float(r['frozen_atr'])
    
    # Next 1s bar after ck_ts
    pos = np.searchsorted(idx_ts, ck_ts, side='right')
    if pos >= len(idx_ts):
        continue
    entry_ts = idx_ts[pos]
    entry_open = opens[pos]
    
    # E0 entry:
    # Bull -> enter LONG (+1)
    # Bear -> enter SHORT (-1)
    entry_fill_gross = entry_open
    
    # Test R1: SL = 0.75 ATR, PT = 1.00 ATR
    sl_dist = 0.75 * atr
    pt_dist = 1.00 * atr
    
    if d == 1:
        pt_px = round((entry_fill_gross + pt_dist) / 0.25) * 0.25
        sl_px = round((entry_fill_gross - sl_dist) / 0.25) * 0.25
    else:
        pt_px = round((entry_fill_gross - pt_dist) / 0.25) * 0.25
        sl_px = round((entry_fill_gross + sl_dist) / 0.25) * 0.25
        
    exit_ts = None
    exit_px_gross = None
    exit_source = None
    
    # Scan subsequent 1s bars
    cur_pos = pos
    while cur_pos < len(idx_ts):
        bar_ts = idx_ts[cur_pos]
        h = highs[cur_pos]
        l = lows[cur_pos]
        o = opens[cur_pos]
        
        if bar_ts > reg_exit_ts:
            # REGIME_TERMINATION_EXIT at this bar's open
            exit_ts = bar_ts
            exit_px_gross = o
            exit_source = "REGIME_TERMINATION_EXIT"
            break
            
        if d == 1: # LONG
            hit_pt = (h >= pt_px)
            hit_sl = (l <= sl_px)
            if hit_pt and hit_sl:
                # Conservative tie: SL wins
                exit_ts = bar_ts
                exit_px_gross = sl_px
                exit_source = "SL_HIT"
                break
            elif hit_sl:
                exit_ts = bar_ts
                exit_px_gross = sl_px
                exit_source = "SL_HIT"
                break
            elif hit_pt:
                exit_ts = bar_ts
                exit_px_gross = pt_px
                exit_source = "PT_HIT"
                break
        else: # SHORT
            hit_pt = (l <= pt_px)
            hit_sl = (h >= sl_px)
            if hit_pt and hit_sl:
                # Conservative tie: SL wins
                exit_ts = bar_ts
                exit_px_gross = sl_px
                exit_source = "SL_HIT"
                break
            elif hit_sl:
                exit_ts = bar_ts
                exit_px_gross = sl_px
                exit_source = "SL_HIT"
                break
            elif hit_pt:
                exit_ts = bar_ts
                exit_px_gross = pt_px
                exit_source = "PT_HIT"
                break
        cur_pos += 1
        
    gross_pts = d * (exit_px_gross - entry_fill_gross)
    net_pts = gross_pts - 0.75 # 0.50 pts slippage (2 ticks) + 0.25 pts comm ($5)
    net_atr = net_pts / atr
    results.append({
        'exit_source': exit_source,
        'gross_pts': gross_pts,
        'net_pts': net_pts,
        'net_atr': net_atr
    })

print(f"Simulated 100 trades in {time.time()-t1:.4f}s")
res_df = pd.DataFrame(results)
print(res_df['exit_source'].value_counts())
print("Mean net ATR:", res_df['net_atr'].mean())
print("Win rate:", (res_df['net_pts'] > 0).mean())
