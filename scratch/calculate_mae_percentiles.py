import pandas as pd
import numpy as np
from pathlib import Path
import time

OUT = Path("studies/regime_state_transition_atlas/results")

def main():
    t0 = time.time()
    scored_parquet = OUT / "scored_state_rows.parquet"
    state_parquet = OUT / "state_rows.parquet"
    label_parquet = OUT / "forward_labels.parquet"
    
    print("Loading parquets...")
    df_scored = pd.read_parquet(scored_parquet)
    df_states = pd.read_parquet(state_parquet)
    df_labels = pd.read_parquet(label_parquet)
    
    print("Merging dataframes...")
    df_all = pd.merge(df_scored, df_states[["regime_id", "bar_ts", "regime_start_ts"]], on=["regime_id", "bar_ts"])
    df_all = pd.merge(df_all, df_labels, on=["regime_id", "bar_ts"])
    
    if "next_1s_open_x" in df_all.columns:
        df_all = df_all.rename(columns={"next_1s_open_x": "next_1s_open"})
    elif "next_1s_open_y" in df_all.columns:
        df_all = df_all.rename(columns={"next_1s_open_y": "next_1s_open"})
        
    df_all = df_all.sort_values("bar_ts").copy()
    
    print("Running OOS filter...")
    df_oos = df_all[df_all["year"].isin([2025, 2026])].copy()
    
    # Calculate score deciles
    df_oos["decile"] = pd.qcut(df_oos["score_opportunity"], 10, labels=False) + 1
    
    # Filter for Decile 10
    df_d10 = df_oos[df_oos["decile"] == 10].copy()
    print(f"Total Decile 10 rows: {len(df_d10)}")
    
    exit_thr_2025 = 0.9712
    exit_thr_2026 = 0.9749
    
    regime_groups = {name: group.sort_values("bar_index_in_regime") for name, group in df_all.groupby("regime_id")}
    
    records = df_d10.to_dict("records")
    mae_before_peak_list = []
    
    t_start = time.time()
    for idx, row in enumerate(records):
        r_id = row["regime_id"]
        K = row["bar_index_in_regime"]
        year = row["year"]
        
        exit_thr = exit_thr_2025 if year == 2025 else exit_thr_2026
        r_df = regime_groups[r_id]
        
        bar_indices = r_df["bar_index_in_regime"].values
        scores = r_df["score_opportunity"].values
        pnls = r_df["current_pnl_atr"].values
        
        k_idx = np.where(bar_indices == K)[0]
        if len(k_idx) == 0:
            continue
        k_idx = k_idx[0]
        
        sub_scores = scores[k_idx+1:]
        exit_trigger_idx = np.where(sub_scores <= exit_thr)[0]
        if len(exit_trigger_idx) > 0:
            e_idx = k_idx + 1 + exit_trigger_idx[0]
        else:
            e_idx = len(bar_indices) - 1
            
        pnls_hold = pnls[k_idx:e_idx+1]
        pnl_diffs_hold = pnls_hold - pnls[k_idx]
        
        mae_subset_approx = max(0.0, np.max(pnls[k_idx] - pnls_hold)) if len(pnls_hold) > 0 else 0.0
        mae_total_approx = max(0.0, np.max(pnls[k_idx] - pnls[k_idx:]))
        
        rem_mae_atr = row["remaining_regime_mae_atr"]
        if mae_total_approx > 0.0:
            held_mae = rem_mae_atr * (mae_subset_approx / mae_total_approx)
        else:
            held_mae = 0.0
        held_mae = min(held_mae, rem_mae_atr)
        
        p_idx_rel = np.argmax(pnl_diffs_hold) if len(pnl_diffs_hold) > 0 else 0
        pnls_before_peak = pnls_hold[:p_idx_rel+1]
        mae_before_mfe_approx = max(0.0, np.max(pnls[k_idx] - pnls_before_peak)) if len(pnls_before_peak) > 0 else 0.0
        
        if mae_subset_approx > 0.0:
            held_mae_before_mfe = held_mae * (mae_before_mfe_approx / mae_subset_approx)
        else:
            held_mae_before_mfe = 0.0
        held_mae_before_mfe = min(held_mae_before_mfe, held_mae)
        
        mae_before_peak_list.append(held_mae_before_mfe)
        
        if (idx + 1) % 10000 == 0:
            print(f"Processed {idx+1}/{len(records)} in {time.time() - t_start:.2f}s")
            
    print(f"\nCalculation done in {time.time() - t0:.2f}s")
    
    # Calculate percentiles
    pvals = [50, 75, 90, 95]
    percentiles = np.percentile(mae_before_peak_list, pvals)
    
    print("\n=== DECILE 10 MAE BEFORE PEAK PROFIT PERCENTILES (ATR) ===")
    for p, val in zip(pvals, percentiles):
        print(f"p{p}: {val:.4f} ATR")

if __name__ == "__main__":
    main()
