"""For each parity event_id, export the offline feature row + offline
model score to a parquet file. This is the 'ground truth' that the NT
runtime feature row must match.

Output:
  parity_offline_features_2025.parquet
"""

import sys
import os
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
import lightgbm as lgb

DS_PATH = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
EVENT_IDS_PATH = ("studies/ml_5m_flip_prediction/parity/"
                   "parity_event_ids_2025.json")
MODEL_PATH = "models/ml_5m_flip/model_2026.txt"
FEAT_COLS_PATH = "models/ml_5m_flip/feature_cols_2026.json"
THR_PATH = "models/ml_5m_flip/threshold_2026.json"

OUT_DIR = Path("studies/ml_5m_flip_prediction/parity")
OUT_PARQUET = OUT_DIR / "parity_offline_features_2025.parquet"


def main():
    with open(EVENT_IDS_PATH) as f:
        sel = json.load(f)
    event_ids = sel["event_ids"]
    print(f"Loading {len(event_ids):,} event ids for parity")

    print("Loading dataset...")
    ds = pd.read_parquet(DS_PATH)
    sub = ds[
        (ds["event_id"].isin(event_ids))
        & (ds["decision_checkpoint_s"] == 0)
        & (ds["is_rth"] == 1)
    ].copy()
    print(f"  Matched dataset rows: {len(sub):,}")

    if len(sub) != len(event_ids):
        missing = set(event_ids) - set(sub["event_id"].astype(int).values)
        print(f"  WARN: {len(missing)} event_ids not found in dataset:")
        for m in list(missing)[:5]:
            print(f"    {m}")

    # Load model and feature cols
    print("Loading model...")
    model = lgb.Booster(model_file=MODEL_PATH)
    with open(FEAT_COLS_PATH) as f:
        feat_cols = json.load(f)
    with open(THR_PATH) as f:
        thr = json.load(f)["bottom_50"]
    print(f"  threshold: {thr:.6f}")

    # Predict
    X = sub[feat_cols].values
    sub["offline_pred"] = model.predict(X)
    sub["offline_decision"] = (sub["offline_pred"] <= thr).astype(int)

    # Build output: event_id + all feature columns + score + decision
    # decision_checkpoint_s and is_rth are already in feat_cols metadata-side
    meta_cols = ["event_id", "signal_ts", "signal_time", "year"]
    # Avoid duplicate columns: remove anything from meta that's in feat_cols
    meta_cols = [c for c in meta_cols if c not in feat_cols]
    out_cols = meta_cols + feat_cols + ["offline_pred", "offline_decision"]
    out = sub[out_cols].copy()
    # Sort by event_id for deterministic ordering
    out = out.sort_values("event_id").reset_index(drop=True)

    out.to_parquet(OUT_PARQUET, index=False)
    print(f"\n  Saved: {OUT_PARQUET}")
    print(f"  Rows: {len(out):,}, cols: {len(out.columns):,}")
    # Show distribution
    print(f"\n  Score distribution: min={out['offline_pred'].min():.4f} "
          f"median={out['offline_pred'].median():.4f} "
          f"max={out['offline_pred'].max():.4f}")
    print(f"  Decisions: {out['offline_decision'].sum()} approved, "
          f"{(out['offline_decision'] == 0).sum()} rejected")


if __name__ == "__main__":
    main()
