import pandas as pd
import numpy as np
from pathlib import Path
import time

RES = Path("studies/regime_flip_truth/results")
YEARS = [2021, 2022, 2023, 2024]
INF = np.inf

def load_data():
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
    
    # Let's define two checkpoint orders:
    # 1. Original (non-chronological because of Bar2/Bar3 sorting)
    orig_order = ["entry", "+30s", "+60s", "+90s", "+120s", "+180s", "Bar2", "Bar3", "Bar5"]
    orig_offsets = np.array([0, 30, 60, 90, 120, 180, 120, 180, 300])
    
    # 2. Chronological (strictly sorted by offset)
    chrono_order = ["entry", "+30s", "+60s", "+90s", "+120s", "Bar2", "+180s", "Bar3", "Bar5"]
    chrono_offsets = np.array([0, 30, 60, 90, 120, 120, 180, 180, 300])

    print("Pivoting checkpoint data (original)...")
    orig_reached = checkpoints.pivot(index="uid", columns="checkpoint", values="reached").reindex(columns=orig_order).fillna(False).to_numpy()
    orig_mfe = checkpoints.pivot(index="uid", columns="checkpoint", values="cur_mfe_atr").reindex(columns=orig_order).fillna(0.0).to_numpy()
    orig_pnl = checkpoints.pivot(index="uid", columns="checkpoint", values="cur_pnl_atr").reindex(columns=orig_order).fillna(-INF).to_numpy()
    
    print("Pivoting checkpoint data (chronological)...")
    chrono_reached = checkpoints.pivot(index="uid", columns="checkpoint", values="reached").reindex(columns=chrono_order).fillna(False).to_numpy()
    chrono_mfe = checkpoints.pivot(index="uid", columns="checkpoint", values="cur_mfe_atr").reindex(columns=chrono_order).fillna(0.0).to_numpy()
    chrono_pnl = checkpoints.pivot(index="uid", columns="checkpoint", values="cur_pnl_atr").reindex(columns=chrono_order).fillna(-INF).to_numpy()
    
    # Create mapping from uid to index
    uid_to_idx = {uid: idx for idx, uid in enumerate(checkpoints["uid"].unique())}
    
    # Reorder events to match checkpoints
    events = events[events.uid.isin(uid_to_idx.keys())].copy()
    events["idx"] = events["uid"].map(uid_to_idx)
    events = events.sort_values("idx").reset_index(drop=True)
    
    return events, (orig_reached, orig_mfe, orig_pnl, orig_offsets), (chrono_reached, chrono_mfe, chrono_pnl, chrono_offsets)

def run_simulation(events, ck_reached, ck_mfe, ck_pnl, ckpt_offsets, sl_val, tp_val, 
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
    
    if tp_val == 3.0:
        valid_win = reached_3_0 & (mae_atr < sl_val)
        t_target[valid_win] = t_reach_3[valid_win]
    elif tp_val == 2.0:
        valid_win = reached_2_0 & (mae_b4_2 < sl_val)
        t_target[valid_win] = t_reach_2[valid_win]
    elif tp_val == 1.5:
        # Interpolate 1.5 ATR target
        # For simplicity, if reached 2.0, we reach 1.5 at t_reach_2 (conservative)
        # or if reached 1.0, and target is 1.5:
        valid_win = reached_2_0 & (mae_b4_2 < sl_val)
        t_target[valid_win] = t_reach_2[valid_win]
    elif tp_val == 1.0:
        valid_win = reached_1_0 & (mae_b4_1 < sl_val)
        t_target[valid_win] = t_reach_1[valid_win]

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

    baseline_time = np.minimum(np.minimum(t_stop, t_target), t_terminal)
    baseline_pnl = np.where(baseline_time == t_target, tp_val, 
                            np.where(baseline_time == t_stop, -sl_val, term_pnl))
    
    final_pnl = baseline_pnl.copy()
    current_time = baseline_time.copy()
    
    active_stops = np.full(n_events, -sl_val)
    be_active = np.zeros(n_events, dtype=bool)
    trail_active = np.zeros(n_events, dtype=bool)
    
    for c_idx in range(len(ckpt_offsets)):
        t_off = ckpt_offsets[c_idx]
        reached = ck_reached[:, c_idx]
        mfe = ck_mfe[:, c_idx]
        pnl = ck_pnl[:, c_idx]
        
        open_mask = (current_time > t_off) & reached
        if not np.any(open_mask):
            continue
            
        if be_trigger is not None:
            be_trig_mask = open_mask & (mfe >= be_trigger) & (~be_active)
            be_active[be_trig_mask] = True
            active_stops[be_trig_mask] = np.maximum(active_stops[be_trig_mask], be_level)
            
        if trail_dist is not None:
            trail_trig_mask = open_mask & (mfe >= trail_dist)
            trail_active[trail_trig_mask] = True
            potential_stops = mfe - trail_dist
            active_stops[trail_trig_mask] = np.maximum(active_stops[trail_trig_mask], potential_stops[trail_trig_mask])
            
        stop_hit_mask = open_mask & (pnl < active_stops)
        if np.any(stop_hit_mask):
            final_pnl[stop_hit_mask] = active_stops[stop_hit_mask]
            current_time[stop_hit_mask] = t_off
            
    net_pnl = final_pnl - friction_atr
    return np.mean(net_pnl), np.mean(final_pnl > 0), np.sum(final_pnl[final_pnl > 0]) / abs(np.sum(final_pnl[final_pnl < 0])) if np.sum(final_pnl[final_pnl < 0]) != 0 else np.nan

def main():
    events, orig, chrono = load_data()
    
    tp = 1.5
    sl = 1.0
    be_trig = 0.25
    be_lev = 0.25
    trail = 0.25
    
    orig_reached, orig_mfe, orig_pnl, orig_offsets = orig
    chrono_reached, chrono_mfe, chrono_pnl, chrono_offsets = chrono
    
    net_orig, win_orig, pf_orig = run_simulation(
        events, orig_reached, orig_mfe, orig_pnl, orig_offsets,
        sl_val=sl, tp_val=tp, be_trigger=be_trig, be_level=be_lev, trail_dist=trail
    )
    
    net_chrono, win_chrono, pf_chrono = run_simulation(
        events, chrono_reached, chrono_mfe, chrono_pnl, chrono_offsets,
        sl_val=sl, tp_val=tp, be_trigger=be_trig, be_level=be_lev, trail_dist=trail
    )
    
    print("\n" + "="*80)
    # Print results comparison
    print("  SIMULATION COMPARISON (TP=1.5, SL=1.0, BE=0.25, Trail=0.25)")
    print("="*80)
    print(f"  Original (non-chrono): Net PnL (ATR) = {net_orig:.4f} | Win Rate = {win_orig:.2%} | PF = {pf_orig:.3f}")
    print(f"  Chronological sorted:  Net PnL (ATR) = {net_chrono:.4f} | Win Rate = {win_chrono:.2%} | PF = {pf_chrono:.3f}")
    print(f"  Realized NT Backtest:  Net PnL (ATR) = -0.0022 | Win Rate = 74.68% | PF = 0.66 (Net)")
    
if __name__ == "__main__":
    main()
