"""Offline feature-reduction sweep for the bracket-aligned model.

For each iteration in {full, top-50, top-35, top-25, top-20, top-15}:
  1. Take top-K features by gain importance from the current full-feature
     model (bracket_entry_v2/results/feature_importance.parquet).
  2. Retrain LightGBM with same hyperparameters as the baseline.
  3. Score 2025 OOS resolved rows.
  4. Compute:
       - classification metrics (AUC, PR-AUC, base rate, top-10% hit)
       - cost-adjusted bracket PnL (commission + 1-tick slippage, scenario C)
       - top-10% economics (mean, median, trimmed-5%, PF, win, total)
       - long/short balance in top-10%

Offline PnL model (matches the recent NT run's scenario C):
  - PT hit (pt100 == 1): +atr × 20 − 5 − 5  (commission + entry slip)
  - SL hit (pt100 == 0): −atr × 20 − 5 − 5 − 5  (commission + entry slip
                                                   + SL exit slip)

Unresolved rows are EXCLUDED from this study per the target rule.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, average_precision_score

NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0  # 1 tick × $20/pt = $5 per tick on NQ

ITERATIONS = [
    ("full", None),     # all features
    ("top_50", 50),
    ("top_35", 35),
    ("top_25", 25),
    ("top_20", 20),
    ("top_15", 15),
    ("top_10", 10),
    ("top_5", 5),       # extreme — expected to clearly degrade
]


def offline_bracket_pnl(df: pd.DataFrame) -> pd.Series:
    """Cost-adjusted bracket PnL — scenario C.

    Only resolved rows (pt100 ∈ {0, 1}) produce values; unresolved
    returns NaN (but we expect the input to be resolved-only).
    """
    pt = df["pt100_before_sl100"].values
    atr = df["atr_at_signal"].values
    out = np.full(len(df), np.nan, dtype=float)
    for i in range(len(df)):
        v = pt[i]
        if pd.isna(v):
            continue
        if v == 1:
            # PT: gross +atr × 20, minus commission + 1-tick entry slip
            out[i] = atr[i] * NQ_MULT - COMMISSION - TICK_COST
        else:
            # SL: gross -atr × 20, minus commission + 1-tick entry slip
            # + 1-tick SL exit slip
            out[i] = -atr[i] * NQ_MULT - COMMISSION - 2 * TICK_COST
    return pd.Series(out, index=df.index)


def train_lgbm(X_tr, y_tr, X_val, y_val, seed=42):
    train_set = lgb.Dataset(X_tr, label=y_tr, free_raw_data=False)
    val_set = lgb.Dataset(X_val, label=y_val, reference=train_set,
                            free_raw_data=False)
    params = {
        "objective": "binary",
        "metric": "auc",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "max_depth": -1,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbosity": -1,
        "seed": seed,
        "deterministic": True,
    }
    model = lgb.train(
        params, train_set,
        num_boost_round=2000,
        valid_sets=[val_set],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=0),   # silent
        ],
    )
    return model


def top_k_row_stats(df: pd.DataFrame, k_frac: float) -> dict:
    """Stats on top-K% by score. Uses pre-computed 'bracket_pnl'."""
    n_total = len(df)
    k = int(round(k_frac * n_total))
    top = df.nlargest(k, "score")
    pnl = top["bracket_pnl"].dropna()
    if len(pnl) == 0:
        return {"n": 0}
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    k_trim = int(len(pnl) * 0.05)
    trimmed = (pnl.sort_values().iloc[k_trim:len(pnl) - k_trim].mean()
                if k_trim * 2 < len(pnl) else float("nan"))
    d_long = int((top["signal_direction"] == 1).sum())
    d_short = int((top["signal_direction"] == -1).sum())
    return {
        "n": int(len(pnl)),
        "mean": float(pnl.mean()),
        "median": float(pnl.median()),
        "trimmed_5pct": float(trimmed),
        "sum": float(pnl.sum()),
        "win_rate": float((pnl > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0 else float("inf")),
        "long_pct": d_long / len(top) if len(top) else 0,
        "short_pct": d_short / len(top) if len(top) else 0,
    }


def run_iteration(
    name: str, k: int | None,
    cohort: pd.DataFrame,
    top_features_by_gain: list[str],
    out_dir: Path,
    full_oos_size: int | None = None,
) -> dict:
    """Train one iteration and compute offline metrics on 2025."""
    # Pick features
    if k is None:
        feat_cols = top_features_by_gain  # full
    else:
        feat_cols = top_features_by_gain[:k]
    feat_cols = [c for c in feat_cols if c in cohort.columns]
    n_feat = len(feat_cols)

    # Resolved-only splits (training target expects clean labels)
    r = cohort[cohort["resolved"] == 1]
    tr = r[r["year"].isin([2020, 2021, 2022, 2023])]
    va = r[r["year"] == 2024]
    oos = r[r["year"] == 2025]

    print(f"  [{name}] features={n_feat}  "
           f"tr={len(tr):,} va={len(va):,} oos={len(oos):,}", flush=True)

    # Drop rows with any NaN in the features (LightGBM handles NaN OK
    # but we want clean training targets)
    y_tr = tr["good_bracket_entry"].values
    y_va = va["good_bracket_entry"].values
    y_oos = oos["good_bracket_entry"].values

    t0 = time.time()
    model = train_lgbm(tr[feat_cols], y_tr, va[feat_cols], y_va)
    train_s = time.time() - t0

    # Score OOS
    oos = oos.copy()
    oos["score"] = model.predict(
        oos[feat_cols], num_iteration=model.best_iteration)
    oos["bracket_pnl"] = offline_bracket_pnl(oos)

    # Persist predictions for later NT use
    keep = ["event_id", "checkpoint_s", "year", "score",
             "good_bracket_entry", "pt100_before_sl100",
             "atr_at_signal", "signal_direction",
             "is_rth_checkpoint",
             "bracket_resolution_time_s_pt100_before_sl100",
             "bracket_pnl"]
    keep = [c for c in keep if c in oos.columns]
    oos[keep].to_parquet(out_dir / f"predictions_2025_{name}.parquet",
                            index=False)

    # Metrics
    auc = float(roc_auc_score(y_oos, oos["score"].values))
    pr_auc = float(average_precision_score(y_oos, oos["score"].values))
    base_rate = float(y_oos.mean())

    # Top-10% on ALL OOS
    top10 = top_k_row_stats(oos, 0.10)
    top20 = top_k_row_stats(oos, 0.20)
    top5 = top_k_row_stats(oos, 0.05)

    # Hit rate at top-10%
    top10_k = int(0.10 * len(oos))
    top10_rows = oos.nlargest(top10_k, "score")
    hit_rate_top10 = float(top10_rows["good_bracket_entry"].mean())

    # Baseline (all-oos) bracket PnL
    all_pnl = oos["bracket_pnl"].dropna()
    baseline_mean = float(all_pnl.mean()) if len(all_pnl) else float("nan")

    return {
        "iter": name,
        "n_features": n_feat,
        "best_iter": model.best_iteration,
        "train_s": train_s,
        "auc": auc,
        "pr_auc": pr_auc,
        "base_rate": base_rate,
        "top10_hit_rate": hit_rate_top10,
        "baseline_mean_pnl": baseline_mean,
        "top10_n": top10["n"],
        "top10_mean": top10["mean"],
        "top10_median": top10["median"],
        "top10_trimmed": top10["trimmed_5pct"],
        "top10_win_rate": top10["win_rate"],
        "top10_pf": top10["pf"],
        "top10_sum": top10["sum"],
        "top10_long_pct": top10["long_pct"],
        "top10_short_pct": top10["short_pct"],
        "top5_mean": top5["mean"],
        "top5_pf": top5["pf"],
        "top20_mean": top20["mean"],
        "top20_pf": top20["pf"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort",
                     default="studies/bracket_entry_v2/results/"
                              "cohort_long.parquet")
    ap.add_argument("--feature-importance",
                     default="studies/bracket_entry_v2/results/"
                              "feature_importance.parquet")
    ap.add_argument("--out-dir",
                     default="studies/bracket_entry_v2/feature_reduction")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("FEATURE REDUCTION SWEEP (offline, 2025 OOS)")
    print("=" * 72)

    t0 = time.time()
    cohort = pd.read_parquet(args.cohort)
    print(f"Cohort: {len(cohort):,} rows")

    imp = pd.read_parquet(args.feature_importance)
    imp = imp.sort_values("gain", ascending=False)
    top_features = imp["feature"].tolist()
    print(f"Full feature list: {len(top_features)} (ranked by gain)")

    # Sanity: split-importance on top 25/35
    split_imp = imp.sort_values("split", ascending=False)
    split_top25 = set(split_imp.head(25)["feature"])
    gain_top25 = set(imp.head(25)["feature"])
    overlap_25 = len(gain_top25 & split_top25)
    split_top35 = set(split_imp.head(35)["feature"])
    gain_top35 = set(imp.head(35)["feature"])
    overlap_35 = len(gain_top35 & split_top35)
    print(f"Split-importance sanity: "
           f"top-25 overlap {overlap_25}/25, "
           f"top-35 overlap {overlap_35}/35")

    rows = []
    for name, k in ITERATIONS:
        row = run_iteration(name, k, cohort, top_features, out_dir)
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_parquet(out_dir / "sweep_results.parquet", index=False)

    # Console summary
    print()
    print("=" * 72)
    print("SWEEP SUMMARY")
    print("=" * 72)
    cols = ["iter", "n_features", "auc", "pr_auc", "top10_hit_rate",
             "top10_mean", "top10_trimmed", "top10_pf",
             "top10_win_rate", "top10_sum",
             "top10_long_pct", "top10_short_pct"]
    print(df[cols].to_string(index=False,
                               float_format=lambda x: f"{x:.4f}"))

    # Save sanity info
    with open(out_dir / "split_importance_sanity.json", "w") as f:
        json.dump({
            "top25_overlap_with_split": overlap_25,
            "top35_overlap_with_split": overlap_35,
        }, f, indent=2)

    print(f"\nElapsed: {time.time() - t0:.1f}s")
    print(f"Outputs: {out_dir}/sweep_results.parquet + "
           f"predictions_2025_*.parquet")


if __name__ == "__main__":
    main()
