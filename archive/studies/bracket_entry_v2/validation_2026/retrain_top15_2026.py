"""Retrain top_15 model with Train=2020-2024, Val=2025, save model.

Saves:
  - model_top15_v2026.txt   (frozen LightGBM model for live strategy)
  - feature_list.json       (15 feature names in order)
  - score_threshold.json    (2025 top-10% threshold for live gating)
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
import time

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, str(project_root / "studies/bracket_entry_v2/feature_reduction"))
from sweep import train_lgbm  # noqa

OUT_DIR = Path("studies/bracket_entry_v2/validation_2026")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    cohort = pd.read_parquet(
        "studies/bracket_entry_v2/results/cohort_long.parquet")
    imp = pd.read_parquet(
        "studies/bracket_entry_v2/results/feature_importance.parquet")
    imp = imp.sort_values("gain", ascending=False)
    feat_cols = [c for c in imp.head(15)["feature"].tolist()
                  if c in cohort.columns]
    print(f"Top-15 features ({len(feat_cols)}):")
    for i, f in enumerate(feat_cols, 1):
        print(f"  {i:>2}. {f}")

    r = cohort[cohort["resolved"] == 1]
    tr = r[r["year"].isin([2020, 2021, 2022, 2023, 2024])]
    va = r[r["year"] == 2025]
    print(f"\nSplits: train={len(tr):,} (2020-2024), "
           f"val={len(va):,} (2025)")

    t0 = time.time()
    model = train_lgbm(tr[feat_cols], tr["good_bracket_entry"],
                         va[feat_cols], va["good_bracket_entry"])
    print(f"Trained in {time.time() - t0:.1f}s "
           f"(best_iter={model.best_iteration})")

    # Score val 2025 to extract top-10% threshold
    va_scored = va.copy()
    va_scored["score"] = model.predict(
        va[feat_cols], num_iteration=model.best_iteration)
    threshold_top10 = float(va_scored["score"].quantile(0.90))
    print(f"Val 2025 top-10% score threshold: {threshold_top10:.4f}")

    # Save artifacts
    model_path = OUT_DIR / "model_top15_v2026.txt"
    model.save_model(str(model_path))
    print(f"Model saved: {model_path}")

    with open(OUT_DIR / "feature_list.json", "w") as f:
        json.dump({"features": feat_cols,
                    "n_features": len(feat_cols)}, f, indent=2)

    with open(OUT_DIR / "score_threshold.json", "w") as f:
        json.dump({
            "threshold_top10": threshold_top10,
            "derived_from": "val_2025_quantile_0.90",
            "best_iter": int(model.best_iteration),
            "splits": {
                "train": "2020-2024",
                "val": "2025",
            },
        }, f, indent=2)
    print(f"Threshold saved: {threshold_top10:.4f}")

    # Quick sanity on val
    from sklearn.metrics import roc_auc_score, average_precision_score
    y = va["good_bracket_entry"].values
    s = va_scored["score"].values
    auc = roc_auc_score(y, s)
    pr_auc = average_precision_score(y, s)
    print(f"Val 2025 AUC: {auc:.4f}  PR-AUC: {pr_auc:.4f}  "
           f"base={y.mean():.4f}")


if __name__ == "__main__":
    main()
