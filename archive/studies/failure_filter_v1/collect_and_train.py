"""Build failure-label cohort + train baseline classifiers for
both OOS years. Then GATE on classification quality before NT.

Failure label:
  is_failure = 1 iff (mfe_300s_atr < 0.25)
                  AND (pt100_before_sl100 != 1)  # i.e. SL or unresolved
             = 0 otherwise

Trains full-feature LightGBM for:
  - 2024 OOS: Train 2020-2022, Val 2023, OOS 2024
  - 2026 OOS: Train 2020-2024, Val 2025, OOS 2026

Saves models, predictions, decile-calibration tables.
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
from sklearn.metrics import roc_auc_score, average_precision_score

sys.path.insert(0, str(project_root
    / "studies/bracket_entry_v2/feature_reduction"))
from sweep import train_lgbm  # noqa

ROOT = Path("studies/failure_filter_v1/results")
ROOT.mkdir(parents=True, exist_ok=True)
SRC_COHORT = "studies/bracket_entry_v3_fullpop/results/cohort_v3.parquet"
CONTRACT = "models/ml_5m_flip/feature_contract_v2.json"

OOS_SPLITS = {
    2024: ([2020, 2021, 2022], 2023, 2024),
    2026: ([2020, 2021, 2022, 2023, 2024], 2025, 2026),
}


def add_failure_label(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pt = df["pt100_before_sl100"]
    mfe = df["mfe_300s_atr"]
    failed_outcome = (pt != 1)  # SL=0 or NaN; treats NaN correctly
    no_traction = mfe < 0.25
    df["is_failure"] = (failed_outcome & no_traction).astype("int8")
    return df


def load_features(contract_path: str) -> list[str]:
    with open(contract_path) as f:
        c = json.load(f)
    return [f["name"] for f in c["features"]
            if f.get("role") == "model_feature"]


def select_numeric(cohort, features):
    keep = []
    for c in features:
        if c not in cohort.columns:
            continue
        s = cohort[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            keep.append(c)
    return keep


def main():
    print(f"Loading cohort: {SRC_COHORT}")
    cohort = pd.read_parquet(SRC_COHORT)
    print(f"  {len(cohort):,} rows")

    cohort = add_failure_label(cohort)
    base = float(cohort["is_failure"].mean())
    print(f"\nFailure label:")
    print(f"  Positive (is_failure=1): "
           f"{int(cohort['is_failure'].sum()):,} "
           f"({100*base:.1f}%)")
    print(f"  Negative: {int((cohort['is_failure']==0).sum()):,}")

    # Per-year base rate
    print(f"\nPer-year failure rate:")
    for y in sorted(cohort["year"].unique()):
        sub = cohort[cohort["year"] == y]
        rate = sub["is_failure"].mean()
        print(f"  {y}: n={len(sub):,}  failure_rate={rate:.4f}")

    feature_names = load_features(CONTRACT)
    feat_cols = select_numeric(cohort, feature_names)
    print(f"\nFeatures: {len(feat_cols)}")

    cohort.to_parquet(ROOT / "cohort_with_failure.parquet",
                        index=False)

    # Train + score per OOS year
    summaries = {}
    for oos_year, (train_y, val_y, _) in OOS_SPLITS.items():
        print(f"\n{'='*60}")
        print(f"OOS {oos_year}  (train {train_y}, val {val_y})")
        print(f"{'='*60}")
        tr = cohort[cohort["year"].isin(train_y)]
        va = cohort[cohort["year"] == val_y]
        oos = cohort[cohort["year"] == oos_year]
        print(f"  splits: tr={len(tr):,} va={len(va):,} "
               f"oos={len(oos):,}")
        print(f"  base rates: tr={tr['is_failure'].mean():.4f} "
               f"va={va['is_failure'].mean():.4f} "
               f"oos={oos['is_failure'].mean():.4f}")

        t0 = time.time()
        model = train_lgbm(tr[feat_cols], tr["is_failure"],
                            va[feat_cols], va["is_failure"])
        print(f"  trained in {time.time()-t0:.1f}s "
               f"best_iter={model.best_iteration}")

        out_dir = ROOT / f"models_oos_{oos_year}"
        out_dir.mkdir(exist_ok=True)
        model.save_model(str(out_dir / "model_full.txt"))
        with open(out_dir / "feature_list.json", "w") as f:
            json.dump({"features": feat_cols}, f, indent=2)

        # Score val + OOS
        val_scores = model.predict(va[feat_cols],
            num_iteration=model.best_iteration)
        oos_scores = model.predict(oos[feat_cols],
            num_iteration=model.best_iteration)

        # Save val percentiles for filter thresholds
        val_pcts = {
            f"p{p}": float(np.percentile(val_scores, p))
            for p in [50, 70, 80, 90, 95, 99]
        }
        with open(out_dir / "val_percentiles.json", "w") as f:
            json.dump(val_pcts, f, indent=2)
        print(f"  val score percentiles: "
               f"p50={val_pcts['p50']:.4f} "
               f"p70={val_pcts['p70']:.4f} "
               f"p80={val_pcts['p80']:.4f} "
               f"p90={val_pcts['p90']:.4f} "
               f"p95={val_pcts['p95']:.4f}")

        # Save OOS predictions
        pred = oos[["event_id", "checkpoint_s", "year",
                     "is_failure", "pt100_before_sl100",
                     "mfe_300s_atr", "atr_at_signal",
                     "signal_direction", "is_rth_checkpoint",
                     "fill_time_actual"]].copy()
        pred["score"] = oos_scores
        pred.to_parquet(out_dir / "oos_predictions.parquet",
                          index=False)

        # Classification metrics
        y_oos = oos["is_failure"].values
        auc = float(roc_auc_score(y_oos, oos_scores))
        pr_auc = float(average_precision_score(y_oos, oos_scores))
        print(f"  OOS AUC={auc:.4f}  PR-AUC={pr_auc:.4f}  "
               f"base={y_oos.mean():.4f}")

        # Decile calibration
        pred["bucket"] = pd.qcut(pred["score"].rank(method="first"),
                                    q=10, labels=False)
        cal = pred.groupby("bucket").agg(
            n=("is_failure", "size"),
            pred_mean=("score", "mean"),
            actual_rate=("is_failure", "mean"),
        ).reset_index()
        cal.to_parquet(out_dir / "decile_calibration.parquet",
                         index=False)

        print(f"  Decile calibration (failure rate by score-decile):")
        print(f"  {'D':<3} {'n':<6} {'pred':<8} {'actual':<8}")
        for _, r in cal.iterrows():
            print(f"  {int(r['bucket']):<3} {int(r['n']):>6} "
                   f"{r['pred_mean']:.4f}   {r['actual_rate']:.4f}")
        d0 = cal.iloc[0]['actual_rate']
        d9 = cal.iloc[-1]['actual_rate']
        spread = d9 - d0
        print(f"  D0 actual: {d0:.4f}   D9 actual: {d9:.4f}   "
               f"spread: {spread:+.4f}")

        summaries[oos_year] = {
            "n_oos": len(oos),
            "base_rate": float(y_oos.mean()),
            "auc": auc, "pr_auc": pr_auc,
            "best_iter": int(model.best_iteration),
            "decile_d0": float(d0), "decile_d9": float(d9),
            "decile_spread": float(spread),
            "val_percentiles": val_pcts,
        }

    with open(ROOT / "training_summary.json", "w") as f:
        json.dump(summaries, f, indent=2)

    # GATE — early read on whether to run NT
    print()
    print("=" * 60)
    print("CLASSIFICATION GATE")
    print("=" * 60)
    for year, s in summaries.items():
        # The model's job is to predict FAILURE.
        # D9 (highest score) should have HIGHER failure rate than base.
        # Meaningful: D9 > base + 0.05 (5pp lift)
        d9_lift = s['decile_d9'] - s['base_rate']
        d0_drop = s['base_rate'] - s['decile_d0']
        print(f"  {year}: D9 lift over base = {d9_lift:+.4f}  "
               f"D0 drop below base = {d0_drop:+.4f}  "
               f"AUC = {s['auc']:.4f}")
        if d9_lift > 0.05:
            print(f"    → HIGH-failure-score group meaningfully more "
                   f"likely to fail. Filter has potential.")
        elif d9_lift > 0.02:
            print(f"    → Modest separation. Worth NT test but expect "
                   f"small economic impact.")
        else:
            print(f"    → Weak separation. NT unlikely to help.")


if __name__ == "__main__":
    main()
