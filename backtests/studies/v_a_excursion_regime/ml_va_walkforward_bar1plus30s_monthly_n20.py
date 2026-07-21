"""Monthly walk-forward bar1+30s ML with FIXED top-20 features.

Same walk-forward schedule as `ml_va_walkforward_bar1plus30s_monthly.py`,
but feature selection is done ONCE on the first 3 months of data
(Jan-Mar 2024) and held fixed across all 25 monthly retrains. This
avoids per-fold feature-selection lookahead and matches what a
deployment would look like (pick features at model design time, hold
fixed in production).

Walk-forward schedule (identical to full-feature run for direct
apples-to-apples comparison):
  - Feature selection: full-feature LGBM trained on Jan-Mar 2024
  - First scored month: 2024-04
  - Last scored month:  2026-04
  - 25 retrains, expanding window
  - Each retrain uses ONLY the top-20 features

Compares directly to the full-feature walk-forward result.
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
N_FEATURES = 20
FS_END_MONTH = "2024-03"   # Use Jan-Mar 2024 for feature selection
FIRST_SCORED_MONTH = "2024-04"
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
    print(f"MONTHLY WALK-FORWARD bar1+30s ML  —  TOP-{N_FEATURES} FEATURES (fixed)")
    print("=" * 78)

    # Load data via the static bar1+30s pipeline
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

    X_full = b30.make_feature_matrix(all_df)
    y = all_df["target_unr075"]
    pnl = all_df["net_pnl"]
    forbidden = {"target_unr075", "unr_5m_atr", "net_pnl", "gross_pnl",
                 "hold_s", "exit_reason", "running_mfe", "running_mae",
                 "entry_ts", "fill_price", "exit_ts", "exit_price",
                 "atr_at_signal", "year", "confirmed", "became_trade"}
    leaked = forbidden.intersection(X_full.columns)
    assert not leaked, f"Label leak: {leaked}"
    print(f"\nFull feature matrix: {X_full.shape}")

    ct = pd.to_datetime(all_df["decision_ts"], unit="ns", utc=True
                          ).dt.tz_convert("America/Chicago")
    all_df["year_month"] = ct.dt.to_period("M")

    # ----- STEP 1: Feature selection on Jan-Mar 2024 ONLY -----
    fs_mask = (all_df["year_month"] <= FS_END_MONTH).to_numpy()
    print(f"\n{'='*78}")
    print(f"STEP 1: Feature selection on first {fs_mask.sum():,} rows "
          f"({all_df.loc[fs_mask, 'year_month'].min()} .. "
          f"{all_df.loc[fs_mask, 'year_month'].max()})")
    print(f"{'='*78}")
    X_fs_full = X_full[fs_mask]
    y_fs_full = y[fs_mask]
    fs_dts = all_df.loc[fs_mask, "decision_ts"].to_numpy()
    order = np.argsort(fs_dts, kind="mergesort")
    X_fs_full = X_fs_full.iloc[order].reset_index(drop=True)
    y_fs_full = y_fs_full.iloc[order].reset_index(drop=True)
    n_val = int(len(X_fs_full) * VAL_FRAC)
    n_tr = len(X_fs_full) - n_val
    if n_tr < 100:
        print(f"  FS training too small: {n_tr}")
        return
    X_fs_tr, y_fs_tr = X_fs_full.iloc[:n_tr], y_fs_full.iloc[:n_tr]
    X_fs_val, y_fs_val = X_fs_full.iloc[n_tr:], y_fs_full.iloc[n_tr:]
    fs_model = b30.fit_model(X_fs_tr, y_fs_tr, X_fs_val, y_fs_val)
    imp = pd.DataFrame({
        "feat": X_full.columns,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    top_feats = imp.head(N_FEATURES)["feat"].tolist()
    print(f"\n  Selected top {N_FEATURES} features (by gain on Jan-Mar 2024):")
    for i, row in imp.head(N_FEATURES).iterrows():
        tag = "  <NEW>" if row["feat"].startswith("p30_") else ""
        print(f"    {i+1:>2}. {row['feat']:<42}  {row['gain']:>8.0f}{tag}")
    n_p30 = sum(1 for f in top_feats if f.startswith("p30_"))
    print(f"\n  p30_* features in top {N_FEATURES}: {n_p30} / 12")
    imp.head(N_FEATURES).to_csv(
        OUT / "ml_walkforward_n20_initial_features.csv", index=False)

    # Restrict feature matrix to top-N
    X = X_full[top_feats]

    # ----- STEP 2: Monthly walk-forward with fixed top-N -----
    all_months = sorted(all_df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(all_months)
                       if str(m) >= FIRST_SCORED_MONTH)
    print(f"\n{'='*78}")
    print(f"STEP 2: Monthly walk-forward with fixed top-{N_FEATURES} features")
    print(f"{'='*78}")
    print(f"  data months: {all_months[0]} .. {all_months[-1]}")
    print(f"  first scored: {all_months[start_idx]}")
    print(f"  last scored:  {LAST_SCORED_MONTH}")
    print(f"  retrains:     up to {len(all_months) - start_idx}")

    fold_results = []
    oos_records = []
    for i in range(start_idx, len(all_months)):
        scoring_month = all_months[i]
        if str(scoring_month) > LAST_SCORED_MONTH:
            break
        train_mask = (all_df["year_month"] < scoring_month).to_numpy()
        oos_mask = (all_df["year_month"] == scoring_month).to_numpy()
        n_train = int(train_mask.sum())
        n_oos = int(oos_mask.sum())
        if n_train < 500 or n_oos < 20:
            continue
        X_tr_full = X[train_mask]
        y_tr_full = y[train_mask]
        train_dts = all_df.loc[train_mask, "decision_ts"].to_numpy()
        order = np.argsort(train_dts, kind="mergesort")
        X_tr_full = X_tr_full.iloc[order].reset_index(drop=True)
        y_tr_full = y_tr_full.iloc[order].reset_index(drop=True)
        n_val = int(len(X_tr_full) * VAL_FRAC)
        n_tr_only = len(X_tr_full) - n_val
        if n_tr_only < 200 or n_val < 50:
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
        for k in range(n_oos):
            oos_records.append({
                "month": scoring_month,
                "p": float(p_oos[k]),
                "y": int(y_oos_actual[k]),
                "pnl": float(pnl_oos[k]),
            })
        fold_results.append({
            "month": str(scoring_month),
            "n_train": n_train, "n_oos": n_oos,
            "auc": float(auc),
            "best_iter": int(model.best_iteration_),
            "month_pnl": float(pnl_oos.sum()),
            "month_mean_pnl": float(pnl_oos.mean()),
        })
        print(f"  {scoring_month}: train={n_train:>4,}  oos={n_oos:>3}  "
              f"AUC={auc:.3f}  best_iter={model.best_iteration_:>3}  "
              f"month_total=${pnl_oos.sum():>+7,.0f}")

    oos_df = pd.DataFrame(oos_records)
    folds_df = pd.DataFrame(fold_results)
    folds_df.to_csv(
        OUT / "ml_walkforward_monthly_n20_folds.csv", index=False)
    oos_df.to_parquet(
        OUT / "ml_walkforward_monthly_n20_oos_preds.parquet", index=False)

    print(f"\n{'='*78}")
    print(f"AGGREGATE OOS  —  {len(oos_df):,} predictions across "
          f"{folds_df.shape[0]} monthly folds (top-{N_FEATURES})")
    print(f"{'='*78}")
    base_total = oos_df["pnl"].sum()
    base_mean = oos_df["pnl"].mean()
    base_wr = (oos_df["pnl"] > 0).mean()
    print(f"  Baseline (all OOS, no filter): n={len(oos_df):,}  "
          f"mean=${base_mean:+.2f}  total=${base_total:+,.0f}  "
          f"WR={base_wr:.1%}")
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

    oos_df["year"] = oos_df["month"].astype(str).str[:4].astype(int)
    print(f"\n  Per-year OOS:")
    print(f"    {'year':>4}  {'n':>5}  {'base_mean':>10}  {'base_total':>11}  "
          f"{'t30_mean':>10}  {'t30_total':>11}  {'t30_vs_base':>11}")
    thresh30 = oos_df["p"].quantile(0.70)
    for year in sorted(oos_df["year"].unique()):
        ysub = oos_df[oos_df["year"] == year]
        y_base = ysub["pnl"].mean()
        y_total = ysub["pnl"].sum()
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

    print(f"\n  Monthly PnL:")
    print(f"    {'month':<8}  {'n':>4}  {'AUC':>6}  "
          f"{'base':>9}  {'t30':>9}  {'lift':>8}")
    monthly_t30_total = []
    for month in folds_df["month"]:
        ysub = oos_df[oos_df["month"].astype(str) == month]
        y_base_total = ysub["pnl"].sum()
        y_top30 = ysub[ysub["p"] >= thresh30]
        y_t30_total = y_top30["pnl"].sum() if len(y_top30) else 0
        auc = folds_df.loc[folds_df["month"] == month, "auc"].iloc[0]
        monthly_t30_total.append(y_t30_total)
        print(f"    {month:<8}  {len(ysub):>4}  {auc:>6.3f}  "
              f"${y_base_total:>+7,.0f}  ${y_t30_total:>+7,.0f}  "
              f"${y_t30_total - y_base_total:>+7,.0f}")

    # Rolling 3-month consistency
    s = pd.Series(monthly_t30_total)
    roll3 = s.rolling(3, min_periods=1).sum()
    n_pos = (roll3 > 0).sum()
    n_total = len(roll3)
    print(f"\n  Rolling 3-month top-30% consistency: "
          f"{n_pos}/{n_total} ({n_pos/n_total:.1%}) positive  "
          f"(best ${roll3.max():+,.0f}  worst ${roll3.min():+,.0f})")

    print(f"\n{'='*78}")
    print(f"COMPARISON: full-feature WF vs top-{N_FEATURES} WF")
    print(f"{'='*78}")
    print(f"  Full-feature walk-forward (78 features):")
    print(f"    Combined OOS top30: -$11,650  "
          f"(2024 -$20K, 2025 +$2K, 2026 +$7K)")
    print(f"  Top-{N_FEATURES} walk-forward:")
    thresh30 = oos_df["p"].quantile(0.70)
    kept = oos_df[oos_df["p"] >= thresh30]
    y24 = oos_df[(oos_df["year"] == 2024) & (oos_df["p"] >= thresh30)]["pnl"].sum()
    y25 = oos_df[(oos_df["year"] == 2025) & (oos_df["p"] >= thresh30)]["pnl"].sum()
    y26 = oos_df[(oos_df["year"] == 2026) & (oos_df["p"] >= thresh30)]["pnl"].sum()
    print(f"    Combined OOS top30: ${kept['pnl'].sum():+,.0f}  "
          f"(2024 ${y24:+,.0f}, 2025 ${y25:+,.0f}, 2026 ${y26:+,.0f})")


if __name__ == "__main__":
    main()
