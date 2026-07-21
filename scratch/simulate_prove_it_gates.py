import pandas as pd
import numpy as np
from pathlib import Path
import time

RES = Path("studies/regime_flip_truth/results")
YEARS = [2021, 2022, 2023, 2024]
INF = np.inf

def load_data():
    t0 = time.time()
    print("Loading datasets...")
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
    
    print(f"Loaded {len(events):,} events and {len(checkpoints):,} checkpoints in {time.time()-t0:.1f}s.")
    return events, checkpoints

def build_checkpoint_dict(checkpoints):
    t0 = time.time()
    print("Building checkpoint fast-lookup dictionary...")
    # Filter for checkpoints we care about
    ck_filtered = checkpoints[checkpoints.checkpoint.isin(["+30s", "+60s", "+90s"]) & checkpoints.reached].copy()
    
    ck_dict = {}
    for r in ck_filtered.itertuples():
        uid = r.uid
        ckpt = r.checkpoint
        if uid not in ck_dict:
            ck_dict[uid] = {}
        ck_dict[uid][ckpt] = {
            "cur_pnl_atr": r.cur_pnl_atr,
            "cur_mae_atr": r.cur_mae_atr,
            "align_5s": r.align_5s
        }
    print(f"Built dict for {len(ck_dict):,} unique events in {time.time()-t0:.1f}s.")
    return ck_dict

def run_simulation(events, ck_dict, sl_val=1.0, tp_val=2.0, 
                   use_30s_gate=True, pnl_30s_thresh=-0.25, align_5s_30s_req=True,
                   use_60s_gate=True, pnl_60s_thresh=0.0, align_5s_60s_req=True,
                   use_90s_gate=False, flips_90s_thresh=1, pnl_90s_thresh=0.2,
                   friction_atr=0.025): # $10 transaction costs is roughly 0.025 ATR for NQ
    
    # Extract times of key milestones for each event
    t_target = np.full(len(events), INF)
    if tp_val == 2.0:
        reached_tp = events["reached_2_0_atr"].to_numpy()
        mae_b4_2 = events["mae_before_2_0_atr"].to_numpy()
        t_reach_2 = events["t_reach_2_0_atr_s"].to_numpy()
        
        valid_win = reached_tp & (mae_b4_2 < sl_val)
        t_target[valid_win] = t_reach_2[valid_win]
    elif tp_val == 1.0:
        reached_tp = events["reached_1_0_atr"].to_numpy()
        mae_b4_1 = events["mae_before_1_0_atr"].to_numpy()
        t_reach_1 = events["t_reach_1_0_atr_s"].to_numpy()
        
        valid_win = reached_tp & (mae_b4_1 < sl_val)
        t_target[valid_win] = t_reach_1[valid_win]

    t_stop = np.full(len(events), INF)
    mae_atr = events["mae_atr"].to_numpy()
    if sl_val == 1.0:
        t_mae_1 = events["t_mae_1_0_atr_s"].to_numpy()
        has_stop = mae_atr >= 1.0
        t_stop[has_stop] = t_mae_1[has_stop]
    elif sl_val == 0.75:
        t_mae_075 = events["t_mae_0_75_atr_s"].to_numpy()
        has_stop = mae_atr >= 0.75
        t_stop[has_stop] = t_mae_075[has_stop]
    elif sl_val == 0.5:
        t_mae_05 = events["t_mae_0_5_atr_s"].to_numpy()
        has_stop = mae_atr >= 0.5
        t_stop[has_stop] = t_mae_05[has_stop]

    t_terminal = events["regime_duration_s"].to_numpy(float)
    term_pnl = events["terminal_pnl_atr"].to_numpy(float)
    uids = events["uid"].to_numpy()
    flips_90s = events["n_5s_flips_first90s"].to_numpy()
    
    n_events = len(events)
    final_pnl = np.zeros(n_events)
    exit_reasons = [""] * n_events
    exit_times = np.zeros(n_events)
    
    for i in range(n_events):
        uid = uids[i]
        t_stop_i = t_stop[i]
        t_target_i = t_target[i]
        t_term_i = t_terminal[i]
        
        baseline_time = min(t_stop_i, t_target_i, t_term_i)
        if baseline_time == t_target_i:
            baseline_pnl = tp_val
            baseline_reason = "target"
        elif baseline_time == t_stop_i:
            baseline_pnl = -sl_val
            baseline_reason = "stop"
        else:
            baseline_pnl = term_pnl[i]
            baseline_reason = "terminal_flip"
            
        # Get checkpoint data for this event if it exists
        ev_ck = ck_dict.get(uid)
        
        # 1. Evaluate +30s Gate
        if use_30s_gate and baseline_time > 30.0 and ev_ck and "+30s" in ev_ck:
            ck_row = ev_ck["+30s"]
            cur_pnl = ck_row["cur_pnl_atr"]
            align_5s = ck_row["align_5s"]
            
            trigger = False
            if cur_pnl < pnl_30s_thresh:
                if not align_5s_30s_req or align_5s == -1: # opposed
                    trigger = True
            
            if trigger:
                final_pnl[i] = cur_pnl
                exit_reasons[i] = "gate_30s"
                exit_times[i] = 30.0
                continue

        # 2. Evaluate +60s Gate
        if use_60s_gate and baseline_time > 60.0 and ev_ck and "+60s" in ev_ck:
            ck_row = ev_ck["+60s"]
            cur_pnl = ck_row["cur_pnl_atr"]
            cur_mae = ck_row["cur_mae_atr"]
            align_5s = ck_row["align_5s"]
            
            trigger = False
            if cur_pnl < pnl_60s_thresh:
                if not align_5s_60s_req or align_5s == -1: # opposed
                    trigger = True
            if cur_mae > 0.6:
                trigger = True
                
            if trigger:
                final_pnl[i] = cur_pnl
                exit_reasons[i] = "gate_60s"
                exit_times[i] = 60.0
                continue

        # 3. Evaluate +90s Gate / Waver Check
        if use_90s_gate and baseline_time > 90.0 and ev_ck and "+90s" in ev_ck:
            ck_row = ev_ck["+90s"]
            cur_pnl = ck_row["cur_pnl_atr"]
            n_flips = flips_90s[i]
            if n_flips >= flips_90s_thresh and cur_pnl < pnl_90s_thresh:
                final_pnl[i] = cur_pnl
                exit_reasons[i] = "gate_90s"
                exit_times[i] = 90.0
                continue

        # If no gate triggered, the trade resolves as baseline
        final_pnl[i] = baseline_pnl
        exit_reasons[i] = baseline_reason
        exit_times[i] = baseline_time
        
    net_pnl = final_pnl - friction_atr
    
    mean_raw_pnl = np.mean(final_pnl)
    mean_net_pnl = np.mean(net_pnl)
    win_rate = np.mean(final_pnl > 0)
    loss_rate = np.mean(final_pnl < 0)
    profit_factor = np.sum(final_pnl[final_pnl > 0]) / abs(np.sum(final_pnl[final_pnl < 0])) if np.sum(final_pnl[final_pnl < 0]) != 0 else np.nan
    
    reasons_series = pd.Series(exit_reasons)
    reason_counts = reasons_series.value_counts(normalize=True).to_dict()
    
    return {
        "mean_raw_pnl": mean_raw_pnl,
        "mean_net_pnl": mean_net_pnl,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "profit_factor": profit_factor,
        "reasons": reason_counts,
        "mean_exit_time": np.mean(exit_times)
    }

if __name__ == "__main__":
    events, checkpoints = load_data()
    ck_dict = build_checkpoint_dict(checkpoints)
    
    print("\n--- BASELINE (TP=2.0, SL=1.0, NO GATES) ---")
    res_base = run_simulation(events, ck_dict, sl_val=1.0, tp_val=2.0, 
                              use_30s_gate=False, use_60s_gate=False)
    for k, v in res_base.items():
        if k != "reasons":
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  exit reasons: {v}")
            
    print("\n--- GATES ACTIVE (TP=2.0, SL=1.0) ---")
    print("30s Gate: PnL < -0.25 & 5s opposed")
    print("60s Gate: PnL < 0.0 & 5s opposed, OR MAE > 0.6")
    res_gates = run_simulation(events, ck_dict, sl_val=1.0, tp_val=2.0,
                               use_30s_gate=True, pnl_30s_thresh=-0.25, align_5s_30s_req=True,
                               use_60s_gate=True, pnl_60s_thresh=0.0, align_5s_60s_req=True)
    for k, v in res_gates.items():
        if k != "reasons":
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  exit reasons: {v}")
            
    print("\n--- GATES ACTIVE + 90s WAVER CHECK (TP=2.0, SL=1.0) ---")
    print("90s Gate: if flipped 5s >= 1 and PnL < 0.2 ATR, cut")
    res_waver = run_simulation(events, ck_dict, sl_val=1.0, tp_val=2.0,
                               use_30s_gate=True, pnl_30s_thresh=-0.25, align_5s_30s_req=True,
                               use_60s_gate=True, pnl_60s_thresh=0.0, align_5s_60s_req=True,
                               use_90s_gate=True, flips_90s_thresh=1, pnl_90s_thresh=0.2)
    for k, v in res_waver.items():
        if k != "reasons":
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  exit reasons: {v}")
            
    print("\n--- SWEEPING GATES ---")
    t0_sweep = time.time()
    best_net = -INF
    best_cfg = {}
    
    # Sweep over SL values, 30s threshold, 60s threshold, and 90s waver check
    for sl in [0.5, 0.75, 1.0]:
        for pnl30 in [-0.3, -0.2, -0.1]:
            for pnl60 in [-0.1, 0.0, 0.1]:
                for use90 in [False, True]:
                    res = run_simulation(events, ck_dict, sl_val=sl, tp_val=2.0,
                                         use_30s_gate=True, pnl_30s_thresh=pnl30, align_5s_30s_req=True,
                                         use_60s_gate=True, pnl_60s_thresh=pnl60, align_5s_60s_req=True,
                                         use_90s_gate=use90, flips_90s_thresh=1, pnl_90s_thresh=0.2)
                    if res["mean_net_pnl"] > best_net:
                        best_net = res["mean_net_pnl"]
                        best_cfg = {
                            "sl": sl, "pnl30": pnl30, "pnl60": pnl60, "use90": use90, "results": res
                        }
    
    print(f"Sweep completed in {time.time()-t0_sweep:.1f}s.")
    print("\n=== BEST CONFIGURATION FOUND ===")
    print(f"SL: {best_cfg['sl']} ATR")
    print(f"30s Gate Threshold: {best_cfg['pnl30']} ATR")
    print(f"60s Gate Threshold: {best_cfg['pnl60']} ATR")
    print(f"90s Waver Gate Active: {best_cfg['use90']}")
    for k, v in best_cfg["results"].items():
        if k != "reasons":
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  exit reasons: {v}")
