"""Save the LightGBM model + feature column order for use in NT strategy.

Trains the walk-forward 2026 model:
  TRAIN: 2020-2024 RTH valid-label rows
  VAL:   2025 RTH valid-label rows (early stopping)

Outputs:
  - models/ml_5m_flip/model_2026.txt  (LightGBM text format)
  - models/ml_5m_flip/feature_cols_2026.json  (feature order)
  - models/ml_5m_flip/threshold_2026.json  (bottom-50% threshold from
    predicting on a held-out 2025 RTH set, NOT 2026 — that would peek)
"""

import sys
import os
import json
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
MODEL_DIR = Path("models/ml_5m_flip")
MODEL_DIR.mkdir(parents=True, exist_ok=True)
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
    print(f"  Features: {len(feat_cols)}")

    # Train on 2020-2024 RTH valid-label, val on 2025 (last available)
    train_mask = (
        ds["year"].isin([2020, 2021, 2022, 2023, 2024])
        & (ds["is_rth"] == 1)
        & ds[TARGET].notna()
    )
    val_mask = (
        (ds["year"] == 2025)
        & (ds["is_rth"] == 1)
        & ds[TARGET].notna()
    )
    print(f"  Train rows: {train_mask.sum():,}")
    print(f"  Val rows:   {val_mask.sum():,}")

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

    # Predict on 2025 to derive a threshold (bottom-50% pred)
    # IMPORTANT: don't use 2026 — that would peek into OOS data.
    pred_2025_mask = (
        (ds["year"] == 2025)
        & (ds["is_rth"] == 1)
        & (ds["decision_checkpoint_s"] == 0)
    )
    pred_rows = ds[pred_2025_mask].copy()
    pred_rows["pred"] = model.predict(pred_rows[feat_cols].values)
    threshold = pred_rows["pred"].quantile(0.50)
    print(f"\n  Threshold (bottom-50% from 2025 RTH preds): "
          f"{threshold:.6f}")

    # Save model
    model_path = MODEL_DIR / "model_2026.txt"
    model.save_model(str(model_path), num_iteration=model.best_iteration)
    print(f"  Saved model: {model_path}")

    # Save feature column order
    fc_path = MODEL_DIR / "feature_cols_2026.json"
    with open(fc_path, "w") as f:
        json.dump(feat_cols, f, indent=2)
    print(f"  Saved feature cols: {fc_path}")

    # Save threshold
    thr_path = MODEL_DIR / "threshold_2026.json"
    with open(thr_path, "w") as f:
        json.dump({"bottom_50": float(threshold),
                    "best_iter": model.best_iteration,
                    "n_train": int(train_mask.sum()),
                    "n_val": int(val_mask.sum()),
                    "trained_through": "2024 (val 2025)",
                    "predict_on": "2026 (true OOS)"}, f, indent=2)
    print(f"  Saved threshold: {thr_path}")


if __name__ == "__main__":
    main()
