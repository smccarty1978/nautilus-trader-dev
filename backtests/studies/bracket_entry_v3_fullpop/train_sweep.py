"""Train sweep for v3 — 7 feature counts × 2 OOS year splits.

For each OOS year:
  1. Train FULL model with appropriate split, save its gain importance
  2. For each of {full, top_50, top_35, top_25, top_20, top_15, top_10}:
     - Train LightGBM binary on `is_pt_first`
     - Score val + OOS, compute top-10% threshold from val scores
     - Save model.txt + feature_list.json + threshold.json
     - Save OOS predictions parquet
"""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
)

sys.path.insert(0,
                 str(project_root / "studies/bracket_entry_v2/feature_reduction"))
from sweep import train_lgbm  # noqa

ROOT = Path("studies/bracket_entry_v3_fullpop/results")
COHORT = ROOT / "cohort_v3.parquet"
CONTRACT = "models/ml_5m_flip/feature_contract_v2.json"

ITERATIONS = ["full", "top_50", "top_35", "top_25", "top_20",
              "top_15", "top_10"]
ITER_K = {"full": None, "top_50": 50, "top_35": 35, "top_25": 25,
          "top_20": 20, "top_15": 15, "top_10": 10}

# OOS year → (train_years, val_year, oos_year)
OOS_SPLITS = {
    2024: ([2020, 2021, 2022], 2023, 2024),
    2026: ([2020, 2021, 2022, 2023, 2024], 2025, 2026),
}


def load_model_feature_names() -> list[str]:
    with open(CONTRACT) as f:
        c = json.load(f)
    return [f["name"] for f in c["features"]
            if f.get("role") == "model_feature"]


def select_numeric(cohort: pd.DataFrame,
                    features: list[str]) -> list[str]:
    keep = []
    for c in features:
        if c not in cohort.columns:
            continue
        s = cohort[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            keep.append(c)
    return keep


def train_one(label: str, k: int | None,
                tr: pd.DataFrame, va: pd.DataFrame, oos: pd.DataFrame,
                top_features: list[str], out_dir: Path) -> dict:
    feat_cols = (top_features if k is None
                  else top_features[:k])
    feat_cols = [c for c in feat_cols if c in tr.columns]

    y_tr = tr["is_pt_first"].values
    y_va = va["is_pt_first"].values
    y_oos = oos["is_pt_first"].values

    t0 = time.time()
    model = train_lgbm(tr[feat_cols], y_tr, va[feat_cols], y_va)
    train_s = time.time() - t0

    val_scores = model.predict(va[feat_cols],
                                  num_iteration=model.best_iteration)
    oos_scores = model.predict(oos[feat_cols],
                                  num_iteration=model.best_iteration)

    threshold = float(pd.Series(val_scores).quantile(0.90))

    auc = float(roc_auc_score(y_oos, oos_scores))
    pr_auc = float(average_precision_score(y_oos, oos_scores))
    base = float(y_oos.mean())

    # Top-10% hit rate
    top_k = int(0.10 * len(oos))
    order = np.argsort(-oos_scores)
    top_idx = order[:top_k]
    top10_hit = float(y_oos[top_idx].mean())

    # Save artifacts
    cand_dir = out_dir / label
    cand_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(str(cand_dir / "model.txt"))
    with open(cand_dir / "feature_list.json", "w") as f:
        json.dump({"features": feat_cols,
                    "n_features": len(feat_cols)}, f, indent=2)
    with open(cand_dir / "threshold.json", "w") as f:
        json.dump({"threshold_top10": threshold,
                    "best_iter": int(model.best_iteration)},
                   f, indent=2)

    # Save OOS predictions
    pred = oos[["event_id", "checkpoint_s", "year",
                 "is_pt_first", "pt100_before_sl100",
                 "atr_at_signal", "signal_direction",
                 "is_rth_checkpoint", "fill_time_actual"]].copy()
    pred["score"] = oos_scores
    pred.to_parquet(cand_dir / "oos_predictions.parquet",
                      index=False)

    return {
        "iter": label, "n_features": len(feat_cols),
        "best_iter": int(model.best_iteration), "train_s": train_s,
        "auc": auc, "pr_auc": pr_auc, "base_rate": base,
        "top10_hit_rate": top10_hit, "threshold": threshold,
    }


def run_oos_year(oos_year: int, cohort: pd.DataFrame,
                  model_features: list[str]) -> pd.DataFrame:
    train_years, val_year, _ = OOS_SPLITS[oos_year]
    print(f"\n===== OOS {oos_year} (train {train_years}, "
           f"val {val_year}) =====")

    tr = cohort[cohort["year"].isin(train_years)]
    va = cohort[cohort["year"] == val_year]
    oos = cohort[cohort["year"] == oos_year]
    print(f"  splits: tr={len(tr):,} va={len(va):,} oos={len(oos):,}")
    print(f"  base rates: tr={tr['is_pt_first'].mean():.4f} "
           f"va={va['is_pt_first'].mean():.4f} "
           f"oos={oos['is_pt_first'].mean():.4f}")

    feat_cols = select_numeric(cohort, model_features)
    print(f"  features available: {len(feat_cols)}")

    out_dir = ROOT / f"models_oos_{oos_year}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Train FULL model first to derive gain ranking
    print("\n  [Step 1] Training FULL model + ranking features...")
    full_row = train_one("full", None, tr, va, oos, feat_cols,
                          out_dir)
    full_model = lgb.Booster(model_file=str(out_dir / "full" / "model.txt"))
    imp = pd.DataFrame({
        "feature": feat_cols,
        "gain": full_model.feature_importance(importance_type="gain"),
    }).sort_values("gain", ascending=False)
    top_features = imp["feature"].tolist()
    imp.to_parquet(
        ROOT / f"feature_importance_oos_{oos_year}.parquet",
        index=False)
    print(f"  Top-10 features for OOS {oos_year}:")
    for i, name in enumerate(top_features[:10], 1):
        print(f"    {i:>2}. {name}")

    rows = [full_row]
    for label in ITERATIONS:
        if label == "full":
            continue
        print(f"\n  [Step 2] Training {label}...")
        row = train_one(label, ITER_K[label], tr, va, oos,
                          top_features, out_dir)
        print(f"    n_feat={row['n_features']}  "
               f"AUC={row['auc']:.4f}  "
               f"PR-AUC={row['pr_auc']:.4f}  "
               f"top10_hit={row['top10_hit_rate']:.4f}  "
               f"thr={row['threshold']:.4f}")
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    print("=" * 72)
    print("V3 TRAIN SWEEP (full-population PT-first label)")
    print("=" * 72)

    cohort = pd.read_parquet(COHORT)
    print(f"Cohort: {len(cohort):,} rows")

    model_features = load_model_feature_names()
    print(f"Contract model features: {len(model_features)}")

    summaries = []
    for oos_year in [2024, 2026]:
        df = run_oos_year(oos_year, cohort, model_features)
        df["oos_year"] = oos_year
        summaries.append(df)

    full = pd.concat(summaries, ignore_index=True)
    full.to_parquet(ROOT / "sweep_summary.parquet", index=False)

    print()
    print("=" * 72)
    print("FULL SWEEP SUMMARY")
    print("=" * 72)
    cols = ["oos_year", "iter", "n_features", "auc", "pr_auc",
            "base_rate", "top10_hit_rate", "threshold"]
    print(full[cols].to_string(
        index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
