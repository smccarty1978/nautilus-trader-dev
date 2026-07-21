"""Phase 3 orchestrator — RTH-only LightGBM regression on
regime_exit_pnl_atr."""

from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from train_phase2 import load_model_feature_names, select_feature_cols
from train_phase3 import make_rth_splits, train_lgbm_regression
from report_phase3 import write_phase3_report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort",
                     default="studies/good_entry_v2/results/"
                              "cohort_long.parquet")
    ap.add_argument("--contract",
                     default="models/ml_5m_flip/feature_contract_v2.json")
    ap.add_argument("--out-dir",
                     default="studies/good_entry_v2/results")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--loss", choices=["l2", "huber"], default="l2",
                     help="Regression loss: l2 (default) or huber "
                           "(falsification check for L2 outlier collapse)")
    ap.add_argument("--huber-alpha", type=float, default=0.9)
    ap.add_argument("--out-suffix", default="",
                     help="Suffix for output files (e.g., '_huber') to "
                           "avoid overwriting prior runs")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("GOOD ENTRY v2 — PHASE 3 (RTH-only regression, OOS=2025)")
    print("=" * 72)

    t0 = time.time()
    print(f"  Loading cohort: {args.cohort}")
    cohort = pd.read_parquet(args.cohort)
    print(f"    {len(cohort):,} total rows, "
           f"{cohort['event_id'].nunique():,} events")

    # Filter to fillable
    n_pre = len(cohort)
    cohort = cohort[cohort["fillable_at_T"] == True].copy()
    print(f"  Filtered to fillable: {len(cohort):,} "
           f"(dropped {n_pre - len(cohort):,})")

    # RTH-only splits
    splits = make_rth_splits(cohort)
    train, val, oos = splits["train"], splits["val"], splits["oos"]
    print(f"  RTH train: {len(train):,} rows from "
           f"{train['event_id'].nunique():,} events (2020-2023)")
    print(f"  RTH val:   {len(val):,} rows from "
           f"{val['event_id'].nunique():,} events (2024)")
    print(f"  RTH OOS:   {len(oos):,} rows from "
           f"{oos['event_id'].nunique():,} events (2025)")

    # Drop rows with NaN target
    for name, df in [("train", train), ("val", val), ("oos", oos)]:
        n = df["regime_exit_pnl_atr"].isna().sum()
        if n > 0:
            print(f"  WARN: {name} has {n} NaN regime_exit_pnl_atr")

    # Features
    model_feats = load_model_feature_names(Path(args.contract))
    feat_cols = select_feature_cols(cohort, model_feats)
    print(f"  Features: {len(feat_cols)} (model_feature × numeric)")

    # Target stats sanity
    print(f"  RTH train regime_exit_pnl_atr: "
           f"mean={train['regime_exit_pnl_atr'].mean():.4f} "
           f"median={train['regime_exit_pnl_atr'].median():.4f} "
           f"std={train['regime_exit_pnl_atr'].std():.4f}")

    loss_label = ("Huber (alpha=" + str(args.huber_alpha) + ")"
                   if args.loss == "huber" else "L2 (MSE)")
    print(f"\n  Training LightGBM regression ({loss_label})...",
           flush=True)
    t1 = time.time()
    train_clean = train.dropna(subset=["regime_exit_pnl_atr"])
    val_clean = val.dropna(subset=["regime_exit_pnl_atr"])
    model = train_lgbm_regression(
        train_clean[feat_cols], train_clean["regime_exit_pnl_atr"],
        val_clean[feat_cols], val_clean["regime_exit_pnl_atr"],
        seed=args.seed,
        loss=args.loss,
        huber_alpha=args.huber_alpha,
    )
    print(f"  Trained in {time.time() - t1:.1f}s; "
           f"best_iter={model.best_iteration}")

    print(f"\n  Scoring OOS (RTH 2025)...", flush=True)
    oos = oos.copy()
    oos["score"] = model.predict(oos[feat_cols],
                                    num_iteration=model.best_iteration)

    # Save predictions + model
    pred_cols = ["event_id", "checkpoint_s", "year", "score",
                  "regime_exit_pnl_atr", "regime_exit_pnl_dollars",
                  "good_entry_300s", "pt100_before_sl100",
                  "is_rth_checkpoint", "signal_direction",
                  "fill_time_actual", "atr_at_signal"]
    pred_cols = [c for c in pred_cols if c in oos.columns]
    suf = args.out_suffix
    oos[pred_cols].to_parquet(
        out_dir / f"phase3_oos_predictions{suf}.parquet", index=False)
    model.save_model(str(out_dir / f"phase3_model{suf}.txt"))

    # Feature importance
    imp = pd.DataFrame({
        "feature": feat_cols,
        "gain": model.feature_importance(importance_type="gain"),
        "split": model.feature_importance(importance_type="split"),
    }).sort_values("gain", ascending=False)
    imp.to_parquet(out_dir / f"phase3_feature_importance{suf}.parquet",
                     index=False)

    # Report
    print(f"\n  Writing report...")
    report_path = out_dir / f"PHASE3_REPORT{suf}.md"
    write_phase3_report(train, val, oos, feat_cols, model, report_path)

    print(f"\n  Done in {time.time() - t0:.1f}s")
    print(f"  Report:    {report_path}")
    print(f"  Predictions: {out_dir / 'phase3_oos_predictions.parquet'}")
    print(f"  Model:     {out_dir / 'phase3_model.txt'}")


if __name__ == "__main__":
    main()
