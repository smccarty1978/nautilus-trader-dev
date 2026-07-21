"""Ablation test: drop `dist_to_1m_flip_threshold_atr_dir` and retrain T-1.

The dominant feature had 50× the gain of the next feature in the
original T-1 model (best_iter=1, essentially single-split). This test
answers: is there real ML signal BEYOND the candidate filter itself?

  - Original T-1: OOS AUC 0.70, top-10% lift 2.32×
  - Ablation T-1: drops the dominant feature, retrains walk-forward

If ablation T-1 OOS AUC drops to ~0.50, the model was essentially the
candidate filter formalized — no genuine ML edge.

If ablation T-1 OOS AUC stays >0.55, the OTHER features (current
regime maturity, micro velocity, etc.) have independent predictive
signal that's worth keeping.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score


OUT = Path("studies/v_a_excursion_regime/results_v0")
SEED = 42
VAL_FRAC = 0.20
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"
ABLATED_FEATURE = "dist_to_1m_flip_threshold_atr_dir"


def feature_columns(df: pd.DataFrame) -> list[str]:
    drop = set([
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s",
        "label_T1", "label_T2", "label_T3",
    ])
    feats = [c for c in df.columns if c not in drop]
    feats = [c for c in feats
              if df[c].dtype not in ("object", "datetime64[ns, UTC]")]
    return feats


def fit_model(X_tr, y_tr, X_val, y_val):
    model = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1,
        is_unbalance=True, verbose=-1)
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(50, verbose=False),
                          lgb.log_evaluation(0)])
    return model


def main():
    t0 = time.time()
    print("=" * 78)
    print(f"ABLATION TEST — drop '{ABLATED_FEATURE}' from T-1")
    print("=" * 78)

    df = pd.read_parquet(OUT / "pre_flip_candidates.parquet")
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    print(f"\nLoaded {len(df):,} candidates")

    feats = feature_columns(df)
    print(f"  features (full): {len(feats)}")
    if ABLATED_FEATURE in feats:
        feats.remove(ABLATED_FEATURE)
        print(f"  Dropped '{ABLATED_FEATURE}'")
    else:
        print(f"  WARN: '{ABLATED_FEATURE}' not in features list")
    print(f"  features (ablated): {len(feats)}")

    label_col = "label_T1"
    months = sorted(df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(months)
                       if str(m) >= FIRST_SCORED_MONTH)

    print(f"\nWalk-forward T-1 (ablated):")
    fold_records = []
    oos_records = []
    imp_records = []
    for i in range(start_idx, len(months)):
        scoring_month = months[i]
        if str(scoring_month) > LAST_SCORED_MONTH:
            break
        train_mask = df["year_month"] < scoring_month
        oos_mask = df["year_month"] == scoring_month
        n_train = int(train_mask.sum())
        n_oos = int(oos_mask.sum())
        if n_train < 500 or n_oos < 20:
            continue
        train_df = df[train_mask].sort_values("close_ts_ns")
        n_val = int(len(train_df) * VAL_FRAC)
        n_tr_only = len(train_df) - n_val
        X_tr = train_df.iloc[:n_tr_only][feats]
        y_tr = train_df.iloc[:n_tr_only][label_col]
        X_val = train_df.iloc[n_tr_only:][feats]
        y_val = train_df.iloc[n_tr_only:][label_col]
        oos_df = df[oos_mask]
        X_oos = oos_df[feats]
        y_oos = oos_df[label_col]
        if y_tr.sum() < 5 or y_val.sum() < 1:
            continue
        model = fit_model(X_tr, y_tr, X_val, y_val)
        p_oos = model.predict_proba(X_oos)[:, 1]
        auc = (roc_auc_score(y_oos, p_oos) if y_oos.nunique() > 1
                  else np.nan)
        fold_records.append({
            "month": str(scoring_month), "n_train": n_train,
            "n_oos": n_oos, "n_pos_oos": int(y_oos.sum()),
            "auc": float(auc),
            "best_iter": int(model.best_iteration_),
        })
        for k in range(len(oos_df)):
            oos_records.append({
                "close_ts_ns": int(oos_df["close_ts_ns"].iloc[k]),
                "direction": int(oos_df["candidate_direction"].iloc[k]),
                "year": int(oos_df["year"].iloc[k]),
                "month": str(scoring_month),
                "p_score": float(p_oos[k]),
                "label": int(y_oos.iloc[k]),
            })
        imp = pd.DataFrame({
            "feat": feats,
            "gain": model.booster_.feature_importance(
                importance_type="gain"),
        }).sort_values("gain", ascending=False).head(15)
        imp["month"] = str(scoring_month)
        imp_records.append(imp)
        print(f"  {scoring_month}: train={n_train:,}  oos={n_oos}  "
              f"AUC={auc:.4f}  iter={model.best_iteration_}")

    folds = pd.DataFrame(fold_records)
    oos = pd.DataFrame(oos_records)
    imp = pd.concat(imp_records, ignore_index=True)

    print(f"\n{'='*78}")
    print(f"ABLATION RESULTS")
    print(f"{'='*78}")
    mean_auc = folds["auc"].mean()
    median_auc = folds["auc"].median()
    above_05 = (folds["auc"] > 0.50).sum()
    above_055 = (folds["auc"] > 0.55).sum()
    print(f"\n  Per-fold AUC: mean={mean_auc:.4f}  median={median_auc:.4f}")
    print(f"    Folds with AUC > 0.50: {above_05}/{len(folds)} "
          f"({above_05/len(folds):.0%})")
    print(f"    Folds with AUC > 0.55: {above_055}/{len(folds)} "
          f"({above_055/len(folds):.0%})")

    agg_auc = roc_auc_score(oos["label"], oos["p_score"])
    base_rate = oos["label"].mean()
    print(f"\n  Aggregate OOS AUC: {agg_auc:.4f}  base rate: {base_rate:.3%}")
    print(f"\n  Top-quantile lift:")
    print(f"    {'gate':<10}  {'kept':>5}  {'prec':>7}  {'rec':>7}  "
          f"{'lift':>6}")
    for q in [0.01, 0.02, 0.05, 0.10]:
        thresh = oos["p_score"].quantile(1 - q)
        kept = oos[oos["p_score"] >= thresh]
        prec = kept["label"].mean()
        rec = kept["label"].sum() / max(oos["label"].sum(), 1)
        lift = prec / max(base_rate, 1e-9)
        print(f"    top {q*100:>3.0f}%   {len(kept):>5,}  "
              f"{prec:>6.2%}  {rec:>6.2%}  {lift:>5.2f}x")

    print(f"\n  Top 15 features (averaged gain across folds):")
    feat_avg = imp.groupby("feat")["gain"].mean().sort_values(
        ascending=False).head(15)
    feat_count = imp.groupby("feat").size().reindex(feat_avg.index)
    for feat, g in feat_avg.items():
        n = feat_count.loc[feat]
        print(f"    {feat:<42}  avg_gain={g:>8.0f}  in {n}/{len(folds)} folds")

    print(f"\n  COMPARISON to original T-1 model (with the dropped feature):")
    print(f"    Original T-1 OOS AUC:    0.6997")
    print(f"    Ablation T-1 OOS AUC:    {agg_auc:.4f}")
    print(f"    Δ:                       {agg_auc - 0.6997:+.4f}")

    if agg_auc < 0.52:
        verdict = "STRUCTURAL — model was essentially the candidate filter"
    elif agg_auc < 0.55:
        verdict = "MARGINAL — small residual signal beyond filter"
    elif agg_auc < 0.60:
        verdict = "MODEST — real additional signal in other features"
    else:
        verdict = "STRONG — other features carry meaningful signal"
    print(f"    Verdict: {verdict}")

    oos.to_parquet(OUT / "pre_flip_ablation_T1_oos.parquet", index=False)
    folds.to_csv(OUT / "pre_flip_ablation_T1_folds.csv", index=False)
    print(f"\n  Saved: pre_flip_ablation_T1_oos.parquet, _folds.csv")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
