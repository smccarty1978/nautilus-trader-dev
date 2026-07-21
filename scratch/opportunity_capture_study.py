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
    print(f"Loaded in {time.time() - t0:.2f}s")
    
    print("Merging dataframes...")
    df_all = pd.merge(df_scored, df_states[["regime_id", "bar_ts", "regime_start_ts"]], on=["regime_id", "bar_ts"])
    df_all = pd.merge(df_all, df_labels, on=["regime_id", "bar_ts"])
    
    # Rename duplicated columns to avoid KeyErrors
    if "next_1s_open_x" in df_all.columns:
        df_all = df_all.rename(columns={"next_1s_open_x": "next_1s_open"})
    elif "next_1s_open_y" in df_all.columns:
        df_all = df_all.rename(columns={"next_1s_open_y": "next_1s_open"})
        
    df_all = df_all.sort_values("bar_ts").copy()
    print(f"Merged and sorted in {time.time() - t0:.2f}s")
    
    print("Running OOS filter...")
    df_oos = df_all[df_all["year"].isin([2025, 2026])].copy()
    print(f"Total OOS rows: {len(df_oos)}")
    
    # Take a representative sample of 20,000 checkpoints to make it run in seconds
    sample_size = min(20000, len(df_oos))
    print(f"Sampling {sample_size} rows for fast calculation...")
    df_oos_sample = df_oos.sample(n=sample_size, random_state=42).copy()
    
    # Exit thresholds
    exit_thr_2025 = 0.9712
    exit_thr_2026 = 0.9749
    
    # Group by regime_id to quickly access subsequent checkpoints
    # Note: we group the full df_all to have the complete regime checkpoints
    regime_groups = {name: group.sort_values("bar_index_in_regime") for name, group in df_all.groupby("regime_id")}
    
    print("Calculating capture metrics for OOS sample checkpoints...")
    
    records = df_oos_sample.to_dict("records")
    results = []
    
    t_start_loop = time.time()
    for idx, row in enumerate(records):
        r_id = row["regime_id"]
        K = row["bar_index_in_regime"]
        year = row["year"]
        score = row["score_opportunity"]
        rem_mfe_atr = row["remaining_regime_mfe_atr"]
        
        exit_thr = exit_thr_2025 if year == 2025 else exit_thr_2026
        
        # Get all checkpoints in this regime
        r_df = regime_groups[r_id]
        
        # Remaining checkpoints from K onwards
        # Using fast numpy filters instead of full pandas where possible
        bar_indices = r_df["bar_index_in_regime"].values
        scores = r_df["score_opportunity"].values
        pnls = r_df["current_pnl_atr"].values
        
        k_idx = np.where(bar_indices == K)[0]
        if len(k_idx) == 0:
            # Fallback if not found
            results.append({
                "score_opportunity": score,
                "remaining_regime_mfe_atr": rem_mfe_atr,
                "captured_mfe_atr": 0.0
            })
            continue
        k_idx = k_idx[0]
        
        # Subsequent checkpoints
        sub_indices = bar_indices[k_idx+1:]
        sub_scores = scores[k_idx+1:]
        
        # Exit trigger index in subsequent arrays
        exit_trigger_idx = np.where(sub_scores <= exit_thr)[0]
        if len(exit_trigger_idx) > 0:
            e_idx_rel = exit_trigger_idx[0]
            e_idx = k_idx + 1 + e_idx_rel
        else:
            e_idx = len(bar_indices) - 1
            
        # Hold period slice is from k_idx to e_idx
        pnls_hold = pnls[k_idx:e_idx+1]
        pnl_diffs_hold = pnls_hold - pnls[k_idx]
        mfe_subset_approx = max(0.0, np.max(pnl_diffs_hold)) if len(pnls_hold) > 0 else 0.0
        
        # Total remaining slice from k_idx to the end
        pnls_total = pnls[k_idx:]
        pnl_diffs_total = pnls_total - pnls[k_idx]
        mfe_total_approx = max(0.0, np.max(pnl_diffs_total)) if len(pnls_total) > 0 else 0.0
        
        # Scale captured MFE high-fidelity
        if mfe_total_approx > 0.0:
            captured_mfe = rem_mfe_atr * (mfe_subset_approx / mfe_total_approx)
        else:
            captured_mfe = 0.0
            
        # Realized PnL at exit checkpoint E
        realized_pnl_atr = pnls[e_idx] - pnls[k_idx]
        
        # Giveback = max profit reached (captured MFE) minus realized PnL
        giveback_atr = max(0.0, captured_mfe - realized_pnl_atr)
        
        # Compute subset approx adverse excursion (MAE)
        mae_subset_approx = max(0.0, np.max(pnls[k_idx] - pnls_hold)) if len(pnls_hold) > 0 else 0.0
        
        # Compute total remaining approx adverse excursion
        mae_total_approx = max(0.0, np.max(pnls[k_idx] - pnls_total)) if len(pnls_total) > 0 else 0.0
        
        # Scale held MAE high-fidelity
        rem_mae_atr = row["remaining_regime_mae_atr"]
        if mae_total_approx > 0.0:
            held_mae = rem_mae_atr * (mae_subset_approx / mae_total_approx)
        else:
            held_mae = 0.0
        held_mae = min(held_mae, rem_mae_atr)
        
        # Compute subset approx adverse excursion before peak profit (max MFE)
        p_idx_rel = np.argmax(pnl_diffs_hold) if len(pnl_diffs_hold) > 0 else 0
        pnls_before_peak = pnls_hold[:p_idx_rel+1]
        mae_before_mfe_approx = max(0.0, np.max(pnls[k_idx] - pnls_before_peak)) if len(pnls_before_peak) > 0 else 0.0
        
        if mae_subset_approx > 0.0:
            held_mae_before_mfe = held_mae * (mae_before_mfe_approx / mae_subset_approx)
        else:
            held_mae_before_mfe = 0.0
        held_mae_before_mfe = min(held_mae_before_mfe, held_mae)
        
        results.append({
            "score_opportunity": score,
            "remaining_regime_mfe_atr": rem_mfe_atr,
            "captured_mfe_atr": captured_mfe,
            "realized_pnl_atr": realized_pnl_atr,
            "giveback_atr": giveback_atr,
            "remaining_regime_mae_atr": rem_mae_atr,
            "held_mae_atr": held_mae,
            "held_mae_before_mfe_atr": held_mae_before_mfe
        })
        
        if (idx + 1) % 5000 == 0:
            print(f"Processed {idx+1}/{sample_size} in {time.time() - t_start_loop:.2f}s")
            
    df_res = pd.DataFrame(results)
    
    # Define score deciles on the OOS population sample
    df_res["decile"] = pd.qcut(df_res["score_opportunity"], 10, labels=False) + 1
    
    # Calculate group metrics
    summary = df_res.groupby("decile").agg(
        count=("score_opportunity", "size"),
        min_score=("score_opportunity", "min"),
        max_score=("score_opportunity", "max"),
        avg_remaining_mfe=("remaining_regime_mfe_atr", "mean"),
        avg_captured_mfe=("captured_mfe_atr", "mean"),
        avg_realized_pnl=("realized_pnl_atr", "mean"),
        avg_giveback=("giveback_atr", "mean"),
        avg_remaining_mae=("remaining_regime_mae_atr", "mean"),
        avg_held_mae=("held_mae_atr", "mean"),
        avg_held_mae_before_mfe=("held_mae_before_mfe_atr", "mean")
    )
    
    summary["capture_ratio_of_means"] = summary["avg_captured_mfe"] / summary["avg_remaining_mfe"]
    summary["realized_capture_ratio_of_means"] = summary["avg_realized_pnl"] / summary["avg_remaining_mfe"]
    
    # Calculate mean of ratios
    df_res["ratio"] = df_res["captured_mfe_atr"] / df_res["remaining_regime_mfe_atr"]
    df_res.loc[df_res["remaining_regime_mfe_atr"] == 0.0, "ratio"] = 0.0
    summary["avg_capture_ratio"] = df_res.groupby("decile")["ratio"].mean()
    
    print("\n=== OPPORTUNITY CAPTURE STUDY BY SCORE DECILE ===")
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(summary.to_string())
    
    # Export summary to markdown
    md_content = "# Opportunity Capture Study by Score Decile\n\n"
    md_content += "| Decile | Count | Min Score | Max Score | Avg Remaining MFE (ATR) | Avg Captured MFE (ATR) | Avg Realized PnL (ATR) | Avg Giveback (ATR) | Avg Remaining MAE (ATR) | Avg Held MAE (ATR) | Avg Held MAE Before Peak Profit (ATR) | Capture Ratio | Realized Capture Ratio |\n"
    md_content += "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    for decile, row in summary.iterrows():
        md_content += f"| {int(decile)} | {int(row['count'])} | {row['min_score']:.4f} | {row['max_score']:.4f} | {row['avg_remaining_mfe']:.4f} | {row['avg_captured_mfe']:.4f} | {row['avg_realized_pnl']:.4f} | {row['avg_giveback']:.4f} | {row['avg_remaining_mae']:.4f} | {row['avg_held_mae']:.4f} | {row['avg_held_mae_before_mfe']:.4f} | {row['capture_ratio_of_means']*100:.1f}% | {row['realized_capture_ratio_of_means']*100:.1f}% |\n"
        
    with open(OUT / "opportunity_capture_study.md", "w") as f:
        f.write(md_content)
    print(f"\nSaved report to {OUT / 'opportunity_capture_study.md'}")

if __name__ == "__main__":
    main()
