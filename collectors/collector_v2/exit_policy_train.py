"""Train exit-policy models walk-forward.

Inputs: collectors/collector_v2/results/exit_policy/<tag>.parquet
        (one per (product, year) — produced by exit_policy_dataset.py)

Two splits per product (or per combined dataset):
  A. Train 2024 → test 2025
  B. Train 2024-2025 → test 2026

Models (simple first):
  - LightGBM (binary classifier; primary)
  - Logistic regression (sanity baseline)

Targets evaluated:
  - exit_now_better_than_hold
  - future_giveback_risk
  - remaining_ev_atr (regression — for policy simulation)

Reports AUC per (split, target, model) and saves trained models to
collectors/collector_v2/results/exit_policy/models/.
"""

from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("collectors/collector_v2/results/exit_policy")
MODELS_DIR = OUT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)


# Feature columns the model sees (causal — all from path_checkpoint
# snapshot fields)
FEATURE_COLS = [
    # Path-state features
    "elapsed_s", "cur_pnl_atr", "cur_mfe_atr", "cur_mae_atr",
    "cur_giveback_atr",
    "trade_atr_at_signal",
    "trade_direction",
    # Registry-context features (per TF)
    "regime_30s", "regime_1m", "regime_3m", "regime_5m",
    "bars_in_regime_30s", "bars_in_regime_1m",
    "bars_in_regime_3m", "bars_in_regime_5m",
    "atr_30s", "atr_1m", "atr_3m", "atr_5m",
    "dist_close_to_ema3_h_1m_atr", "dist_close_to_ema9_h_1m_atr",
    "dist_close_to_ema3_l_1m_atr", "dist_close_to_ema9_l_1m_atr",
    "dist_close_to_ema3_h_3m_atr", "dist_close_to_ema9_h_3m_atr",
    "dist_close_to_ema3_l_3m_atr", "dist_close_to_ema9_l_3m_atr",
    "dist_close_to_ema3_h_5m_atr", "dist_close_to_ema9_h_5m_atr",
    "dist_close_to_ema3_l_5m_atr", "dist_close_to_ema9_l_5m_atr",
]


def add_alignment_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add binary alignment features per TF vs trade direction."""
    d = df["trade_direction"]
    for tf in ["30s", "1m", "3m", "5m"]:
        df[f"aligned_{tf}"] = (df[f"regime_{tf}"] == d).astype(int)
    return df


def load_dataset(tags: list[str]) -> pd.DataFrame:
    """Load and concatenate one or more (tag).parquet files."""
    frames = []
    for tag in tags:
        p = OUT / f"{tag}.parquet"
        if not p.exists():
            print(f"  skip missing: {p}")
            continue
        frames.append(pd.read_parquet(p))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return add_alignment_features(df)


def auc(y_true, y_pred):
    from sklearn.metrics import roc_auc_score
    try:
        return float(roc_auc_score(y_true, y_pred))
    except Exception:
        return float("nan")


def train_lgbm(train_df, test_df, target, *, classifier=True):
    import lightgbm as lgb
    feat = [c for c in FEATURE_COLS if c in train_df.columns]
    feat_align = [f"aligned_{tf}" for tf in
                    ["30s", "1m", "3m", "5m"]]
    feat = feat + [f for f in feat_align
                      if f in train_df.columns]
    Xtr = train_df[feat].astype(float)
    ytr = train_df[target].astype(float)
    Xte = test_df[feat].astype(float)
    yte = test_df[target].astype(float)
    if classifier:
        params = dict(objective="binary", metric="auc",
                          num_leaves=31, learning_rate=0.05,
                          feature_fraction=0.9, verbose=-1)
    else:
        params = dict(objective="regression", metric="rmse",
                          num_leaves=31, learning_rate=0.05,
                          feature_fraction=0.9, verbose=-1)
    dtr = lgb.Dataset(Xtr, label=ytr)
    dva = lgb.Dataset(Xte, label=yte, reference=dtr)
    model = lgb.train(params, dtr, num_boost_round=300,
                          valid_sets=[dva],
                          callbacks=[lgb.early_stopping(20),
                                       lgb.log_evaluation(0)])
    pred_te = model.predict(Xte,
                                num_iteration=model.best_iteration)
    return model, pred_te, feat


def train_logreg(train_df, test_df, target):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    feat = [c for c in FEATURE_COLS if c in train_df.columns]
    feat_align = [f"aligned_{tf}" for tf in
                    ["30s", "1m", "3m", "5m"]]
    feat = feat + [f for f in feat_align
                      if f in train_df.columns]
    Xtr = train_df[feat].fillna(0.0).astype(float)
    Xte = test_df[feat].fillna(0.0).astype(float)
    ytr = train_df[target].astype(int)
    yte = test_df[target].astype(int)
    sc = StandardScaler().fit(Xtr)
    Xtr_s = sc.transform(Xtr); Xte_s = sc.transform(Xte)
    m = LogisticRegression(max_iter=200).fit(Xtr_s, ytr)
    pred_te = m.predict_proba(Xte_s)[:, 1]
    return m, pred_te, feat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-tags", nargs="+", required=True,
                     help="e.g. NQ_2024")
    ap.add_argument("--test-tags", nargs="+", required=True,
                     help="e.g. NQ_2025")
    ap.add_argument("--label", required=True,
                     help="run label, e.g. nq_24_to_25")
    args = ap.parse_args()

    train_df = load_dataset(args.train_tags)
    test_df = load_dataset(args.test_tags)
    if not len(train_df) or not len(test_df):
        print("No data — exiting"); sys.exit(1)
    print(f"Train: {len(train_df):,} rows ({args.train_tags})")
    print(f"Test:  {len(test_df):,} rows ({args.test_tags})")

    results = {"label": args.label,
                  "train_tags": args.train_tags,
                  "test_tags": args.test_tags,
                  "train_n": len(train_df),
                  "test_n": len(test_df)}

    # Classification targets
    for target in ["exit_now_better_than_hold",
                      "future_giveback_risk"]:
        if target not in train_df.columns:
            continue
        # LGBM
        m, pred_te, feat = train_lgbm(train_df, test_df, target,
                                            classifier=True)
        a = auc(test_df[target], pred_te)
        results[f"lgbm_{target}_auc"] = a
        # Save predictions on test set
        test_df[f"score_lgbm_{target}"] = pred_te
        # Logistic
        m_lr, pred_lr, _ = train_logreg(train_df, test_df, target)
        a_lr = auc(test_df[target], pred_lr)
        results[f"logreg_{target}_auc"] = a_lr
        test_df[f"score_logreg_{target}"] = pred_lr
        print(f"  {target}: LGBM AUC={a:.3f}, "
               f"LogReg AUC={a_lr:.3f}")

    # Regression target — remaining_ev_atr
    target = "remaining_ev_atr"
    if target in train_df.columns:
        m, pred_te, feat = train_lgbm(train_df, test_df, target,
                                            classifier=False)
        # No AUC for regression; use correlation as a sanity stat
        cor = float(np.corrcoef(test_df[target], pred_te)[0, 1])
        rmse = float(((test_df[target] - pred_te) ** 2).mean() ** 0.5)
        results[f"lgbm_{target}_corr"] = cor
        results[f"lgbm_{target}_rmse"] = rmse
        test_df[f"score_lgbm_{target}"] = pred_te
        print(f"  {target}: LGBM corr={cor:.3f}, "
               f"RMSE={rmse:.3f}")

    # Save predicted-test parquet for policy simulation
    out_pred = MODELS_DIR / f"{args.label}_test_predictions.parquet"
    test_df.to_parquet(out_pred, index=False)
    print(f"Predictions: {out_pred}")

    # Save metadata JSON
    out_meta = MODELS_DIR / f"{args.label}_meta.json"
    with open(out_meta, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Meta: {out_meta}")


if __name__ == "__main__":
    main()
