"""Phase 2 orchestrator — train LightGBM on good_entry_300s, OOS=2025."""

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
from train_phase2 import (
    load_model_feature_names, select_feature_cols, make_splits,
    train_lgbm,
)
from report_phase2 import write_phase2_report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort",
                     default="studies/good_entry_v2/results/"
                              "cohort_long.parquet",
                     help="Phase 1 cohort parquet")
    ap.add_argument("--contract",
                     default="models/ml_5m_flip/feature_contract_v2.json")
    ap.add_argument("--out-dir",
                     default="studies/good_entry_v2/results")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("GOOD ENTRY v2 — PHASE 2 (LightGBM, OOS=2025)")
    print("=" * 72)

    t0 = time.time()
    print(f"  Loading cohort: {args.cohort}")
    cohort = pd.read_parquet(args.cohort)
    print(f"    {len(cohort):,} rows; "
           f"{cohort['event_id'].nunique():,} events; "
           f"years {sorted(cohort['year'].unique())}")

    # Filter to fillable rows only — unfillable can't be entered
    n_pre = len(cohort)
    cohort = cohort[cohort["fillable_at_T"] == True].copy()
    print(f"  Filtered to fillable: "
           f"{len(cohort):,} (dropped {n_pre - len(cohort):,})")

    # Select features
    print(f"  Loading model_feature names from contract...")
    model_feats = load_model_feature_names(Path(args.contract))
    feat_cols = select_feature_cols(cohort, model_feats)
    print(f"    Contract features: {len(model_feats)}; "
           f"present + numeric: {len(feat_cols)}")

    # Splits
    splits = make_splits(cohort)
    train = splits["train"]
    val = splits["val"]
    oos = splits["oos"]
    print(f"  Train: {len(train):,} rows ({len(train)/len(cohort)*100:.1f}%)")
    print(f"  Val:   {len(val):,} rows ({len(val)/len(cohort)*100:.1f}%)")
    print(f"  OOS:   {len(oos):,} rows ({len(oos)/len(cohort)*100:.1f}%)")
    print(f"  Train base rate: {train['good_entry_300s'].mean():.4f}")
    print(f"  Val base rate:   {val['good_entry_300s'].mean():.4f}")
    print(f"  OOS base rate:   {oos['good_entry_300s'].mean():.4f}")

    # Train
    print(f"\n  Training LightGBM...", flush=True)
    t1 = time.time()
    model = train_lgbm(
        train[feat_cols], train["good_entry_300s"],
        val[feat_cols], val["good_entry_300s"],
        seed=args.seed,
    )
    print(f"  Trained in {time.time() - t1:.1f}s; "
           f"best_iter={model.best_iteration}")

    # Score OOS
    print(f"\n  Scoring OOS...", flush=True)
    oos = oos.copy()
    oos["score"] = model.predict(oos[feat_cols],
                                    num_iteration=model.best_iteration)

    # Save predictions
    pred_cols = ["event_id", "checkpoint_s", "year", "score",
                  "good_entry_300s", "regime_exit_pnl_dollars",
                  "pt100_before_sl100", "is_rth_checkpoint",
                  "signal_direction"]
    oos[pred_cols].to_parquet(out_dir / "phase2_oos_predictions.parquet",
                                 index=False)

    # Save model
    model.save_model(str(out_dir / "phase2_model.txt"))

    # Save feature importance
    imp = pd.DataFrame({
        "feature": feat_cols,
        "gain": model.feature_importance(importance_type="gain"),
        "split": model.feature_importance(importance_type="split"),
    }).sort_values("gain", ascending=False)
    imp.to_parquet(out_dir / "phase2_feature_importance.parquet",
                     index=False)

    # Write report
    print(f"\n  Writing report...")
    report_path = out_dir / "PHASE2_REPORT.md"
    write_phase2_report(train, val, oos, feat_cols, model, report_path)

    print(f"\n  Done in {time.time() - t0:.1f}s")
    print(f"  Report:    {report_path}")
    print(f"  Predictions: {out_dir / 'phase2_oos_predictions.parquet'}")
    print(f"  Model:     {out_dir / 'phase2_model.txt'}")


if __name__ == "__main__":
    main()
