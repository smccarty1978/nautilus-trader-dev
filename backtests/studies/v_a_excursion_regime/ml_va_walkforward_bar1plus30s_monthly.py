"""Monthly expanding-window walk-forward for bar1+30s ML.

Refits the model at the start of each calendar month, training on all
prior data and scoring the upcoming month. Aggregates OOS predictions
across the entire period.

Temporal triple (same as static version):
  T_F = bar1_close + 30s
  T_E = bar1_close + 30s  (uses WITH-DELAY trades.parquet)
  T_L = T_E + 300s

Walk-forward schedule:
  - First scored month: 2024-04 (after 3 months warm-up training)
  - Last scored month:  2026-04
  - ~25 retrains, expanding window

For each month M:
  - Train: all rows with decision_ts before start of M
  - Val:   last 20% of training (temporal split for early stopping)
  - OOS:   all rows in month M

Reports:
  - Combined OOS PnL (all months stitched together)
  - Per-month PnL
  - Per-year aggregation (gives us 2024 OOS for the first time)
  - Filter variants (top 30%, 20%, 10%) on combined OOS predictions
  - Rolling stability check (3-month rolling PnL)
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

# Import the data prep functions from the static bar1+30s script
import importlib.util
spec = importlib.util.spec_from_file_location(
    "bar1plus30s",
    "studies/v_a_excursion_regime/ml_va_walkforward_bar1plus30s.py")
b30 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b30)


OUT = Path("studies/v_a_excursion_regime/results_v0")
SEED = 42
VAL_FRAC = 0.20
N_BOOT = 2000
MIN_TRAIN_MONTHS = 3
FIRST_SCORED_MONTH = "2024-04"  # = MIN_TRAIN_MONTHS after data start
LAST_SCORED_MONTH = "2026-04"


def bootstrap_mean(values: np.ndarray, n_boot=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": np.nan, "p05": np.nan, "p95": np.nan,
                "total": 0.0}
    boot = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot[b] = values[idx].mean()
    return {
        "n": n, "mean": float(values.mean()),
        "total": float(values.sum()),
        "p05": float(np.percentile(boot, 5)),
        "p95": float(np.percentile(boot, 95)),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("MONTHLY WALK-FORWARD bar1+30s ML  (expanding window)")
    print("=" * 78)

    # ----- Load data using the same pipeline as the static script -----
    all_rows = []
    for yr in b30.YEARS:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        df = b30.load_bar1_trades_with_p30(yr)
        print(f"  V_A confirmed RTH (with-delay): {len(df):,}  "
              f"({time.time()-t0:.0f}s)")
        all_rows.append(df)
    all_df = pd.concat(all_rows, ignore_index=True)
    n_pre = len(all_df)
    all_df = all_df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset=["decision_ts", "direction"], keep="first"
        ).reset_index(drop=True)
    print(f"\nDedupe: {n_pre:,} -> {len(all_df):,}")

    X = b30.make_feature_matrix(all_df)
    y = all_df["target_unr075"]
    pnl = all_df["net_pnl"]
    forbidden = {"target_unr075", "unr_5m_atr", "net_pnl", "gross_pnl",
                 "hold_s", "exit_reason", "running_mfe", "running_mae",
                 "entry_ts", "fill_price", "exit_ts", "exit_price",
                 "atr_at_signal", "year", "confirmed", "became_trade"}
    leaked = forbidden.intersection(X.columns)
    assert not leaked, f"Label leak: {leaked}"
    print(f"\nFeature matrix shape: {X.shape}")

    # ----- Walk-forward loop -----
    ct = pd.to_datetime(all_df["decision_ts"], unit="ns", utc=True
                          ).dt.tz_convert("America/Chicago")
    all_df["year_month"] = ct.dt.to_period("M")
    all_months = sorted(all_df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(all_months)
                       if str(m) >= FIRST_SCORED_MONTH)
    print(f"\nWalk-forward schedule:")
    print(f"  data months: {all_months[0]} .. {all_months[-1]}")
    print(f"  first scored: {all_months[start_idx]}")
    print(f"  last scored:  {all_months[-1]}")
    print(f"  retrains:     {len(all_months) - start_idx}")

    fold_results = []
    oos_records = []
    for i in range(start_idx, len(all_months)):
        scoring_month = all_months[i]
        if str(scoring_month) > LAST_SCORED_MONTH:
            break
        train_mask = (all_df["year_month"] < scoring_month).to_numpy()
        oos_mask = (all_df["year_month"] == scoring_month).to_numpy()
        n_train = train_mask.sum()
        n_oos = oos_mask.sum()
        if n_train < 500 or n_oos < 20:
            print(f"  skip {scoring_month}: train n={n_train}  oos n={n_oos}")
            continue

        # Temporal val split within training set
        X_tr_full = X[train_mask]
        y_tr_full = y[train_mask]
        train_dts = all_df.loc[train_mask, "decision_ts"].to_numpy()
        order = np.argsort(train_dts, kind="mergesort")
        X_tr_full = X_tr_full.iloc[order].reset_index(drop=True)
        y_tr_full = y_tr_full.iloc[order].reset_index(drop=True)
        n_val = int(len(X_tr_full) * VAL_FRAC)
        n_tr_only = len(X_tr_full) - n_val
        if n_tr_only < 200 or n_val < 50:
            print(f"  skip {scoring_month}: split too small")
            continue
        X_tr = X_tr_full.iloc[:n_tr_only]
        y_tr = y_tr_full.iloc[:n_tr_only]
        X_val = X_tr_full.iloc[n_tr_only:]
        y_val = y_tr_full.iloc[n_tr_only:]

        model = b30.fit_model(X_tr, y_tr, X_val, y_val)
        p_oos = model.predict_proba(X[oos_mask])[:, 1]
        y_oos_actual = y[oos_mask].to_numpy()
        pnl_oos = pnl[oos_mask].to_numpy()
        auc = (roc_auc_score(y_oos_actual, p_oos)
                if len(set(y_oos_actual)) > 1 else np.nan)

        # Record OOS predictions for aggregation
        for k in range(n_oos):
            oos_records.append({
                "month": scoring_month,
                "p": float(p_oos[k]),
                "y": int(y_oos_actual[k]),
                "pnl": float(pnl_oos[k]),
            })

        fold_results.append({
            "month": str(scoring_month),
            "n_train": int(n_train),
            "n_oos": int(n_oos),
            "auc": float(auc),
            "best_iter": int(model.best_iteration_),
            "month_pnl": float(pnl_oos.sum()),
            "month_mean_pnl": float(pnl_oos.mean()),
        })
        print(f"  {scoring_month}: train={n_train:>4,}  oos={n_oos:>3}  "
              f"AUC={auc:.3f}  best_iter={model.best_iteration_:>3}  "
              f"month_total=${pnl_oos.sum():>+7,.0f}  "
              f"month_mean=${pnl_oos.mean():>+6.2f}")

    # ----- Aggregate -----
    oos_df = pd.DataFrame(oos_records)
    folds_df = pd.DataFrame(fold_results)
    folds_df.to_csv(OUT / "ml_walkforward_monthly_folds.csv", index=False)
    oos_df.to_parquet(
        OUT / "ml_walkforward_monthly_oos_preds.parquet", index=False)

    print(f"\n{'='*78}")
    print(f"AGGREGATE OOS  —  {len(oos_df):,} predictions across "
          f"{folds_df.shape[0]} monthly folds")
    print(f"{'='*78}")

    base_total = oos_df["pnl"].sum()
    base_mean = oos_df["pnl"].mean()
    base_wr = (oos_df["pnl"] > 0).mean()
    print(f"  Baseline (all OOS, no filter): n={len(oos_df):,}  "
          f"mean=${base_mean:+.2f}  total=${base_total:+,.0f}  "
          f"WR={base_wr:.1%}")

    # Filter variants on aggregated OOS predictions
    print(f"\n  Filter variants on combined OOS:")
    print(f"    {'gate':<22}  {'kept':>5}  {'mean':>9}  "
          f"{'p05':>9}  {'p95':>9}  {'total':>10}  {'vs_base':>9}")
    for q in [0.50, 0.30, 0.20, 0.10]:
        thresh = oos_df["p"].quantile(1 - q)
        kept = oos_df[oos_df["p"] >= thresh]
        bs = bootstrap_mean(kept["pnl"].to_numpy())
        print(f"    top {q*100:>3.0f}% (p>={thresh:.4f})  "
              f"{len(kept):>5,}  ${bs['mean']:>+7.2f}  "
              f"${bs['p05']:>+7.2f}  ${bs['p95']:>+7.2f}  "
              f"${bs['total']:>+8,.0f}  "
              f"${bs['mean']-base_mean:>+7.2f}")

    # Per-year aggregation (now includes 2024 as OOS!)
    oos_df["year"] = oos_df["month"].astype(str).str[:4].astype(int)
    print(f"\n  Per-year OOS baseline and filter performance:")
    print(f"    {'year':>4}  {'n':>5}  {'base_mean':>10}  {'base_total':>11}  "
          f"{'t30_mean':>10}  {'t30_total':>11}  {'t30_vs_base':>11}")
    for year in sorted(oos_df["year"].unique()):
        ysub = oos_df[oos_df["year"] == year]
        y_base = ysub["pnl"].mean()
        y_total = ysub["pnl"].sum()
        # Apply global top-30% threshold (computed across all OOS)
        thresh30 = oos_df["p"].quantile(0.70)
        y_top30 = ysub[ysub["p"] >= thresh30]
        if len(y_top30) > 0:
            yt30_mean = y_top30["pnl"].mean()
            yt30_total = y_top30["pnl"].sum()
        else:
            yt30_mean = np.nan
            yt30_total = 0
        print(f"    {year:>4}  {len(ysub):>5,}  "
              f"${y_base:>+8.2f}  ${y_total:>+9,.0f}  "
              f"${yt30_mean:>+8.2f}  ${yt30_total:>+9,.0f}  "
              f"${yt30_mean - y_base:>+9.2f}")

    # Monthly stability scan
    print(f"\n  Monthly PnL (baseline vs top-30%):")
    print(f"    {'month':<8}  {'n':>4}  {'AUC':>6}  "
          f"{'base':>9}  {'t30':>9}  {'lift':>8}")
    thresh30 = oos_df["p"].quantile(0.70)
    for month in folds_df["month"]:
        ysub = oos_df[oos_df["month"].astype(str) == month]
        y_base_total = ysub["pnl"].sum()
        y_top30 = ysub[ysub["p"] >= thresh30]
        y_t30_total = y_top30["pnl"].sum() if len(y_top30) else 0
        auc = folds_df.loc[folds_df["month"] == month, "auc"].iloc[0]
        print(f"    {month:<8}  {len(ysub):>4}  {auc:>6.3f}  "
              f"${y_base_total:>+7,.0f}  ${y_t30_total:>+7,.0f}  "
              f"${y_t30_total - y_base_total:>+7,.0f}")

    # Rolling 3-month consistency
    print(f"\n  Rolling 3-month consistency of top-30% filter:")
    monthly_t30 = []
    for month in folds_df["month"]:
        ysub = oos_df[oos_df["month"].astype(str) == month]
        kept = ysub[ysub["p"] >= thresh30]
        monthly_t30.append({
            "month": month,
            "n": len(kept),
            "total": float(kept["pnl"].sum()) if len(kept) else 0.0,
        })
    mt = pd.DataFrame(monthly_t30)
    mt["roll3_total"] = mt["total"].rolling(3, min_periods=1).sum()
    mt["roll3_pos"] = (mt["roll3_total"] > 0).rolling(
        3, min_periods=1).sum().astype(int)
    n_pos_rolls = (mt["roll3_total"] > 0).sum()
    n_total_rolls = len(mt)
    print(f"    Rolling-3 windows positive: {n_pos_rolls}/{n_total_rolls} "
          f"({n_pos_rolls/n_total_rolls:.1%})")
    print(f"    Best rolling-3: ${mt['roll3_total'].max():+,.0f}  "
          f"({mt.loc[mt['roll3_total'].idxmax(), 'month']})")
    print(f"    Worst rolling-3: ${mt['roll3_total'].min():+,.0f}  "
          f"({mt.loc[mt['roll3_total'].idxmin(), 'month']})")

    # Compare to static split
    print(f"\n{'='*78}")
    print(f"COMPARISON  —  walk-forward vs static")
    print(f"{'='*78}")
    print(f"  Static (single train/eval):")
    print(f"    Config A (train 2024 -> score 2025) top30:  ~+$33,650")
    print(f"    Config B (train 24+25 -> score 2026) top30: ~-$10,635")
    print(f"    Combined global top30:                       +$54,790")
    print(f"\n  Walk-forward (monthly, expanding):")
    top30_kept = oos_df[oos_df["p"] >= thresh30]
    print(f"    Combined top30 across all retrains:          "
          f"${top30_kept['pnl'].sum():+,.0f}")
    print(f"    n_predictions: {len(top30_kept):,} of {len(oos_df):,}")
    print(f"\nFiles:")
    print(f"  {OUT/'ml_walkforward_monthly_folds.csv'}")
    print(f"  {OUT/'ml_walkforward_monthly_oos_preds.parquet'}")


if __name__ == "__main__":
    main()
