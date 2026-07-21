"""Phase 4: Six-model ablation study on expanded feature set.

Models:
  A: baseline_only         -- 28 existing collector features
  B: expanded_path         -- existing + derived path/interaction features
  C: knn_dna_only          -- pre-flip DNA features only (regime_dna)
  D: baseline_plus_dna     -- existing + pre-flip DNA
  E: expanded_plus_dna     -- all non-DNA + all DNA features
  F: full_dynamic          -- all ~100 features

Produces:
  results/ablation_metrics.parquet
  results/ablation_features.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
import lightgbm as lgb

OUT_DIR    = Path("studies/rl_regime_feasibility/expanded_dynamic/results")
FEAT_FILE  = OUT_DIR / "expanded_features.parquet"
TGT_FILE   = OUT_DIR / "entry_targets.parquet"

_SEED = 42

# ── Feature group definitions ─────────────────────────────────────────────────

_EXISTING_COLS = [
    "seconds_since_flip", "current_progress_atr", "max_progress_atr",
    "max_adverse_atr", "pullback_from_peak_atr", "seconds_since_peak",
    "progress_efficiency", "aligned_return_5s_atr", "aligned_return_15s_atr",
    "aligned_return_30s_atr", "aligned_return_60s_atr", "realized_vol_60s_atr",
    "range_5s_atr", "volume_5s_zscore", "volume_30s_vs_5m",
    "bollinger_width_percentile_1m", "bollinger_keltner_width_ratio_1m",
    "kalman_velocity_atr_per_s", "kalman_acceleration_atr_per_s2",
    "kalman_innovation_zscore", "ema3_ema9_spread_30s_atr",
    "regime_5s_aligned", "regime_30s_aligned", "regime_5m_aligned",
    "regime_age_1m_bars", "adx14_1m", "position_in_trailing_1m_range",
    "minutes_since_rth_open",
]

_DNA_COLS = [
    "atr_norm_at_flip", "atr_ratio_vs_60",
    "pre_5_return_atr", "pre_5_range_atr", "pre_5_body_sum_atr",
    "pre_5_realized_vol_atr", "pre_5_efficiency", "pre_5_chop_score",
    "pre_5_hh_ll_count", "pre_5_failed_breakout_count",
    "pre_5_range_ratio_vs_60", "pre_5_compression_score",
    "pre_5_expansion_score", "pre_5_lr_slope_atr",
    "pre_5_volume_ratio", "pre_5_volume_trend", "pre_5_volume_zscore",
    "pre_5_signed_volume_proxy",
    "pre_15_return_atr", "pre_15_range_atr", "pre_15_body_sum_atr",
    "pre_15_realized_vol_atr", "pre_15_efficiency", "pre_15_chop_score",
    "pre_15_hh_ll_count", "pre_15_failed_breakout_count",
    "pre_15_range_ratio_vs_60", "pre_15_compression_score",
    "pre_15_expansion_score", "pre_15_lr_slope_atr",
    "pre_15_volume_ratio", "pre_15_volume_trend", "pre_15_volume_zscore",
    "pre_15_signed_volume_proxy",
    "pre_30_return_atr", "pre_30_range_atr", "pre_30_body_sum_atr",
    "pre_30_realized_vol_atr", "pre_30_efficiency", "pre_30_chop_score",
    "pre_30_hh_ll_count", "pre_30_failed_breakout_count",
    "pre_30_range_ratio_vs_60", "pre_30_compression_score",
    "pre_30_expansion_score", "pre_30_lr_slope_atr",
    "pre_30_volume_ratio", "pre_30_volume_trend", "pre_30_volume_zscore",
    "pre_30_signed_volume_proxy",
    "ema9_slope_atr", "ema21_slope_atr", "slope_acceleration",
    "distance_from_ema9_atr", "distance_from_ema21_atr",
    "minutes_to_rth_close", "is_rth",
    "distance_to_vwap_atr", "distance_to_session_high_atr",
    "distance_to_session_low_atr", "distance_to_overnight_high_atr",
    "distance_to_overnight_low_atr",
]

_DERIVED_COLS = [
    "progress_sq_atr", "adverse_vs_peak_ratio", "progress_minus_adverse",
    "pb_severity_ratio", "current_vs_max_progress", "time_since_peak_ratio",
    "position_in_episode", "seconds_remaining",
    "vol_x_velocity", "vol_x_acceleration", "range_x_vol",
    "regime_alignment_score", "adx_x_progress", "adx_x_max_progress",
    "ema_spread_x_progress", "bb_x_vol",
    "progress_x_compression", "progress_x_pre5_eff", "progress_x_lr_slope",
    "pre_eff_5v15", "pre_vol_5v15", "pre_comp_5v30", "flip_momentum_qual", "pre_vol_accel",
    "kalman_aligned", "kalman_accel_aligned", "step_index_scaled",
]

_EXPANDED_PATH = _EXISTING_COLS + _DERIVED_COLS
_EXPANDED_DNA  = _EXISTING_COLS + _DNA_COLS
_FULL          = _EXISTING_COLS + _DNA_COLS + _DERIVED_COLS


ABLATIONS = {
    "A_baseline_only":    _EXISTING_COLS,
    "B_expanded_path":    _EXPANDED_PATH,
    "C_dna_only":         _DNA_COLS,
    "D_baseline_plus_dna": _EXPANDED_DNA,
    "E_expanded_plus_dna": _FULL,
    "F_full_dynamic":     _FULL,  # same features but different target
}

_LGB_PARAMS = {
    "objective":        "binary",
    "metric":           "auc",
    "n_estimators":     400,
    "learning_rate":    0.05,
    "num_leaves":       63,
    "min_child_samples": 200,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "reg_alpha":        0.1,
    "reg_lambda":       1.0,
    "random_state":     _SEED,
    "n_jobs":           -1,
    "verbose":          -1,
}


def train_lgb(
    X_train, y_train, X_val, y_val
) -> tuple[lgb.LGBMClassifier, float]:
    model = lgb.LGBMClassifier(**_LGB_PARAMS)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
    )
    val_prob  = model.predict_proba(X_val)[:, 1]
    val_auc   = roc_auc_score(y_val, val_prob)
    return model, val_auc


def run_ablations() -> tuple[pd.DataFrame, dict]:
    t0 = time.time()
    print("\nPhase 4: Running ablation models ...")

    print("  Loading expanded features ...")
    feat = pd.read_parquet(FEAT_FILE)
    print("  Loading entry targets ...")
    tgt = pd.read_parquet(TGT_FILE)

    # Merge features + targets on observation_time
    df = feat.merge(tgt[["observation_time", "y_entry_positive_300s", "y_entry_adv_300s"]],
                    on="observation_time", how="inner")
    print(f"  Merged: {len(df):,} rows")

    train = df[df["period"] == "train"]
    val   = df[df["period"] == "val"]
    test  = df[df["period"] == "test"]
    print(f"  Split: train={len(train):,} val={len(val):,} test={len(test):,}")

    y_col = "y_entry_positive_300s"
    records = []
    feat_registry = {}

    for name, feature_list in ABLATIONS.items():
        t1 = time.time()
        # Filter to only features present in df
        available = [c for c in feature_list if c in df.columns]
        missing   = [c for c in feature_list if c not in df.columns]
        if missing:
            print(f"  [{name}] WARNING: {len(missing)} features missing: {missing[:5]}")

        feat_registry[name] = available

        X_tr = train[available].fillna(0).values
        y_tr = train[y_col].values
        X_vl = val[available].fillna(0).values
        y_vl = val[y_col].values
        X_te = test[available].fillna(0).values
        y_te = test[y_col].values

        model, val_auc = train_lgb(X_tr, y_tr, X_vl, y_vl)

        test_prob = model.predict_proba(X_te)[:, 1]
        test_auc  = roc_auc_score(y_te, test_prob)
        val_prob  = model.predict_proba(X_vl)[:, 1]

        # Save predictions for later
        df.loc[val.index,  f"prob_{name}"]  = val_prob
        df.loc[test.index, f"prob_{name}"]  = test_prob

        # Gate 1 check: AUC >= 0.54
        gate1_pass = val_auc >= 0.54 and test_auc >= 0.54

        elapsed = time.time() - t1
        print(f"  [{name}] n_feat={len(available)}  val_AUC={val_auc:.4f}  "
              f"test_AUC={test_auc:.4f}  gate1={'PASS' if gate1_pass else 'FAIL'}  "
              f"({elapsed:.1f}s)")

        records.append({
            "ablation":    name,
            "n_features":  len(available),
            "val_auc":     round(val_auc, 4),
            "test_auc":    round(test_auc, 4),
            "gate1_pass":  gate1_pass,
            "elapsed_s":   round(elapsed, 1),
        })

    metrics = pd.DataFrame(records)
    metrics.to_parquet(OUT_DIR / "ablation_metrics.parquet", index=False)
    with open(OUT_DIR / "ablation_features.json", "w") as f:
        json.dump(feat_registry, f, indent=2)

    print(f"\n  Ablation complete in {time.time()-t0:.1f}s")
    print(f"\n{'Ablation':30s} {'val_AUC':>9s} {'test_AUC':>9s} {'Gate1':>6s}")
    print("-" * 60)
    for _, row in metrics.iterrows():
        g = "PASS" if row["gate1_pass"] else "fail"
        print(f"  {row['ablation']:28s} {row['val_auc']:9.4f} {row['test_auc']:9.4f} {g:>6s}")

    # Save df with all predictions
    df.to_parquet(OUT_DIR / "ablation_predictions.parquet", index=False)

    return metrics, feat_registry


if __name__ == "__main__":
    run_ablations()
    print("\nPhase 4 complete.")
