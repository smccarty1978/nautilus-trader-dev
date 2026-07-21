"""Train ML Models v2 - Using ALL data (no CTB filter).

Same 3 models, but trained on full dataset including CTB=0 trades.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import (
    roc_auc_score, accuracy_score, precision_score, recall_score,
    f1_score, precision_recall_curve, roc_curve, confusion_matrix
)
from sklearn.calibration import calibration_curve
import matplotlib.pyplot as plt
import json


# Feature columns (64 features from FEATURES.md)
FEATURE_COLUMNS = [
    # Arrival Velocity (10)
    'arrival_vel_5s', 'arrival_vel_10s', 'arrival_vel_20s', 'arrival_vel_30s',
    'arrival_accel_5s', 'arrival_accel_10s', 'arrival_jerk', 'max_vel_30s',
    'vel_ratio_5_20', 'is_decelerating',
    # Arrival Volume (10)
    'rvol_1s', 'rvol_5s', 'rvol_10s', 'vol_trend_10s', 'vol_spike', 'vol_climax',
    'vol_accel', 'up_vol_ratio_10s', 'down_vol_ratio_10s', 'vol_price_corr_10s',
    # Touch Bar Structure (10)
    'touch_bar_body_ratio', 'touch_bar_upper_wick', 'touch_bar_lower_wick',
    'touch_bar_direction', 'touch_bar_size_atr', 'touch_bar_body_atr',
    'touch_bar_position', 'touch_overshoot_atr', 'touch_precision', 'touch_bar_is_doji',
    # Pullback Structure 1s (8)
    'higher_lows_count_1s', 'lower_highs_count_1s', 'swing_count_1s',
    'pullback_linearity_1s', 'consecutive_down_1s', 'consecutive_up_1s',
    'range_30s_atr', 'close_vs_range_30s',
    # Pullback Structure 1m (8)
    'higher_lows_count_1m', 'lower_highs_count_1m', 'swing_count_1m',
    'pullback_depth_atr', 'pullback_bars_1m', 'pullback_efficiency_1m',
    'retracement_pct', 'clean_pullback_score_1m',
    # Regime Context (12)
    'regime_direction', 'bars_in_regime', 'regime_strength', 'ema_slope_short',
    'ema_slope_long', 'ema_spread', 'ema_spread_expanding', 'ctb_at_touch',
    'breach_count_in_regime', 'touch_number_in_regime', 'atr_1m', 'atr_ratio_5_20',
    # Time Context (6)
    'hour_of_day_ct', 'minute_of_hour', 'day_of_week', 'minutes_since_rth_open',
    'is_rth', 'session',
]


def load_data():
    """Load ALL data (no CTB filter) and split by timestamp."""
    print("Loading data (ALL, no CTB filter)...")
    df = pd.read_parquet("studies/mfe_mae_foundation/results/ml_features_2025_all.parquet")
    print(f"Total samples: {len(df):,}")

    # CTB distribution
    print(f"\nCTB distribution:")
    print(f"  CTB=0: {len(df[df['ctb_at_touch']==0]):,}")
    print(f"  CTB>=1: {len(df[df['ctb_at_touch']>=1]):,}")

    # Convert entry_ts to datetime for splitting
    df['entry_dt'] = pd.to_datetime(df['entry_ts'], unit='ns', utc=True)

    # Split: Train = Jan-Sep, Test = Oct-Dec
    train_end = pd.Timestamp("2025-10-01", tz="UTC")

    train_df = df[df['entry_dt'] < train_end].copy()
    test_df = df[df['entry_dt'] >= train_end].copy()

    print(f"\nTrain samples: {len(train_df):,} (Jan-Sep)")
    print(f"Test samples: {len(test_df):,} (Oct-Dec)")

    return train_df, test_df


def prepare_features(df):
    """Extract feature matrix and handle missing values."""
    X = df[FEATURE_COLUMNS].copy()
    X = X.replace([np.inf, -np.inf], np.nan)
    X = X.fillna(0)
    return X


def train_and_evaluate(X_train, y_train, X_test, y_test, model_name, output_dir):
    """Train LightGBM model and evaluate."""
    print(f"\n{'='*70}")
    print(f"TRAINING: {model_name}")
    print(f"{'='*70}")

    pos_rate = y_train.mean()
    print(f"Train positive rate: {pos_rate:.1%}")
    print(f"Test positive rate: {y_test.mean():.1%}")

    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'seed': 42,
        'n_jobs': -1,
    }

    if pos_rate < 0.3:
        params['scale_pos_weight'] = (1 - pos_rate) / pos_rate

    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    print("\nTraining...")
    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[train_data, valid_data],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=100),
        ],
    )

    # Predictions
    y_train_pred = model.predict(X_train)
    y_test_pred = model.predict(X_test)

    # Metrics
    train_auc = roc_auc_score(y_train, y_train_pred)
    test_auc = roc_auc_score(y_test, y_test_pred)

    print(f"\nROC-AUC:")
    print(f"  Train: {train_auc:.4f}")
    print(f"  Test:  {test_auc:.4f}")

    # Precision/Recall at thresholds
    print(f"\nPrecision/Recall at thresholds:")
    print(f"{'Thresh':>8} {'Prec':>8} {'Recall':>8} {'N_pred':>10} {'Skip%':>8}")
    print("-" * 50)

    total_test = len(y_test)
    for thresh in [0.3, 0.4, 0.5, 0.6, 0.7]:
        y_pred_t = (y_test_pred >= thresh).astype(int)
        n_pred = y_pred_t.sum()
        skip_pct = n_pred / total_test

        if n_pred > 0:
            prec = precision_score(y_test, y_pred_t, zero_division=0)
            rec = recall_score(y_test, y_pred_t, zero_division=0)
        else:
            prec = rec = 0

        print(f"{thresh:>8.1f} {prec:>8.3f} {rec:>8.3f} {n_pred:>10,} {skip_pct:>7.1%}")

    # Feature importance
    importance = pd.DataFrame({
        'feature': FEATURE_COLUMNS,
        'importance': model.feature_importance(importance_type='gain'),
    }).sort_values('importance', ascending=False)

    print(f"\nTop 15 Features:")
    for i, row in importance.head(15).iterrows():
        print(f"  {row['feature']:<30} {row['importance']:>10.1f}")

    # Save model
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(str(output_dir / "model_v2.lgb"))

    return model, test_auc, importance


def main():
    print("=" * 70)
    print("ML MODEL TRAINING v2 - ALL DATA (no CTB filter)")
    print("=" * 70)

    train_df, test_df = load_data()

    X_train = prepare_features(train_df)
    X_test = prepare_features(test_df)

    # MODEL 1: Immediate Fail Detector
    model_1, auc_1, imp_1 = train_and_evaluate(
        X_train, train_df['immediate_fail'].values,
        X_test, test_df['immediate_fail'].values,
        "Model 1: Immediate Fail Detector",
        Path("models/immediate_fail")
    )

    # MODEL 2: 1.0 ATR Winner (skip if Model 1 worked well)
    model_2, auc_2, imp_2 = train_and_evaluate(
        X_train, train_df['reached_1atr_mfe_first'].values,
        X_test, test_df['reached_1atr_mfe_first'].values,
        "Model 2: 1.0 ATR Winner",
        Path("models/winner_1atr")
    )

    # MODEL 3: 1.5 ATR Winner
    model_3, auc_3, imp_3 = train_and_evaluate(
        X_train, train_df['reached_15atr_mfe_first'].values,
        X_test, test_df['reached_15atr_mfe_first'].values,
        "Model 3: 1.5 ATR Winner",
        Path("models/winner_15atr")
    )

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\n{'Model':<35} {'Test AUC':>10}")
    print("-" * 50)
    print(f"{'Model 1: Immediate Fail Detector':<35} {auc_1:>10.4f}")
    print(f"{'Model 2: 1.0 ATR Winner':<35} {auc_2:>10.4f}")
    print(f"{'Model 3: 1.5 ATR Winner':<35} {auc_3:>10.4f}")

    # Check if ctb_at_touch became more important
    print("\n\nCTB Feature Importance (ctb_at_touch):")
    for name, imp in [("Model 1", imp_1), ("Model 2", imp_2), ("Model 3", imp_3)]:
        ctb_imp = imp[imp['feature'] == 'ctb_at_touch']['importance'].values[0]
        ctb_rank = (imp['importance'] > ctb_imp).sum() + 1
        print(f"  {name}: importance={ctb_imp:.1f}, rank={ctb_rank}/64")


if __name__ == "__main__":
    main()
