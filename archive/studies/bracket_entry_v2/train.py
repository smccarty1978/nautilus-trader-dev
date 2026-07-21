"""LightGBM classifier training for good_bracket_entry."""

from __future__ import annotations
from pathlib import Path
import json
import pandas as pd
import lightgbm as lgb


def load_model_feature_names(contract_path: Path) -> list[str]:
    with open(contract_path) as f:
        c = json.load(f)
    return [f["name"] for f in c["features"]
            if f.get("role") == "model_feature"]


def select_feature_cols(cohort: pd.DataFrame,
                          model_features: list[str]) -> list[str]:
    cols = [c for c in model_features if c in cohort.columns]
    keep = []
    for c in cols:
        s = cohort[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            keep.append(c)
    return keep


def make_splits(cohort: pd.DataFrame) -> dict:
    """Train: 2020-2023, Val: 2024, OOS: 2025."""
    train = cohort[cohort["year"].isin([2020, 2021, 2022, 2023])]
    val = cohort[cohort["year"] == 2024]
    oos = cohort[cohort["year"] == 2025]
    return {"train": train, "val": val, "oos": oos}


def train_lgbm_binary(
    X_train: pd.DataFrame, y_train: pd.Series,
    X_val: pd.DataFrame, y_val: pd.Series,
    seed: int = 42,
) -> lgb.Booster:
    train_set = lgb.Dataset(X_train, label=y_train,
                              free_raw_data=False)
    val_set = lgb.Dataset(X_val, label=y_val, reference=train_set,
                            free_raw_data=False)
    params = {
        "objective": "binary",
        "metric": "auc",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "max_depth": -1,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbosity": -1,
        "seed": seed,
        "deterministic": True,
    }
    model = lgb.train(
        params,
        train_set,
        num_boost_round=2000,
        valid_sets=[val_set],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=100),
        ],
    )
    return model
