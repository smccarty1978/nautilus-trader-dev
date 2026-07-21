"""Test T-2 confidence as secondary filter on T-1 top-10% trades.

Steps:
1. Retrain T-2 N=30 walk-forward (best AUC from feature sweep)
2. Save per-candidate T-2 OOS predictions
3. Join T-2 scores to the 1,177 NT MBP-1 trades (T-1 top-10% 2026)
4. Slice by T-2 quintile (Q1=lowest, Q5=highest T-2 score)
5. Report PnL / $/tr / WR / VA-confirm rate per quintile

Hypothesis: If both T-2 and T-1 agree (Q5 of T-2 within T-1 top-10%),
the trades concentrate the V_A-confirm cohort that drives the edge.
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


OUT = Path("studies/v_a_excursion_regime/results_v0")
TRADES_PATH = ("backtests/pre_flip_T1/results/"
                  "nt_mbp1_2026_top10_N20/trades_all_months.parquet")
N_FEATURES = 30
SEED = 42
VAL_FRAC = 0.20
FS_END_MONTH = "2024-03"
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"


def feature_columns(df):
    drop = set([
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s", "close_3m", "close_5m",
        "vwap_value",
        "label_T1", "label_T2", "label_T3",
    ])
    feats = [c for c in df.columns if c not in drop]
    feats = [c for c in feats
              if df[c].dtype not in ("object", "datetime64[ns, UTC]")]
    return feats


def fit_model(X_tr, y_tr, X_val, y_val):
    m = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1,
        is_unbalance=True, verbose=-1)
    m.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
          callbacks=[lgb.early_stopping(50, verbose=False),
                      lgb.log_evaluation(0)])
    return m


def main():
    t0 = time.time()
    print("Training T-2 N=30 walk-forward")

    df = pd.read_parquet(OUT / "pre_flip_candidates_augmented.parquet")
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    all_feats = feature_columns(df)

    # FS on Jan-Mar 2024 for T-2
    fs_df = df[df["year_month"] <= FS_END_MONTH].sort_values(
        "close_ts_ns").reset_index(drop=True)
    n_val = int(len(fs_df) * VAL_FRAC)
    n_tr = len(fs_df) - n_val
    fs_model = fit_model(
        fs_df.iloc[:n_tr][all_feats], fs_df.iloc[:n_tr]["label_T2"],
        fs_df.iloc[n_tr:][all_feats], fs_df.iloc[n_tr:]["label_T2"])
    imp = pd.DataFrame({
        "feat": all_feats,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    top_feats = imp.head(N_FEATURES)["feat"].tolist()
    print(f"  Top {N_FEATURES} T-2 features (first 10):")
    for i, f in enumerate(top_feats[:10], 1):
        print(f"    {i:>2}. {f}")

    # Walk-forward
    months = sorted(df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(months)
                       if str(m) >= FIRST_SCORED_MONTH)
    oos_records = []
    for i in range(start_idx, len(months)):
        scoring_month = months[i]
        if str(scoring_month) > LAST_SCORED_MONTH:
            break
        train_mask = df["year_month"] < scoring_month
        oos_mask = df["year_month"] == scoring_month
        if int(train_mask.sum()) < 500 or int(oos_mask.sum()) < 20:
            continue
        train_df = df[train_mask].sort_values("close_ts_ns")
        n_val = int(len(train_df) * VAL_FRAC)
        n_tr_only = len(train_df) - n_val
        X_tr = train_df.iloc[:n_tr_only][top_feats]
        y_tr = train_df.iloc[:n_tr_only]["label_T2"]
        X_val = train_df.iloc[n_tr_only:][top_feats]
        y_val = train_df.iloc[n_tr_only:]["label_T2"]
        if y_tr.sum() < 5 or y_val.sum() < 1:
            continue
        model = fit_model(X_tr, y_tr, X_val, y_val)
        oos_df = df[oos_mask]
        p_oos = model.predict_proba(oos_df[top_feats])[:, 1]
        for k in range(len(oos_df)):
            oos_records.append({
                "close_ts_ns": int(oos_df["close_ts_ns"].iloc[k]),
                "direction": int(oos_df["candidate_direction"].iloc[k]),
                "p_T2": float(p_oos[k]),
                "label_T2": int(oos_df["label_T2"].iloc[k]),
            })
    t2 = pd.DataFrame(oos_records)
    t2.to_parquet(OUT / "pre_flip_T2_n30_oos.parquet", index=False)
    print(f"  T-2 OOS predictions: {len(t2):,}  "
          f"({time.time()-t0:.0f}s)")

    # Join to NT MBP-1 trades
    trades = pd.read_parquet(TRADES_PATH)
    trades = trades[trades["exit_filled"]].copy()
    trades["close_ts_ns"] = trades["entry_ts_ns"].astype("int64")
    print(f"\n  Loaded {len(trades):,} MBP-1 trades")
    merged = trades.merge(t2, on=["close_ts_ns", "direction"],
                              how="left")
    n_missing = merged["p_T2"].isna().sum()
    print(f"  Joined; missing T-2 score: {n_missing}")
    merged = merged.dropna(subset=["p_T2"])

    # Slice by T-2 quintile WITHIN T-1 top-10% population
    merged["t2_quintile"] = pd.qcut(merged["p_T2"], 5,
                                          labels=["Q1", "Q2", "Q3",
                                                    "Q4", "Q5"])
    print("\n" + "=" * 78)
    print("T-1 top-10% trades sliced by T-2 quintile (NT MBP-1 PnL)")
    print("=" * 78)
    print(f"{'Quint':<6} {'n':>5} {'total':>10} {'$/tr':>9} "
          f"{'WR':>6} {'p_T2 mean':>10} {'VA%':>6} {'VA$/tr':>9}")
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        sub = merged[merged["t2_quintile"] == q]
        if len(sub) == 0:
            continue
        va = sub[sub["is_va_confirm"]]
        print(f"{q:<6} {len(sub):>5} "
              f"${sub['net_pnl'].sum():>+9,.0f} "
              f"${sub['net_pnl'].mean():>+7.2f} "
              f"{(sub['net_pnl']>0).mean():>5.1%} "
              f"{sub['p_T2'].mean():>9.4f} "
              f"{sub['is_va_confirm'].mean():>5.1%} "
              f"${va['net_pnl'].mean() if len(va) else 0:>+7.2f}")

    # Combined view — what does the full population look like in each quintile?
    print("\n" + "=" * 78)
    print("Cohort split within each T-2 quintile")
    print("=" * 78)
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        sub = merged[merged["t2_quintile"] == q]
        va = sub[sub["is_va_confirm"]]
        nf = sub[~sub["is_va_confirm"]]
        print(f"\n  {q}: n={len(sub)}  p_T2 range "
              f"[{sub['p_T2'].min():.4f}, {sub['p_T2'].max():.4f}]")
        print(f"    VA-confirm n={len(va):>3}: "
              f"${va['net_pnl'].sum():>+8,.0f}  "
              f"${va['net_pnl'].mean() if len(va) else 0:>+7.2f}/tr  "
              f"WR={(va['net_pnl']>0).mean() if len(va) else 0:.1%}")
        print(f"    No-flip   n={len(nf):>3}: "
              f"${nf['net_pnl'].sum():>+8,.0f}  "
              f"${nf['net_pnl'].mean() if len(nf) else 0:>+7.2f}/tr  "
              f"WR={(nf['net_pnl']>0).mean() if len(nf) else 0:.1%}")

    # Top quintile alone vs the headline
    q5 = merged[merged["t2_quintile"] == "Q5"]
    q4_q5 = merged[merged["t2_quintile"].isin(["Q4", "Q5"])]
    print("\n" + "=" * 78)
    print("Filter scenarios (T-2 quintile within T-1 top-10%)")
    print("=" * 78)
    print(f"Baseline (all T-1 top-10%): "
          f"n={len(merged):>4}  "
          f"${merged['net_pnl'].sum():>+7,.0f}  "
          f"${merged['net_pnl'].mean():>+6.2f}/tr  "
          f"VA={merged['is_va_confirm'].mean():>5.1%}")
    print(f"T-2 Q5 only:                "
          f"n={len(q5):>4}  "
          f"${q5['net_pnl'].sum():>+7,.0f}  "
          f"${q5['net_pnl'].mean():>+6.2f}/tr  "
          f"VA={q5['is_va_confirm'].mean():>5.1%}")
    print(f"T-2 Q4+Q5:                  "
          f"n={len(q4_q5):>4}  "
          f"${q4_q5['net_pnl'].sum():>+7,.0f}  "
          f"${q4_q5['net_pnl'].mean():>+6.2f}/tr  "
          f"VA={q4_q5['is_va_confirm'].mean():>5.1%}")

    merged.to_parquet(OUT / "t2_quintile_analysis.parquet", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
