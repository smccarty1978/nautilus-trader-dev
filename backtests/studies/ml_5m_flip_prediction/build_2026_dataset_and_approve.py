"""Build 2026 ML dataset from trades_2026.parquet (the v3 collector output),
predict with the saved model (trained 2020-2024, val 2025), generate
approved list (bottom 50%), all in one shot.

Output:
  approved_signals_2026_bottom_50.parquet
"""

import sys
import os
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
import lightgbm as lgb

TRADES_2026_PATH = ("studies/1m_delayed_checkpoint_context/results/"
                     "trades_2026.parquet")
MODEL_PATH = "models/ml_5m_flip/model_2026.txt"
FEAT_COLS_PATH = "models/ml_5m_flip/feature_cols_2026.json"
THR_PATH = "models/ml_5m_flip/threshold_2026.json"
OUT_DIR = Path("studies/ml_5m_flip_prediction/results")


def main():
    # Reuse the dataset build code by importing build_dataset's helpers
    sys.path.insert(0, str(Path("studies/ml_5m_flip_prediction")))
    from build_dataset import (
        build_decision_rows, ROOT_FEATURES, CP_FEATURE_STEMS,
        METADATA_COLS, HORIZONS, CHECKPOINTS,
    )

    print("Loading trades_2026...")
    df = pd.read_parquet(TRADES_2026_PATH)
    df = df.drop_duplicates(subset=["signal_ts"], keep="first")
    print(f"  {len(df):,} confirmed signals")

    # Build only T_d=0 rows for 2026
    print("Building T_d=0 decision rows...")
    rows = build_decision_rows(df, 0)
    print(f"  {len(rows):,} eligible T_d=0 rows")

    # Filter to RTH
    rows_rth = rows[rows["is_rth"] == 1].copy()
    # Add event_id
    rows_rth["event_id"] = rows_rth["signal_ts"].values
    print(f"  RTH only: {len(rows_rth):,}")

    # Load model + feature cols + threshold
    print("Loading model...")
    model = lgb.Booster(model_file=MODEL_PATH)
    with open(FEAT_COLS_PATH) as f:
        feat_cols = json.load(f)
    with open(THR_PATH) as f:
        thr_data = json.load(f)
    threshold = thr_data["bottom_50"]
    print(f"  features: {len(feat_cols)}, threshold: {threshold:.4f}")

    # Verify all feature cols are in rows_rth (add NaN for missing)
    missing = [c for c in feat_cols if c not in rows_rth.columns]
    if missing:
        print(f"  WARN: missing features in rows: {missing}")
        for c in missing:
            rows_rth[c] = np.nan

    # Predict
    X = rows_rth[feat_cols].values
    rows_rth["pred"] = model.predict(X)
    print(f"  Pred distribution:")
    print(f"    min:    {rows_rth['pred'].min():.4f}")
    print(f"    p25:    {rows_rth['pred'].quantile(0.25):.4f}")
    print(f"    median: {rows_rth['pred'].median():.4f}")
    print(f"    p75:    {rows_rth['pred'].quantile(0.75):.4f}")
    print(f"    max:    {rows_rth['pred'].max():.4f}")
    print(f"  % below threshold ({threshold:.4f}): "
          f"{(rows_rth['pred'] <= threshold).mean()*100:.1f}%")

    # Approved list = bottom 50% by pred (relative to this year's distribution)
    # Two options:
    #   A. Use the saved threshold (cross-year fixed)
    #   B. Use 2026 median (year-relative)
    # The walk-forward used year-relative (option B). Match that.
    yr_thr = rows_rth["pred"].quantile(0.50)
    print(f"\n  2026 median threshold (year-relative): {yr_thr:.4f}")
    approved = rows_rth[rows_rth["pred"] <= yr_thr][
        ["event_id", "pred"]].copy()
    out = OUT_DIR / "approved_signals_2026_bottom_50.parquet"
    approved.to_parquet(out, index=False)
    print(f"  approved N: {len(approved):,}")
    print(f"  saved: {out}")

    # Also save full predictions
    rows_rth[["event_id", "pred"]].to_parquet(
        OUT_DIR / "preds_2026_walk_forward.parquet", index=False)


if __name__ == "__main__":
    main()
