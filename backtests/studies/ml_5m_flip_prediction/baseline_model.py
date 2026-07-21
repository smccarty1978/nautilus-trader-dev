"""Phase 3a — Baseline LightGBM model (RTH-only, target=300s).

- Group-by-event chronological split:
    TRAIN: event signal_year in [2020..2023]
    VAL:   event signal_year == 2024
    TEST:  event signal_year == 2025
- LightGBM binary classifier, early-stopping on VAL AUC.
- Reports: AUC, calibration, top-decile/quintile hit rates, precision@recall.

Reads:  studies/ml_5m_flip_prediction/results/ml_5m_flip_prediction_dataset.parquet
Writes: studies/ml_5m_flip_prediction/results/ml_5m_flip_baseline_models.log
        studies/ml_5m_flip_prediction/results/ml_5m_flip_baseline_preds_{val,test}.parquet
        studies/ml_5m_flip_prediction/results/ml_5m_flip_baseline_importance.parquet
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import (
    roc_auc_score, precision_recall_curve, average_precision_score
)

DATASET = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
OUT_DIR = Path("studies/ml_5m_flip_prediction/results")
OUT_LOG = OUT_DIR / "ml_5m_flip_baseline_models.log"
TARGET = "target_5m_flip_within_300s"

METADATA_COLS = {
    "trade_id", "signal_time", "signal_ts", "year", "date", "session",
    "event_id", "decision_ts", "decision_fill_ts",
}

LGB_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "lambda_l1": 0.1,
    "lambda_l2": 0.1,
    "verbose": -1,
}


def prepare(df, target_col=TARGET, rth_only=True):
    """Build RTH subset with valid target, split train/val/test."""
    sub = df[df[target_col].notna()].copy()
    if rth_only:
        sub = sub[sub["is_rth"] == 1].copy()
    # Split by event signal year
    is_train = sub["year"].isin([2020, 2021, 2022, 2023])
    is_val = sub["year"] == 2024
    is_test = sub["year"] == 2025
    return sub, is_train, is_val, is_test


def fit_model(X_train, y_train, X_val, y_val, feat_cols):
    train_ds = lgb.Dataset(X_train, label=y_train, feature_name=feat_cols)
    val_ds = lgb.Dataset(
        X_val, label=y_val, reference=train_ds, feature_name=feat_cols)
    model = lgb.train(
        LGB_PARAMS,
        train_set=train_ds,
        num_boost_round=2000,
        valid_sets=[train_ds, val_ds],
        valid_names=["train", "val"],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=100),
        ],
    )
    return model


def eval_ranking(y_true, y_pred, label):
    """Decile + quintile hit rates + precision-recall curve stats."""
    out = {"label": label, "n": len(y_true)}
    n = len(y_true)
    base_rate = y_true.mean() * 100
    out["base_rate%"] = base_rate
    auc = roc_auc_score(y_true, y_pred)
    ap = average_precision_score(y_true, y_pred)
    out["auc"] = auc
    out["avg_precision"] = ap

    # Deciles by predicted score (high to low)
    order = np.argsort(-y_pred)
    y_sorted = y_true[order]
    deciles = np.array_split(y_sorted, 10)
    decile_rates = [d.mean() * 100 for d in deciles]
    out["decile_rates"] = decile_rates

    quintiles = np.array_split(y_sorted, 5)
    quintile_rates = [q.mean() * 100 for q in quintiles]
    out["quintile_rates"] = quintile_rates

    # Top-decile precision and recall
    top10_mask = order[:max(1, n // 10)]
    out["top10_hit_rate%"] = y_true[top10_mask].mean() * 100
    out["top10_n"] = len(top10_mask)
    out["top10_pos"] = int(y_true[top10_mask].sum())
    out["top10_lift"] = out["top10_hit_rate%"] / base_rate

    # Precision at recall levels
    precision, recall, thresholds = precision_recall_curve(y_true, y_pred)
    # Find precision at recall = 0.1, 0.2, 0.3, 0.5
    targets = [0.1, 0.2, 0.3, 0.5]
    pr_at = {}
    for t in targets:
        # Highest precision where recall >= t
        mask = recall >= t
        if mask.any():
            pr_at[t] = precision[mask].max()
        else:
            pr_at[t] = np.nan
    out["precision_at_recall"] = pr_at

    return out


def fmt_ranking(res: dict) -> list:
    lines = []
    lines.append(
        f"  {res['label']:>8}: n={res['n']:>7,}  "
        f"base_rate={res['base_rate%']:>5.1f}%  "
        f"AUC={res['auc']:.4f}  AP={res['avg_precision']:.4f}")
    lines.append(f"    Deciles (high→low pred score):")
    for i, r in enumerate(res["decile_rates"], 1):
        lines.append(
            f"      D{i:>2}: {r:>5.1f}% "
            f"({'█' * int(r / 2)})")
    lines.append(f"    Quintiles:")
    for i, r in enumerate(res["quintile_rates"], 1):
        lines.append(
            f"      Q{i:>2}: {r:>5.1f}% "
            f"({'█' * int(r / 2)})")
    lines.append(
        f"    Top decile (N={res['top10_n']:,}): "
        f"hit_rate={res['top10_hit_rate%']:.1f}%  "
        f"lift={res['top10_lift']:.2f}x base")
    lines.append(f"    Precision @ recall:")
    for t, p in res["precision_at_recall"].items():
        lines.append(f"      R>={t:.1f}:  P={p:.3f}"
                      if not pd.isna(p) else
                      f"      R>={t:.1f}:  (unreachable)")
    return lines


def main():
    df = pd.read_parquet(DATASET)
    print(f"Loaded {len(df):,} rows")

    sub, is_train, is_val, is_test = prepare(df)
    feat_cols = [
        c for c in sub.columns
        if c not in METADATA_COLS
        and not c.startswith("target_")
        and c != "is_rth"   # constant=1 in RTH-only subset
    ]
    print(f"RTH rows with valid target: {len(sub):,}")
    print(f"Features: {len(feat_cols)}")

    y = sub[TARGET].astype(int).values
    X = sub[feat_cols]

    X_train = X[is_train].values
    y_train = y[is_train.values]
    X_val = X[is_val].values
    y_val = y[is_val.values]
    X_test = X[is_test].values
    y_test = y[is_test.values]

    print(f"\n  Train: {len(y_train):,}  pos_rate="
          f"{y_train.mean()*100:.1f}%")
    print(f"  Val:   {len(y_val):,}  pos_rate={y_val.mean()*100:.1f}%")
    print(f"  Test:  {len(y_test):,}  pos_rate={y_test.mean()*100:.1f}%")

    # Train
    print("\nTraining LightGBM...")
    model = fit_model(X_train, y_train, X_val, y_val, feat_cols)

    # Predict
    p_train = model.predict(X_train)
    p_val = model.predict(X_val)
    p_test = model.predict(X_test)

    # Eval
    train_res = eval_ranking(y_train, p_train, "TRAIN")
    val_res = eval_ranking(y_val, p_val, "VAL")
    test_res = eval_ranking(y_test, p_test, "TEST")

    # Feature importance
    gain_imp = model.feature_importance(importance_type="gain")
    split_imp = model.feature_importance(importance_type="split")
    imp_df = pd.DataFrame({
        "feature": feat_cols,
        "gain": gain_imp,
        "split": split_imp,
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    imp_df["gain_pct"] = imp_df["gain"] / imp_df["gain"].sum() * 100

    # Save predictions
    val_events = sub[is_val].copy()
    val_events["pred"] = p_val
    val_events["y"] = y_val
    val_events[[
        "event_id", "decision_checkpoint_s", "year", "signal_direction",
        "is_rth", "pred", "y", "atr_at_signal",
    ]].to_parquet(
        OUT_DIR / "ml_5m_flip_baseline_preds_val.parquet", index=False)

    test_events = sub[is_test].copy()
    test_events["pred"] = p_test
    test_events["y"] = y_test
    test_events[[
        "event_id", "decision_checkpoint_s", "year", "signal_direction",
        "is_rth", "pred", "y", "atr_at_signal",
    ]].to_parquet(
        OUT_DIR / "ml_5m_flip_baseline_preds_test.parquet", index=False)

    imp_df.to_parquet(
        OUT_DIR / "ml_5m_flip_baseline_importance.parquet", index=False)

    # Also save a sanity-check CSV for the top rows we'll inspect
    top_test = test_events.sort_values("pred", ascending=False).head(
        len(test_events) // 10)
    top_test_events = top_test["event_id"].unique()

    # Write log
    lines = []
    lines.append("=" * 130)
    lines.append(
        "ML 5m FLIP PREDICTION — BASELINE MODEL (LightGBM)")
    lines.append(f"  Target: {TARGET}")
    lines.append(f"  Scope:  RTH-only")
    lines.append(
        f"  Split:  TRAIN 2020-2023 | VAL 2024 | TEST 2025 "
        f"(group-by-event chronological)")
    lines.append("=" * 130)

    lines.append("\n--- 1. DATA SHAPE ---")
    lines.append(f"  Train rows:  {len(y_train):>7,}  "
                 f"pos_rate={y_train.mean()*100:.1f}%")
    lines.append(f"  Val rows:    {len(y_val):>7,}  "
                 f"pos_rate={y_val.mean()*100:.1f}%")
    lines.append(f"  Test rows:   {len(y_test):>7,}  "
                 f"pos_rate={y_test.mean()*100:.1f}%")
    lines.append(f"  Features:    {len(feat_cols):>7}")
    lines.append(f"  Best iter:   {model.best_iteration}")

    lines.append("\n--- 2. PERFORMANCE ---")
    for res in [train_res, val_res, test_res]:
        lines.extend(fmt_ranking(res))
        lines.append("")

    lines.append("\n--- 3. FEATURE IMPORTANCE (TOP 25 BY GAIN) ---")
    lines.append(
        f"  {'rank':>4} {'feature':<42} {'gain':>12} "
        f"{'gain%':>7} {'splits':>7}")
    lines.append("  " + "-" * 80)
    for i in range(min(25, len(imp_df))):
        r = imp_df.iloc[i]
        lines.append(
            f"  {i+1:>4} {r['feature']:<42} {r['gain']:>12,.0f} "
            f"{r['gain_pct']:>6.1f}% {int(r['split']):>7,}")

    # Concentration: how much gain is in top-5?
    top5_gain_pct = imp_df.head(5)["gain_pct"].sum()
    top10_gain_pct = imp_df.head(10)["gain_pct"].sum()
    lines.append(f"\n  Top-5 features carry {top5_gain_pct:.1f}% of gain")
    lines.append(f"  Top-10 features carry {top10_gain_pct:.1f}% of gain")

    # AUC stability
    lines.append("\n--- 4. OVERFIT / GENERALIZATION ---")
    lines.append(f"  Train AUC: {train_res['auc']:.4f}")
    lines.append(f"  Val AUC:   {val_res['auc']:.4f}  "
                 f"(gap to train: {train_res['auc']-val_res['auc']:+.4f})")
    lines.append(f"  Test AUC:  {test_res['auc']:.4f}  "
                 f"(gap to val: {val_res['auc']-test_res['auc']:+.4f})")

    # Write log
    out = "\n".join(lines)
    print("\n" + out)
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\n  Saved log: {OUT_LOG}")


if __name__ == "__main__":
    main()
