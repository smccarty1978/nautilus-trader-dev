"""Freeze the T-1 N=20 model into a single deployable artifact.

One-time mechanical fit using the EXACT established procedure (same 20
features, same LightGBM hyperparameters as the walk-forward in
pre_flip_feature_sweep.py / build_n20_schedule.py). Trained on all
2024-2026 augmented candidates, then frozen.

Outputs (the deployable artifacts the live strategy loads):
  results_v0/frozen_t1/model.txt          — LightGBM booster
  results_v0/frozen_t1/feature_list.json  — ordered 20-feature list
  results_v0/frozen_t1/thresholds.json    — entry (top10) + rescore (top50)
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


CANDIDATES = ("studies/v_a_excursion_regime/results_v0/"
                 "pre_flip_candidates_augmented.parquet")
OOS = ("studies/v_a_excursion_regime/results_v0/"
          "pre_flip_T1_n20_oos.parquet")
OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/frozen_t1")
SEED = 42
VAL_FRAC = 0.20
N_FEATURES = 20
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

    df = pd.read_parquet(CANDIDATES)
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns",
                                          utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    print(f"Loaded {len(df):,} augmented candidates")
    all_feats = feature_columns(df)

    # Step 1: FS on Jan-Mar 2024 to pick the top-20 (same as
    # pre_flip_feature_sweep.py — established procedure)
    fs_df = df[df["year_month"] <= FS_END_MONTH].sort_values(
        "close_ts_ns").reset_index(drop=True)
    n_val = int(len(fs_df) * VAL_FRAC)
    n_tr = len(fs_df) - n_val
    fs_model = fit_model(
        fs_df.iloc[:n_tr][all_feats], fs_df.iloc[:n_tr]["label_T1"],
        fs_df.iloc[n_tr:][all_feats], fs_df.iloc[n_tr:]["label_T1"])
    imp = pd.DataFrame({
        "feat": all_feats,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    top_feats = imp.head(N_FEATURES)["feat"].tolist()
    print(f"\nTop {N_FEATURES} features (FS on Jan-Mar 2024):")
    for i, f in enumerate(top_feats, 1):
        print(f"  {i:>2}. {f}")

    # Step 2: fit the FROZEN model on 2024-2025 candidates ONLY.
    # 2026 is held out as forward-OOS; 2020-2023 are backward-OOS.
    # Use a RANDOM 20% holdout for early-stopping (not chronological
    # tail): a multi-year fit with a chronological tail val = all of
    # late-2025 is too regime-distinct, early stopping fires at tree 1.
    # A random holdout gives a representative val set. This is the
    # standard way to instantiate one deployable model; it does not
    # change the validation methodology.
    full = df[df["year"].isin([2024, 2025])].sort_values(
        "close_ts_ns").reset_index(drop=True)
    print(f"\nTraining pool: 2024-2025 only ({len(full):,} of "
          f"{len(df):,} candidates). 2026 held out as OOS.")
    n_val = int(len(full) * VAL_FRAC)
    rng = np.random.RandomState(SEED)
    perm = rng.permutation(len(full))
    val_idx = np.sort(perm[:n_val])
    tr_idx = np.sort(perm[n_val:])
    print(f"\nFreezing model on all {len(full):,} candidates "
          f"(train {len(tr_idx):,} / random-val {len(val_idx):,})...")
    frozen = fit_model(
        full.iloc[tr_idx][top_feats], full.iloc[tr_idx]["label_T1"],
        full.iloc[val_idx][top_feats], full.iloc[val_idx]["label_T1"])
    frozen.booster_.save_model(str(OUT_DIR / "model.txt"))
    print(f"  saved model.txt  (best_iter={frozen.booster_.best_iteration})")

    # Step 3: thresholds from the existing walk-forward OOS predictions
    oos = pd.read_parquet(OOS)
    entry_thr = float(oos["p_score"].quantile(0.90))   # top 10%
    rescore_thr = float(oos["p_score"].quantile(0.50))  # top 50%
    print(f"\nThresholds (from walk-forward OOS p_score distribution):")
    print(f"  entry (top 10%):   p >= {entry_thr:.4f}")
    print(f"  rescore (top 50%): p >= {rescore_thr:.4f}")

    with open(OUT_DIR / "feature_list.json", "w") as f:
        json.dump(top_feats, f, indent=2)
    with open(OUT_DIR / "thresholds.json", "w") as f:
        json.dump({"entry_top10": entry_thr,
                      "rescore_top50": rescore_thr,
                      "frozen_on": "2024-2025 candidates only",
                      "n_train_candidates": len(full)}, f, indent=2)

    # Sanity check 1: 2026-OOS AUC. The frozen model never saw 2026.
    # Walk-forward sweep reported T-1 N=20 AUC ~0.6950. If the frozen
    # model scores 2026 near that, it is sound regardless of best_iter
    # (one feature dominates, so a shallow model can be near-optimal).
    from sklearn.metrics import roc_auc_score
    df_2026 = df[df["year"] == 2026]
    p_2026 = frozen.predict_proba(df_2026[top_feats])[:, 1]
    auc_2026 = roc_auc_score(df_2026["label_T1"], p_2026)
    print(f"\nSanity 1: 2026 forward-OOS AUC = {auc_2026:.4f}  "
          f"(walk-forward sweep was ~0.6950 — frozen is sound if close)")

    # Sanity check 2: in-sample 2024-2025 AUC
    p_is = frozen.predict_proba(full[top_feats])[:, 1]
    auc_is = roc_auc_score(full["label_T1"], p_is)
    print(f"Sanity 2: 2024-2025 in-sample AUC = {auc_is:.4f}")

    # Sanity check 3: correlation with walk-forward scores
    full_scored = full[["close_ts_ns", "candidate_direction"]].copy()
    full_scored["p_frozen"] = p_is
    merged = full_scored.merge(
        oos[["close_ts_ns", "direction", "p_score"]],
        left_on=["close_ts_ns", "candidate_direction"],
        right_on=["close_ts_ns", "direction"], how="inner")
    corr = merged["p_frozen"].corr(merged["p_score"])
    print(f"Sanity 3: frozen-vs-walkforward p_score corr = "
          f"{corr:.4f}  (n={len(merged):,})")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")
    print(f"Artifacts in {OUT_DIR}/")


if __name__ == "__main__":
    main()
