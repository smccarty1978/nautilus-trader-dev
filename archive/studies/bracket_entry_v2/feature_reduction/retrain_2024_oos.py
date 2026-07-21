"""Retrain the 3 finalists with 2024 OOS splits + save predictions.

Split: Train=2020-2022, Val=2023, OOS=2024.
Features: full / top_15 / top_10 (same as 2025 sweep).

Writes one predictions parquet per finalist:
  predictions_2024_full.parquet
  predictions_2024_top_15.parquet
  predictions_2024_top_10.parquet

These will be fed to the NT backtest runner.
"""

from __future__ import annotations
import time
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

from sweep import (  # noqa: E402
    train_lgbm, offline_bracket_pnl,
)

FINALISTS = [
    ("full", None),
    ("top_15", 15),
    ("top_10", 10),
]


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort",
                     default="studies/bracket_entry_v2/results/"
                              "cohort_long.parquet")
    ap.add_argument("--feature-importance",
                     default="studies/bracket_entry_v2/results/"
                              "feature_importance.parquet")
    ap.add_argument("--out-dir",
                     default="studies/bracket_entry_v2/feature_reduction")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("RETRAIN FINALISTS WITH 2024 OOS SPLIT")
    print("  Train=2020-2022  Val=2023  OOS=2024")
    print("=" * 72)

    cohort = pd.read_parquet(args.cohort)
    imp = pd.read_parquet(args.feature_importance)
    imp = imp.sort_values("gain", ascending=False)
    top_features = imp["feature"].tolist()

    r = cohort[cohort["resolved"] == 1]
    tr = r[r["year"].isin([2020, 2021, 2022])]
    va = r[r["year"] == 2023]
    oos = r[r["year"] == 2024]
    print(f"Resolved splits: tr={len(tr):,} va={len(va):,} "
           f"oos={len(oos):,}")

    for name, k in FINALISTS:
        if k is None:
            feat_cols = [c for c in top_features if c in cohort.columns]
        else:
            feat_cols = [c for c in top_features[:k]
                          if c in cohort.columns]

        y_tr = tr["good_bracket_entry"].values
        y_va = va["good_bracket_entry"].values
        y_oos = oos["good_bracket_entry"].values
        print(f"\n[{name}] features={len(feat_cols)}")

        t0 = time.time()
        model = train_lgbm(tr[feat_cols], y_tr,
                             va[feat_cols], y_va)
        print(f"  Trained in {time.time() - t0:.1f}s "
               f"(best_iter={model.best_iteration})")

        oos_scored = oos.copy()
        oos_scored["score"] = model.predict(
            oos[feat_cols], num_iteration=model.best_iteration)
        oos_scored["bracket_pnl"] = offline_bracket_pnl(oos_scored)

        keep = ["event_id", "checkpoint_s", "year", "score",
                 "good_bracket_entry", "pt100_before_sl100",
                 "atr_at_signal", "signal_direction",
                 "is_rth_checkpoint",
                 "bracket_resolution_time_s_pt100_before_sl100",
                 "bracket_pnl"]
        keep = [c for c in keep if c in oos_scored.columns]

        out_path = out_dir / f"predictions_2024_{name}.parquet"
        oos_scored[keep].to_parquet(out_path, index=False)

        # Quick stats
        from sklearn.metrics import roc_auc_score, average_precision_score
        auc = roc_auc_score(y_oos, oos_scored["score"])
        pr_auc = average_precision_score(y_oos, oos_scored["score"])
        base = y_oos.mean()
        top10 = oos_scored.nlargest(int(0.10 * len(oos_scored)),
                                       "score")
        tp = top10["bracket_pnl"].dropna()
        wins = tp[tp > 0]
        losses = tp[tp < 0]
        pf = (wins.sum() / abs(losses.sum())
               if len(losses) and losses.sum() != 0
               else float("inf"))
        print(f"  OOS AUC={auc:.4f}  PR-AUC={pr_auc:.4f}  "
               f"base={base:.4f}")
        print(f"  Top-10%: n={len(top10)}  "
               f"mean={tp.mean():.2f}  PF={pf:.2f}  "
               f"win%={(tp>0).mean()*100:.1f}")
        print(f"  Saved: {out_path}")


if __name__ == "__main__":
    main()
