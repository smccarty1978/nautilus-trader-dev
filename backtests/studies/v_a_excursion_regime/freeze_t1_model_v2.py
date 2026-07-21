"""Freeze the T-1 N=20 model — v2, fixed multi-tree config.

The v1 freeze hit best_iter=1 (early stopping degenerated on a
multi-year fit) -> a 29-value staircase score, too coarse to drive the
per-bar rescore gate. v2 fixes that: disable early stopping, train a
FIXED number of trees so the score distribution is smooth and
responsive like the walk-forward models.

Config: n_estimators=200 fixed, no early stopping, all other
hyperparameters identical to the established walk-forward
(max_depth=6, num_leaves=31, lr=0.05, feature_fraction=0.8,
bagging 0.8/5, min_data_in_leaf=50, is_unbalance=True).

Trained ONLY on 2024-2025 candidates (the approved window). 2026 is
held out OOS; 2020-2023 are backward-OOS. n_estimators=200 is a
generic conservative GBM choice — NOT tuned to any year.

Outputs: frozen_t1/model.txt, feature_list.json, thresholds.json
(overwrites the v1 artifacts).
"""
from __future__ import annotations
import os, sys, json, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score


CANDIDATES = ("studies/v_a_excursion_regime/results_v0/"
                 "pre_flip_candidates_augmented.parquet")
OOS = ("studies/v_a_excursion_regime/results_v0/"
          "pre_flip_T1_n20_oos.parquet")
OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/frozen_t1")
SEED = 42
VAL_FRAC = 0.20
N_FEATURES = 20
N_TREES = 200          # fixed; no early stopping
FS_END_MONTH = "2024-03"


def feature_columns(df):
    drop = set([
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s", "close_3m", "close_5m",
        "vwap_value",
        "label_T1", "label_T2", "label_T3",
    ])
    feats = [c for c in df.columns if c not in drop]
    feats = [c for c in feats
              if df[c].dtype not in ("object", "datetime64[ns, UTC]")]
    return feats


def fit_es(X_tr, y_tr, X_val, y_val):
    """Early-stopping fit — only used for the FS feature ranking."""
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


def fit_fixed(X_tr, y_tr, n_trees):
    """Fixed-tree fit — no early stopping. The deployable model."""
    m = lgb.LGBMClassifier(
        n_estimators=n_trees, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1,
        is_unbalance=True, verbose=-1)
    m.fit(X_tr, y_tr)
    return m


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(CANDIDATES)
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns",
                                          utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    all_feats = feature_columns(df)
    print(f"Loaded {len(df):,} candidates  ({len(all_feats)} features)")

    # FS on Jan-Mar 2024 (unchanged established procedure)
    fs_df = df[df["year_month"] <= FS_END_MONTH].sort_values(
        "close_ts_ns").reset_index(drop=True)
    n_val = int(len(fs_df) * VAL_FRAC)
    n_tr = len(fs_df) - n_val
    fs_model = fit_es(
        fs_df.iloc[:n_tr][all_feats], fs_df.iloc[:n_tr]["label_T1"],
        fs_df.iloc[n_tr:][all_feats], fs_df.iloc[n_tr:]["label_T1"])
    imp = pd.DataFrame({
        "feat": all_feats,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    top_feats = imp.head(N_FEATURES)["feat"].tolist()
    print(f"Top {N_FEATURES} features selected (FS Jan-Mar 2024)")

    # Freeze on 2024-2025, FIXED 200 trees, no early stopping
    full = df[df["year"].isin([2024, 2025])].sort_values(
        "close_ts_ns").reset_index(drop=True)
    print(f"\nFreezing on 2024-2025: {len(full):,} candidates  "
          f"n_estimators={N_TREES} fixed (no early stopping)")
    frozen = fit_fixed(full[top_feats], full["label_T1"], N_TREES)
    frozen.booster_.save_model(str(OUT_DIR / "model.txt"))
    print(f"  saved model.txt  (n_trees={frozen.booster_.num_trees()})")

    # ---- sanity / score-distribution checks ----
    p_is = frozen.predict_proba(full[top_feats])[:, 1]
    df_2026 = df[df["year"] == 2026]
    p_2026 = frozen.predict_proba(df_2026[top_feats])[:, 1]
    auc_is = roc_auc_score(full["label_T1"], p_is)
    auc_2026 = roc_auc_score(df_2026["label_T1"], p_2026)
    n_distinct = len(np.unique(np.round(p_is, 6)))
    print(f"\nSanity:")
    print(f"  2024-2025 in-sample AUC = {auc_is:.4f}")
    print(f"  2026 forward-OOS AUC    = {auc_2026:.4f}  "
          f"(walk-forward sweep ~0.6950)")
    print(f"  distinct score values   = {n_distinct:,}  "
          f"(v1 1-tree model had 29)")

    # Score distribution vs walk-forward OOS (PARITY GATE step 1)
    oos = pd.read_parquet(OOS)
    print(f"\nScore distribution — v2 frozen vs walk-forward OOS:")
    print(f"  {'pctile':>8} {'v2 frozen':>12} {'walk-forward':>14}")
    for q in [0.10, 0.25, 0.50, 0.70, 0.90, 0.95]:
        fv = np.quantile(p_is, q)
        wv = np.quantile(oos["p_score"], q)
        print(f"  {'p'+str(int(q*100)):>8} {fv:>12.5f} {wv:>14.5f}")

    # Thresholds: derive from v2 frozen model's own 2024-2025
    # distribution (p90 entry, p50 rescore) — the principled
    # "top 10% / top 50%" cutoffs for THIS model.
    entry_thr = float(np.quantile(p_is, 0.90))
    rescore_thr = float(np.quantile(p_is, 0.50))
    print(f"\nThresholds (v2 frozen, 2024-2025 distribution):")
    print(f"  entry (p90):   {entry_thr:.5f}")
    print(f"  rescore (p50): {rescore_thr:.5f}")
    print(f"  (walk-forward-derived were 0.09914 / 0.07699)")

    with open(OUT_DIR / "feature_list.json", "w") as f:
        json.dump(top_feats, f, indent=2)
    with open(OUT_DIR / "thresholds.json", "w") as f:
        json.dump({
            "entry_top10": entry_thr,
            "rescore_top50": rescore_thr,
            "frozen_on": "2024-2025 candidates only",
            "n_train_candidates": len(full),
            "config": f"fixed {N_TREES} trees, no early stopping",
            "n_distinct_scores": int(n_distinct),
            "auc_2026_oos": float(auc_2026),
        }, f, indent=2)
    print(f"\n[done] runtime: {time.time()-t0:.0f}s  -> {OUT_DIR}/")


if __name__ == "__main__":
    main()
