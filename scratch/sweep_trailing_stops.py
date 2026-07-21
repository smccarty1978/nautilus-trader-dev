import pandas as pd
import numpy as np
from pathlib import Path
import time

RES = Path("studies/regime_flip_truth/results")
YEARS = [2021, 2022, 2023, 2024]
INF = np.inf

def load_data():
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
    
    # Filter for Population A and warmed up events
    events = events[(events.population == "A") & events.warmed_up].copy()
    checkpoints = checkpoints[checkpoints.uid.isin(events.uid)].copy()
    
    # Extract checkpoints chronologically
    ckpt_order = ["entry", "+30s", "+60s", "+90s", "+120s", "+180s", "Bar2", "Bar3", "Bar5"]
    
    # We want a 3D numpy array or structured dict of checkpoints for fast vectorized check
    # Let's pivot checkpoints: rows = uid, cols = checkpoint, values = (cur_mfe_atr, cur_pnl_atr, reached)
    print("Pivoting checkpoint data...")
    ck_reached = checkpoints.pivot(index="uid", columns="checkpoint", values="reached").reindex(columns=ckpt_order).fillna(False).to_numpy()
    ck_mfe = checkpoints.pivot(index="uid", columns="checkpoint", values="cur_mfe_atr").reindex(columns=ckpt_order).fillna(0.0).to_numpy()
    ck_pnl = checkpoints.pivot(index="uid", columns="checkpoint", values="cur_pnl_atr").reindex(columns=ckpt_order).fillna(-INF).to_numpy()
    
    # Create mapping from uid to index
    uid_to_idx = {uid: idx for idx, uid in enumerate(checkpoints["uid"].unique())}
    
    # Reorder events to match checkpoints
    events = events[events.uid.isin(uid_to_idx.keys())].copy()
    events["idx"] = events["uid"].map(uid_to_idx)
    events = events.sort_values("idx").reset_index(drop=True)
    
    print(f"Prepared {len(events):,} events and checkpoints in {time.time()-t0:.1f}s.")
    return events, ck_reached, ck_mfe, ck_pnl

def run_simulation(events, ck_reached, ck_mfe, ck_pnl, sl_val, tp_val, 
                   be_trigger, be_level, trail_dist, friction_atr=0.025):
    
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
    
    # Checkpoint offsets in seconds
    ckpt_offsets = np.array([0, 30, 60, 90, 120, 180, 120, 180, 300]) # Bar2=120, Bar3=180, Bar5=300
    
    # 3. Simulate Trailing Stop and Break-even chronologically at each checkpoint
    # Active trailing stop levels for each event
    active_stops = np.full(n_events, -sl_val)
    be_active = np.zeros(n_events, dtype=bool)
    trail_active = np.zeros(n_events, dtype=bool)
    
    for c_idx in range(len(ckpt_offsets)):
        t_off = ckpt_offsets[c_idx]
        reached = ck_reached[:, c_idx]
        mfe = ck_mfe[:, c_idx]
        pnl = ck_pnl[:, c_idx]
        
        # Check if trade is still open at this checkpoint
        open_mask = (current_time > t_off) & reached
        if not np.any(open_mask):
            continue
            
        # Update trailing stop / break-even status
        # Break-even trigger
        if be_trigger is not None:
            be_trig_mask = open_mask & (mfe >= be_trigger) & (~be_active)
            be_active[be_trig_mask] = True
            active_stops[be_trig_mask] = np.maximum(active_stops[be_trig_mask], be_level)
            
        # Trailing stop trigger
        if trail_dist is not None:
            trail_trig_mask = open_mask & (mfe >= trail_dist)
            trail_active[trail_trig_mask] = True
            # Trail stop is MFE - trail_dist
            potential_stops = mfe - trail_dist
            active_stops[trail_trig_mask] = np.maximum(active_stops[trail_trig_mask], potential_stops[trail_trig_mask])
            
        # Check if stop is hit at this checkpoint
        stop_hit_mask = open_mask & (pnl < active_stops)
        if np.any(stop_hit_mask):
            final_pnl[stop_hit_mask] = active_stops[stop_hit_mask]
            current_time[stop_hit_mask] = t_off
            
    net_pnl = final_pnl - friction_atr
    return np.mean(net_pnl), np.mean(final_pnl > 0), np.sum(final_pnl[final_pnl > 0]) / abs(np.sum(final_pnl[final_pnl < 0])) if np.sum(final_pnl[final_pnl < 0]) != 0 else np.nan

def main():
    events, ck_reached, ck_mfe, ck_pnl = load_data()
    
    print("Starting trailing stop grid search...")
    results = []
    
    tp_options = [1.0, 1.5, 2.0, 3.0]
    sl_options = [0.5, 0.75, 1.0]
    be_trigger_options = [0.25, 0.5, 0.75, None]
    be_level_options = [-0.25, 0.0, 0.25]
    trail_dist_options = [0.25, 0.5, 0.75, None]
    
    best_net_pnl = -INF
    best_config = None
    
    count = 0
    t0 = time.time()
    
    for tp in tp_options:
        for sl in sl_options:
            for be_trig in be_trigger_options:
                for be_lev in be_level_options if be_trig is not None else [0.0]:
                    for trail in trail_dist_options:
                        net, win, pf = run_simulation(
                            events, ck_reached, ck_mfe, ck_pnl, sl_val=sl, tp_val=tp,
                            be_trigger=be_trig, be_level=be_lev, trail_dist=trail
                        )
                        count += 1
                        results.append({
                            "tp": tp, "sl": sl, "be_trig": be_trig, "be_lev": be_lev, "trail": trail,
                            "net_pnl": net, "win_rate": win, "pf": pf
                        })
                        if net > best_net_pnl:
                            best_net_pnl = net
                            best_config = results[-1]
                                    
    df_res = pd.DataFrame(results)
    print(f"Grid search finished: evaluated {count} configs in {time.time()-t0:.1f}s.")
    
    print("\n=== TOP 15 CONFIGURATIONS BY NET PNL ===")
    top_10 = df_res.sort_values("net_pnl", ascending=False).head(15)
    for idx, r in top_10.iterrows():
        print(f"TP: {r['tp']:.1f} | SL: {r['sl']:.2f} | BE Trig: {r['be_trig']} (Lvl={r['be_lev']:.2f}) | Trail: {r['trail']} | Net PnL: {r['net_pnl']:.4f} | Win Rate: {r['win_rate']:.2%} | PF: {r['pf']:.3f}")

if __name__ == "__main__":
    main()
