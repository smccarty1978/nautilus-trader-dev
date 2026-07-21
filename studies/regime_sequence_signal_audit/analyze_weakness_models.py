import os
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LinearRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, log_loss

# Add Nautilus Trader path
PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))

OUT_DIR = Path("studies/regime_sequence_signal_audit/results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def is_rth(ts_ns):
    dt = pd.Timestamp(ts_ns, unit='ns', tz='UTC').tz_convert('America/Chicago')
    from datetime import time
    t = dt.time()
    return (dt.dayofweek < 5) and (time(8, 30) <= t <= time(15, 15))

# Define feature families
LOCAL_FEATS = ["regime_age", "current_pnl", "current_mfe", "current_mae", "giveback"]

CENTER_FEATS = [
    "aligned_price_minus_center_5m", "aligned_price_minus_center_15m", "aligned_price_minus_center_30m",
    "slope_5m_1m_aligned_atr", "slope_5m_3m_aligned_atr", "slope_5m_5m_aligned_atr",
    "slope_15m_3m_aligned_atr", "slope_15m_5m_aligned_atr", "slope_15m_10m_aligned_atr",
    "slope_30m_5m_aligned_atr", "slope_30m_10m_aligned_atr", "slope_30m_15m_aligned_atr",
    "center_slope_change_5m", "center_slope_change_15m", "center_slope_change_30m",
    "center_slope_acceleration_5m", "center_slope_acceleration_15m", "center_slope_acceleration_30m",
    "center_spread_5m_15m", "center_spread_15m_30m", "center_spread_5m_30m",
    "spread_change_5m_15m", "spread_change_15m_30m", "spread_change_5m_30m",
    "ordering_state", "seconds_in_current_ordering",
    "ordering_changes_15m", "ordering_changes_30m", "ordering_changes_60m",
    "price_cross_count_5m", "price_cross_count_15m", "price_cross_count_30m",
    "crosses_per_minute", "fraction_of_time_on_favorable_side", "fraction_of_time_on_adverse_side",
    "activity_regime_count_5m", "activity_regime_count_15m", "activity_regime_count_30m", "activity_regime_count_60m", "activity_regime_count_120m",
    "activity_flip_count_30m", "activity_duration_median_30m",
    "duration_median_last_3", "duration_median_last_5", "duration_median_last_10",
    "duration_ratio_3_vs_10", "duration_ratio_5_vs_10",
    "cross_family_spread_vs_reg_count", "cross_family_slope_vs_reg_count"
]

SEQUENCE_FEATS = []
for K in (3, 5, 8, 12):
    for f in ["alternation_rate", "perfect_alternation", "efficiency", "disp_atr",
              "mean_overlap", "median_overlap", "max_overlap", "overlap_above_50", "overlap_above_75",
              "mean_retracement", "mean_retracement_mfe", "reclaim_rate", "range_atr", "position_pct",
              "dist_to_high_atr", "dist_to_low_atr", "center_migration_slope_atr", "center_migration_r2",
              "center_dir_consistency", "center_reversal_count", "asym_duration", "asym_mfe",
              "asym_net_move", "asym_efficiency", "asym_volume"]:
        SEQUENCE_FEATS.append(f"seq_{K}r_{f}")

def compute_new_fav_labels(df_subset):
    # Sort
    df_subset = df_subset.sort_values(["direction", "regime_start_time", "observation_time"]).copy()
    
    new_fav_30s = np.zeros(len(df_subset), dtype=int)
    new_fav_60s = np.zeros(len(df_subset), dtype=int)
    new_fav_120s = np.zeros(len(df_subset), dtype=int)
    
    # Group by episode
    gp_idx = df_subset.groupby(["direction", "regime_start_time"]).indices
    
    times = df_subset["observation_time"].values
    mfes = df_subset["current_mfe"].values
    add_mfes = df_subset["additional_mfe_remaining"].values
    
    for ep_key, idxs in gp_idx.items():
        if len(idxs) == 0:
            continue
        ep_times = times[idxs]
        ep_mfes = mfes[idxs]
        
        n_cp = len(idxs)
        for i in range(n_cp):
            t_curr = ep_times[i]
            mfe_curr = ep_mfes[i]
            
            # Find future checkpoints within W seconds
            for W, target_arr in [(30, new_fav_30s), (60, new_fav_60s), (120, new_fav_120s)]:
                future_idx = i + 1
                made_new_fav = False
                while future_idx < n_cp and ep_times[future_idx] <= t_curr + W * 1e9:
                    if ep_mfes[future_idx] > mfe_curr:
                        made_new_fav = True
                        break
                    future_idx += 1
                
                # Also check if a new extreme was made at the end of the regime
                if not made_new_fav:
                    if add_mfes[idxs[i]] > 0 and (ep_times[-1] - t_curr) <= W * 1e9:
                        made_new_fav = True
                        
                if made_new_fav:
                    target_arr[idxs[i]] = 1
                    
    df_subset["new_fav_in_30s"] = new_fav_30s
    df_subset["new_fav_in_60s"] = new_fav_60s
    df_subset["new_fav_in_120s"] = new_fav_120s
    return df_subset

def main():
    print("Running Phase 6 & 7: Weakness models audit and score deciles...")
    
    # Load combined weakness checkpoint atlas
    atlas_path = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/weakness_checkpoint_atlas.parquet"
    if not atlas_path.exists():
        print(f"Error: {atlas_path} not found.")
        return
        
    df_weak = pd.read_parquet(atlas_path)
    
    # Create regime_start_time column to identify episodes
    df_weak["regime_start_time"] = df_weak["observation_time"] - (df_weak["regime_age"] * 1e9).astype(int)
    
    # Clean up NaNs
    df_weak = df_weak.dropna(subset=["aligned_price_minus_center_5m"]).copy()
    
    # Create target_weakness_120s target
    df_weak["target_weakness_120s"] = ((df_weak["opp_flip_in_120s"] == 1) | (df_weak["terminal_deterioration"] == 1)).astype(int)
    
    # Split periods
    train = df_weak[df_weak["period"] == "train"].copy()
    val = df_weak[df_weak["period"] == "val"].copy()
    test = df_weak[df_weak["period"] == "test"].copy()
    
    print(f"  Split counts - Train: {len(train):,}, Val: {len(val):,}, Test: {len(test):,}")
    
    spec_features = {
        "W0": LOCAL_FEATS,
        "W1": CENTER_FEATS,
        "W2": SEQUENCE_FEATS,
        "W3": CENTER_FEATS + SEQUENCE_FEATS,
        "W4": CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS
    }
    
    y_tr = train["target_weakness_120s"].values
    y_vl = val["target_weakness_120s"].values
    y_te = test["target_weakness_120s"].values
    
    # Fit and score W0-W4
    val_probs = {}
    test_probs = {}
    
    comparison_metrics = []
    
    for name, feats in spec_features.items():
        print(f"  Fitting {name}...")
        clf = HistGradientBoostingClassifier(
            max_iter=100, max_depth=5, learning_rate=0.05, random_state=42
        )
        # Train on train
        clf.fit(train[feats].values, y_tr)
        
        # Predict validation & test
        p_vl = clf.predict_proba(val[feats].values)[:, 1]
        p_te = clf.predict_proba(test[feats].values)[:, 1]
        
        val_probs[name] = p_vl
        test_probs[name] = p_te
        
        # Calculate validation and test metrics
        for split_name, y_true, p_pred in [("validation", y_vl, p_vl), ("test", y_te, p_te)]:
            roc_auc = roc_auc_score(y_true, p_pred)
            pr_auc = average_precision_score(y_true, p_pred)
            brier = brier_score_loss(y_true, p_pred)
            ll = log_loss(y_true, p_pred)
            
            # Calibration slope & intercept
            reg = LinearRegression()
            reg.fit(p_pred.reshape(-1, 1), y_true)
            slope = reg.coef_[0]
            intercept = reg.intercept_
            
            # Top-decile precision & recall
            th_decile = np.percentile(p_pred, 90)
            top_decile_preds = (p_pred >= th_decile).astype(int)
            
            # Precision = true positives / predicted positives
            precision = (y_true[p_pred >= th_decile] == 1).mean() if (p_pred >= th_decile).any() else 0.0
            # Recall = true positives / actual positives
            recall = (y_true[p_pred >= th_decile] == 1).sum() / (y_true == 1).sum() if (y_true == 1).sum() > 0 else 0.0
            
            comparison_metrics.append({
                "model": name,
                "split": split_name,
                "roc_auc": float(roc_auc),
                "pr_auc": float(pr_auc),
                "brier_score": float(brier),
                "log_loss": float(ll),
                "calibration_slope": float(slope),
                "calibration_intercept": float(intercept),
                "top_decile_precision": float(precision),
                "top_decile_recall": float(recall),
                "base_event_rate": float(y_true.mean())
            })
            
    df_comparison = pd.DataFrame(comparison_metrics)
    df_comparison.to_parquet(OUT_DIR / "weakness_model_comparison.parquet", index=False)
    
    # Save test W4 probability on test set for downstream use
    test = test.copy()
    test["w4_prob"] = test_probs["W4"]
    
    # Paired Bootstrap Confidence Intervals for Metric Differences (Test Set)
    print("  Running bootstrap for W4 metric lift...")
    n_boots = 1000
    boot_diffs = []
    
    # Draw indices
    np.random.seed(42)
    # Downsample bootstrap evaluation to 50k rows for speed
    boot_eval_size = 50000
    
    for i in range(n_boots):
        idx = np.random.choice(len(test), size=boot_eval_size, replace=True)
        y_true_b = y_te[idx]
        
        # Calculate metrics for each model
        model_aucs = {}
        model_pr_aucs = {}
        for name in ["W0", "W1", "W2", "W3", "W4"]:
            p_pred_b = test_probs[name][idx]
            model_aucs[name] = roc_auc_score(y_true_b, p_pred_b)
            model_pr_aucs[name] = average_precision_score(y_true_b, p_pred_b)
            
        boot_diffs.append({
            "boot_idx": i,
            "W4_minus_W0_auc": model_aucs["W4"] - model_aucs["W0"],
            "W4_minus_W0_pr_auc": model_pr_aucs["W4"] - model_pr_aucs["W0"],
            "W3_minus_W0_auc": model_aucs["W3"] - model_aucs["W0"],
            "W2_minus_W0_auc": model_aucs["W2"] - model_aucs["W0"],
            "W1_minus_W0_auc": model_aucs["W1"] - model_aucs["W0"]
        })
        
    df_diffs = pd.DataFrame(boot_diffs)
    
    # Compute CIs
    ci_records = []
    for col in ["W4_minus_W0_auc", "W4_minus_W0_pr_auc", "W3_minus_W0_auc", "W2_minus_W0_auc", "W1_minus_W0_auc"]:
        vals = df_diffs[col].values
        ci_records.append({
            "comparison": col,
            "mean_difference": float(vals.mean()),
            "ci_lower": float(np.percentile(vals, 2.5)),
            "ci_upper": float(np.percentile(vals, 97.5))
        })
    pd.DataFrame(ci_records).to_parquet(OUT_DIR / "weakness_incremental_lift.parquet", index=False)
    
    # Calibration Curves
    # Save a table containing prediction and target metrics for validation
    calibration_records = []
    # Bin W4 validation predictions into 10 bins
    val = val.copy()
    val["w4_prob"] = val_probs["W4"]
    val["bin"] = pd.qcut(val["w4_prob"], 10, labels=False, duplicates="drop")
    for b_idx, g in val.groupby("bin"):
        calibration_records.append({
            "bin": int(b_idx),
            "mean_prediction": float(g["w4_prob"].mean()),
            "observed_event_rate": float(g["target_weakness_120s"].mean()),
            "count": len(g)
        })
    pd.DataFrame(calibration_records).to_parquet(OUT_DIR / "weakness_calibration.parquet", index=False)
    
    
    # --- PHASE 7: WEAKNESS SCORE DECILE ECONOMICS ---
    print("  Computing Phase 7 decile economics...")
    # Calculate decile cut points on validation set's W4 score
    val_w4_scores = val["w4_prob"].dropna().values
    edges = np.percentile(val_w4_scores, np.linspace(0, 100, 11))
    edges[0] -= 1e-9
    edges[-1] += 1e-9
    
    # Assign deciles on test set
    test["decile"] = pd.cut(test["w4_prob"], bins=edges, labels=range(1, 11)).astype(float)
    test = test.dropna(subset=["decile"])
    test["decile"] = test["decile"].astype(int)
    
    # Add RTH/ETH session column to test checkpoints
    test["session"] = test["observation_time"].apply(
        lambda ts: "RTH" if is_rth(ts) else "ETH"
    )
    
    # Compute new favorable extreme labels on validation & test sets
    test = compute_new_fav_labels(test)
    
    # Helper to calculate decile stats for weakness
    def calculate_weakness_decile_table(df_grp):
        records = []
        for decile, g in df_grp.groupby("decile"):
            n = len(g)
            ep_n = len(g.groupby(["direction", "regime_start_time"]))
            
            weakness_rate = g["target_weakness_120s"].mean()
            opp_30s = g["opp_flip_in_30s"].mean()
            opp_60s = g["opp_flip_in_60s"].mean()
            opp_120s = g["opp_flip_in_120s"].mean()
            
            rec_mfe = g["recovered_120s"].mean()
            
            new_fav_30 = g["new_fav_in_30s"].mean()
            new_fav_60 = g["new_fav_in_60s"].mean()
            new_fav_120 = g["new_fav_in_120s"].mean()
            
            exp_rem_mfe = g["additional_mfe_remaining"].mean()
            exp_add_gb = g["max_giveback_before_next_fav_extreme"].mean()
            
            records.append({
                "decile": int(decile),
                "checkpoint_N": n,
                "episode_N": ep_n,
                "terminal_weakness_event_rate": float(weakness_rate),
                "opposite_flip_within_30s": float(opp_30s),
                "opposite_flip_within_60s": float(opp_60s),
                "opposite_flip_within_120s": float(opp_120s),
                "recovery_to_prior_MFE": float(rec_mfe),
                "new_favorable_extreme_within_30s": float(new_fav_30),
                "new_favorable_extreme_within_60s": float(new_fav_60),
                "new_favorable_extreme_within_120s": float(new_fav_120),
                "expected_remaining_MFE": float(exp_rem_mfe),
                "expected_additional_giveback": float(exp_add_gb)
            })
        return pd.DataFrame(records)

    # Segment breakdowns for weakness deciles
    # Age breaks: early (regime_age < 60), middle (60 <= regime_age < 300), late (regime_age >= 300)
    weak_segments = {
        "pooled": test,
        "long": test[test["direction"] == 1],
        "short": test[test["direction"] == -1],
        "RTH": test[test["session"] == "RTH"],
        "ETH": test[test["session"] == "ETH"],
        "early_regime_age": test[test["regime_age"] < 60.0],
        "middle_regime_age": test[(test["regime_age"] >= 60.0) & (test["regime_age"] < 300.0)],
        "late_regime_age": test[test["regime_age"] >= 300.0],
        "top_decile_runner_regimes": test[test["current_mfe"] >= 2.0],
        "ordinary_regimes": test[test["current_mfe"] < 2.0]
    }
    
    weak_decile_dfs = []
    for name, df_seg in weak_segments.items():
        if len(df_seg) > 0:
            df_dec = calculate_weakness_decile_table(df_seg)
            df_dec["segment"] = name
            weak_decile_dfs.append(df_dec)
            
    df_weak_segment_deciles = pd.concat(weak_decile_dfs, ignore_index=True)
    df_weak_segment_deciles.to_parquet(OUT_DIR / "weakness_score_segment_deciles.parquet", index=False)
    
    # Save pooled weakness deciles separately
    pooled_weak_dec = df_weak_segment_deciles[df_weak_segment_deciles["segment"] == "pooled"].sort_values("decile")
    pooled_weak_dec.to_parquet(OUT_DIR / "weakness_score_deciles.parquet", index=False)
    
    print("Phase 6 & 7 complete.")

if __name__ == "__main__":
    main()
