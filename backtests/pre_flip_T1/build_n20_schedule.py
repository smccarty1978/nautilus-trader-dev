"""Build the NT schedule for T-1 N=20 top 10% on 2026 OOS.

Steps:
1. Load augmented pre-flip candidates (97 features)
2. Compute initial T-1 feature ranking on Jan-Mar 2024 (FS data)
3. Take top 20 features
4. Walk-forward train T-1 using only those 20 features
5. Save OOS predictions
6. Filter to 2026 top-10% by GLOBAL threshold
7. Resolve exits (V_A confirm at T+60s OR bar-close fallback)
8. Save schedule parquet for NT runners

Reuses logic from pre_flip_feature_sweep.py and build_schedule.py.
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


OUT = Path("studies/v_a_excursion_regime/results_v0")
SCHEDULE_DIR = Path("backtests/pre_flip_T1/results")
N_FEATURES = 20
SEED = 42
VAL_FRAC = 0.20
FS_END_MONTH = "2024-03"
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"
TOP_QUANTILE = 0.10
HORIZON_S = 60


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
    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    print("Building T-1 N=20 schedule for 2026 OOS top-10%")

    df = pd.read_parquet(OUT / "pre_flip_candidates_augmented.parquet")
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    print(f"  Loaded {len(df):,} candidates")
    all_feats = feature_columns(df)
    print(f"  Full feature count: {len(all_feats)}")

    # Initial FS on Jan-Mar 2024 for T-1
    fs_mask = (df["year_month"] <= FS_END_MONTH).to_numpy()
    fs_df = df[fs_mask].sort_values("close_ts_ns").reset_index(drop=True)
    n_val = int(len(fs_df) * VAL_FRAC)
    n_tr = len(fs_df) - n_val
    fs_model = fit_model(
        fs_df.iloc[:n_tr][all_feats], fs_df.iloc[:n_tr]["label_T1"],
        fs_df.iloc[n_tr:][all_feats], fs_df.iloc[n_tr:]["label_T1"])
    imp = pd.DataFrame({
        "feat": all_feats,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    top_feats = imp.head(N_FEATURES)["feat"].tolist()
    print(f"\n  Top {N_FEATURES} features:")
    for i, f in enumerate(top_feats, 1):
        print(f"    {i:>2}. {f}")

    # Walk-forward train T-1 N=20
    print(f"\n  Walk-forward T-1 N=20 ...")
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
        n_train = int(train_mask.sum())
        n_oos = int(oos_mask.sum())
        if n_train < 500 or n_oos < 20:
            continue
        train_df = df[train_mask].sort_values("close_ts_ns")
        n_val = int(len(train_df) * VAL_FRAC)
        n_tr_only = len(train_df) - n_val
        X_tr = train_df.iloc[:n_tr_only][top_feats]
        y_tr = train_df.iloc[:n_tr_only]["label_T1"]
        X_val = train_df.iloc[n_tr_only:][top_feats]
        y_val = train_df.iloc[n_tr_only:]["label_T1"]
        oos_df = df[oos_mask]
        X_oos = oos_df[top_feats]
        y_oos = oos_df["label_T1"]
        if y_tr.sum() < 5 or y_val.sum() < 1:
            continue
        model = fit_model(X_tr, y_tr, X_val, y_val)
        p_oos = model.predict_proba(X_oos)[:, 1]
        for k in range(len(oos_df)):
            oos_records.append({
                "close_ts_ns": int(oos_df["close_ts_ns"].iloc[k]),
                "direction": int(oos_df["candidate_direction"].iloc[k]),
                "year": int(oos_df["year"].iloc[k]),
                "p_score": float(p_oos[k]),
                "label": int(y_oos.iloc[k]),
            })
    oos = pd.DataFrame(oos_records)
    print(f"  OOS predictions: {len(oos):,}")
    oos.to_parquet(OUT / "pre_flip_T1_n20_oos.parquet", index=False)

    # Global top-10% threshold + filter to 2026
    thresh = oos["p_score"].quantile(1 - TOP_QUANTILE)
    fired_2026 = oos[(oos["p_score"] >= thresh)
                        & (oos["year"] == 2026)].copy()
    fired_2026 = fired_2026.sort_values("close_ts_ns").reset_index(drop=True)
    print(f"  Global top-10% threshold: p >= {thresh:.4f}")
    print(f"  Fired in 2026: {len(fired_2026):,}")

    # Build entry/exit timestamps + outcome
    fired_2026["entry_ts_ns"] = fired_2026["close_ts_ns"]
    fired_2026["target_flip_ts_ns"] = (
        fired_2026["close_ts_ns"] + HORIZON_S * 1_000_000_000)

    # Load V_A confirmed flips for 2026
    snap_2026 = pd.read_parquet(
        "collectors/collector_v2/results/v_a_v0_2026/snapshots_with_vol_vwap.parquet",
        columns=["kind", "decision_ts", "direction", "became_trade",
                   "session"])
    trades_2026 = pd.read_parquet(
        "collectors/collector_v2/results/v_a_v0_2026/trades.parquet",
        columns=["decision_ts", "direction", "exit_ts", "atr_at_signal",
                   "fill_price", "exit_price", "session"])
    b1 = snap_2026[(snap_2026["kind"] == "bar1_check")
                      & (snap_2026["became_trade"])
                      & (snap_2026["session"] == "RTH")].copy()
    b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
    va = b1.merge(
        trades_2026[trades_2026["session"] == "RTH"][[
            "decision_ts", "direction", "exit_ts", "atr_at_signal"]],
        on=["decision_ts", "direction"], how="inner")
    va_lookup = va.set_index(["flip_bar_close_ts", "direction"])

    cands = pd.read_parquet(
        OUT / "pre_flip_candidates_augmented.parquet")
    cand_lookup = cands.set_index(
        ["close_ts_ns", "candidate_direction"])

    exit_ts_list = []
    is_va_list = []
    atr_list = []
    close_at_signal = []
    for _, fr in fired_2026.iterrows():
        target = int(fr["target_flip_ts_ns"])
        d = int(fr["direction"])
        cts = int(fr["close_ts_ns"])
        try:
            va_row = va_lookup.loc[(target, d)]
            exit_ts_list.append(int(va_row["exit_ts"]))
            is_va_list.append(True)
            atr_list.append(float(va_row["atr_at_signal"]))
        except KeyError:
            exit_ts_list.append(target)
            is_va_list.append(False)
            try:
                atr_list.append(float(
                    cand_lookup.loc[(cts, d), "atr_1m"]))
            except KeyError:
                atr_list.append(np.nan)
        try:
            close_at_signal.append(float(
                cand_lookup.loc[(cts, d), "close_1m"]))
        except KeyError:
            close_at_signal.append(np.nan)

    fired_2026["exit_ts_ns"] = exit_ts_list
    fired_2026["is_va_confirm"] = is_va_list
    fired_2026["atr_at_signal"] = atr_list
    fired_2026["close_1m_at_signal"] = close_at_signal
    fired_2026["year"] = 2026
    fired_2026["month"] = pd.to_datetime(
        fired_2026["entry_ts_ns"], unit="ns",
        utc=True).dt.month

    schedule = fired_2026[[
        "entry_ts_ns", "exit_ts_ns", "direction", "atr_at_signal",
        "p_score", "label", "is_va_confirm", "close_1m_at_signal",
        "year", "month",
    ]].copy()
    out_path = SCHEDULE_DIR / "schedule_T1_n20_2026_top10.parquet"
    schedule.to_parquet(out_path, index=False)
    print(f"\n  Wrote {len(schedule):,} trades to {out_path}")
    print(f"  VA-confirm rate: {schedule['is_va_confirm'].mean():.1%}")
    print(f"  Per-month: "
          f"{schedule['month'].value_counts().sort_index().to_dict()}")
    print(f"  Per-direction: "
          f"{schedule['direction'].value_counts().to_dict()}")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
