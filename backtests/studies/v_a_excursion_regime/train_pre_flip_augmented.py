"""Walk-forward training on AUGMENTED pre-flip candidates.

Trains T-1, T-2, and T-3 horizon models on the augmented candidate
table (50 original features + ~46 vol/VWAP/calendar/3m+5m TF features).

Comparison target:
  - Original (50 features): T-1 AUC 0.70, T-2 AUC 0.54, T-3 AUC 0.51
  - Augmented: see if vol/VWAP/calendar context lifts the weaker
    horizons (esp. T-2, T-3)

Outputs per horizon:
  - pre_flip_augmented_oos_T{1,2,3}.parquet
  - pre_flip_augmented_folds_T{1,2,3}.csv
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


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Drop identifiers, raw prices, raw EMAs, labels. Keep all the
    rest (existing pre-flip features + augmented features)."""
    drop = set([
        # Identifiers / timestamps
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        # Raw 1m prices (year-proxy)
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        # Raw sub-1m prices
        "close_5s", "close_15s", "close_30s",
        # Raw 3m/5m prices (from augmentation)
        "close_3m", "close_5m",
        # Raw VWAP value (absolute price level — year-proxy)
        "vwap_value",
        # Raw vol_imbalance (we have the dir-aware version too)
        # — keep both, they have different info
        # Labels
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


def walk_forward_horizon(df: pd.DataFrame, feats: list[str],
                            label_col: str, horizon_name: str):
    print(f"\n{'='*78}\nHORIZON {horizon_name}\n{'='*78}")
    months = sorted(df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(months)
                       if str(m) >= FIRST_SCORED_MONTH)
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
        }).sort_values("gain", ascending=False).head(20)
        imp["month"] = str(scoring_month)
        imp_records.append(imp)
        print(f"  {scoring_month}: train={n_train:>5,}  oos={n_oos:>4}  "
              f"AUC={auc:.4f}  best_iter={model.best_iteration_:>3}")
    return (pd.DataFrame(fold_records),
              pd.DataFrame(oos_records),
              pd.concat(imp_records, ignore_index=True))


def report_horizon(name: str, folds, oos, imp, baseline_auc: float):
    print(f"\n--- {name} ---")
    mean_auc = folds["auc"].mean()
    above_055 = (folds["auc"] > 0.55).sum()
    print(f"  Per-fold AUC: mean={mean_auc:.4f}  "
          f"folds > 0.55: {above_055}/{len(folds)}")
    agg_auc = (roc_auc_score(oos["label"], oos["p_score"])
                  if oos["label"].nunique() > 1 else np.nan)
    base_rate = oos["label"].mean()
    print(f"  Aggregate OOS AUC: {agg_auc:.4f}  base rate: {base_rate:.3%}")
    print(f"  vs baseline (50-feat): {baseline_auc:.4f}  Δ {agg_auc-baseline_auc:+.4f}")
    print(f"  Top-quantile lift:")
    for q in [0.01, 0.02, 0.05, 0.10]:
        thresh = oos["p_score"].quantile(1 - q)
        kept = oos[oos["p_score"] >= thresh]
        prec = kept["label"].mean()
        lift = prec / max(base_rate, 1e-9)
        print(f"    top {q*100:>3.0f}%   n={len(kept):>5,}  "
              f"prec={prec:>5.2%}  lift={lift:.2f}x")
    print(f"  Top 15 features (avg gain):")
    feat_avg = imp.groupby("feat")["gain"].mean().sort_values(
        ascending=False).head(15)
    feat_count = imp.groupby("feat").size().reindex(feat_avg.index)
    for f, g in feat_avg.items():
        n = feat_count.loc[f]
        marker = "  <NEW>" if (f.startswith(("vol_", "vwap_", "obv_",
                                                 "dist_close_to_vwap",
                                                 "dist_to_vwap_",
                                                 "regime_3m", "regime_5m",
                                                 "bars_in_regime_3m",
                                                 "bars_in_regime_5m",
                                                 "atr_3m", "atr_5m",
                                                 "cum_vol", "minute_",
                                                 "hour_", "day_of_week",
                                                 "minutes_since"))) else ""
        print(f"    {f:<42}  gain={g:>8.0f}  in {n}/{len(folds)} folds{marker}")
    return agg_auc


def main():
    t0 = time.time()
    print("=" * 78)
    print("WALK-FORWARD ON AUGMENTED FEATURES — T-1 / T-2 / T-3")
    print("=" * 78)

    aug_path = OUT / "pre_flip_candidates_augmented.parquet"
    if not aug_path.exists():
        print(f"\nERROR: {aug_path} not found. Run augment_pre_flip_candidates.py first.")
        return

    df = pd.read_parquet(aug_path)
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    print(f"\nLoaded {len(df):,} augmented candidates")
    feats = feature_columns(df)
    print(f"  features: {len(feats)}")
    new_feats = [f for f in feats if f.startswith((
        "vol_", "vwap_", "obv_", "dist_close_to_vwap",
        "dist_to_vwap_", "regime_3m", "regime_5m",
        "bars_in_regime_3m", "bars_in_regime_5m",
        "atr_3m", "atr_5m", "cum_vol", "minute_", "hour_",
        "day_of_week", "minutes_since"))]
    print(f"  augmented features in matrix: {len(new_feats)}")

    # Baseline AUCs from prior run (for Δ reporting)
    baselines = {1: 0.6997, 2: 0.5418, 3: 0.5148}

    aug_aucs = {}
    for H in [1, 2, 3]:
        folds, oos, imp = walk_forward_horizon(
            df, feats, f"label_T{H}", f"T-{H}")
        auc = report_horizon(f"T-{H} (augmented)", folds, oos, imp,
                                  baselines[H])
        aug_aucs[H] = auc
        oos.to_parquet(OUT / f"pre_flip_augmented_oos_T{H}.parquet",
                          index=False)
        folds.to_csv(OUT / f"pre_flip_augmented_folds_T{H}.csv", index=False)

    print(f"\n{'='*78}\nFINAL COMPARISON\n{'='*78}")
    print(f"  {'Horizon':<12}  {'Baseline AUC':>13}  {'Augmented AUC':>13}  "
          f"{'Δ':>8}")
    for H in [1, 2, 3]:
        print(f"  T-{H:<10}  {baselines[H]:>13.4f}  {aug_aucs[H]:>13.4f}  "
              f"{aug_aucs[H] - baselines[H]:>+8.4f}")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
