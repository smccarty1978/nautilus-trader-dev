import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score, mean_squared_error
import warnings
warnings.filterwarnings("ignore")

# Define features families
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

def train_and_evaluate_weakness_models(df_weakness: pd.DataFrame, out_dir: Path) -> dict:
    print("Training Within-Regime Weakness models...")
    
    # Filter out NaNs in key features
    df_weakness = df_weakness.dropna(subset=['aligned_price_minus_center_5m']).copy()
    
    # Target: terminal weakness within 120s
    # Terminal weakness: opp_flip_in_120s == 1 or terminal_deterioration == 1
    y_all = (df_weakness['opp_flip_in_120s'] == 1) | (df_weakness['terminal_deterioration'] == 1)
    df_weakness['target_weakness_120s'] = y_all.astype(int)
    
    # Split periods
    train = df_weakness[df_weakness['period'] == 'train'].copy()
    val = df_weakness[df_weakness['period'] == 'val'].copy()
    test = df_weakness[df_weakness['period'] == 'test'].copy()
    
    print(f"  Split counts - Train: {len(train):,}, Val: {len(val):,}, Test: {len(test):,}")
    
    if len(train) < 100 or len(val) < 20:
        print("  Not enough data to train weakness models.")
        return {}
        
    y_tr = train['target_weakness_120s'].values
    y_vl = val['target_weakness_120s'].values
    y_te = test['target_weakness_120s'].values if len(test) > 0 else None
    
    # Define models specifications
    spec_features = {
        "W0": LOCAL_FEATS,
        "W1": CENTER_FEATS,
        "W2": SEQUENCE_FEATS,
        "W3": CENTER_FEATS + SEQUENCE_FEATS,
        "W4": CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS
    }
    
    results = []
    trained_models = {}
    
    for name, feats in spec_features.items():
        print(f"  Training specification {name} ({len(feats)} features)...")
        
        # Prepare arrays (HistGradientBoosting Classifier handles NaNs automatically)
        X_tr = train[feats].values
        X_vl = val[feats].values
        
        clf = HistGradientBoostingClassifier(
            max_iter=100, max_depth=5, learning_rate=0.05, random_state=42
        )
        clf.fit(X_tr, y_tr)
        
        # Evaluate
        prob_tr = clf.predict_proba(X_tr)[:, 1]
        prob_vl = clf.predict_proba(X_vl)[:, 1]
        
        auc_tr = roc_auc_score(y_tr, prob_tr)
        auc_vl = roc_auc_score(y_vl, prob_vl)
        
        # Test evaluation if available
        if y_te is not None and len(test) > 0:
            X_te = test[feats].values
            prob_te = clf.predict_proba(X_te)[:, 1]
            auc_te = roc_auc_score(y_te, prob_te)
        else:
            auc_te = np.nan
            prob_te = None
            
        print(f"    {name} Validation AUC: {auc_vl:.4f} | Train AUC: {auc_tr:.4f}")
        results.append({
            "model_spec": name,
            "auc_train": float(auc_tr),
            "auc_val": float(auc_vl),
            "auc_test": float(auc_te)
        })
        trained_models[name] = clf
        
    df_res = pd.DataFrame(results)
    df_res.to_parquet(out_dir / "weakness_validation_metrics.parquet", index=False)
    
    # Save best model manifest
    best_spec = df_res.loc[df_res['auc_val'].idxmax(), 'model_spec']
    manifest = {
        "best_spec": best_spec,
        "features": spec_features[best_spec],
        "all_specs": results
    }
    with open(out_dir / "weakness_model_manifest.json", "w") as f_out:
        json.dump(manifest, f_out, indent=2)
        
    print(f"  Best specification is {best_spec}.")
    return {
        "models": trained_models,
        "best_spec": best_spec,
        "features_by_spec": spec_features
    }
