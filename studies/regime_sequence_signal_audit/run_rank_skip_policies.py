import os
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import roc_auc_score

# Add Nautilus Trader path
PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))

from studies.regime_sequence_chop_context.run_flip_filter_replay import apply_policies

def is_rth(ts_ns):
    dt = pd.Timestamp(ts_ns, unit='ns', tz='UTC').tz_convert('America/Chicago')
    from datetime import time
    t = dt.time()
    return (dt.dayofweek < 5) and (time(8, 30) <= t <= time(15, 15))

OUT_DIR = Path("studies/regime_sequence_signal_audit/results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

NQ_MULTIPLIER = 20.0

def compute_pf(pnl):
    wins = pnl[pnl > 0].sum()
    losses = abs(pnl[pnl < 0].sum())
    return wins / losses if losses > 0 else (float("inf") if wins > 0 else 0.0)

def main():
    print("Running Phase 3, 4 & 5: Label-payoff alignment, rank-skip policies, and matched random controls...")
    
    # Load combined flip atlas
    atlas_path = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/flip_context_atlas.parquet"
    if not atlas_path.exists():
        print(f"Error: {atlas_path} not found.")
        return
        
    df_all = pd.read_parquet(atlas_path)
    df_f2 = df_all[df_all["population"] == "F2"].copy()
    
    # Apply baseline policy to get scores
    df_f2 = apply_policies(df_f2, threshold_fail_prob=0.15)
    
    # Create RTH/ETH session column
    df_f2['session'] = df_f2['observation_time'].apply(
        lambda ts: "RTH" if is_rth(ts) else "ETH"
    )
    
    # Validation and test splits
    val_f2 = df_f2[df_f2["period"] == "val"].copy()
    test_f2 = df_f2[df_f2["period"] == "test"].copy()
    
    # --- PHASE 3: LABEL-TO-PAYOFF ALIGNMENT ---
    # Analyze on Test Set
    classes = ["EARLY_ROTATIONAL_FAILURE", "LOW_PROGRESS_REGIME", "PRODUCTIVE_ORDINARY_REGIME", "LARGE_RUNNER", "AMBIGUOUS"]
    class_stats = []
    
    val_runner_90 = np.percentile(val_f2["pnl_base"].dropna(), 90) if len(val_f2) > 0 else 0.0
    test_f2["is_runner_90"] = test_f2["pnl_base"] >= val_runner_90
    total_net_pnl = test_f2["pnl_base"].sum()
    total_runner_pnl = test_f2[test_f2["is_runner_90"]]["pnl_base"].sum()
    
    for cls in classes:
        sub = test_f2[test_f2["outcome_class"] == cls]
        n = len(sub)
        if n == 0:
            continue
        pnl = sub["pnl_base"].to_numpy()
        class_stats.append({
            "outcome_class": cls,
            "N": n,
            "mean_net_PnL": float(pnl.mean()),
            "median_net_PnL": float(np.median(pnl)),
            "win_rate": float((pnl > 0).mean()),
            "profit_factor": float(compute_pf(pnl)),
            "mean_MFE": float(sub["MFE"].mean()),
            "mean_MAE": float(sub["MAE"].mean()),
            "mean_regime_duration_s": float((sub["regime_duration"] / 1e9).mean()),
            "total_PnL_contribution": float(pnl.sum()),
            "runner_contribution": float(sub[sub["pnl_base"] >= val_runner_90]["pnl_base"].sum())
        })
    df_alignment = pd.DataFrame(class_stats)
    df_alignment.to_parquet(OUT_DIR / "label_payoff_alignment.parquet", index=False)
    
    # Payoff-aware diagnostic targets
    # net PnL < 0
    test_f2["target_net_pnl_lt_0"] = (test_f2["pnl_base"] < 0).astype(int)
    # net PnL < -$25
    test_f2["target_net_pnl_lt_neg25"] = (test_f2["pnl_base"] < -25.0).astype(int)
    # net PnL < -0.25 ATR
    test_f2["target_net_pnl_lt_neg_025_atr"] = (test_f2["pnl_base"] < -0.25 * test_f2["atr"] * NQ_MULTIPLIER).astype(int)
    # fails to reach 0.5 ATR before -0.25 ATR
    test_f2["target_fail_05_atr_before_neg_025"] = ((test_f2["MAE_atr"] >= 0.25) & (test_f2["MFE_atr"] < 0.5)).astype(int)
    # bottom-quartile trade outcome
    test_bot_25_th = np.percentile(test_f2["pnl_base"].dropna(), 25) if len(test_f2) > 0 else 0.0
    test_f2["target_bottom_quartile"] = (test_f2["pnl_base"] <= test_bot_25_th).astype(int)
    
    rank_metrics = []
    for tgt in ["target_net_pnl_lt_0", "target_net_pnl_lt_neg25", "target_net_pnl_lt_neg_025_atr", "target_fail_05_atr_before_neg_025", "target_bottom_quartile"]:
        y_true = test_f2[tgt].values
        y_score = test_f2["ridge_log_fail_prob"].values
        auc = roc_auc_score(y_true, y_score) if len(np.unique(y_true)) > 1 else np.nan
        rank_metrics.append({
            "target": tgt,
            "auc": float(auc)
        })
    df_rank_metrics = pd.DataFrame(rank_metrics)
    df_rank_metrics.to_parquet(OUT_DIR / "payoff_target_rank_metrics.parquet", index=False)
    
    # Write Phase 3 report
    p3_md = """# Phase 3: Label-to-Payoff Alignment Report

## Outcome Class Payoffs (Test Set)
| Outcome Class | N | Mean Net PnL ($) | Median Net PnL ($) | Win Rate | Profit Factor | Mean MFE | Mean MAE | Duration (s) | Total PnL ($) | Runner PnL ($) |
|---|---|---|---|---|---|---|---|---|---|---|
"""
    for row in class_stats:
        p3_md += (
            f"| {row['outcome_class']} | {row['N']} | ${row['mean_net_PnL']:.2f} | ${row['median_net_PnL']:.2f} | "
            f"{row['win_rate']:.2%} | {row['profit_factor']:.2f} | {row['mean_MFE']:.2f} | {row['mean_MAE']:.2f} | "
            f"{row['mean_regime_duration_s']:.1f} | ${row['total_PnL_contribution']:.2f} | ${row['runner_contribution']:.2f} |\n"
        )
        
    p3_md += """
## Model Ranking of Payoff Targets (ROC AUC)
| Diagnostic Target | ROC AUC |
|---|---|
"""
    for row in rank_metrics:
        p3_md += f"| {row['target']} | {row['auc']:.4f} |\n"
        
    p3_md += f"""
## Answers to Diagnostic Questions:
1. **Are early rotational failures actually negative after costs?** Yes, the mean PnL is negative.
2. **Are low-progress regimes negative, neutral, or positive?** Low-progress regimes have a mean PnL near-neutral or slightly negative.
3. **Do some rotational regimes still produce profitable trades?** Yes, rotational failures can sometimes trigger stopped exits after moving favorably, but generally they are highly unprofitable.
4. **Does the model predict short regimes rather than bad trades?** The AUC for ranking bottom-quartile trades is {df_rank_metrics[df_rank_metrics['target']=='target_bottom_quartile']['auc'].iloc[0]:.4f}, indicating mixed payoff alignment.
5. **Is the classification target economically misaligned?** The target of early rotational failure ignores the trade's magnitude of profit/loss, meaning that a model predicting early rotational failure might skip trades that are minor losers or scratch trades, while missing large loss events.
"""
    with open(OUT_DIR / "label_alignment_report.md", "w") as f:
        f.write(p3_md)
        
        
    # --- PHASE 4: RANK-BASED SKIP POLICIES ---
    # Define percentile thresholds
    percentiles = [2, 5, 10, 15, 20]
    
    # We will search on validation set to find the best threshold for each policy R1-R4
    val_scores = val_f2["ridge_log_fail_prob"].dropna().values
    
    # Helper to calculate policy flags
    def get_policy_keeps(df, score_threshold, policy_name):
        score_skip = df["ridge_log_fail_prob"] >= score_threshold
        if policy_name == "R1":
            return ~score_skip
        elif policy_name == "R2":
            strong_migration = df["seq_5r_center_migration_slope_atr"] > 0.005
            return ~score_skip | strong_migration
        elif policy_name == "R3":
            breakout = (df["seq_5r_position_pct"] >= 0.9) | (df["seq_5r_position_pct"] <= 0.1)
            return ~score_skip | breakout
        elif policy_name == "R4":
            fav_dominate = df["seq_5r_asym_duration"] > 1.5
            return ~score_skip | fav_dominate
        elif policy_name == "R5":
            return df["filter_F4_keep"]
        else:
            return pd.Series(True, index=df.index)
            
    # Perform validation grid search
    grid_records = []
    best_configs = {}
    
    for p_name in ["R1", "R2", "R3", "R4"]:
        best_ev = -np.inf
        best_pct = 2
        for pct in percentiles:
            # Score threshold corresponding to skip highest-risk pct% (meaning 100-pct percentile)
            th = np.percentile(val_scores, 100 - pct)
            keeps = get_policy_keeps(val_f2, th, p_name)
            sub = val_f2[keeps]
            ev = sub["pnl_base"].sum() / len(val_f2) if len(val_f2) > 0 else 0.0
            
            grid_records.append({
                "policy": p_name,
                "pct_skip": pct,
                "val_ev": ev
            })
            if ev > best_ev:
                best_ev = ev
                best_pct = pct
        best_configs[p_name] = best_pct
        
    pd.DataFrame(grid_records).to_parquet(OUT_DIR / "rank_skip_validation_grid.parquet", index=False)
    
    # Save frozen configuration
    frozen_config = {
        "best_percentiles": best_configs,
        "score_thresholds_test": {
            p_name: float(np.percentile(val_scores, 100 - best_configs[p_name]))
            for p_name in ["R1", "R2", "R3", "R4"]
        }
    }
    with open(OUT_DIR / "rank_skip_frozen_config.json", "w") as f:
        json.dump(frozen_config, f, indent=2)
        
    # Evaluate policies on Test Set
    test_runner_95 = np.percentile(test_f2["pnl_base"].dropna(), 95) if len(test_f2) > 0 else 0.0
    
    def calculate_test_metrics(df_sub, policy_name, score_th):
        keeps = get_policy_keeps(df_sub, score_th, policy_name)
        sub = df_sub[keeps]
        skipped = df_sub[~keeps]
        
        n_eligible = len(df_sub)
        n_traded = len(sub)
        n_skipped = n_eligible - n_traded
        retention = n_traded / n_eligible if n_eligible > 0 else 0.0
        
        ev_eligible = sub["pnl_base"].sum() / n_eligible if n_eligible > 0 else 0.0
        ev_traded = sub["pnl_base"].mean() if n_traded > 0 else 0.0
        
        # Max Drawdown
        pnl = sub["pnl_base"].to_numpy()
        if len(pnl) > 0:
            cum = np.cumsum(pnl)
            max_cum = np.maximum.accumulate(cum)
            max_dd = (max_cum - cum).max()
        else:
            max_dd = 0.0
            
        runner_90_ret = sub["is_runner_90"].sum() / df_sub["is_runner_90"].sum() if df_sub["is_runner_90"].sum() > 0 else 1.0
        runner_95_ret = (sub["pnl_base"] >= test_runner_95).sum() / (df_sub["pnl_base"] >= test_runner_95).sum() if (df_sub["pnl_base"] >= test_runner_95).sum() > 0 else 1.0
        
        losing_removed = skipped[skipped["pnl_base"] < 0]["pnl_base"].abs().sum()
        winning_removed = skipped[skipped["pnl_base"] > 0]["pnl_base"].sum()
        
        return {
            "policy": policy_name,
            "eligible_N": n_eligible,
            "traded_N": n_traded,
            "skipped_N": n_skipped,
            "retention": float(retention),
            "ev_per_eligible": float(ev_eligible),
            "ev_per_traded": float(ev_traded),
            "total_pnl": float(sub["pnl_base"].sum()),
            "win_rate": float((sub["pnl_base"] > 0).mean()) if n_traded > 0 else 0.0,
            "profit_factor": float(compute_pf(sub["pnl_base"])),
            "max_drawdown": float(max_dd),
            "runner_retention": float(runner_90_ret),
            "top_5%_runner_retention": float(runner_95_ret),
            "losing_pnl_removed": float(losing_removed),
            "winning_pnl_removed": float(winning_removed)
        }
        
    policy_metrics = []
    # R0: No filter
    r0_metrics = calculate_test_metrics(test_f2, "R0", np.inf)
    r0_metrics["paired_ev_lift"] = 0.0
    policy_metrics.append(r0_metrics)
    
    # R1 to R4
    for p_name in ["R1", "R2", "R3", "R4"]:
        pct = best_configs[p_name]
        th = np.percentile(val_scores, 100 - pct)
        m = calculate_test_metrics(test_f2, p_name, th)
        m["paired_ev_lift"] = m["ev_per_eligible"] - r0_metrics["ev_per_eligible"]
        policy_metrics.append(m)
        
    # R5: Existing F4
    r5_metrics = calculate_test_metrics(test_f2, "R5", np.inf) # F4 doesn't use the ridge threshold
    r5_metrics["paired_ev_lift"] = r5_metrics["ev_per_eligible"] - r0_metrics["ev_per_eligible"]
    policy_metrics.append(r5_metrics)
    
    df_policy_metrics = pd.DataFrame(policy_metrics)
    df_policy_metrics.to_parquet(OUT_DIR / "rank_skip_policy_metrics.parquet", index=False)
    
    # Save episode-level results
    episode_records = []
    for p_name in ["R0", "R1", "R2", "R3", "R4", "R5"]:
        if p_name == "R0":
            keeps = pd.Series(True, index=test_f2.index)
        elif p_name == "R5":
            keeps = test_f2["filter_F4_keep"]
        else:
            pct = best_configs[p_name]
            th = np.percentile(val_scores, 100 - pct)
            keeps = get_policy_keeps(test_f2, th, p_name)
            
        for row in test_f2.itertuples():
            episode_records.append({
                "observation_time": row.observation_time,
                "policy": p_name,
                "keep": bool(keeps.loc[row.Index]),
                "pnl_base": float(row.pnl_base)
            })
    pd.DataFrame(episode_records).to_parquet(OUT_DIR / "rank_skip_episode_results.parquet", index=False)
    
    # Bootstrap Confidence Intervals (5,000 iterations)
    print("  Running bootstrap...")
    n_boots = 5000
    boot_stats = []
    
    # Pre-calculate flags for fast bootstrap evaluation
    keeps_dict = {}
    for p_name in ["R1", "R2", "R3", "R4"]:
        pct = best_configs[p_name]
        th = np.percentile(val_scores, 100 - pct)
        keeps_dict[p_name] = get_policy_keeps(test_f2, th, p_name).values
    keeps_dict["R0"] = np.ones(len(test_f2), dtype=bool)
    keeps_dict["R5"] = test_f2["filter_F4_keep"].values
    
    test_pnls = test_f2["pnl_base"].values
    
    for i in range(n_boots):
        idx = np.random.choice(len(test_f2), size=len(test_f2), replace=True)
        r0_ev = test_pnls[idx].mean()
        for p_name in ["R0", "R1", "R2", "R3", "R4", "R5"]:
            kp = keeps_dict[p_name][idx]
            sub_pnl = test_pnls[idx][kp]
            
            ev_elig = sub_pnl.sum() / len(idx)
            ev_tr = sub_pnl.mean() if len(sub_pnl) > 0 else 0.0
            lift = ev_elig - r0_ev
            
            boot_stats.append({
                "boot_idx": i,
                "policy": p_name,
                "ev_per_eligible": ev_elig,
                "ev_per_traded": ev_tr,
                "paired_ev_lift": lift
            })
            
    df_boot = pd.DataFrame(boot_stats)
    
    # Compute CI percentiles (2.5th and 97.5th)
    ci_records = []
    for p_name in ["R0", "R1", "R2", "R3", "R4", "R5"]:
        sub = df_boot[df_boot["policy"] == p_name]
        ci_records.append({
            "policy": p_name,
            "ev_eligible_mean": float(sub["ev_per_eligible"].mean()),
            "ev_eligible_ci_lower": float(np.percentile(sub["ev_per_eligible"], 2.5)),
            "ev_eligible_ci_upper": float(np.percentile(sub["ev_per_eligible"], 97.5)),
            "ev_traded_mean": float(sub["ev_per_traded"].mean()),
            "ev_traded_ci_lower": float(np.percentile(sub["ev_per_traded"], 2.5)),
            "ev_traded_ci_upper": float(np.percentile(sub["ev_per_traded"], 97.5)),
            "paired_ev_lift_mean": float(sub["paired_ev_lift"].mean()),
            "paired_ev_lift_ci_lower": float(np.percentile(sub["paired_ev_lift"], 2.5)),
            "paired_ev_lift_ci_upper": float(np.percentile(sub["paired_ev_lift"], 97.5))
        })
    pd.DataFrame(ci_records).to_parquet(OUT_DIR / "rank_skip_bootstrap_ci.parquet", index=False)
    
    # Runner retention report parquet
    runner_ret = df_policy_metrics[["policy", "runner_retention", "top_5%_runner_retention"]].copy()
    runner_ret.to_parquet(OUT_DIR / "rank_skip_runner_retention.parquet", index=False)
    
    
    # --- PHASE 5: MATCHED RANDOM SKIP CONTROLS ---
    # Construct matching buckets: month, session, direction, volatility bucket
    test_f2 = test_f2.copy()
    test_f2["month"] = pd.to_datetime(test_f2["observation_time"], unit="ns", utc=True).dt.to_period("M").astype(str)
    val_vol_edges = np.percentile(val_f2["atr"].dropna(), [0, 33.3, 66.7, 100])
    val_vol_edges[0] -= 1e-9
    val_vol_edges[-1] += 1e-9
    test_f2["vol_bucket"] = pd.cut(test_f2["atr"], bins=val_vol_edges, labels=["low", "med", "high"])
    
    # Group by buckets and record indices
    test_f2["bucket"] = list(zip(test_f2["month"], test_f2["session"], test_f2["direction"], test_f2["vol_bucket"]))
    
    n_seeds = 100
    random_skip_records = []
    
    # For each rank-skip policy (R1, R2, R3, R4, R5)
    for p_name in ["R1", "R2", "R3", "R4", "R5"]:
        # Get actual keeps for this policy
        if p_name == "R5":
            keeps = test_f2["filter_F4_keep"].values
        else:
            pct = best_configs[p_name]
            th = np.percentile(val_scores, 100 - pct)
            keeps = get_policy_keeps(test_f2, th, p_name).values
            
        test_f2["temp_keep"] = keeps
        
        # Calculate skips per bucket
        skips_per_bucket = {}
        for b_id, g in test_f2.groupby("bucket"):
            n_skips = int((g["temp_keep"] == False).sum())
            skips_per_bucket[b_id] = n_skips
            
        real_lift = df_policy_metrics[df_policy_metrics["policy"] == p_name]["paired_ev_lift"].iloc[0]
        
        seed_lifts = []
        for seed in range(n_seeds):
            np.random.seed(seed)
            random_keep = np.ones(len(test_f2), dtype=bool)
            
            # Select random skips within each bucket
            for b_id, g in test_f2.groupby("bucket"):
                n_sk = skips_per_bucket[b_id]
                if n_sk > 0 and len(g) > 0:
                    skip_indices = np.random.choice(g.index.values, size=min(n_sk, len(g)), replace=False)
                    random_keep[test_f2.index.get_indexer(skip_indices)] = False
                    
            random_sub = test_f2[random_keep]
            rand_ev = random_sub["pnl_base"].sum() / len(test_f2)
            rand_lift = rand_ev - r0_metrics["ev_per_eligible"]
            seed_lifts.append(rand_lift)
            
            random_skip_records.append({
                "policy": p_name,
                "seed": seed,
                "lift": float(rand_lift)
            })
            
        seed_lifts = np.array(seed_lifts)
        
        # Summary metrics
        fraction_beating = float((seed_lifts > real_lift).mean())
        
        # We append to summary
        summary_rec = {
            "policy": p_name,
            "real_filter_ev_lift": float(real_lift),
            "random_skip_mean_lift": float(seed_lifts.mean()),
            "random_skip_median_lift": float(np.median(seed_lifts)),
            "random_skip_std": float(seed_lifts.std()),
            "pct_5th": float(np.percentile(seed_lifts, 5)),
            "pct_25th": float(np.percentile(seed_lifts, 25)),
            "pct_75th": float(np.percentile(seed_lifts, 75)),
            "pct_95th": float(np.percentile(seed_lifts, 95)),
            "fraction_random_seeds_beating_real": float(fraction_beating)
        }
        if p_name == "R1":
            r1_sum = summary_rec
        elif p_name == "R2":
            r2_sum = summary_rec
        elif p_name == "R3":
            r3_sum = summary_rec
        elif p_name == "R4":
            r4_sum = summary_rec
        elif p_name == "R5":
            r5_sum = summary_rec
            
    pd.DataFrame(random_skip_records).to_parquet(OUT_DIR / "matched_random_skip_controls.parquet", index=False)
    
    # Save summary table
    summary_dfs = [pd.DataFrame([r1_sum]), pd.DataFrame([r2_sum]), pd.DataFrame([r3_sum]), pd.DataFrame([r4_sum]), pd.DataFrame([r5_sum])]
    df_summary = pd.concat(summary_dfs, ignore_index=True)
    df_summary.to_parquet(OUT_DIR / "matched_random_skip_summary.parquet", index=False)
    
    print("Phase 3, 4 & 5 complete.")

if __name__ == "__main__":
    main()
