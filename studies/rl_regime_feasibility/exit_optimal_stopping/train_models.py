"""
Phase 5-6: Train exit models (entry-conditioned, out-of-fold).

Models:
  M1: Remaining-opportunity regressor (remaining_mfe_atr)
  M2: Giveback regressor (max_future_giveback_atr)
  M3: Hazard classifier (hazard_terminal_60s)
  M4: Fitted-Q regressor (hold_advantage)
  M5: Exit-window classifier (inside_025atr_window)

Training protocol:
  - Train only on 'train' period checkpoints
  - Entry-conditioned: only states actually encountered after P2 entries
  - Out-of-fold validation on val period
  - Threshold selection strictly on val period
  - Freeze all thresholds before test evaluation
"""

from pathlib import Path
import json
import numpy as np
import pandas as pd
import joblib
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, mean_squared_error

BASE_DIR = Path("studies/rl_regime_feasibility")
OUT_DIR  = BASE_DIR / "exit_optimal_stopping/results"
MODEL_DIR = OUT_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Regularisation strength
LGB_PARAMS = dict(
    n_estimators=300, learning_rate=0.05, max_depth=5,
    min_child_samples=100, num_leaves=20, reg_lambda=10.0,
    colsample_bytree=0.7, subsample=0.8,
    random_state=42, n_jobs=4, verbose=-1
)


def load_data() -> tuple:
    df = pd.read_parquet(OUT_DIR / "exit_targets.parquet")
    with open(OUT_DIR / "exit_feature_contract.json") as f:
        contract = json.load(f)
    feats = [f for f in contract["features"] if f in df.columns]
    return df, feats


def train_model(X_tr, y_tr, X_va, y_va, task: str, name: str) -> tuple:
    """
    Train LightGBM + Ridge/Logistic baseline.
    Returns (lgb_model, scaler, results_dict).
    """
    scaler = StandardScaler()
    X_tr_sc = scaler.fit_transform(X_tr)
    X_va_sc = scaler.transform(X_va)

    if task == "regression":
        lgb = LGBMRegressor(**LGB_PARAMS)
        lgb.fit(X_tr, y_tr)
        pred_va = lgb.predict(X_va)

        base = Ridge(alpha=100.0)
        base.fit(X_tr_sc, y_tr)
        base_pred_va = base.predict(X_va_sc)

        mse_lgb  = mean_squared_error(y_va, pred_va)
        mse_base = mean_squared_error(y_va, base_pred_va)
        null_mse = mean_squared_error(y_va, np.full(len(y_va), y_va.mean()))

        results = {
            "model": name, "task": task,
            "lgb_val_rmse":  float(np.sqrt(mse_lgb)),
            "base_val_rmse": float(np.sqrt(mse_base)),
            "null_val_rmse": float(np.sqrt(null_mse)),
            "lgb_r2":  float(1 - mse_lgb / null_mse),
        }
        print(f"  {name}: RMSE lgb={results['lgb_val_rmse']:.4f} "
              f"base={results['base_val_rmse']:.4f} null={results['null_val_rmse']:.4f} "
              f"R2={results['lgb_r2']:.4f}")

    elif task == "classification":
        lgb = LGBMClassifier(**LGB_PARAMS)
        lgb.fit(X_tr, y_tr)
        prob_va = lgb.predict_proba(X_va)[:, 1]

        base = LogisticRegression(C=0.01, max_iter=500, random_state=42)
        base.fit(X_tr_sc, y_tr)
        base_prob_va = base.predict_proba(X_va_sc)[:, 1]

        auc_lgb  = roc_auc_score(y_va, prob_va)
        auc_base = roc_auc_score(y_va, base_prob_va)

        results = {
            "model": name, "task": task,
            "lgb_val_auc":  float(auc_lgb),
            "base_val_auc": float(auc_base),
            "positive_rate": float(y_va.mean()),
        }
        print(f"  {name}: AUC lgb={auc_lgb:.4f} base={auc_base:.4f} "
              f"pos_rate={y_va.mean():.3f}")

    return lgb, scaler, results


def select_threshold_on_val(model, scaler, X_va, df_va, target_col,
                              feature_type: str, metric: str = "ev_per_episode") -> float:
    """
    Select exit threshold on val period by maximizing EV per eligible episode.

    For exit models: exit when predicted value falls below threshold.
    - Remaining opp: exit when pred_remaining_mfe < threshold
    - Hazard: exit when pred_hazard_prob > threshold
    - Hold advantage: exit when pred_hold_advantage < threshold
    """
    if feature_type == "regression":
        preds = model.predict(X_va)
    else:
        preds = model.predict_proba(X_va)[:, 1]

    df_va = df_va.copy()
    df_va["_score"] = preds

    # For hold_advantage model: exit when score < threshold
    # For hazard: exit when score > threshold
    # For remaining_mfe: exit when score < threshold
    # We'll parametrize as: threshold is the exit trigger point
    # For all models, we'll compute EV for "hold while score passes threshold, else exit"

    n_episodes = df_va["episode_id"].nunique()
    # Just try a sweep and pick best
    # Approach: simulate exit policy on val period

    # Build episode-level simulation
    # For each episode, exit at first checkpoint where condition is met
    best_ev, best_thr = -np.inf, None

    if feature_type == "regression":
        # Exit when pred < threshold
        thresholds = np.percentile(preds, np.arange(10, 80, 5))
    else:
        # Exit when pred > threshold
        thresholds = np.arange(0.30, 0.90, 0.05)

    for thr in thresholds:
        total_pnl = _simulate_exit_policy(df_va, preds, thr, feature_type)
        ev = total_pnl / n_episodes
        if ev > best_ev:
            best_ev = ev
            best_thr = thr

    print(f"    Val threshold={best_thr:.4f}, EV/episode={best_ev:.2f}")
    return float(best_thr)


def _simulate_exit_policy(df: pd.DataFrame, scores: np.ndarray,
                            threshold: float, feature_type: str) -> float:
    """
    Simulate exit policy: exit at first checkpoint meeting exit condition.
    Returns total PnL.
    """
    df = df.copy()
    df["_score"] = scores

    # Determine exit condition
    if feature_type == "regression":
        df["_exit_signal"] = (df["_score"] < threshold).astype(int)
    else:
        df["_exit_signal"] = (df["_score"] > threshold).astype(int)

    # For each episode: find first exit signal checkpoint, or end of episode
    df = df.sort_values(["episode_id", "seconds_since_entry"])

    total_pnl = 0.0
    for ep_id, grp in df.groupby("episode_id"):
        grp = grp.sort_values("seconds_since_entry")
        signal = grp["_exit_signal"].values
        exit_rows = np.where(signal == 1)[0]

        if len(exit_rows) == 0:
            # Hold to end: use the last checkpoint's exit value
            # Approximation: use total_pnl_hold_regime or last exit_now_pnl
            if "total_pnl_hold_regime" in grp.columns:
                pnl = grp["total_pnl_hold_regime"].iloc[0]
            else:
                pnl = grp["exit_now_pnl"].iloc[-1]
        else:
            # Exit at first signal: use exit_now_pnl at that checkpoint
            # For the dynamic exit, fill at next 5s open ≈ exit_now_pnl
            exit_idx = exit_rows[0]
            pnl = grp["exit_now_pnl"].iloc[exit_idx]

        total_pnl += pnl

    return total_pnl


def main():
    print("=" * 70)
    print("Phase 5-6: Train Exit Models")
    print("=" * 70)

    df, feats = load_data()
    print(f"  Loaded: {df.shape}, {len(feats)} features")

    train_mask = df["period"] == "train"
    val_mask   = df["period"] == "val"

    X_tr = df.loc[train_mask, feats].fillna(0).values
    X_va = df.loc[val_mask,   feats].fillna(0).values

    print(f"  Train: {train_mask.sum():,} checkpoints, Val: {val_mask.sum():,}")

    manifests = []
    thresholds = {}

    # ── M1: Remaining opportunity regressor ──────────────────────────────────
    print("\nM1: Remaining opportunity (remaining_mfe_atr) ...")
    y1_tr = df.loc[train_mask, "remaining_mfe_atr"].fillna(0).values
    y1_va = df.loc[val_mask,   "remaining_mfe_atr"].fillna(0).values
    m1, sc1, r1 = train_model(X_tr, y1_tr, X_va, y1_va, "regression", "M1_remaining_opp")
    joblib.dump({"model": m1, "scaler": sc1, "feats": feats}, MODEL_DIR / "m1_remaining_opp.pkl")

    # Threshold: exit when predicted remaining_mfe < threshold
    thr1 = select_threshold_on_val(m1, sc1, X_va, df[val_mask], "remaining_mfe_atr", "regression")
    thresholds["m1_remaining_opp"] = thr1
    manifests.append(r1)

    # ── M2: Giveback regressor ────────────────────────────────────────────────
    print("\nM2: Expected giveback (max_future_giveback_atr) ...")
    y2_tr = df.loc[train_mask, "max_future_giveback_atr"].fillna(0).values
    y2_va = df.loc[val_mask,   "max_future_giveback_atr"].fillna(0).values
    m2, sc2, r2 = train_model(X_tr, y2_tr, X_va, y2_va, "regression", "M2_giveback")
    joblib.dump({"model": m2, "scaler": sc2, "feats": feats}, MODEL_DIR / "m2_giveback.pkl")
    manifests.append(r2)

    # ── M3: Hazard classifier ─────────────────────────────────────────────────
    print("\nM3: Terminal hazard (hazard_terminal_60s) ...")
    y3_tr = df.loc[train_mask, "hazard_terminal_60s"].fillna(0).values
    y3_va = df.loc[val_mask,   "hazard_terminal_60s"].fillna(0).values
    m3, sc3, r3 = train_model(X_tr, y3_tr, X_va, y3_va, "classification", "M3_hazard")
    joblib.dump({"model": m3, "scaler": sc3, "feats": feats}, MODEL_DIR / "m3_hazard.pkl")

    thr3 = select_threshold_on_val(m3, sc3, X_va, df[val_mask], "hazard_terminal_60s", "classification")
    thresholds["m3_hazard"] = thr3
    manifests.append(r3)

    # ── M4: Fitted-Q regressor ────────────────────────────────────────────────
    print("\nM4: Fitted-Q (hold_advantage) ...")
    y4_tr = df.loc[train_mask, "hold_advantage"].fillna(0).values
    y4_va = df.loc[val_mask,   "hold_advantage"].fillna(0).values
    m4, sc4, r4 = train_model(X_tr, y4_tr, X_va, y4_va, "regression", "M4_fitted_q")
    joblib.dump({"model": m4, "scaler": sc4, "feats": feats}, MODEL_DIR / "m4_fitted_q.pkl")

    # Threshold: exit when predicted hold_advantage < threshold (0 = prefer to exit)
    thr4 = select_threshold_on_val(m4, sc4, X_va, df[val_mask], "hold_advantage", "regression")
    thresholds["m4_fitted_q"] = thr4
    manifests.append(r4)

    # ── M5: Exit-window classifier ────────────────────────────────────────────
    print("\nM5: Exit-window membership (inside_025atr_window) ...")
    y5_tr = df.loc[train_mask, "inside_025atr_window"].fillna(0).values
    y5_va = df.loc[val_mask,   "inside_025atr_window"].fillna(0).values
    m5, sc5, r5 = train_model(X_tr, y5_tr, X_va, y5_va, "classification", "M5_exit_window")
    joblib.dump({"model": m5, "scaler": sc5, "feats": feats}, MODEL_DIR / "m5_exit_window.pkl")
    manifests.append(r5)

    # ── Save manifests ────────────────────────────────────────────────────────
    for_json = {
        "models": manifests,
        "features": feats,
        "n_features": len(feats),
        "train_checkpoints": int(train_mask.sum()),
        "val_checkpoints":   int(val_mask.sum()),
    }
    with open(OUT_DIR / "remaining_value_model_manifest.json", "w") as f:
        json.dump(for_json, f, indent=2, default=float)

    with open(OUT_DIR / "hazard_model_manifest.json", "w") as f:
        json.dump({"hazard": r3, "threshold": thr3}, f, indent=2, default=float)

    with open(OUT_DIR / "fitted_q_model_manifest.json", "w") as f:
        json.dump({"fitted_q": r4, "threshold": thr4}, f, indent=2, default=float)

    # Save frozen thresholds
    with open(OUT_DIR / "policy_thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=2)

    print("\nModel summary:")
    for r in manifests:
        if "lgb_val_rmse" in r:
            print(f"  {r['model']}: RMSE={r['lgb_val_rmse']:.4f} (null={r['null_val_rmse']:.4f}) R2={r['lgb_r2']:.4f}")
        elif "lgb_val_auc" in r:
            print(f"  {r['model']}: AUC={r['lgb_val_auc']:.4f}")

    print(f"\nFrozen thresholds: {thresholds}")
    print("\nPhase 5-6 complete.")


if __name__ == "__main__":
    main()
