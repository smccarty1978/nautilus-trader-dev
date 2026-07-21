"""Orchestrator — bracket-aligned entry quality study."""

from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from collect import collect_all_years  # noqa
from train import (
    load_model_feature_names, select_feature_cols,
    make_splits, train_lgbm_binary,
)  # noqa
from report import compute_bracket_pnl, write_report  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int,
                     default=[2020, 2021, 2022, 2023, 2024, 2025])
    ap.add_argument("--results-dir",
                     default="studies/1m_regime_collector_v2/results")
    ap.add_argument("--contract",
                     default="models/ml_5m_flip/feature_contract_v2.json")
    ap.add_argument("--out-dir",
                     default="studies/bracket_entry_v2/results")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("BRACKET-ALIGNED ENTRY QUALITY MODEL v2")
    print("=" * 72)

    t0 = time.time()
    print("Loading RTH cohort + attaching target...")
    cohort = collect_all_years(
        Path(args.results_dir), Path(args.contract), args.years,
        rth_only=True)
    print(f"  {len(cohort):,} rows "
           f"({time.time() - t0:.1f}s)")
    cohort.to_parquet(out_dir / "cohort_long.parquet", index=False)

    # Features + splits
    model_feats = load_model_feature_names(Path(args.contract))
    feat_cols = select_feature_cols(cohort, model_feats)
    print(f"  Features: {len(feat_cols)}")

    splits = make_splits(cohort)
    train, val, oos = splits["train"], splits["val"], splits["oos"]
    # Filter unresolved out of TRAINING data only
    train_r = train[train["resolved"] == 1].copy()
    val_r = val[val["resolved"] == 1].copy()
    oos_r = oos[oos["resolved"] == 1].copy()
    print(f"  Train resolved: {len(train_r):,} "
           f"(base rate {train_r['good_bracket_entry'].mean():.4f})")
    print(f"  Val resolved:   {len(val_r):,} "
           f"(base rate {val_r['good_bracket_entry'].mean():.4f})")
    print(f"  OOS resolved:   {len(oos_r):,} "
           f"(base rate {oos_r['good_bracket_entry'].mean():.4f})")

    # Train
    print(f"\n  Training LightGBM...", flush=True)
    t1 = time.time()
    model = train_lgbm_binary(
        train_r[feat_cols], train_r["good_bracket_entry"],
        val_r[feat_cols], val_r["good_bracket_entry"],
        seed=args.seed,
    )
    print(f"  Done in {time.time() - t1:.1f}s "
           f"(best_iter={model.best_iteration})")

    # Score OOS resolved rows + compute bracket PnL
    oos_r = oos_r.copy()
    oos_r["score"] = model.predict(
        oos_r[feat_cols], num_iteration=model.best_iteration)
    oos_r["bracket_pnl"] = compute_bracket_pnl(oos_r)

    # Persist
    pred_cols = ["event_id", "checkpoint_s", "year", "score",
                  "good_bracket_entry", "bracket_pnl",
                  "pt100_before_sl100", "atr_at_signal",
                  "signal_direction",
                  "is_rth_checkpoint",
                  "bracket_resolution_time_s_pt100_before_sl100"]
    pred_cols = [c for c in pred_cols if c in oos_r.columns]
    oos_r[pred_cols].to_parquet(
        out_dir / "oos_predictions.parquet", index=False)
    model.save_model(str(out_dir / "model.txt"))

    imp = pd.DataFrame({
        "feature": feat_cols,
        "gain": model.feature_importance(importance_type="gain"),
        "split": model.feature_importance(importance_type="split"),
    }).sort_values("gain", ascending=False)
    imp.to_parquet(out_dir / "feature_importance.parquet",
                     index=False)

    # Report
    report_path = out_dir / "REPORT.md"
    write_report(train_r, val_r, oos_r, oos, feat_cols, model,
                   report_path)
    print(f"\n  Report: {report_path}")
    print(f"  Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
