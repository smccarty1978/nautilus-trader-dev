"""Rolling retraining + fold-internal threshold selection for the adaptive
rank filter (A1/A2/A4 x 3m/6m/12m).

For every fold (window_size, deploy_month):
  1. train  = F2 episodes in the trailing window, PURGED of any episode whose
              terminal outcome (ep_end_time) resolves after the train window
              ends (leakage control).
  2. fit a ridge-logistic score on train only (train-median impute + scaler,
     same recipe as train_flip_filter.py). No new features.
  3. validate = the single prior month, PURGED the same way against the
     validation window's own end.
  4. score validate with the train-fit model; for each candidate skip rate in
     {5%,10%,15%}, take the validation-percentile score threshold and measure
     the EV lift from skipping (retained EV vs. all-eligible EV) on
     validation only. Freeze the threshold of the best-lift candidate.
  5. freeze ATR bucket edges (terciles) on validation's atr column.
  6. score the deployment month (NOT purged -- these are the actual episodes
     being traded) with the SAME train-fit model, apply the FROZEN numeric
     threshold (not a recomputed deployment-month percentile), assign the
     frozen ATR buckets, and derive A1 (pure score skip), A2 (+ R2-style
     exemption), A4 (+ R4-style exemption) skip decisions.

Nothing here ever uses deployment-month outcomes for fitting, thresholding,
or bucketing.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c


def ev_lift(df_val: pd.DataFrame, score: np.ndarray, threshold: float) -> dict:
    """EV/eligible-signal lift on validation from skipping score >= threshold."""
    filled = df_val["trade_status"] == "filled"
    pnl = np.where(filled, df_val["baseline_pnl"].values, 0.0)
    n_all = len(df_val)
    ev_all = pnl.sum() / n_all if n_all > 0 else 0.0

    keep = score < threshold
    n_keep = int(keep.sum())
    ev_keep = pnl[keep].sum() / n_keep if n_keep > 0 else 0.0
    return {"n_eligible": n_all, "n_retained": n_keep, "skip_rate_actual": 1 - n_keep / n_all if n_all else 0.0,
            "ev_per_eligible_all": ev_all, "ev_per_eligible_retained": ev_keep, "ev_lift": ev_keep - ev_all}


def run_fold(f2: pd.DataFrame, fold_row: pd.Series) -> dict:
    train_end_ts = pd.Timestamp(fold_row["train_end_ts"], tz="UTC")
    val_end_ts = pd.Timestamp(fold_row["val_end_ts"], tz="UTC")

    train_mask = (f2["observation_time"] >= fold_row["train_start_ts"]) & (f2["observation_time"] <= fold_row["train_end_ts"])
    val_mask = (f2["observation_time"] >= fold_row["val_start_ts"]) & (f2["observation_time"] <= fold_row["val_end_ts"])
    deploy_mask = (f2["observation_time"] >= fold_row["deploy_start_ts"]) & (f2["observation_time"] <= fold_row["deploy_end_ts"])

    train_raw = f2[train_mask]
    val_raw = f2[val_mask]
    deploy = f2[deploy_mask].copy()

    train = c.purge_straddling(train_raw, train_end_ts)
    val = c.purge_straddling(val_raw, val_end_ts)

    n_train_raw, n_train_purged = len(train_raw), len(train)
    n_val_raw, n_val_purged = len(val_raw), len(val)

    training_audit_row = {
        "window_name": fold_row["window_name"], "deploy_month": fold_row["deploy_month"],
        "val_month": fold_row["val_month"], "train_start_month": fold_row["train_start_month"],
        "train_end_month": fold_row["train_end_month"],
        "n_train_raw": n_train_raw, "n_train_purged": n_train_purged,
        "n_train_purged_dropped": n_train_raw - n_train_purged,
        "n_val_raw": n_val_raw, "n_val_purged": n_val_purged,
        "n_val_purged_dropped": n_val_raw - n_val_purged,
        "n_deploy": int(deploy_mask.sum()),
    }

    if n_train_purged < 50 or n_val_purged < 10:
        training_audit_row.update({"status": "insufficient_data", "val_auc": None})
        return {"training_audit": training_audit_row, "threshold_rows": [], "deploy_scores": pd.DataFrame()}

    pipe, medians = c.fit_ridge_logistic(train)
    val_score = c.score_with(pipe, medians, val)

    from sklearn.metrics import roc_auc_score
    y_val = (val["outcome_class"] == "EARLY_ROTATIONAL_FAILURE").astype(int).values
    val_auc = roc_auc_score(y_val, val_score) if y_val.sum() > 0 and y_val.sum() < len(y_val) else None
    training_audit_row.update({"status": "ok", "val_auc": val_auc})

    # --- threshold selection: validation only ---
    threshold_rows = []
    best = None
    for rate in c.CANDIDATE_SKIP_RATES:
        thr = float(np.quantile(val_score, 1 - rate))
        stats = ev_lift(val, val_score, thr)
        row = {"window_name": fold_row["window_name"], "deploy_month": fold_row["deploy_month"],
               "candidate_skip_rate": rate, "threshold_value": thr, **stats}
        threshold_rows.append(row)
        if best is None or stats["ev_lift"] > best["ev_lift"]:
            best = {**row, "_thr": thr}

    frozen_threshold = best["_thr"]
    frozen_skip_rate = best["candidate_skip_rate"]
    for row in threshold_rows:
        row["selected"] = (row["candidate_skip_rate"] == frozen_skip_rate)

    # freeze ATR bucket edges on validation (terciles)
    atr_edges = np.quantile(val["atr"].values, [1 / 3, 2 / 3])

    # --- apply frozen threshold/edges to the deployment month ---
    deploy_score = c.score_with(pipe, medians, deploy) if len(deploy) else np.array([])
    deploy["adaptive_score"] = deploy_score
    deploy["frozen_threshold"] = frozen_threshold
    deploy["frozen_skip_rate"] = frozen_skip_rate
    deploy["window_name"] = fold_row["window_name"]
    deploy["atr_bucket"] = np.digitize(deploy["atr"].values, atr_edges) if len(deploy) else []

    score_skip = deploy["adaptive_score"] >= frozen_threshold
    r2_exempt = deploy[c.R2_EXEMPT_COL] > c.R2_EXEMPT_THR
    r4_exempt = deploy[c.R4_EXEMPT_COL] > c.R4_EXEMPT_THR
    deploy["a1_skip"] = score_skip
    deploy["a2_skip"] = score_skip & ~r2_exempt
    deploy["a4_skip"] = score_skip & ~r4_exempt

    keep_cols = ["episode_id", "confirmation_ts", "decision_ts", "observation_time", "direction", "session", "month",
                 "atr", "atr_bucket", "trade_status", "baseline_pnl", "window_name", "adaptive_score",
                 "frozen_threshold", "frozen_skip_rate", "a1_skip", "a2_skip", "a4_skip"]
    deploy_scores = deploy[keep_cols].copy()
    deploy_scores["deploy_month"] = fold_row["deploy_month"]

    return {"training_audit": training_audit_row, "threshold_rows": threshold_rows, "deploy_scores": deploy_scores}


def main():
    f2 = c.load_f2_atlas()
    folds = pd.read_parquet(c.OUT / "fold_definitions.parquet")

    training_audit_rows = []
    threshold_rows_all = []
    deploy_scores_all = []

    for i, fold_row in folds.iterrows():
        result = run_fold(f2, fold_row)
        training_audit_rows.append(result["training_audit"])
        threshold_rows_all.extend(result["threshold_rows"])
        if len(result["deploy_scores"]):
            deploy_scores_all.append(result["deploy_scores"])
        if (i + 1) % 12 == 0:
            print(f"  ... {i + 1}/{len(folds)} folds done", flush=True)

    training_audit = pd.DataFrame(training_audit_rows)
    threshold_audit = pd.DataFrame(threshold_rows_all)
    deploy_scores = pd.concat(deploy_scores_all, ignore_index=True) if deploy_scores_all else pd.DataFrame()

    training_audit.to_parquet(c.OUT / "model_training_audit.parquet", index=False)
    threshold_audit.to_parquet(c.OUT / "threshold_selection_audit.parquet", index=False)

    work_dir = c.OUT.parent / "_work"
    work_dir.mkdir(exist_ok=True)
    deploy_scores.to_parquet(work_dir / "adaptive_skip_decisions.parquet", index=False)

    print(f"model_training_audit: {len(training_audit)} rows, "
          f"{(training_audit['status'] == 'insufficient_data').sum()} insufficient-data folds")
    print(f"threshold_selection_audit: {len(threshold_audit)} rows")
    print(f"deploy_scores: {len(deploy_scores)} episodes across all folds")
    print("Per-window selected skip rate distribution:")
    print(threshold_audit[threshold_audit["selected"]].groupby("window_name")["candidate_skip_rate"].value_counts())


if __name__ == "__main__":
    main()
