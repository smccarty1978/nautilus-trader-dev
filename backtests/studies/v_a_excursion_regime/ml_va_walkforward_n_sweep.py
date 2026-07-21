"""Sub-sweep N ∈ {25, 30, 35, 45, 50} around N=40 finding.

Runs the same monthly walk-forward pipeline at each N, prints a compact
summary table to compare top 50% / 30% / 10% PnL.

Confirms whether N=40 is on a smooth curve (real signal) or a noise
spike (unreliable optimum).
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
FS_END_MONTH = "2024-03"
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"
N_VALUES = [25, 30, 35, 45, 50]


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


def run_walkforward(X_full, y, pnl, all_df, top_feats, n_label=""):
    X = X_full[top_feats]
    ct = pd.to_datetime(all_df["decision_ts"], unit="ns", utc=True
                          ).dt.tz_convert("America/Chicago")
    yr_month = ct.dt.to_period("M")
    all_months = sorted(yr_month.unique())
    start_idx = next(i for i, m in enumerate(all_months)
                       if str(m) >= FIRST_SCORED_MONTH)
    oos_records = []
    fold_aucs = []
    monthly_t30_totals = []
    monthly_t50_totals = []
    for i in range(start_idx, len(all_months)):
        scoring_month = all_months[i]
        if str(scoring_month) > LAST_SCORED_MONTH:
            break
        train_mask = (yr_month < scoring_month).to_numpy()
        oos_mask = (yr_month == scoring_month).to_numpy()
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
        fold_aucs.append(auc)
        for k in range(n_oos):
            oos_records.append({
                "month": str(scoring_month),
                "p": float(p_oos[k]),
                "y": int(y_oos_actual[k]),
                "pnl": float(pnl_oos[k]),
            })
    oos_df = pd.DataFrame(oos_records)
    oos_df["year"] = oos_df["month"].str[:4].astype(int)
    base_total = oos_df["pnl"].sum()
    base_mean = oos_df["pnl"].mean()
    # Filter variants
    thresholds = {}
    for q in [0.50, 0.30, 0.20, 0.10]:
        thresh = oos_df["p"].quantile(1 - q)
        kept = oos_df[oos_df["p"] >= thresh]
        bs = bootstrap_mean(kept["pnl"].to_numpy())
        thresholds[q] = {
            "n": len(kept), "mean": bs["mean"], "p05": bs["p05"],
            "p95": bs["p95"], "total": bs["total"],
        }
    # Per-year top 30 and top 50
    thresh30 = oos_df["p"].quantile(0.70)
    thresh50 = oos_df["p"].quantile(0.50)
    per_year = {}
    for year in [2024, 2025, 2026]:
        ysub = oos_df[oos_df["year"] == year]
        t30 = ysub[ysub["p"] >= thresh30]
        t50 = ysub[ysub["p"] >= thresh50]
        per_year[year] = {
            "base_total": float(ysub["pnl"].sum()),
            "t30_total": float(t30["pnl"].sum()) if len(t30) else 0.0,
            "t50_total": float(t50["pnl"].sum()) if len(t50) else 0.0,
        }
    # Rolling-3 consistency on top 30
    by_month = oos_df.groupby("month")
    monthly = []
    for m, grp in by_month:
        kept = grp[grp["p"] >= thresh30]
        monthly.append(float(kept["pnl"].sum()) if len(kept) else 0.0)
    s = pd.Series(monthly)
    roll3 = s.rolling(3, min_periods=1).sum()
    n_pos = int((roll3 > 0).sum())
    n_total = int(len(roll3))
    return {
        "base_total": base_total, "base_mean": base_mean,
        "n_oos": len(oos_df),
        "thresholds": thresholds, "per_year": per_year,
        "mean_auc": float(np.nanmean(fold_aucs)),
        "rolling3_pos": n_pos, "rolling3_total": n_total,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print(f"N-SWEEP  —  N ∈ {N_VALUES} (around N=40 finding)")
    print("=" * 78)

    # Load data once
    all_rows = []
    for yr in b30.YEARS:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        df = b30.load_bar1_trades_with_p30(yr)
        print(f"  V_A confirmed RTH: {len(df):,}  ({time.time()-t0:.0f}s)")
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
    print(f"\nFull feature matrix: {X_full.shape}")

    # Initial feature ranking from Jan-Mar 2024 only
    ct = pd.to_datetime(all_df["decision_ts"], unit="ns", utc=True
                          ).dt.tz_convert("America/Chicago")
    yr_month = ct.dt.to_period("M")
    fs_mask = (yr_month <= FS_END_MONTH).to_numpy()
    X_fs_full = X_full[fs_mask]
    y_fs_full = y[fs_mask]
    fs_dts = all_df.loc[fs_mask, "decision_ts"].to_numpy()
    order = np.argsort(fs_dts, kind="mergesort")
    X_fs_full = X_fs_full.iloc[order].reset_index(drop=True)
    y_fs_full = y_fs_full.iloc[order].reset_index(drop=True)
    n_val = int(len(X_fs_full) * VAL_FRAC)
    n_tr = len(X_fs_full) - n_val
    X_fs_tr = X_fs_full.iloc[:n_tr]
    y_fs_tr = y_fs_full.iloc[:n_tr]
    X_fs_val = X_fs_full.iloc[n_tr:]
    y_fs_val = y_fs_full.iloc[n_tr:]
    fs_model = b30.fit_model(X_fs_tr, y_fs_tr, X_fs_val, y_fs_val)
    imp = pd.DataFrame({
        "feat": X_full.columns,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)

    # Run walk-forward for each N
    summary_rows = []
    for N in N_VALUES:
        print(f"\n{'='*78}\n  Running N = {N}\n{'='*78}")
        top_feats = imp.head(N)["feat"].tolist()
        t0 = time.time()
        res = run_walkforward(X_full, y, pnl, all_df, top_feats,
                                  n_label=f"N={N}")
        elapsed = time.time() - t0
        print(f"  Elapsed: {elapsed:.0f}s")
        print(f"  Mean fold AUC: {res['mean_auc']:.4f}  "
              f"OOS n={res['n_oos']:,}  "
              f"baseline mean=${res['base_mean']:+.2f}  "
              f"total=${res['base_total']:+,.0f}")
        for q in [0.50, 0.30, 0.20, 0.10]:
            t = res["thresholds"][q]
            print(f"    top {int(q*100):>2}% — n={t['n']:,}  "
                  f"mean=${t['mean']:+7.2f}  "
                  f"p05=${t['p05']:+7.2f}  "
                  f"total=${t['total']:+9,.0f}")
        print(f"  Per-year top-30%:  "
              f"2024 ${res['per_year'][2024]['t30_total']:+,.0f}  "
              f"2025 ${res['per_year'][2025]['t30_total']:+,.0f}  "
              f"2026 ${res['per_year'][2026]['t30_total']:+,.0f}")
        print(f"  Per-year top-50%:  "
              f"2024 ${res['per_year'][2024]['t50_total']:+,.0f}  "
              f"2025 ${res['per_year'][2025]['t50_total']:+,.0f}  "
              f"2026 ${res['per_year'][2026]['t50_total']:+,.0f}")
        print(f"  Rolling-3 positive: "
              f"{res['rolling3_pos']}/{res['rolling3_total']} "
              f"({res['rolling3_pos']/res['rolling3_total']:.0%})")
        summary_rows.append({
            "N": N, "mean_auc": res["mean_auc"],
            "base_total": res["base_total"],
            "top50_total": res["thresholds"][0.50]["total"],
            "top50_mean": res["thresholds"][0.50]["mean"],
            "top50_p05": res["thresholds"][0.50]["p05"],
            "top30_total": res["thresholds"][0.30]["total"],
            "top30_mean": res["thresholds"][0.30]["mean"],
            "top30_p05": res["thresholds"][0.30]["p05"],
            "top20_total": res["thresholds"][0.20]["total"],
            "top10_total": res["thresholds"][0.10]["total"],
            "y2024_t30": res["per_year"][2024]["t30_total"],
            "y2025_t30": res["per_year"][2025]["t30_total"],
            "y2026_t30": res["per_year"][2026]["t30_total"],
            "y2024_t50": res["per_year"][2024]["t50_total"],
            "y2025_t50": res["per_year"][2025]["t50_total"],
            "y2026_t50": res["per_year"][2026]["t50_total"],
            "rolling3_pos": res["rolling3_pos"],
        })

    # Final summary table
    print(f"\n{'='*78}")
    print(f"N-SWEEP SUMMARY (with N=20 and N=40 prior runs included)")
    print(f"{'='*78}")
    # Insert known prior runs for context
    prior = [
        {"N": 20, "top50_total": 2040, "top50_mean": 0.60, "top50_p05": -22.13,
         "top30_total": 24935, "top30_mean": 12.14, "top30_p05": -18.11,
         "top20_total": -12130, "top10_total": -12820,
         "y2024_t30": -12410, "y2025_t30": 55665, "y2026_t30": -18320,
         "y2024_t50": np.nan, "y2025_t50": np.nan, "y2026_t50": np.nan,
         "rolling3_pos": 12, "mean_auc": np.nan, "base_total": 22335},
        {"N": 40, "top50_total": 74870, "top50_mean": 21.76, "top50_p05": -1.20,
         "top30_total": 14935, "top30_mean": 7.21, "top30_p05": -20.50,
         "top20_total": 8465, "top10_total": 335,
         "y2024_t30": -10110, "y2025_t30": 29615, "y2026_t30": -4570,
         "y2024_t50": np.nan, "y2025_t50": np.nan, "y2026_t50": np.nan,
         "rolling3_pos": 13, "mean_auc": np.nan, "base_total": 22335},
        {"N": 90, "top50_total": 25625, "top50_mean": 7.49, "top50_p05": -15.86,
         "top30_total": -11650, "top30_mean": -5.65, "top30_p05": -33.15,
         "top20_total": -5945, "top10_total": 19365,
         "y2024_t30": -20550, "y2025_t30": 1935, "y2026_t30": 6965,
         "y2024_t50": np.nan, "y2025_t50": np.nan, "y2026_t50": np.nan,
         "rolling3_pos": 12, "mean_auc": np.nan, "base_total": 22335},
    ]
    combined = pd.DataFrame(summary_rows + prior).sort_values("N").reset_index(drop=True)
    combined.to_csv(OUT / "ml_walkforward_n_sweep.csv", index=False)

    print(f"  {'N':>3}  {'AUC':>6}  {'t50_$':>10}  {'t50_p05':>8}  "
          f"{'t30_$':>10}  {'t20_$':>10}  {'t10_$':>10}  "
          f"{'2026_t30':>10}")
    for _, row in combined.iterrows():
        auc_str = f"{row['mean_auc']:.4f}" if not pd.isna(row['mean_auc']) else "  —  "
        print(f"  {int(row['N']):>3}  {auc_str:>6}  "
              f"${row['top50_total']:>+8,.0f}  "
              f"${row['top50_p05']:>+6.2f}  "
              f"${row['top30_total']:>+8,.0f}  "
              f"${row['top20_total']:>+8,.0f}  "
              f"${row['top10_total']:>+8,.0f}  "
              f"${row['y2026_t30']:>+8,.0f}")

    print(f"\n  Wrote: {OUT/'ml_walkforward_n_sweep.csv'}")


if __name__ == "__main__":
    main()
