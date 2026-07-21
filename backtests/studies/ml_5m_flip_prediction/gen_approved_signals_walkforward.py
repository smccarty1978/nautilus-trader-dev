"""Generate approved signal lists for 2022, 2023, 2024 (walk-forward).

For each predict_year, train on years prior (last prior year as VAL),
predict on T_d=0 RTH non-aligned + fillable population, save bottom-50%
approved list.

Output:
  approved_signals_{year}_bottom_50.parquet  for each year in {2022,2023,2024}
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

    # Walk-forward configs (same as walk_forward_filter_validation.py)
    configs = [
        (2022, [2020], 2021),
        (2023, [2020, 2021], 2022),
        (2024, [2020, 2021, 2022], 2023),
    ]

    for predict_year, train_years, val_year in configs:
        print(f"\n=== Year {predict_year}: train {train_years} val {val_year} ===")

        train_mask = (
            ds["year"].isin(train_years)
            & (ds["is_rth"] == 1)
            & ds[TARGET].notna()
        )
        val_mask = (
            (ds["year"] == val_year)
            & (ds["is_rth"] == 1)
            & ds[TARGET].notna()
        )
        pred_mask = (
            (ds["year"] == predict_year)
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

        thr_b50 = pred_rows["pred"].quantile(0.50)
        approved_b50 = pred_rows[pred_rows["pred"] <= thr_b50][
            ["event_id", "pred"]].copy()

        out = OUT_DIR / f"approved_signals_{predict_year}_bottom_50.parquet"
        approved_b50.to_parquet(out, index=False)
        print(f"  threshold (b50): {thr_b50:.4f}")
        print(f"  approved N:      {len(approved_b50):,}")
        print(f"  saved: {out}")


if __name__ == "__main__":
    main()
