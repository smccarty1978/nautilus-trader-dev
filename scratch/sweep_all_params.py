import pandas as pd
import numpy as np
from pathlib import Path
import time

RES = Path("studies/regime_flip_truth/results")
YEARS = [2021, 2022, 2023, 2024]
INF = np.inf

def load_all_raw_data():
    t0 = time.time()
    print("Loading raw datasets...")
    ev_parts = []
    ck_parts = []
    for y in YEARS:
        ep = RES / f"flip_truth_dataset_{y}.parquet"
        cp = RES / f"flip_checkpoint_dataset_{y}.parquet"
        if ep.exists() and cp.exists():
            e = pd.read_parquet(ep)
            e["year"] = y
            e["uid"] = e["year"] * 10_000_000 + e["event_id"]
            ev_parts.append(e)
            
            c = pd.read_parquet(cp)
            c["year"] = y
            c["uid"] = c["year"] * 10_000_000 + c["event_id"]
            ck_parts.append(c)
            
    events = pd.concat(ev_parts, ignore_index=True)
    checkpoints = pd.concat(ck_parts, ignore_index=True)
    
    print(f"Concatenated events: {len(events):,}, checkpoints: {len(checkpoints):,}")
    
    # Extract checkpoints at +30s, +60s, +90s
    ck_30 = checkpoints[(checkpoints.checkpoint == "+30s") & checkpoints.reached][["uid", "cur_pnl_atr", "align_5s"]].rename(
        columns={"cur_pnl_atr": "pnl_30", "align_5s": "a5_30"})
    
    ck_60 = checkpoints[(checkpoints.checkpoint == "+60s") & checkpoints.reached][["uid", "cur_pnl_atr", "cur_mae_atr", "align_5s"]].rename(
        columns={"cur_pnl_atr": "pnl_60", "cur_mae_atr": "mae_60", "align_5s": "a5_60"})
        
    ck_90 = checkpoints[(checkpoints.checkpoint == "+90s") & checkpoints.reached][["uid", "cur_pnl_atr"]].rename(
        columns={"cur_pnl_atr": "pnl_90"})
        
    # Merge onto events
    print("Merging checkpoints onto events...")
    events = events.merge(ck_30, on="uid", how="left")
    events = events.merge(ck_60, on="uid", how="left")
    events = events.merge(ck_90, on="uid", how="left")
    
    # Fill missing checkpoint values for unreached checkpoints with NaNs/Neutral values
    events["pnl_30"] = events["pnl_30"].fillna(-INF)
    events["a5_30"] = events["a5_30"].fillna(0)
    events["pnl_60"] = events["pnl_60"].fillna(-INF)
    events["mae_60"] = events["mae_60"].fillna(INF)
    events["a5_60"] = events["a5_60"].fillna(0)
    events["pnl_90"] = events["pnl_90"].fillna(-INF)
    
    print(f"Finished loading and merging in {time.time()-t0:.1f}s.")
    return events

# Load global dataset once at import
events_raw = load_all_raw_data()

def load_data(pop):
    t0 = time.time()
    events = events_raw[(events_raw.population == pop) & events_raw.warmed_up].copy()
    print(f"Filtered {len(events):,} warmed events for Population {pop} in {time.time()-t0:.2f}s.")
    return events

def run_simulation_vectorized(events, sl_val, tp_val, 
                              use_30s_gate, pnl_30s_thresh, align_5s_30s_req,
                              use_60s_gate, pnl_60s_thresh, align_5s_60s_req,
                              use_90s_gate, flips_90s_thresh, pnl_90s_thresh,
                              friction_atr=0.025):
    
    n_events = len(events)
    t_target = np.full(n_events, INF)
    
    reached_2_0 = events["reached_2_0_atr"].to_numpy()
    mae_b4_2 = events["mae_before_2_0_atr"].to_numpy()
    t_reach_2 = events["t_reach_2_0_atr_s"].to_numpy()
    
    reached_1_0 = events["reached_1_0_atr"].to_numpy()
    mae_b4_1 = events["mae_before_1_0_atr"].to_numpy()
    t_reach_1 = events["t_reach_1_0_atr_s"].to_numpy()

    reached_3_0 = events["reached_3_0_atr"].to_numpy()
    t_reach_3 = events["t_reach_3_0_atr_s"].to_numpy()

    mae_atr = events["mae_atr"].to_numpy()
    t_mae_1 = events["t_mae_1_0_atr_s"].to_numpy()
    t_mae_075 = events["t_mae_0_75_atr_s"].to_numpy()
    t_mae_05 = events["t_mae_0_5_atr_s"].to_numpy()
    
    t_terminal = events["regime_duration_s"].to_numpy(float)
    term_pnl = events["terminal_pnl_atr"].to_numpy(float)
    flips_90s = events["n_5s_flips_first90s"].to_numpy()
    
    # Checkpoint columns (already merged)
    pnl_30 = events["pnl_30"].to_numpy()
    a5_30 = events["a5_30"].to_numpy()
    pnl_60 = events["pnl_60"].to_numpy()
    mae_60 = events["mae_60"].to_numpy()
    a5_60 = events["a5_60"].to_numpy()
    pnl_90 = events["pnl_90"].to_numpy()
    
    # 1. Target times
    if tp_val == 3.0:
        valid_win = reached_3_0 & (mae_atr < sl_val)
        t_target[valid_win] = t_reach_3[valid_win]
    elif tp_val == 2.0:
        valid_win = reached_2_0 & (mae_b4_2 < sl_val)
        t_target[valid_win] = t_reach_2[valid_win]
    elif tp_val == 1.0:
        valid_win = reached_1_0 & (mae_b4_1 < sl_val)
        t_target[valid_win] = t_reach_1[valid_win]

    # 2. Stop times
    t_stop = np.full(n_events, INF)
    if sl_val == 1.0:
        has_stop = mae_atr >= 1.0
        t_stop[has_stop] = t_mae_1[has_stop]
    elif sl_val == 0.75:
        has_stop = mae_atr >= 0.75
        t_stop[has_stop] = t_mae_075[has_stop]
    elif sl_val == 0.5:
        has_stop = mae_atr >= 0.5
        t_stop[has_stop] = t_mae_05[has_stop]

    # Baseline calculations
    baseline_time = np.minimum(np.minimum(t_stop, t_target), t_terminal)
    baseline_pnl = np.where(baseline_time == t_target, tp_val, 
                            np.where(baseline_time == t_stop, -sl_val, term_pnl))
    
    final_pnl = baseline_pnl.copy()
    current_time = baseline_time.copy()
    
    # 3. +30s Gate
    if use_30s_gate:
        cond_30 = (current_time > 30.0) & (pnl_30 < pnl_30s_thresh)
        if align_5s_30s_req:
            cond_30 = cond_30 & (a5_30 == -1)
        
        final_pnl[cond_30] = pnl_30[cond_30]
        current_time[cond_30] = 30.0
        
    # 4. +60s Gate
    if use_60s_gate:
        cond_pnl_60 = (pnl_60 < pnl_60s_thresh)
        if align_5s_60s_req:
            cond_pnl_60 = cond_pnl_60 & (a5_60 == -1)
            
        cond_mae_60 = (mae_60 > 0.6)
        cond_60 = (current_time > 60.0) & (cond_pnl_60 | cond_mae_60)
        
        final_pnl[cond_60] = pnl_60[cond_60]
        current_time[cond_60] = 60.0
        
    # 5. +90s Gate
    if use_90s_gate:
        cond_90 = (current_time > 90.0) & (flips_90s >= flips_90s_thresh) & (pnl_90 < pnl_90s_thresh)
        final_pnl[cond_90] = pnl_90[cond_90]
        
    net_pnl = final_pnl - friction_atr
    
    mean_raw_pnl = np.mean(final_pnl)
    mean_net_pnl = np.mean(net_pnl)
    win_rate = np.mean(final_pnl > 0)
    
    # Calculate profit factor safely
    pos_sum = np.sum(final_pnl[final_pnl > 0])
    neg_sum = abs(np.sum(final_pnl[final_pnl < 0]))
    profit_factor = pos_sum / neg_sum if neg_sum > 0 else np.nan
    
    return mean_net_pnl, win_rate, profit_factor

def main():
    for pop in ["A", "B"]:
        print(f"\n==================================================")
        print(f"RUNNING SWEEP FOR POPULATION {pop}")
        print(f"==================================================")
        events = load_data(pop)
        
        print("Starting vectorized grid search...")
        results = []
        
        tp_options = [1.0, 1.5, 2.0, 3.0]
        sl_options = [0.5, 0.75, 1.0]
        pnl30_options = [-0.4, -0.3, -0.2, -0.1]
        pnl60_options = [-0.2, -0.1, 0.0, 0.1, 0.2]
        use_30_options = [False, True]
        use_60_options = [False, True]
        use_90_options = [False, True]
        
        best_net_pnl = -INF
        best_config = None
        
        count = 0
        t0 = time.time()
        
        for tp in tp_options:
            for sl in sl_options:
                # Baseline
                base_net, base_win, base_pf = run_simulation_vectorized(
                    events, sl_val=sl, tp_val=tp,
                    use_30s_gate=False, pnl_30s_thresh=0.0, align_5s_30s_req=False,
                    use_60s_gate=False, pnl_60s_thresh=0.0, align_5s_60s_req=False,
                    use_90s_gate=False, flips_90s_thresh=1, pnl_90s_thresh=0.0
                )
                results.append({
                    "tp": tp, "sl": sl, "use30": False, "pnl30": 0.0, "use60": False, "pnl60": 0.0, "use90": False,
                    "net_pnl": base_net, "win_rate": base_win, "pf": base_pf, "is_baseline": True
                })
                if base_net > best_net_pnl:
                    best_net_pnl = base_net
                    best_config = results[-1]
                    
                for use30 in use_30_options:
                    for pnl30 in pnl30_options if use30 else [0.0]:
                        for use60 in use_60_options:
                            for pnl60 in pnl60_options if use60 else [0.0]:
                                for use90 in use_90_options:
                                    if not use30 and not use60 and not use90:
                                        continue # baseline
                                        
                                    net, win, pf = run_simulation_vectorized(
                                        events, sl_val=sl, tp_val=tp,
                                        use_30s_gate=use30, pnl_30s_thresh=pnl30, align_5s_30s_req=True,
                                        use_60s_gate=use60, pnl_60s_thresh=pnl60, align_5s_60s_req=True,
                                        use_90s_gate=use90, flips_90s_thresh=1, pnl_90s_thresh=0.2
                                    )
                                    count += 1
                                    results.append({
                                        "tp": tp, "sl": sl, "use30": use30, "pnl30": pnl30, "use60": use60, "pnl60": pnl60, "use90": use90,
                                        "net_pnl": net, "win_rate": win, "pf": pf, "is_baseline": False
                                    })
                                    if net > best_net_pnl:
                                        best_net_pnl = net
                                        best_config = results[-1]
                                        
        df_res = pd.DataFrame(results)
        print(f"Vectorized grid search finished: evaluated {count + len(tp_options)*len(sl_options)} configs in {time.time()-t0:.1f}s.")
        
        print(f"\n=== TOP 10 CONFIGURATIONS FOR POPULATION {pop} ===")
        top_10 = df_res.sort_values("net_pnl", ascending=False).head(10)
        for idx, r in top_10.iterrows():
            print(f"TP: {r['tp']:.1f} | SL: {r['sl']:.2f} | 30s Gate: {r['use30']} (Th={r['pnl30']:.2f}) | 60s Gate: {r['use60']} (Th={r['pnl60']:.2f}) | 90s Waver: {r['use90']} | Net PnL: {r['net_pnl']:.4f} | Win Rate: {r['win_rate']:.2%} | PF: {r['pf']:.3f} | Baseline?: {r['is_baseline']}")

if __name__ == "__main__":
    main()
