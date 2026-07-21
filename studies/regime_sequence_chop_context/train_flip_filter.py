import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss, mean_squared_error
from sklearn.pipeline import Pipeline
import warnings
warnings.filterwarnings("ignore")

FEATURES_LIST = [
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

# Add sequence features
for K in (3, 5, 8, 12):
    for f in ["alternation_rate", "perfect_alternation", "efficiency", "disp_atr",
              "mean_overlap", "median_overlap", "max_overlap", "overlap_above_50", "overlap_above_75",
              "mean_retracement", "mean_retracement_mfe", "reclaim_rate", "range_atr", "position_pct",
              "dist_to_high_atr", "dist_to_low_atr", "center_migration_slope_atr", "center_migration_r2",
              "center_dir_consistency", "center_reversal_count", "asym_duration", "asym_mfe",
              "asym_net_move", "asym_efficiency", "asym_volume"]:
        FEATURES_LIST.append(f"seq_{K}r_{f}")

def train_and_evaluate_flip_filters(df_atlas: pd.DataFrame, out_dir: Path, population_name: str) -> dict:
    """Train models for Track A: Flip-time chop filters."""
    print(f"Training Flip-Filter models for {population_name}...")
    
    # Filter valid rows (features must not be all NaN, and target must be present)
    df_atlas = df_atlas.dropna(subset=['aligned_price_minus_center_5m', 'pnl_base']).copy()
    
    # Split periods
    train = df_atlas[df_atlas['period'] == 'train'].copy()
    val = df_atlas[df_atlas['period'] == 'val'].copy()
    test = df_atlas[df_atlas['period'] == 'test'].copy()
    
    print(f"  Split counts - Train: {len(train):,}, Val: {len(val):,}, Test: {len(test):,}")
    if len(train) < 50 or len(val) < 10:
        print("  Not enough data to train models.")
        return {}
        
    # Prepare features
    # Impute missing values with train median
    X_train_raw = train[FEATURES_LIST].values
    X_val_raw = val[FEATURES_LIST].values
    X_test_raw = test[FEATURES_LIST].values
    
    medians = np.nanmedian(X_train_raw, axis=0)
    # Replace remaining NaNs (e.g. if a feature is all NaNs in train) with 0.0
    medians = np.nan_to_num(medians, nan=0.0)
    
    X_tr = np.where(np.isnan(X_train_raw), medians, X_train_raw)
    X_vl = np.where(np.isnan(X_val_raw), medians, X_val_raw)
    X_te = np.where(np.isnan(X_test_raw), medians, X_test_raw)
    
    # Target: early failure (early failure = 1, productive = 0)
    y_tr_fail = (train['outcome_class'] == 'EARLY_ROTATIONAL_FAILURE').astype(int).values
    y_vl_fail = (val['outcome_class'] == 'EARLY_ROTATIONAL_FAILURE').astype(int).values
    
    # Target: expected PnL
    y_tr_pnl = train['pnl_base'].values
    y_vl_pnl = val['pnl_base'].values
    
    # Models
    models = {
        "ridge_log_fail": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=0.1, max_iter=500, penalty='l2'))
        ]),
        "gbm_fail": HistGradientBoostingClassifier(
            max_iter=100, max_depth=4, learning_rate=0.05, random_state=42
        ),
        "gbm_pnl_regressor": HistGradientBoostingRegressor(
            max_iter=100, max_depth=4, learning_rate=0.05, random_state=42
        )
    }
    
    # Fit models
    print("  Fitting early-failure classifier (Ridge Log)...")
    models["ridge_log_fail"].fit(X_tr, y_tr_fail)
    print("  Fitting early-failure classifier (GBM)...")
    models["gbm_fail"].fit(X_tr, y_tr_fail)
    print("  Fitting PnL regressor (GBM)...")
    models["gbm_pnl_regressor"].fit(X_tr, y_tr_pnl)
    
    # Predict on validation
    prob_vl_ridge = models["ridge_log_fail"].predict_proba(X_vl)[:, 1]
    prob_vl_gbm = models["gbm_fail"].predict_proba(X_vl)[:, 1]
    pred_vl_pnl = models["gbm_pnl_regressor"].predict(X_vl)
    
    auc_ridge = roc_auc_score(y_vl_fail, prob_vl_ridge)
    auc_gbm = roc_auc_score(y_vl_fail, prob_vl_gbm)
    mse_pnl = mean_squared_error(y_vl_pnl, pred_vl_pnl)
    
    print(f"  Validation results:")
    print(f"    Ridge Log Fail AUC: {auc_ridge:.4f}")
    print(f"    GBM Fail AUC: {auc_gbm:.4f}")
    print(f"    GBM PnL MSE: {mse_pnl:.4f}")
    
    # Save predictions and metrics
    metrics = {
        "population": population_name,
        "auc_ridge_fail": float(auc_ridge),
        "auc_gbm_fail": float(auc_gbm),
        "mse_gbm_pnl": float(mse_pnl),
    }
    
    # Write validation metrics
    pd.DataFrame([metrics]).to_parquet(out_dir / f"flip_validation_metrics_{population_name}.parquet", index=False)
    
    # Manifest
    manifest = {
        "features": FEATURES_LIST,
        "medians": list(medians),
        "population": population_name
    }
    with open(out_dir / f"flip_model_manifest_{population_name}.json", "w") as f_out:
        json.dump(manifest, f_out, indent=2)
        
    return {
        "models": models,
        "medians": medians,
        "features": FEATURES_LIST
    }
