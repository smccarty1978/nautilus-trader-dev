"""Phase 3 — RTH-only LightGBM regression on `regime_exit_pnl_atr`.

Pivots from the binary `good_entry_300s` framing because Phase 2
showed:
  - binary AUC weak (0.5447 OOS)
  - ETH had no signal
  - top-decile economic lift in RTH was real ($+59-$77/trade)
  - the score appeared to rank PnL MAGNITUDE better than binary class

So this phase asks the sharper question:
  "Within RTH, can checkpoints be ranked by expected payoff?"

Splits (same as Phase 2, event-grouped chronological):
  - Train: 2020-2023 (RTH only)
  - Val:   2024 (RTH only)
  - OOS:   2025 (RTH only)

Target: `regime_exit_pnl_atr` (ATR-normalized PnL from fill_price to
regime_exit_price). Chosen over dollars because RTH ATR is more
uniform than dollar-PnL across the 6-year span.

Loss: L2 (MSE) baseline. Tail behavior is reported separately so we
can detect "thin-tail mirage" vs durable signal.
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.stats import spearmanr


# Re-use feature selection from Phase 2
from train_phase2 import (
    load_model_feature_names, select_feature_cols,
)


def make_rth_splits(cohort: pd.DataFrame) -> dict:
    """RTH-only event-grouped chronological splits."""
    rth = cohort[cohort["is_rth_checkpoint"] == 1].copy()
    train = rth[rth["year"].isin([2020, 2021, 2022, 2023])]
    val = rth[rth["year"] == 2024]
    oos = rth[rth["year"] == 2025]
    return {"train": train, "val": val, "oos": oos}


def train_lgbm_regression(
    X_train: pd.DataFrame, y_train: pd.Series,
    X_val: pd.DataFrame, y_val: pd.Series,
    seed: int = 42,
    loss: str = "l2",
    huber_alpha: float = 0.9,
) -> lgb.Booster:
    """
    loss:
      - "l2"     : squared error (default)
      - "huber"  : robust loss; alpha = transition threshold (in target
                   units) between L2 (small residuals) and L1 (large).
                   target std ≈ 2.26 ATR → alpha=0.9 clips outliers
                   beyond ~0.4 std, blending bulk-fit with robust tails.
    """
    train_set = lgb.Dataset(X_train, label=y_train,
                              free_raw_data=False)
    val_set = lgb.Dataset(X_val, label=y_val, reference=train_set,
                            free_raw_data=False)
    if loss == "l2":
        objective = "regression"
        metric = "rmse"
        extra: dict = {}
    elif loss == "huber":
        objective = "huber"
        metric = "huber"
        extra = {"alpha": huber_alpha}
    else:
        raise ValueError(f"unknown loss: {loss}")
    params = {
        "objective": objective,
        "metric": metric,
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
        **extra,
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


# ---------- evaluation helpers ----------

def rank_metrics(df: pd.DataFrame,
                   pred_col: str = "score",
                   target_col: str = "regime_exit_pnl_atr") -> dict:
    y = df[target_col].dropna()
    s = df.loc[y.index, pred_col]
    if len(y) < 2:
        return {"n": int(len(y)), "spearman": float("nan"),
                 "rmse": float("nan"), "mae": float("nan")}
    rho, p = spearmanr(s, y)
    rmse = float(np.sqrt(((s - y) ** 2).mean()))
    mae = float(np.abs(s - y).mean())
    return {"n": int(len(y)), "spearman": float(rho),
             "spearman_p": float(p), "rmse": rmse, "mae": mae}


def trimmed_mean(s: pd.Series, trim_pct: float = 0.05) -> float:
    s = s.dropna().sort_values()
    if len(s) == 0:
        return float("nan")
    k = int(len(s) * trim_pct)
    if k * 2 >= len(s):
        return float("nan")
    return float(s.iloc[k:len(s) - k].mean())


def risk_block(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan,
                 "p25": np.nan, "p75": np.nan,
                 "trimmed_mean_5pct": np.nan,
                 "win_rate": np.nan, "avg_winner": np.nan,
                 "avg_loser": np.nan}
    wins = s[s > 0]
    losses = s[s < 0]
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "trimmed_mean_5pct": trimmed_mean(s, 0.05),
        "win_rate": float((s > 0).mean()),
        "avg_winner": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loser": float(losses.mean()) if len(losses) else float("nan"),
    }


def decile_table(df: pd.DataFrame, target_dollars: str,
                   n_buckets: int = 10) -> pd.DataFrame:
    """Decile by predicted score with PnL stats. Includes both ATR
    target and dollar PnL for actionable reading."""
    df = df.copy()
    df["bucket"] = pd.qcut(df["score"].rank(method="first"),
                            q=n_buckets, labels=False)
    rows = []
    for b in range(n_buckets):
        sub = df[df["bucket"] == b]
        atr = sub["regime_exit_pnl_atr"].dropna()
        usd = sub[target_dollars].dropna()
        rows.append({
            "decile": b,
            "n": int(len(sub)),
            "pred_mean": float(sub["score"].mean()),
            "actual_atr_mean": float(atr.mean())
                if len(atr) else float("nan"),
            "actual_atr_median": float(atr.median())
                if len(atr) else float("nan"),
            "usd_mean": float(usd.mean()) if len(usd) else float("nan"),
            "usd_median": float(usd.median()) if len(usd) else float("nan"),
            "usd_p25": float(usd.quantile(0.25))
                if len(usd) else float("nan"),
            "usd_p75": float(usd.quantile(0.75))
                if len(usd) else float("nan"),
            "trimmed_usd_5pct": trimmed_mean(usd, 0.05),
            "win_rate": float((usd > 0).mean())
                if len(usd) else float("nan"),
            "avg_winner_usd": float(usd[usd > 0].mean())
                if (usd > 0).any() else float("nan"),
            "avg_loser_usd": float(usd[usd < 0].mean())
                if (usd < 0).any() else float("nan"),
        })
    return pd.DataFrame(rows)


def topk_economics_with_risk(df: pd.DataFrame,
                                fractions: list[float]) -> pd.DataFrame:
    """Top-k% bucket with full risk profile (mean + median + trimmed
    + win rate + avg winner/loser)."""
    df = df.copy().sort_values("score", ascending=False).reset_index(
        drop=True)
    rows = []
    # Baseline (ALL)
    rb = risk_block(df["regime_exit_pnl_dollars"])
    rb["fraction"] = 1.0
    rb["label"] = "ALL (baseline)"
    rows.append(rb)
    # Top-k
    n = len(df)
    for f in fractions:
        k = int(round(f * n))
        if k == 0:
            continue
        top = df.iloc[:k]
        rb = risk_block(top["regime_exit_pnl_dollars"])
        rb["fraction"] = f
        rb["label"] = f"top {int(f * 100)}%"
        rows.append(rb)
    return pd.DataFrame(rows)
