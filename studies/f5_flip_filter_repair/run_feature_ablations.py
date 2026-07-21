"""Phase 12: Cached-feature-family ablations on the frozen ridge_log_fail
spec. Uses only cached F2 features (no raw reconstruction). Diagnostic only
-- no replacement production model is selected from this or from OOS.
"""
import re
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

from common import OUT, SRC, load_atlas, repair_and_build_f2, load_frozen_policy
import sys
sys.path.insert(0, str(SRC.parent))
from train_flip_filter import FEATURES_LIST

FAMILIES = {}
for h in ("5m", "15m", "30m", "60m"):
    FAMILIES[f"median_center_{h}"] = [
        f for f in FEATURES_LIST
        if (f"_{h}" in f or f"{h}_" in f)
        and not f.startswith("seq_") and not f.startswith("activity_") and not f.startswith("duration_")
    ]
FAMILIES["regime_counts"] = [f for f in FEATURES_LIST if f.startswith("activity_") or f.startswith("duration_")]
for K in (3, 5, 8, 12):
    FAMILIES[f"{K}_regime_sequence"] = [f for f in FEATURES_LIST if f.startswith(f"seq_{K}r_")]
FAMILIES["overlap_retracement"] = [f for f in FEATURES_LIST if ("overlap" in f or "retracement" in f)]
FAMILIES["sequence_efficiency"] = [f for f in FEATURES_LIST if "_efficiency" in f]
FAMILIES["center_migration"] = [f for f in FEATURES_LIST if "center_migration" in f]
FAMILIES["directional_asymmetry"] = [f for f in FEATURES_LIST if "_asym_" in f]


def fit_and_eval(train, val, features, target_retention):
    X_train_raw = train[features].values
    medians = np.nan_to_num(np.nanmedian(X_train_raw, axis=0), nan=0.0)
    X_tr = np.where(np.isnan(X_train_raw), medians, X_train_raw)
    X_val_raw = val[features].values
    X_vl = np.where(np.isnan(X_val_raw), medians, X_val_raw)

    y_tr = (train["outcome_class"] == "EARLY_ROTATIONAL_FAILURE").astype(int).values
    y_vl = (val["outcome_class"] == "EARLY_ROTATIONAL_FAILURE").astype(int).values

    model = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(C=0.1, max_iter=500, penalty="l2"))])
    model.fit(X_tr, y_tr)
    prob_vl = model.predict_proba(X_vl)[:, 1]

    auc = roc_auc_score(y_vl, prob_vl) if len(np.unique(y_vl)) > 1 else float("nan")
    pr_auc = average_precision_score(y_vl, prob_vl) if len(np.unique(y_vl)) > 1 else float("nan")
    brier = brier_score_loss(y_vl, prob_vl)

    # threshold giving retention closest to target_retention
    thr_candidate = np.quantile(prob_vl, target_retention)
    skip = prob_vl >= thr_candidate
    retention = 1 - skip.mean()
    baseline = val["pnl_base"].values
    kept = np.where(skip, 0.0, baseline)
    lift = float((kept - baseline).mean())
    skip_count = int(skip.sum())

    return {
        "auc": float(auc), "pr_auc": float(pr_auc), "calibration_brier": float(brier),
        "skip_count_at_equivalent_retention": skip_count,
        "actual_retention": float(retention),
        "economic_lift_at_equivalent_retention": lift,
    }


def run():
    df_atlas = load_atlas()
    df_f2 = df_atlas[df_atlas["population"] == "F2"].copy()
    train = df_f2[df_f2["period"] == "train"].dropna(subset=["pnl_base"])
    val = df_f2[df_f2["period"] == "val"].dropna(subset=["pnl_base"])

    frozen = load_frozen_policy()
    full_result = fit_and_eval(train, val, FEATURES_LIST, target_retention=0.984225)
    full_result["family"] = "FULL_MODEL_(no_ablation)"
    full_result["n_features_removed"] = 0

    rows = [full_result]
    for fam_name, fam_feats in FAMILIES.items():
        remaining = [f for f in FEATURES_LIST if f not in fam_feats]
        r = fit_and_eval(train, val, remaining, target_retention=0.984225)
        r["family"] = fam_name
        r["n_features_removed"] = len(fam_feats)
        rows.append(r)

    df = pd.DataFrame(rows)
    df["auc_delta_vs_full"] = df["auc"] - full_result["auc"]
    df["lift_delta_vs_full"] = df["economic_lift_at_equivalent_retention"] - full_result["economic_lift_at_equivalent_retention"]
    df = df[["family", "n_features_removed", "auc", "auc_delta_vs_full", "pr_auc", "calibration_brier",
             "skip_count_at_equivalent_retention", "actual_retention",
             "economic_lift_at_equivalent_retention", "lift_delta_vs_full"]]
    df.to_parquet(OUT / "f5_feature_family_ablations.parquet", index=False)

    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    import os
    os.chdir(SRC.parent.parent.parent)
    run()
