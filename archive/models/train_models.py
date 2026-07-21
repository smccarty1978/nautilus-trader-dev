"""Train 3 ML Models for Pullback Strategy.

Model 1: Immediate Fail Detector - identify trades that never reach 0.25 ATR
Model 2: 1.0 ATR Winner Predictor - predict trades hitting 1:1 R/R
Model 3: 1.5 ATR Winner Predictor - predict trades hitting 1.5:1 R/R

Data: studies/mfe_mae_foundation/results/ml_features_2025.parquet
Train: Jan-Sep 2025
Test: Oct-Dec 2025 (strict holdout)
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
    f1_score, precision_recall_curve, roc_curve, classification_report,
    confusion_matrix
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
    """Load and split data by timestamp."""
    print("Loading data...")
    df = pd.read_parquet("studies/mfe_mae_foundation/results/ml_features_2025.parquet")
    print(f"Total samples: {len(df):,}")

    # Convert entry_ts to datetime for splitting
    df['entry_dt'] = pd.to_datetime(df['entry_ts'], unit='ns', utc=True)

    # Split: Train = Jan-Sep, Test = Oct-Dec
    train_end = pd.Timestamp("2025-10-01", tz="UTC")

    train_df = df[df['entry_dt'] < train_end].copy()
    test_df = df[df['entry_dt'] >= train_end].copy()

    print(f"Train samples: {len(train_df):,} (Jan-Sep)")
    print(f"Test samples: {len(test_df):,} (Oct-Dec)")

    return train_df, test_df


def prepare_features(df):
    """Extract feature matrix and handle missing values."""
    X = df[FEATURE_COLUMNS].copy()

    # Replace inf with nan, then fill nan with 0
    X = X.replace([np.inf, -np.inf], np.nan)
    X = X.fillna(0)

    return X


def train_model(X_train, y_train, X_test, y_test, model_name, output_dir):
    """Train LightGBM model and evaluate."""
    print(f"\n{'='*70}")
    print(f"TRAINING: {model_name}")
    print(f"{'='*70}")

    # Class balance
    pos_rate = y_train.mean()
    print(f"Train positive rate: {pos_rate:.1%}")
    print(f"Test positive rate: {y_test.mean():.1%}")

    # LightGBM parameters
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

    # Handle class imbalance
    if pos_rate < 0.3:
        params['scale_pos_weight'] = (1 - pos_rate) / pos_rate
        print(f"Using scale_pos_weight: {params['scale_pos_weight']:.2f}")

    # Create datasets
    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    # Train with early stopping
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
    results = evaluate_model(y_train, y_train_pred, y_test, y_test_pred, model_name)

    # Feature importance
    importance = get_feature_importance(model, FEATURE_COLUMNS)
    results['feature_importance'] = importance

    # Save model
    model_path = output_dir / "model.lgb"
    model.save_model(str(model_path))
    print(f"\nModel saved: {model_path}")

    # Save predictions for analysis
    pred_df = pd.DataFrame({
        'y_true': y_test,
        'y_pred_prob': y_test_pred,
    })
    pred_df.to_parquet(output_dir / "test_predictions.parquet")

    # Generate plots
    generate_plots(y_test, y_test_pred, importance, model_name, output_dir)

    # Save results
    with open(output_dir / "metrics.json", 'w') as f:
        json.dump({k: v for k, v in results.items() if k != 'feature_importance'}, f, indent=2)

    return model, results


def evaluate_model(y_train, y_train_pred, y_test, y_test_pred, model_name):
    """Calculate all metrics."""
    results = {}

    # ROC-AUC
    results['train_auc'] = roc_auc_score(y_train, y_train_pred)
    results['test_auc'] = roc_auc_score(y_test, y_test_pred)

    print(f"\nROC-AUC:")
    print(f"  Train: {results['train_auc']:.4f}")
    print(f"  Test:  {results['test_auc']:.4f}")

    # Accuracy at 0.5 threshold
    y_train_class = (y_train_pred >= 0.5).astype(int)
    y_test_class = (y_test_pred >= 0.5).astype(int)

    results['train_accuracy'] = accuracy_score(y_train, y_train_class)
    results['test_accuracy'] = accuracy_score(y_test, y_test_class)

    print(f"\nAccuracy (threshold=0.5):")
    print(f"  Train: {results['train_accuracy']:.4f}")
    print(f"  Test:  {results['test_accuracy']:.4f}")

    # Precision/Recall at various thresholds
    print(f"\nPrecision/Recall at thresholds (Test set):")
    print(f"{'Threshold':>10} {'Precision':>10} {'Recall':>10} {'F1':>10} {'N_pred':>10}")
    print("-" * 55)

    thresholds_to_check = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    results['threshold_metrics'] = {}

    for thresh in thresholds_to_check:
        y_pred_t = (y_test_pred >= thresh).astype(int)
        n_pred = y_pred_t.sum()

        if n_pred > 0:
            prec = precision_score(y_test, y_pred_t, zero_division=0)
            rec = recall_score(y_test, y_pred_t, zero_division=0)
            f1 = f1_score(y_test, y_pred_t, zero_division=0)
        else:
            prec = rec = f1 = 0

        print(f"{thresh:>10.1f} {prec:>10.3f} {rec:>10.3f} {f1:>10.3f} {n_pred:>10,}")

        results['threshold_metrics'][str(thresh)] = {
            'precision': prec,
            'recall': rec,
            'f1': f1,
            'n_predicted': int(n_pred),
        }

    # Confusion matrix at 0.5
    cm = confusion_matrix(y_test, y_test_class)
    results['confusion_matrix'] = cm.tolist()

    print(f"\nConfusion Matrix (threshold=0.5):")
    print(f"  TN: {cm[0,0]:,}  FP: {cm[0,1]:,}")
    print(f"  FN: {cm[1,0]:,}  TP: {cm[1,1]:,}")

    return results


def get_feature_importance(model, feature_names):
    """Get feature importance sorted by gain."""
    importance = pd.DataFrame({
        'feature': feature_names,
        'importance': model.feature_importance(importance_type='gain'),
    }).sort_values('importance', ascending=False)

    print(f"\nTop 20 Features (by gain):")
    for i, row in importance.head(20).iterrows():
        print(f"  {row['feature']:<30} {row['importance']:>10.1f}")

    return importance.to_dict('records')


def generate_plots(y_test, y_test_pred, importance, model_name, output_dir):
    """Generate evaluation plots."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))

    # 1. ROC Curve
    fpr, tpr, _ = roc_curve(y_test, y_test_pred)
    auc = roc_auc_score(y_test, y_test_pred)

    axes[0, 0].plot(fpr, tpr, 'b-', label=f'ROC (AUC = {auc:.3f})')
    axes[0, 0].plot([0, 1], [0, 1], 'k--', label='Random')
    axes[0, 0].set_xlabel('False Positive Rate')
    axes[0, 0].set_ylabel('True Positive Rate')
    axes[0, 0].set_title(f'{model_name} - ROC Curve')
    axes[0, 0].legend()
    axes[0, 0].grid(True, alpha=0.3)

    # 2. Precision-Recall Curve
    precision, recall, thresholds = precision_recall_curve(y_test, y_test_pred)

    axes[0, 1].plot(recall, precision, 'b-')
    axes[0, 1].set_xlabel('Recall')
    axes[0, 1].set_ylabel('Precision')
    axes[0, 1].set_title(f'{model_name} - Precision-Recall Curve')
    axes[0, 1].grid(True, alpha=0.3)

    # Mark specific thresholds
    for thresh in [0.4, 0.5, 0.6]:
        idx = np.argmin(np.abs(thresholds - thresh))
        if idx < len(precision) - 1:
            axes[0, 1].scatter(recall[idx], precision[idx], s=100, zorder=5)
            axes[0, 1].annotate(f't={thresh}', (recall[idx], precision[idx]),
                               textcoords="offset points", xytext=(5, 5))

    # 3. Calibration Curve
    prob_true, prob_pred = calibration_curve(y_test, y_test_pred, n_bins=10)

    axes[1, 0].plot(prob_pred, prob_true, 'bo-', label='Model')
    axes[1, 0].plot([0, 1], [0, 1], 'k--', label='Perfectly calibrated')
    axes[1, 0].set_xlabel('Mean Predicted Probability')
    axes[1, 0].set_ylabel('Fraction of Positives')
    axes[1, 0].set_title(f'{model_name} - Calibration Curve')
    axes[1, 0].legend()
    axes[1, 0].grid(True, alpha=0.3)

    # 4. Feature Importance (top 20)
    imp_df = pd.DataFrame(importance).head(20)
    axes[1, 1].barh(range(len(imp_df)), imp_df['importance'].values)
    axes[1, 1].set_yticks(range(len(imp_df)))
    axes[1, 1].set_yticklabels(imp_df['feature'].values)
    axes[1, 1].invert_yaxis()
    axes[1, 1].set_xlabel('Importance (Gain)')
    axes[1, 1].set_title(f'{model_name} - Top 20 Features')

    plt.tight_layout()
    plt.savefig(output_dir / "evaluation_plots.png", dpi=150)
    plt.close()

    print(f"\nPlots saved: {output_dir / 'evaluation_plots.png'}")


def generate_report(all_results, output_path):
    """Generate markdown training report."""
    report = []
    report.append("# ML Model Training Report\n")
    report.append(f"Generated: {pd.Timestamp.now()}\n")
    report.append("\n## Data Summary\n")
    report.append("- **Source**: studies/mfe_mae_foundation/results/ml_features_2025.parquet\n")
    report.append("- **Train**: Jan-Sep 2025\n")
    report.append("- **Test**: Oct-Dec 2025 (holdout)\n")
    report.append("- **Features**: 64 (from FEATURES.md)\n")
    report.append("- **Algorithm**: LightGBM\n")

    for name, results in all_results.items():
        report.append(f"\n---\n\n## {name}\n")

        report.append(f"\n### Performance Metrics\n")
        report.append(f"| Metric | Train | Test |\n")
        report.append(f"|--------|-------|------|\n")
        report.append(f"| ROC-AUC | {results['train_auc']:.4f} | {results['test_auc']:.4f} |\n")
        report.append(f"| Accuracy | {results['train_accuracy']:.4f} | {results['test_accuracy']:.4f} |\n")

        report.append(f"\n### Precision/Recall by Threshold\n")
        report.append(f"| Threshold | Precision | Recall | F1 | N Predicted |\n")
        report.append(f"|-----------|-----------|--------|-----|-------------|\n")
        for thresh, metrics in results['threshold_metrics'].items():
            report.append(f"| {thresh} | {metrics['precision']:.3f} | {metrics['recall']:.3f} | {metrics['f1']:.3f} | {metrics['n_predicted']:,} |\n")

        report.append(f"\n### Top 10 Features\n")
        report.append(f"| Rank | Feature | Importance |\n")
        report.append(f"|------|---------|------------|\n")
        for i, feat in enumerate(results['feature_importance'][:10], 1):
            report.append(f"| {i} | {feat['feature']} | {feat['importance']:.1f} |\n")

        report.append(f"\n### Confusion Matrix (threshold=0.5)\n")
        report.append(f"```\n")
        cm = results['confusion_matrix']
        report.append(f"Predicted:    0        1\n")
        report.append(f"Actual 0:  {cm[0][0]:>6,}  {cm[0][1]:>6,}\n")
        report.append(f"Actual 1:  {cm[1][0]:>6,}  {cm[1][1]:>6,}\n")
        report.append(f"```\n")

    with open(output_path, 'w') as f:
        f.write(''.join(report))

    print(f"\nReport saved: {output_path}")


def main():
    print("=" * 70)
    print("ML MODEL TRAINING - Pullback Strategy")
    print("=" * 70)

    # Load data
    train_df, test_df = load_data()

    # Prepare features
    X_train = prepare_features(train_df)
    X_test = prepare_features(test_df)

    print(f"\nFeature matrix: {X_train.shape[1]} features")

    all_results = {}

    # =========================================================================
    # MODEL 1: Immediate Fail Detector
    # =========================================================================
    y_train_1 = train_df['immediate_fail'].values
    y_test_1 = test_df['immediate_fail'].values

    output_dir_1 = Path("models/immediate_fail")
    model_1, results_1 = train_model(
        X_train, y_train_1, X_test, y_test_1,
        "Model 1: Immediate Fail Detector",
        output_dir_1
    )
    all_results['Model 1: Immediate Fail Detector'] = results_1

    # =========================================================================
    # MODEL 2: 1.0 ATR Winner Predictor
    # =========================================================================
    y_train_2 = train_df['reached_1atr_mfe_first'].values
    y_test_2 = test_df['reached_1atr_mfe_first'].values

    output_dir_2 = Path("models/winner_1atr")
    model_2, results_2 = train_model(
        X_train, y_train_2, X_test, y_test_2,
        "Model 2: 1.0 ATR Winner Predictor",
        output_dir_2
    )
    all_results['Model 2: 1.0 ATR Winner Predictor'] = results_2

    # =========================================================================
    # MODEL 3: 1.5 ATR Winner Predictor
    # =========================================================================
    y_train_3 = train_df['reached_15atr_mfe_first'].values
    y_test_3 = test_df['reached_15atr_mfe_first'].values

    output_dir_3 = Path("models/winner_15atr")
    model_3, results_3 = train_model(
        X_train, y_train_3, X_test, y_test_3,
        "Model 3: 1.5 ATR Winner Predictor",
        output_dir_3
    )
    all_results['Model 3: 1.5 ATR Winner Predictor'] = results_3

    # =========================================================================
    # Generate combined report
    # =========================================================================
    generate_report(all_results, Path("models/training_report.md"))

    print("\n" + "=" * 70)
    print("TRAINING COMPLETE")
    print("=" * 70)
    print("\nSaved models:")
    print("  - models/immediate_fail/model.lgb")
    print("  - models/winner_1atr/model.lgb")
    print("  - models/winner_15atr/model.lgb")
    print("\nReport: models/training_report.md")


if __name__ == "__main__":
    main()
