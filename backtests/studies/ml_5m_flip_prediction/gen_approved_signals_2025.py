"""Generate the 'approved' signal_ts list for 2025 NT backtest.

Trains the walk-forward 2025 model (TRAIN 2020-2023, VAL 2024), predicts
on all 2025 T_d=0 RTH non-aligned + fillable rows, and outputs:
  - bottom 50% (low-pred) signal_ts → 'keep bottom 50%' approved list
  - bottom 25% → tighter filter
  - bottom 10% → strictest

Saves both the predictions and the approval lists to parquet for the
NT backtest to load.
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

DS_PATH = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
OUT_DIR = Path("studies/ml_5m_flip_prediction/results")
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


def main():
    print("Loading dataset...")
    ds = pd.read_parquet(DS_PATH)
    feat_cols = [c for c in ds.columns
                 if c not in METADATA_COLS
                 and not c.startswith("target_")
                 and c != "is_rth"]

    train_mask = (
        ds["year"].isin([2020, 2021, 2022, 2023])
        & (ds["is_rth"] == 1)
        & ds[TARGET].notna()
    )
    val_mask = (
        (ds["year"] == 2024)
        & (ds["is_rth"] == 1)
        & ds[TARGET].notna()
    )
    pred_mask = (
        (ds["year"] == 2025)
        & (ds["is_rth"] == 1)
        & (ds["decision_checkpoint_s"] == 0)
    )

    print(f"  train rows: {train_mask.sum():,}")
    print(f"  val rows:   {val_mask.sum():,}")
    print(f"  pred rows:  {pred_mask.sum():,}")

    X_tr = ds.loc[train_mask, feat_cols].values
    y_tr = ds.loc[train_mask, TARGET].astype(int).values
    X_vl = ds.loc[val_mask, feat_cols].values
    y_vl = ds.loc[val_mask, TARGET].astype(int).values

    print("\nTraining...")
    train_ds = lgb.Dataset(X_tr, label=y_tr, feature_name=feat_cols)
    val_ds = lgb.Dataset(X_vl, label=y_vl, reference=train_ds,
                          feature_name=feat_cols)
    model = lgb.train(
        LGB_PARAMS, train_ds, num_boost_round=2000,
        valid_sets=[train_ds, val_ds], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    print(f"  best iter: {model.best_iteration}")

    pred_rows = ds[pred_mask].copy()
    pred_rows["pred"] = model.predict(pred_rows[feat_cols].values)
    print(f"\n  Pred distribution:")
    print(f"    min:    {pred_rows['pred'].min():.4f}")
    print(f"    p10:    {pred_rows['pred'].quantile(0.10):.4f}")
    print(f"    p25:    {pred_rows['pred'].quantile(0.25):.4f}")
    print(f"    median: {pred_rows['pred'].median():.4f}")
    print(f"    p75:    {pred_rows['pred'].quantile(0.75):.4f}")
    print(f"    p90:    {pred_rows['pred'].quantile(0.90):.4f}")
    print(f"    max:    {pred_rows['pred'].max():.4f}")

    # Save full predictions
    out_preds = pred_rows[["event_id", "signal_ts", "year", "date",
                            "signal_direction", "is_rth",
                            "decision_checkpoint_s", "atr_at_signal",
                            "pred"]].copy()
    out_preds.to_parquet(OUT_DIR / "preds_2025_walk_forward.parquet",
                          index=False)

    # Save thresholds and approved lists
    thresholds = {}
    for label, pct in [("bottom_50", 0.50),
                       ("bottom_25", 0.25),
                       ("bottom_10", 0.10)]:
        thr = pred_rows["pred"].quantile(pct)
        approved = pred_rows[pred_rows["pred"] <= thr][
            ["event_id", "pred"]].copy()
        thresholds[label] = thr
        approved.to_parquet(
            OUT_DIR / f"approved_signals_2025_{label}.parquet",
            index=False)
        print(f"\n  {label}: threshold={thr:.4f}, "
              f"approved N={len(approved):,}")

    # Print summary of thresholds
    print("\nThresholds:")
    for k, v in thresholds.items():
        print(f"  {k}: {v:.6f}")


if __name__ == "__main__":
    main()
