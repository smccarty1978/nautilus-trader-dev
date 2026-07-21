"""Phase 7: Six control experiments.

Controls:
  1. KNN-DNA shuffle (shuffle DNA pre-flip features across episodes)
  2. Within-episode sequence shuffle (shuffle step_index order within each episode)
  3. 5-second feature lag (shift observation_time by 5s, using stale features)
  4. Future-score positive control (use actual label as predictor: should be ~oracle)
  5. Feature-group removal (ablation: remove pre-flip DNA, measure delta AUC)
  6. Prediction parity (compare entry_prob distribution: train vs val vs test)

Produces:
  results/control_results.parquet
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
TGT_ENTRY  = OUT_DIR / "entry_targets.parquet"
ABLATION_F = OUT_DIR / "ablation_features.json"
ABLATION_M = OUT_DIR / "ablation_metrics.parquet"
REPLAY_S   = OUT_DIR / "replay_summary.parquet"

_SEED = 42

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

_LGB_PARAMS = {
    "objective": "binary", "metric": "auc",
    "n_estimators": 300, "learning_rate": 0.05,
    "num_leaves": 63, "min_child_samples": 200,
    "subsample": 0.8, "colsample_bytree": 0.8,
    "reg_alpha": 0.1, "reg_lambda": 1.0,
    "random_state": _SEED, "n_jobs": -1, "verbose": -1,
}

_ALL_FEATURES = _EXISTING_COLS + _DNA_COLS + [
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


def _quick_auc(df: pd.DataFrame, features: list, y_col: str) -> tuple[float, float]:
    """Train on train, eval on val+test. Return (val_auc, test_auc)."""
    avail = [c for c in features if c in df.columns]
    train = df[df["period"] == "train"]
    val   = df[df["period"] == "val"]
    test  = df[df["period"] == "test"]

    model = lgb.LGBMClassifier(**_LGB_PARAMS)
    model.fit(
        train[avail].fillna(0).values, train[y_col].values,
        eval_set=[(val[avail].fillna(0).values, val[y_col].values)],
        callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(-1)],
    )
    val_auc  = roc_auc_score(val[y_col].values, model.predict_proba(val[avail].fillna(0).values)[:, 1])
    test_auc = roc_auc_score(test[y_col].values, model.predict_proba(test[avail].fillna(0).values)[:, 1])
    return round(val_auc, 4), round(test_auc, 4)


def run_controls() -> pd.DataFrame:
    t0 = time.time()
    print("\nPhase 7: Running control experiments ...")

    feat = pd.read_parquet(FEAT_FILE)
    tgt  = pd.read_parquet(TGT_ENTRY)
    df   = feat.merge(tgt[["observation_time", "y_entry_positive_300s"]], on="observation_time", how="inner")

    y_col    = "y_entry_positive_300s"
    avail    = [c for c in _ALL_FEATURES if c in df.columns]

    # Baseline AUC for comparison (already in ablation_metrics.parquet)
    try:
        abl_m = pd.read_parquet(ABLATION_M)
        baseline_val_auc  = float(abl_m[abl_m["ablation"] == "F_full_dynamic"]["val_auc"].iloc[0])
        baseline_test_auc = float(abl_m[abl_m["ablation"] == "F_full_dynamic"]["test_auc"].iloc[0])
    except Exception:
        baseline_val_auc, baseline_test_auc = _quick_auc(df, avail, y_col)
    print(f"  Baseline (full): val_AUC={baseline_val_auc:.4f} test_AUC={baseline_test_auc:.4f}")

    records = []

    # Control 1: DNA-shuffle — shuffle pre-flip DNA features across episodes
    print("\n  Control 1: DNA-feature shuffle across episodes ...")
    df_c1 = df.copy()
    rng = np.random.default_rng(_SEED)
    episode_ids = df_c1["episode_id"].unique()
    shuffled_ids = rng.permutation(episode_ids)
    id_map = dict(zip(episode_ids, shuffled_ids))

    # For each observation, replace DNA features with those from a different episode's flip
    dna_by_ep = df_c1.groupby("episode_id")[_DNA_COLS].first()
    for col in _DNA_COLS:
        if col in df_c1.columns:
            shuffled_ep = df_c1["episode_id"].map(id_map)
            df_c1[col] = shuffled_ep.map(dna_by_ep[col])

    val_auc_c1, test_auc_c1 = _quick_auc(df_c1, avail, y_col)
    delta_c1_val  = val_auc_c1  - baseline_val_auc
    delta_c1_test = test_auc_c1 - baseline_test_auc
    print(f"    val_AUC={val_auc_c1:.4f} (delta={delta_c1_val:+.4f})  test_AUC={test_auc_c1:.4f} (delta={delta_c1_test:+.4f})")
    records.append({
        "control": "1_dna_shuffle",
        "description": "Shuffle pre-flip DNA features across episodes (break cross-episode info)",
        "val_auc": val_auc_c1, "test_auc": test_auc_c1,
        "delta_val": delta_c1_val, "delta_test": delta_c1_test,
        "interpretation": "Small delta = DNA adds little; large negative = DNA has genuine info",
    })

    # Control 2: Within-episode sequence shuffle (shuffle step_index order)
    print("\n  Control 2: Within-episode sequence shuffle ...")
    # Vectorized approach: sort orig by (ep, step), sort shuffled by (ep, random) -> same episode
    # boundaries but shuffled row order within each episode. Assign shuffled values to orig positions.
    seq_feats = [
        "seconds_since_flip", "current_progress_atr", "max_progress_atr",
        "max_adverse_atr", "pullback_from_peak_atr", "seconds_since_peak",
        "aligned_return_5s_atr", "aligned_return_15s_atr",
        "aligned_return_30s_atr", "aligned_return_60s_atr",
        "regime_5s_aligned", "regime_30s_aligned",
        "step_index_scaled", "position_in_episode",
    ]
    seq_avail = [c for c in seq_feats if c in df.columns]
    df_orig = df.copy().sort_values(["episode_id", "step_index"]).reset_index(drop=True)
    df_c2 = df_orig.copy()
    df_c2["_rnd"] = rng.random(len(df_c2))
    # Sort by (episode_id, random) to get within-episode shuffle
    df_shuffled = df_c2.sort_values(["episode_id", "_rnd"]).reset_index(drop=True)
    for col in seq_avail:
        df_c2[col] = df_shuffled[col].values
    df_c2 = df_c2.drop(columns=["_rnd"])

    val_auc_c2, test_auc_c2 = _quick_auc(df_c2, avail, y_col)
    delta_c2_val  = val_auc_c2  - baseline_val_auc
    delta_c2_test = test_auc_c2 - baseline_test_auc
    print(f"    val_AUC={val_auc_c2:.4f} (delta={delta_c2_val:+.4f})  test_AUC={test_auc_c2:.4f} (delta={delta_c2_test:+.4f})")
    records.append({
        "control": "2_sequence_shuffle",
        "description": "Shuffle step-level features within each episode (destroy temporal order)",
        "val_auc": val_auc_c2, "test_auc": test_auc_c2,
        "delta_val": delta_c2_val, "delta_test": delta_c2_test,
        "interpretation": "Large negative delta = model uses temporal sequence; ~0 = sequence doesn't matter",
    })

    # Control 3: 5s feature lag (shift obs features forward by 5s / 1 step)
    print("\n  Control 3: 5-second feature lag ...")
    df_c3 = df.copy().sort_values(["episode_id", "step_index"])
    path_feats = [
        "current_progress_atr", "max_progress_atr", "pullback_from_peak_atr",
        "aligned_return_5s_atr", "aligned_return_15s_atr",
        "kalman_velocity_atr_per_s", "kalman_innovation_zscore",
        "regime_5s_aligned", "range_5s_atr",
    ]
    pf_avail = [c for c in path_feats if c in df_c3.columns]
    for col in pf_avail:
        df_c3[col] = df_c3.groupby("episode_id")[col].shift(1)  # 1 step lag = 5s lag

    val_auc_c3, test_auc_c3 = _quick_auc(df_c3.dropna(subset=pf_avail[:1]), avail, y_col)
    delta_c3_val  = val_auc_c3  - baseline_val_auc
    delta_c3_test = test_auc_c3 - baseline_test_auc
    print(f"    val_AUC={val_auc_c3:.4f} (delta={delta_c3_val:+.4f})  test_AUC={test_auc_c3:.4f} (delta={delta_c3_test:+.4f})")
    records.append({
        "control": "3_5s_lag",
        "description": "Apply 5s (1 step) lag to path features — use stale observation",
        "val_auc": val_auc_c3, "test_auc": test_auc_c3,
        "delta_val": delta_c3_val, "delta_test": delta_c3_test,
        "interpretation": "Large negative = features are temporally specific; ~0 = stale features work equally well (weak signal)",
    })

    # Control 4: Future-score positive control (use actual label as predictor)
    print("\n  Control 4: Future-score positive control ...")
    df_c4 = df.copy()
    df_c4["future_score_cheat"] = df_c4[y_col].astype(float)
    cheat_feats = avail + ["future_score_cheat"]
    cheat_avail = [c for c in cheat_feats if c in df_c4.columns]
    val_auc_c4, test_auc_c4 = _quick_auc(df_c4, cheat_avail, y_col)
    print(f"    val_AUC={val_auc_c4:.4f} test_AUC={test_auc_c4:.4f}  (expected: near 1.0)")
    records.append({
        "control": "4_future_score",
        "description": "Add true label as a feature (sanity check: should give AUC near 1.0)",
        "val_auc": val_auc_c4, "test_auc": test_auc_c4,
        "delta_val": val_auc_c4 - baseline_val_auc,
        "delta_test": test_auc_c4 - baseline_test_auc,
        "interpretation": "Should be ~1.0; confirms pipeline is correct",
    })

    # Control 5: Remove pre-flip DNA features (measure loss)
    print("\n  Control 5: Remove pre-flip DNA group ...")
    no_dna_feats = [c for c in _ALL_FEATURES if c not in _DNA_COLS and c in df.columns]
    val_auc_c5, test_auc_c5 = _quick_auc(df, no_dna_feats, y_col)
    delta_c5_val  = val_auc_c5  - baseline_val_auc
    delta_c5_test = test_auc_c5 - baseline_test_auc
    print(f"    val_AUC={val_auc_c5:.4f} (delta={delta_c5_val:+.4f})  test_AUC={test_auc_c5:.4f} (delta={delta_c5_test:+.4f})")
    records.append({
        "control": "5_remove_dna",
        "description": "Remove all pre-flip DNA features; measure AUC delta",
        "val_auc": val_auc_c5, "test_auc": test_auc_c5,
        "delta_val": delta_c5_val, "delta_test": delta_c5_test,
        "interpretation": "Large negative = DNA features contribute; ~0 = DNA adds nothing",
    })

    # Control 6: Prediction parity — compare score distributions across splits
    print("\n  Control 6: Prediction parity ...")
    avail_f = [c for c in avail if c in df.columns]
    train = df[df["period"] == "train"]
    val   = df[df["period"] == "val"]
    test  = df[df["period"] == "test"]

    model_parity = lgb.LGBMClassifier(**_LGB_PARAMS)
    model_parity.fit(
        train[avail_f].fillna(0).values, train[y_col].values,
        eval_set=[(val[avail_f].fillna(0).values, val[y_col].values)],
        callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(-1)],
    )

    for split_name, split_df in [("train", train), ("val", val), ("test", test)]:
        probs = model_parity.predict_proba(split_df[avail_f].fillna(0).values)[:, 1]
        auc = roc_auc_score(split_df[y_col].values, probs)
        mean_prob = probs.mean()
        pct_above_50 = 100 * (probs > 0.5).mean()
        print(f"    [{split_name}] AUC={auc:.4f} mean_prob={mean_prob:.3f} pct>0.50={pct_above_50:.1f}%")

    # For this control, report the calibration gap (train_auc - test_auc)
    tr_auc  = roc_auc_score(train[y_col].values, model_parity.predict_proba(train[avail_f].fillna(0).values)[:, 1])
    val_auc_c6, test_auc_c6 = _quick_auc(df, avail_f, y_col)
    cal_gap = tr_auc - test_auc_c6
    records.append({
        "control": "6_prediction_parity",
        "description": "Check score distribution + calibration across train/val/test splits",
        "val_auc": val_auc_c6, "test_auc": test_auc_c6,
        "delta_val": tr_auc - val_auc_c6,
        "delta_test": cal_gap,
        "interpretation": f"Train-test AUC gap={cal_gap:.4f}; large = overfit risk",
    })

    ctrl_df = pd.DataFrame(records)
    ctrl_df.to_parquet(OUT_DIR / "control_results.parquet", index=False)
    print(f"\n  Control experiments complete in {time.time()-t0:.1f}s")
    print(f"\n{'Control':25s} {'val_AUC':>9s} {'test_AUC':>9s} {'delta_v':>9s} {'delta_t':>9s}")
    print("-" * 68)
    for _, row in ctrl_df.iterrows():
        print(f"  {row['control']:23s} {row['val_auc']:9.4f} {row['test_auc']:9.4f} "
              f"{row['delta_val']:+9.4f} {row['delta_test']:+9.4f}")

    return ctrl_df


if __name__ == "__main__":
    run_controls()
    print("\nPhase 7 complete.")
