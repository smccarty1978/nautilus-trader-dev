"""Gate 1: Train and evaluate causal ML models on feature_snapshots.

Target: Can we predict the DIRECTION of next-increment price movement
from the 28 features, better than chance?

We frame this as binary classification at each of 6 horizons:
  target_{H}s_dir: 1 if aligned_return_{H}s > 0 else 0

Models:
  ridge_log  — Logistic Regression with L2 penalty (linear baseline)
  gbm        — HistGradientBoosting (captures non-linearities)

For each model × horizon, we report:
  - In-sample AUC (train 2024)
  - Validation AUC (2025-01 to 2025-02)
  - Validation calibration (Brier score)
  - Selected policy threshold (Youden J on validation)

Gate 1 pass criteria:
  At least 2 horizons with val_AUC >= 0.54 on at least one model.
  If no horizon meets this criterion: "NOT FEASIBLE" verdict.

Outputs:
  results/gate1_metrics.parquet     all AUC/Brier per model/horizon/period
  results/gate1_predictions.parquet OOS predictions for policy evaluation
  results/gate1_report.txt          human-readable report
"""
from __future__ import annotations

import math
import os
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import numpy as np
import pandas as pd

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, brier_score_loss
    from sklearn.pipeline import Pipeline
    _SKLEARN = True
except ImportError:
    _SKLEARN = False
    print("WARNING: scikit-learn not available — skipping Gate 1 models")

OUT_DIR   = Path("studies/rl_regime_feasibility/results")
SNAP_FILE = OUT_DIR / "feature_snapshots.parquet"
LBL_FILE  = OUT_DIR / "forward_labels.parquet"

HORIZONS_S = [5, 15, 30, 60, 120, 300]
FEATURES   = [
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

_AUC_THRESHOLD = 0.54   # Gate 1 pass criterion
_N_HORIZONS_NEEDED = 2


def _build_targets(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Build binary classification targets from label columns."""
    targets = {}
    for h in HORIZONS_S:
        col = f"base__pnl_{h}s"
        if col not in df.columns:
            continue
        # Positive class: trade makes money (>0 PnL)
        targets[h] = (df[col] > 0).astype(int)
    return targets


def _clip_features(X: np.ndarray, pct_lo: np.ndarray, pct_hi: np.ndarray) -> np.ndarray:
    return np.clip(X, pct_lo, pct_hi)


def run_gate1() -> dict:
    if not _SKLEARN:
        print("scikit-learn not available; returning empty results")
        return {}

    print("Loading data ...")
    snaps = pd.read_parquet(SNAP_FILE)
    lbls  = pd.read_parquet(LBL_FILE)
    df    = snaps.merge(lbls, on="observation_time", how="inner")
    print(f"  {len(df):,} rows total")

    train = df[df["period"] == "train"].copy()
    val   = df[df["period"] == "val"].copy()
    test  = df[df["period"] == "test"].copy()
    print(f"  train={len(train):,}  val={len(val):,}  test={len(test):,}")

    targets_train = _build_targets(train)
    targets_val   = _build_targets(val)

    # Feature matrix — fill NaN with median from train
    X_train_raw = train[FEATURES].values.astype(np.float64)
    X_val_raw   = val[FEATURES].values.astype(np.float64)
    X_test_raw  = test[FEATURES].values.astype(np.float64)

    # Per-feature clip percentiles from train only
    pct_lo = np.nanpercentile(X_train_raw, 1, axis=0)
    pct_hi = np.nanpercentile(X_train_raw, 99, axis=0)

    X_train_clipped = _clip_features(X_train_raw, pct_lo, pct_hi)
    X_val_clipped   = _clip_features(X_val_raw,   pct_lo, pct_hi)
    X_test_clipped  = _clip_features(X_test_raw,  pct_lo, pct_hi)

    # NaN fill with feature medians from train (after clipping) applied to all splits
    train_medians = np.nanmedian(X_train_clipped, axis=0)
    for j in range(X_train_clipped.shape[1]):
        mask_tr = np.isnan(X_train_clipped[:, j])
        mask_vl = np.isnan(X_val_clipped[:, j])
        mask_te = np.isnan(X_test_clipped[:, j])
        X_train_clipped[mask_tr, j] = train_medians[j]
        X_val_clipped[mask_vl, j]   = train_medians[j]
        X_test_clipped[mask_te, j]  = train_medians[j]

    models_def = {
        "ridge_log": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=0.1, max_iter=500, solver="lbfgs")),
        ]),
        "gbm": HistGradientBoostingClassifier(
            max_iter=200, max_depth=5, learning_rate=0.05,
            min_samples_leaf=50, random_state=42,
        ),
    }

    all_metrics = []
    all_preds   = []

    for model_name, model_proto in models_def.items():
        print(f"\n  Model: {model_name}")
        for h in HORIZONS_S:
            if h not in targets_train:
                continue
            y_tr = targets_train[h].values
            y_vl = targets_val[h].values if h in targets_val else None

            # Filter out rows where label is NaN (censored)
            lbl_col = f"base__pnl_{h}s"
            valid_tr = ~np.isnan(train[lbl_col].values)
            valid_vl = ~np.isnan(val[lbl_col].values) if y_vl is not None else None

            if valid_tr.sum() < 200:
                print(f"    h={h}s: not enough samples ({valid_tr.sum()})")
                continue

            import copy
            m = copy.deepcopy(model_proto)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m.fit(X_train_clipped[valid_tr], y_tr[valid_tr])

            # In-sample AUC
            prob_tr = m.predict_proba(X_train_clipped[valid_tr])[:, 1]
            auc_tr  = roc_auc_score(y_tr[valid_tr], prob_tr)

            # Validation AUC
            if y_vl is not None and valid_vl.sum() >= 50:
                prob_vl = m.predict_proba(X_val_clipped[valid_vl])[:, 1]
                auc_vl  = roc_auc_score(y_vl[valid_vl], prob_vl)
                brier_vl = brier_score_loss(y_vl[valid_vl], prob_vl)
            else:
                auc_vl = float("nan")
                brier_vl = float("nan")

            # Youden J threshold on validation
            if not math.isnan(auc_vl):
                from sklearn.metrics import roc_curve
                fpr, tpr, thresholds = roc_curve(y_vl[valid_vl], prob_vl)
                j_scores = tpr - fpr
                best_thr = float(thresholds[np.argmax(j_scores)])
            else:
                best_thr = 0.5

            gate_pass = (not math.isnan(auc_vl)) and auc_vl >= _AUC_THRESHOLD

            print(f"    h={h:3d}s  train_AUC={auc_tr:.4f}  val_AUC={auc_vl:.4f}"
                  f"  brier={brier_vl:.4f}  thr={best_thr:.3f}"
                  f"  {'PASS' if gate_pass else 'fail'}")

            all_metrics.append({
                "model": model_name, "horizon_s": h,
                "auc_train": auc_tr, "auc_val": auc_vl,
                "brier_val": brier_vl, "threshold": best_thr,
                "gate_pass": gate_pass,
            })

            # Store val + test predictions so Gate 2 ML policies have real scores
            pred_parts = []
            if y_vl is not None:
                prob_full_vl = m.predict_proba(X_val_clipped)[:, 1]
                vl_df = val[["observation_time", "episode_id", "direction", "period"]].copy()
                vl_df[f"{model_name}_h{h}_prob"] = prob_full_vl
                vl_df[f"{model_name}_h{h}_thr"]  = best_thr
                pred_parts.append(vl_df)
            if len(test) > 0:
                prob_full_te = m.predict_proba(X_test_clipped)[:, 1]
                te_df = test[["observation_time", "episode_id", "direction", "period"]].copy()
                te_df[f"{model_name}_h{h}_prob"] = prob_full_te
                te_df[f"{model_name}_h{h}_thr"]  = best_thr
                pred_parts.append(te_df)
            if pred_parts:
                all_preds.append(pd.concat(pred_parts, ignore_index=True))

    # Save metrics
    metrics_df = pd.DataFrame(all_metrics)
    metrics_df.to_parquet(OUT_DIR / "gate1_metrics.parquet", index=False)

    # Save predictions
    if all_preds:
        import functools
        pred_combined = functools.reduce(
            lambda a, b: a.merge(
                b.drop(columns=[c for c in b.columns if c in a.columns and c != "observation_time"]),
                on="observation_time", how="outer"
            ),
            all_preds,
        )
        pred_combined.to_parquet(OUT_DIR / "gate1_predictions.parquet", index=False)

    # Gate 1 verdict
    _write_gate1_report(metrics_df)

    return {"metrics": metrics_df, "gate_pass": _gate1_verdict(metrics_df)}


def _gate1_verdict(metrics_df: pd.DataFrame) -> bool:
    if metrics_df.empty:
        return False
    passing = metrics_df[metrics_df["gate_pass"] == True]
    horizons_pass = passing["horizon_s"].nunique()
    return horizons_pass >= _N_HORIZONS_NEEDED


def _write_gate1_report(metrics_df: pd.DataFrame) -> None:
    lines = []
    lines.append("=" * 70)
    lines.append("GATE 1: CONDITIONAL FORWARD-INCREMENT PREDICTABILITY")
    lines.append("=" * 70)
    lines.append(f"\nCriteria: val_AUC >= {_AUC_THRESHOLD} on at least {_N_HORIZONS_NEEDED} horizons\n")

    if metrics_df.empty:
        lines.append("NO RESULTS (scikit-learn unavailable or no data)")
    else:
        for model in metrics_df["model"].unique():
            sub = metrics_df[metrics_df["model"] == model]
            lines.append(f"\n--- {model} ---")
            lines.append(f"  {'horizon':>8}  {'AUC_train':>10}  {'AUC_val':>10}  {'brier':>8}  {'thr':>6}  {'pass?':>6}")
            for _, r in sub.sort_values("horizon_s").iterrows():
                lines.append(
                    f"  {r['horizon_s']:>6d}s  {r['auc_train']:>10.4f}  "
                    f"{r['auc_val']:>10.4f}  {r['brier_val']:>8.4f}  "
                    f"{r['threshold']:>6.3f}  {'PASS' if r['gate_pass'] else 'fail':>6}"
                )

        passing_h = metrics_df[metrics_df["gate_pass"]==True]["horizon_s"].unique()
        verdict   = "FEASIBLE" if _gate1_verdict(metrics_df) else "NOT FEASIBLE"
        lines.append(f"\nPassing horizons: {sorted(passing_h.tolist())}  (need >= {_N_HORIZONS_NEEDED})")
        lines.append(f"\nGATE 1 VERDICT: {verdict}")

    report = "\n".join(lines)
    print(report)
    (OUT_DIR / "gate1_report.txt").write_text(report)


if __name__ == "__main__":
    run_gate1()
