"""Train the exit model (walk-forward) on dataset built by
exit_model_build_dataset.py.

Walk-forward monthly: each month's predictions come from a model
trained on past months only. First scored month 2024-04, last 2026-04.

Output:
  exit_model_oos.parquet — keyed by (entry_ts_ns, elapsed_s, direction)
  exit_model_feature_importance.csv
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


DATA_PATH = ("studies/v_a_excursion_regime/results_v0/exit_model/"
                "exit_model_data_all.parquet")
OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/exit_model")
SEED = 42
VAL_FRAC = 0.20
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"

FEATURES = [
    "elapsed_s",
    "direction",
    "atr_at_signal",
    "entry_p_T1",
    "unrealized_atr",
    "mfe_atr",
    "mae_atr",
    "mfe_mae_ratio",
    "new_cand_p_T1",
    "new_cand_fired",
    "new_cand_score_vs_entry",
    "regime_age_s",
    "micro_alignment_count",
    "broader_alignment_count",
    "regime_1m_now_d",
    "regime_flipped_to_d",
    "bars_in_regime_1m",
    "dist_to_flip_threshold_atr",
    "vol_delta_1m",
    "vol_imbalance_1m",
    "bars_since_entry",
]


def fit_model(X_tr, y_tr, X_val, y_val):
    m = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1,
        is_unbalance=True, verbose=-1)
    m.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
          callbacks=[lgb.early_stopping(50, verbose=False),
                      lgb.log_evaluation(0)])
    return m


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(DATA_PATH)
    df["entry_dt"] = pd.to_datetime(df["entry_ts_ns"], unit="ns",
                                          utc=True)
    df["year_month"] = (
        df["entry_dt"].dt.tz_convert("America/Chicago")
        ).dt.to_period("M")
    df = df.sort_values(["entry_ts_ns", "elapsed_s"]).reset_index(
        drop=True)
    print(f"Loaded {len(df):,} rows")
    print(f"  Feature count: {len(FEATURES)}")
    print(f"  Label-1 rate: {df['label_B'].mean():.1%}")

    # WARNING-3 audit fix: assert RTH-only (UTC hours 13-22)
    entry_hr = df["entry_dt"].dt.hour
    rth_hours_ok = entry_hr.isin(range(13, 22)).all()
    print(f"  RTH-only check (UTC h13-22): {rth_hours_ok}")
    if not rth_hours_ok:
        print(f"  WARNING: {(~entry_hr.isin(range(13, 22))).sum()} "
              f"non-RTH rows in dataset")

    months = sorted(df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(months)
                       if str(m) >= FIRST_SCORED_MONTH)
    print(f"  Months: {len(months)}  scoring from {months[start_idx]}")

    oos_records = []
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
        train_df = df[train_mask].sort_values("entry_ts_ns")
        n_val = int(len(train_df) * VAL_FRAC)
        n_tr_only = len(train_df) - n_val
        X_tr = train_df.iloc[:n_tr_only][FEATURES]
        y_tr = train_df.iloc[:n_tr_only]["label_B"]
        X_val = train_df.iloc[n_tr_only:][FEATURES]
        y_val = train_df.iloc[n_tr_only:]["label_B"]
        if y_tr.sum() < 5 or y_val.sum() < 1:
            continue
        model = fit_model(X_tr, y_tr, X_val, y_val)
        oos_df = df[oos_mask]
        p_oos = model.predict_proba(oos_df[FEATURES])[:, 1]
        for k in range(len(oos_df)):
            r = oos_df.iloc[k]
            oos_records.append({
                "entry_ts_ns": int(r["entry_ts_ns"]),
                "elapsed_s": int(r["elapsed_s"]),
                "direction": int(r["direction"]),
                "year": int(r["year"]),
                "p_exit_model": float(p_oos[k]),
                "label_B": int(r["label_B"]),
            })
        # Last-month FI
        if i == len(months) - 1 or str(scoring_month) == LAST_SCORED_MONTH:
            imp = pd.DataFrame({
                "feat": FEATURES,
                "gain": model.booster_.feature_importance(
                    importance_type="gain"),
            }).sort_values("gain", ascending=False)
            imp.to_csv(OUT_DIR / "exit_model_feature_importance.csv",
                          index=False)
            print(f"\n  Feature importance (last walk-forward fit):")
            for j, row in imp.iterrows():
                print(f"    {row['feat']:<35} gain={row['gain']:>8.0f}")

    oos = pd.DataFrame(oos_records)
    oos.to_parquet(OUT_DIR / "exit_model_oos.parquet", index=False)
    print(f"\n  OOS predictions: {len(oos):,}  "
          f"({time.time()-t0:.0f}s)")

    # AUC by year and elapsed_s
    print(f"\nAUC by year:")
    for yr in [2024, 2025, 2026]:
        sub = oos[oos["year"] == yr]
        if len(sub) > 100 and sub["label_B"].nunique() > 1:
            auc = roc_auc_score(sub["label_B"], sub["p_exit_model"])
            base = sub["label_B"].mean()
            print(f"  {yr}: AUC={auc:.4f}  base rate={base:.1%}  "
                  f"n={len(sub):,}")

    print(f"\nAUC by elapsed_s:")
    for es in sorted(oos["elapsed_s"].unique()):
        sub = oos[oos["elapsed_s"] == es]
        if len(sub) > 100 and sub["label_B"].nunique() > 1:
            auc = roc_auc_score(sub["label_B"], sub["p_exit_model"])
            base = sub["label_B"].mean()
            print(f"  +{int(es):>3}s: AUC={auc:.4f}  "
                  f"base={base:.1%}  n={len(sub):,}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
