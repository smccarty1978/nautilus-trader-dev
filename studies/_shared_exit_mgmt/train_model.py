"""Population-agnostic weakness-model training + evaluation harness.

Trains a single LightGBM binary classifier for a given named feature
family (W0 today; W1-W4 are future work per the study's phased plan),
evaluates on the four chronological splits, and produces the decile /
calibration diagnostics required by Phase 3.

Target: is_terminal_weakness = (terminal_weakness_label ==
"TERMINAL_WEAKNESS") -- "this checkpoint's already-achieved MFE peak
will never be reached again before the trade's terminal exit." This is
the direct operationalization of "weakness": a checkpoint that never
recovers is genuinely weak; one that recovers or sets a new high is not.

No population-specific logic lives here -- population identity only
appears in the output file paths supplied by each study's own driver
script.
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from sklearn.linear_model import LogisticRegression
import lightgbm as lgb

from studies._shared_exit_mgmt.w0_features import add_target, add_split_label

N_DECILES = 10


def _calibration_slope_intercept(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Cox calibration regression: fit y ~ logit(p). Returns
    (slope, intercept). Slope=1, intercept=0 is perfect calibration."""
    eps = 1e-6
    p_clipped = np.clip(p, eps, 1 - eps)
    logit_p = np.log(p_clipped / (1 - p_clipped))
    lr = LogisticRegression()
    lr.fit(logit_p.reshape(-1, 1), y)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def _split_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    if len(np.unique(y)) < 2:
        return {"roc_auc": float("nan"), "pr_auc": float("nan"),
                   "brier": float(brier_score_loss(y, p)),
                   "calib_slope": float("nan"), "calib_intercept": float("nan"),
                   "n": int(len(y))}
    slope, intercept = _calibration_slope_intercept(y, p)
    return {
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "calib_slope": slope, "calib_intercept": intercept,
        "n": int(len(y)),
    }


def train_and_evaluate(
    atlas: pd.DataFrame, feature_cols: list[str], model_name: str,
) -> dict:
    """Returns dict with keys: model, metrics_by_split (DataFrame),
    decile_diagnostics (DataFrame), decile_edges (np.ndarray)."""
    atlas = add_target(atlas)
    atlas = add_split_label(atlas)

    splits = {name: atlas[atlas["split"] == name]
                 for name in ("train", "validation", "dev_test", "reserved_eval")}
    for name, df in splits.items():
        if len(df) == 0:
            raise ValueError(f"Split '{name}' is empty -- check split "
                                f"boundaries against atlas date range")

    train, val = splits["train"], splits["validation"]
    X_train, y_train = train[feature_cols], train["is_terminal_weakness"]
    X_val, y_val = val[feature_cols], val["is_terminal_weakness"]

    model = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, learning_rate=0.05,
        num_leaves=31, min_child_samples=1000,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=-1,
    )
    model.fit(
        X_train, y_train, eval_set=[(X_val, y_val)],
        eval_metric="auc",
        callbacks=[lgb.early_stopping(30, verbose=False),
                      lgb.log_evaluation(0)],
    )

    metrics_rows = []
    pred_by_split = {}
    for name, df in splits.items():
        X, y = df[feature_cols], df["is_terminal_weakness"].to_numpy()
        p = model.predict_proba(X)[:, 1]
        pred_by_split[name] = p
        m = _split_metrics(y, p)
        m["model"] = model_name
        m["split"] = name
        metrics_rows.append(m)
    metrics_df = pd.DataFrame(metrics_rows)

    # Decile bin edges frozen from TRAIN predictions only.
    p_train = pred_by_split["train"]
    _, edges = pd.qcut(p_train, N_DECILES, retbins=True, duplicates="drop")
    edges = edges.copy()
    edges[0], edges[-1] = -np.inf, np.inf

    decile_rows = []
    for name, df in splits.items():
        p = pred_by_split[name]
        decile = pd.cut(p, bins=edges, labels=False, include_lowest=True) + 1
        d = df.copy()
        d["decile"] = decile
        d["pred_weakness_prob"] = p
        agg = d.groupby("decile", observed=True).agg(
            n=("is_terminal_weakness", "size"),
            event_rate=("is_terminal_weakness", "mean"),
            recovery_rate=("eventual_recovery_to_prior_mfe", "mean"),
            new_mfe_rate=("eventual_new_mfe", "mean"),
            mean_remaining_mfe_atr=("remaining_mfe_atr", "mean"),
            mean_remaining_mae_before_next_mfe_atr=(
                "remaining_mae_before_next_mfe_atr", "mean"),
            mean_pred_prob=("pred_weakness_prob", "mean"),
        ).reset_index()
        agg["model"] = model_name
        agg["split"] = name
        decile_rows.append(agg)
    decile_df = pd.concat(decile_rows, ignore_index=True)

    return {
        "model": model, "metrics_by_split": metrics_df,
        "decile_diagnostics": decile_df, "decile_edges": edges,
    }
