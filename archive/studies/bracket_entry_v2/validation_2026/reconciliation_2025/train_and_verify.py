"""Reproduce the feature_reduction top_15 model for 2025 OOS.

Splits: Train=2020-2023, Val=2024 (matches sweep.py).
Saves: model_top15_2025oos.txt + feature_list.json + threshold.json

Then verifies that re-scoring val 2024 + OOS 2025 with this fresh
model produces scores identical to those in
studies/bracket_entry_v2/feature_reduction/predictions_2025_top_15.parquet.

If score parity holds (within 1e-12), the model is bit-identical to
the one used in the feature_reduction sweep. The LiveBracketStrategy
can use this model to compare against the sweep's saved predictions.
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
import time

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0,
    str(project_root / "studies/bracket_entry_v2/feature_reduction"))
from sweep import train_lgbm  # noqa

OUT_DIR = Path(
    "studies/bracket_entry_v2/validation_2026/reconciliation_2025")
OUT_DIR.mkdir(parents=True, exist_ok=True)

COHORT = "studies/bracket_entry_v2/results/cohort_long.parquet"
FEATURE_IMP = "studies/bracket_entry_v2/results/feature_importance.parquet"
REF_PREDICTIONS = (
    "studies/bracket_entry_v2/feature_reduction/"
    "predictions_2025_top_15.parquet")


def main():
    cohort = pd.read_parquet(COHORT)
    imp = pd.read_parquet(FEATURE_IMP).sort_values(
        "gain", ascending=False)
    feat_cols = [c for c in imp.head(15)["feature"].tolist()
                  if c in cohort.columns]
    print(f"Top-15 features: {feat_cols}")

    r = cohort[cohort["resolved"] == 1]
    tr = r[r["year"].isin([2020, 2021, 2022, 2023])]
    va = r[r["year"] == 2024]
    oos = r[r["year"] == 2025]
    print(f"\nTr {len(tr):,} / Val {len(va):,} / OOS {len(oos):,}")

    t0 = time.time()
    model = train_lgbm(tr[feat_cols], tr["good_bracket_entry"],
                        va[feat_cols], va["good_bracket_entry"])
    print(f"Trained in {time.time() - t0:.1f}s, "
           f"best_iter={model.best_iteration}")

    # Score OOS 2025
    oos = oos.copy()
    oos["score_fresh"] = model.predict(
        oos[feat_cols], num_iteration=model.best_iteration)

    # Compare against reference
    ref = pd.read_parquet(REF_PREDICTIONS)[
        ["event_id", "checkpoint_s", "score"]]
    merged = oos.merge(
        ref.rename(columns={"score": "score_ref"}),
        on=["event_id", "checkpoint_s"], how="inner")
    print(f"\nMatched rows: {len(merged):,} "
           f"(fresh OOS {len(oos):,} vs ref {len(ref):,})")

    diff = (merged["score_fresh"] - merged["score_ref"]).abs()
    max_abs = diff.max()
    mean_abs = diff.mean()
    print(f"Score diff: max={max_abs:.2e}  mean={mean_abs:.2e}")
    n_exact = int((diff < 1e-12).sum())
    print(f"Exact matches (diff < 1e-12): {n_exact} / {len(merged)}")

    val_scores = model.predict(va[feat_cols],
                                 num_iteration=model.best_iteration)
    threshold = float(pd.Series(val_scores).quantile(0.90))
    print(f"\nThreshold (val 2024 top-10%): {threshold:.6f}")

    # Save
    model_path = OUT_DIR / "model_top15_2025oos.txt"
    model.save_model(str(model_path))
    with open(OUT_DIR / "feature_list.json", "w") as f:
        json.dump({"features": feat_cols,
                    "n_features": len(feat_cols)}, f, indent=2)
    with open(OUT_DIR / "score_threshold.json", "w") as f:
        json.dump({
            "threshold_top10": threshold,
            "derived_from": "val_2024_quantile_0.90",
            "best_iter": int(model.best_iteration),
            "splits": {"train": "2020-2023", "val": "2024"},
            "parity": {
                "ref_predictions": REF_PREDICTIONS,
                "max_abs_score_diff": float(max_abs),
                "mean_abs_score_diff": float(mean_abs),
                "n_exact_matches": n_exact,
                "n_total": len(merged),
            },
        }, f, indent=2)
    print(f"\nSaved: {model_path}")
    print(f"Features: {OUT_DIR / 'feature_list.json'}")
    print(f"Threshold: {OUT_DIR / 'score_threshold.json'}")


if __name__ == "__main__":
    main()
