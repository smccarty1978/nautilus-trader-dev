"""POC Stage A — Base model for target_clean_path_300s.

Trains both logistic regression and LightGBM on current-row features only
(no prior-score augmentation). Evaluates on VAL 2024 and TEST 2025.

Reports per variant (T0 only / T0+60+120 pooled / 60+120 delayed only):
  - N per split, base rate
  - AUC (train / val / test)
  - top-decile hit rate + lift
  - per-bucket target rate (deciles, quintiles)
  - feature importance (LGBM gain)
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
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score

DS_PATH = ("studies/ml_5m_flip_prediction_poc/results/"
            "clean_path_300_dataset.parquet")
OUT_DIR = Path("studies/ml_5m_flip_prediction_poc/results")
OUT_LOG = OUT_DIR / "clean_path_300_base_model.log"
TARGET = "target_clean_path_300s"

METADATA_COLS = {
    "trade_id", "signal_time", "signal_ts", "year", "date", "session",
    "event_id", "decision_ts", "decision_fill_ts",
    "_fwd_mfe_300", "_fwd_mae_300",
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


def rank_stats(y_true, y_pred, label=""):
    n = len(y_true)
    if n == 0 or y_true.sum() == 0 or y_true.sum() == n:
        return {"label": label, "n": n, "auc": np.nan,
                "base_rate": np.nan, "top10_rate": np.nan, "top10_lift": np.nan}
    base = y_true.mean()
    auc = roc_auc_score(y_true, y_pred)
    order = np.argsort(-y_pred)
    y_sorted = y_true[order]
    top10 = y_sorted[: max(1, n // 10)]
    q_rates = [q.mean() for q in np.array_split(y_sorted, 5)]
    d_rates = [d.mean() for d in np.array_split(y_sorted, 10)]
    return {
        "label": label, "n": n, "base_rate": base, "auc": auc,
        "top10_rate": top10.mean(),
        "top10_lift": top10.mean() / base,
        "quintile_rates": q_rates,
        "decile_rates": d_rates,
    }


def fit_lgb(X_tr, y_tr, X_vl, y_vl, feat_cols):
    train_ds = lgb.Dataset(X_tr, label=y_tr, feature_name=feat_cols)
    val_ds = lgb.Dataset(X_vl, label=y_vl, reference=train_ds,
                          feature_name=feat_cols)
    model = lgb.train(
        LGB_PARAMS, train_ds, num_boost_round=2000,
        valid_sets=[train_ds, val_ds], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    return model


def fit_logreg(X_tr, y_tr, feat_cols):
    pipe = Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc", StandardScaler()),
        ("lr", LogisticRegression(max_iter=2000, C=0.1, solver="lbfgs")),
    ])
    pipe.fit(X_tr, y_tr)
    return pipe


def fmt_stats(r, indent=4):
    pad = " " * indent
    if np.isnan(r["auc"]):
        return f"{pad}{r['label']}: (no valid stats)"
    return (
        f"{pad}{r['label']:<20} N={r['n']:>6,} "
        f"base={r['base_rate']:.3f} "
        f"AUC={r['auc']:.4f} "
        f"top10={r['top10_rate']:.3f} "
        f"lift={r['top10_lift']:.2f}x"
    )


def run_variant(df, feat_cols, variant_name, filter_fn, lines):
    sub = df[filter_fn(df)].copy()
    if len(sub) == 0:
        lines.append(f"\n  VARIANT {variant_name}: no rows")
        return None

    lines.append(f"\n{'='*90}")
    lines.append(f"VARIANT: {variant_name}")
    lines.append(f"{'='*90}")

    train_mask = sub["year"].isin([2020, 2021, 2022, 2023])
    val_mask = sub["year"] == 2024
    test_mask = sub["year"] == 2025

    X_tr = sub.loc[train_mask, feat_cols].values
    y_tr = sub.loc[train_mask, TARGET].astype(int).values
    X_vl = sub.loc[val_mask, feat_cols].values
    y_vl = sub.loc[val_mask, TARGET].astype(int).values
    X_te = sub.loc[test_mask, feat_cols].values
    y_te = sub.loc[test_mask, TARGET].astype(int).values

    lines.append(
        f"  TRAIN: N={len(y_tr):,}  base={y_tr.mean():.3f}")
    lines.append(
        f"  VAL:   N={len(y_vl):,}  base={y_vl.mean():.3f}")
    lines.append(
        f"  TEST:  N={len(y_te):,}  base={y_te.mean():.3f}")

    if len(y_tr) == 0 or len(y_vl) == 0 or len(y_te) == 0:
        lines.append("  (insufficient rows, skipping)")
        return None

    # Logistic
    try:
        lr = fit_logreg(X_tr, y_tr, feat_cols)
        p_tr = lr.predict_proba(X_tr)[:, 1]
        p_vl = lr.predict_proba(X_vl)[:, 1]
        p_te = lr.predict_proba(X_te)[:, 1]
        lines.append(f"\n  LOGISTIC:")
        for r in [rank_stats(y_tr, p_tr, "train"),
                   rank_stats(y_vl, p_vl, "val"),
                   rank_stats(y_te, p_te, "test")]:
            lines.append(fmt_stats(r))
    except Exception as e:
        lines.append(f"  LOGISTIC: failed ({e})")

    # LightGBM
    model = fit_lgb(X_tr, y_tr, X_vl, y_vl, feat_cols)
    p_tr = model.predict(X_tr)
    p_vl = model.predict(X_vl)
    p_te = model.predict(X_te)
    lgb_stats = [
        rank_stats(y_tr, p_tr, "train"),
        rank_stats(y_vl, p_vl, "val"),
        rank_stats(y_te, p_te, "test"),
    ]
    lines.append(f"\n  LGBM (best_iter={model.best_iteration}):")
    for r in lgb_stats:
        lines.append(fmt_stats(r))

    # Deciles on test
    test_r = lgb_stats[2]
    if not np.isnan(test_r["auc"]):
        lines.append(f"\n  TEST decile hit-rate (D1=highest pred):")
        for i, d in enumerate(test_r["decile_rates"], 1):
            bar = "█" * int(d * 30)
            lines.append(f"    D{i:>2}: {d:.3f}  {bar}")

    # Feature importance (LGBM)
    lines.append(f"\n  Top-15 LGBM features by gain:")
    gain = model.feature_importance(importance_type="gain")
    imp = pd.DataFrame({
        "feature": feat_cols, "gain": gain,
    }).sort_values("gain", ascending=False)
    gain_total = imp["gain"].sum()
    for i, row in imp.head(15).iterrows():
        pct = row["gain"] / gain_total * 100 if gain_total > 0 else 0
        lines.append(
            f"    {row['feature']:<42} {int(row['gain']):>12,}  "
            f"{pct:>5.1f}%")

    return {
        "variant": variant_name,
        "n_train": len(y_tr), "n_val": len(y_vl), "n_test": len(y_te),
        "base_rate_test": float(y_te.mean()),
        "lgbm_val_auc": lgb_stats[1]["auc"],
        "lgbm_test_auc": lgb_stats[2]["auc"],
        "lgbm_test_top10": lgb_stats[2]["top10_rate"],
        "lgbm_test_lift": lgb_stats[2]["top10_lift"],
        "best_iter": model.best_iteration,
    }


def main():
    print("Loading POC dataset...")
    df = pd.read_parquet(DS_PATH)
    df = df[df[TARGET].notna()].copy()
    print(f"  {len(df):,} valid rows")

    feat_cols = [c for c in df.columns
                 if c not in METADATA_COLS
                 and not c.startswith("target_")
                 and c != "is_rth"]
    print(f"  Features: {len(feat_cols)}")

    lines = []
    lines.append("=" * 90)
    lines.append("POC — BASE MODEL (target_clean_path_300s, RTH, T∈{0,60,120})")
    lines.append("=" * 90)
    lines.append(f"  Features: {len(feat_cols)} (includes decision_checkpoint_s)")

    # Variants
    variants = [
        ("T0 only",
         lambda d: d["decision_checkpoint_s"] == 0),
        ("T0+60+120 pooled",
         lambda d: d["decision_checkpoint_s"].isin([0, 60, 120])),
        ("T60+120 delayed only",
         lambda d: d["decision_checkpoint_s"].isin([60, 120])),
    ]

    summary = []
    for vname, vfilter in variants:
        s = run_variant(df, feat_cols, vname, vfilter, lines)
        if s:
            summary.append(s)

    # Summary table
    lines.append("\n" + "=" * 90)
    lines.append("SUMMARY TABLE")
    lines.append("=" * 90)
    lines.append(
        f"  {'Variant':<22} {'N_test':>7} {'base':>5} "
        f"{'val_AUC':>7} {'test_AUC':>8} "
        f"{'top10%':>7} {'lift':>5}")
    lines.append("  " + "-" * 78)
    for s in summary:
        if np.isnan(s['lgbm_test_auc']):
            continue
        lines.append(
            f"  {s['variant']:<22} {s['n_test']:>7,} "
            f"{s['base_rate_test']:>5.3f} "
            f"{s['lgbm_val_auc']:>7.4f} {s['lgbm_test_auc']:>8.4f} "
            f"{s['lgbm_test_top10']*100:>6.1f}% "
            f"{s['lgbm_test_lift']:>5.2f}x")

    out = "\n".join(lines)
    print(out[:5000])
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\n  Saved: {OUT_LOG}")


if __name__ == "__main__":
    main()
