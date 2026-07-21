"""Phase 2 — LightGBM classifier for good_entry_300s.

Splits (event-grouped chronological — NEVER row-level random):
  - Train: years in {2020, 2021, 2022, 2023}
  - Val:   year == 2024
  - OOS:   year == 2025

Features: contract `role == "model_feature"` (177 cols), intersection
with what the v2 collector actually emits. `checkpoint_s` IS included
because we pool across checkpoints.

Target: good_entry_300s (already computed in cohort_long.parquet).

Filtering: fillable_at_T == True (only fillable rows can be entered
in real life — unfillable rows will never trigger a trade).

Reports:
  - Train/val/OOS sizes + base rates
  - OOS AUC, PR-AUC
  - OOS calibration: 10 score-deciles with mean predicted vs actual rate
  - Top 10% / 20% / 30% economics: n trades, mean PnL, PT100 win-rate
  - Per-stratum (RTH/ETH × Long/Short) cuts on OOS
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import (
    roc_auc_score, average_precision_score, brier_score_loss,
)


# ---------- feature/role helpers ----------

def load_model_feature_names(contract_path: Path) -> list[str]:
    with open(contract_path) as f:
        c = json.load(f)
    return [f["name"] for f in c["features"]
            if f.get("role") == "model_feature"]


def select_feature_cols(cohort: pd.DataFrame,
                          model_features: list[str]) -> list[str]:
    """Intersect contract features with cols actually present + drop
    columns that aren't numeric. checkpoint_s IS retained as a feature
    per spec."""
    cols = [c for c in model_features if c in cohort.columns]
    # Filter out non-numeric (defensive — bool cast to int by lgbm OK)
    keep = []
    for c in cols:
        s = cohort[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            keep.append(c)
    return keep


# ---------- splits ----------

def make_splits(cohort: pd.DataFrame) -> dict:
    """Event-grouped chronological splits."""
    train = cohort[cohort["year"].isin([2020, 2021, 2022, 2023])]
    val = cohort[cohort["year"] == 2024]
    oos = cohort[cohort["year"] == 2025]
    return {"train": train, "val": val, "oos": oos}


# ---------- training ----------

def train_lgbm(
    X_train: pd.DataFrame, y_train: pd.Series,
    X_val: pd.DataFrame, y_val: pd.Series,
    seed: int = 42,
) -> lgb.Booster:
    """Standard LightGBM binary classifier baseline. No fancy
    hyperparameter tuning for v1 — just sensible defaults plus
    early stopping on val AUC."""
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


# ---------- evaluation ----------

def _stratify(df: pd.DataFrame, stratum: str) -> pd.DataFrame:
    if stratum == "All":
        return df
    rth = df["is_rth_checkpoint"] == 1
    long_ = df["signal_direction"] == 1
    if stratum == "RTH":
        return df[rth]
    if stratum == "ETH":
        return df[~rth]
    if stratum == "Long":
        return df[long_]
    if stratum == "Short":
        return df[~long_]
    if stratum == "RTH-Long":
        return df[rth & long_]
    if stratum == "RTH-Short":
        return df[rth & ~long_]
    if stratum == "ETH-Long":
        return df[~rth & long_]
    if stratum == "ETH-Short":
        return df[~rth & ~long_]
    raise ValueError(stratum)


STRATA = ["All", "RTH", "ETH", "Long", "Short",
          "RTH-Long", "RTH-Short", "ETH-Long", "ETH-Short"]


def metrics_block(df: pd.DataFrame, score_col: str = "score",
                    label_col: str = "good_entry_300s") -> dict:
    """AUC + PR-AUC + base rate for the given dataframe."""
    y = df[label_col].values
    s = df[score_col].values
    if len(y) == 0 or y.sum() == 0 or y.sum() == len(y):
        return {"n": int(len(y)), "base_rate": float("nan"),
                 "auc": float("nan"), "pr_auc": float("nan"),
                 "brier": float("nan")}
    return {
        "n": int(len(y)),
        "base_rate": float(y.mean()),
        "auc": float(roc_auc_score(y, s)),
        "pr_auc": float(average_precision_score(y, s)),
        "brier": float(brier_score_loss(y, s)),
    }


def calibration_table(df: pd.DataFrame, n_buckets: int = 10) -> pd.DataFrame:
    """Score-bucket calibration: predicted vs actual rate per decile."""
    df = df.copy()
    # rank-based bucket so ties don't collapse a bucket
    df["bucket"] = pd.qcut(df["score"].rank(method="first"),
                            q=n_buckets, labels=False)
    out = (df.groupby("bucket")
              .agg(n=("good_entry_300s", "size"),
                    pred_mean=("score", "mean"),
                    actual_rate=("good_entry_300s", "mean"),
                    pnl_mean=("regime_exit_pnl_dollars", "mean"),
                    pnl_median=("regime_exit_pnl_dollars", "median"),
                    pt100_n=("pt100_before_sl100",
                              lambda s: int(s.notna().sum())),
                    pt100_rate=("pt100_before_sl100",
                                  lambda s: float((s == 1).mean())
                                            if s.notna().any()
                                            else float("nan")))
              .reset_index())
    return out


def topk_economics(df: pd.DataFrame, fractions: list[float]) -> pd.DataFrame:
    """For each top-k% bucket (by predicted score), report n and
    economic stats."""
    df = df.copy().sort_values("score", ascending=False).reset_index(
        drop=True)
    n_total = len(df)
    rows = []
    for f in fractions:
        k = int(round(f * n_total))
        if k == 0:
            continue
        top = df.iloc[:k]
        rows.append({
            "fraction": f,
            "n": k,
            "good_entry_rate": float(top["good_entry_300s"].mean()),
            "pnl_mean": float(top["regime_exit_pnl_dollars"].mean()),
            "pnl_median": float(top["regime_exit_pnl_dollars"].median()),
            "pt100_rate": float((top["pt100_before_sl100"] == 1).mean()),
            "pt100_resolved":
                int(top["pt100_before_sl100"].notna().sum()),
        })
    # Always include "ALL" baseline row
    rows.insert(0, {
        "fraction": 1.0,
        "n": n_total,
        "good_entry_rate": float(df["good_entry_300s"].mean()),
        "pnl_mean": float(df["regime_exit_pnl_dollars"].mean()),
        "pnl_median": float(df["regime_exit_pnl_dollars"].median()),
        "pt100_rate": float((df["pt100_before_sl100"] == 1).mean()),
        "pt100_resolved":
            int(df["pt100_before_sl100"].notna().sum()),
    })
    return pd.DataFrame(rows)
