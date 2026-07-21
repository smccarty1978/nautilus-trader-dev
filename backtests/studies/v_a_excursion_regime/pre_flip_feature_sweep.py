"""Feature reduction sweep on augmented pre-flip candidates.

For each horizon (T-1, T-2, T-3) and each N in {97 (full), 50, 40, 30, 20}:
  1. Train a full-feature model on Jan-Mar 2024 (initial FS).
  2. Take top-N features by gain importance.
  3. Walk-forward train with those N features only.
  4. Aggregate OOS, report AUC, top-quantile lift, trade-sim PnL.

The dominant feature (`dist_to_1m_flip_threshold_atr_dir`) is KEPT in
this run — we want to see if predictive power survives as we shrink
the auxiliary feature set.

Per-horizon FS rankings are computed on each horizon's own labels.

Output: pre_flip_feature_sweep_summary.csv with one row per (H, N).
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
import pyarrow.parquet as pq
import lightgbm as lgb
from sklearn.metrics import roc_auc_score


OUT = Path("studies/v_a_excursion_regime/results_v0")
NQ_MULT = 20.0
COMMISSION_ONE_WAY = 5.0
SEED = 42
VAL_FRAC = 0.20
FS_END_MONTH = "2024-03"
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"
N_VALUES = [50, 40, 30, 20]


def feature_columns(df: pd.DataFrame) -> list[str]:
    drop = set([
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s",
        "close_3m", "close_5m",
        "vwap_value",
        "label_T1", "label_T2", "label_T3",
    ])
    feats = [c for c in df.columns if c not in drop]
    feats = [c for c in feats
              if df[c].dtype not in ("object", "datetime64[ns, UTC]")]
    return feats


def fit_model(X_tr, y_tr, X_val, y_val):
    model = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1,
        is_unbalance=True, verbose=-1)
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(50, verbose=False),
                          lgb.log_evaluation(0)])
    return model


def initial_feature_ranking(df, all_feats, label_col):
    """Train full-feature model on Jan-Mar 2024 only, return importance
    ranking."""
    fs_mask = (df["year_month"] <= FS_END_MONTH).to_numpy()
    fs_df = df[fs_mask].sort_values("close_ts_ns").reset_index(drop=True)
    n_val = int(len(fs_df) * VAL_FRAC)
    n_tr = len(fs_df) - n_val
    X_tr = fs_df.iloc[:n_tr][all_feats]
    y_tr = fs_df.iloc[:n_tr][label_col]
    X_val = fs_df.iloc[n_tr:][all_feats]
    y_val = fs_df.iloc[n_tr:][label_col]
    model = fit_model(X_tr, y_tr, X_val, y_val)
    imp = pd.DataFrame({
        "feat": all_feats,
        "gain": model.booster_.feature_importance(importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    return imp


def walk_forward(df, feats, label_col):
    months = sorted(df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(months)
                       if str(m) >= FIRST_SCORED_MONTH)
    fold_records = []
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
        X_tr = train_df.iloc[:n_tr_only][feats]
        y_tr = train_df.iloc[:n_tr_only][label_col]
        X_val = train_df.iloc[n_tr_only:][feats]
        y_val = train_df.iloc[n_tr_only:][label_col]
        oos_df = df[oos_mask]
        X_oos = oos_df[feats]
        y_oos = oos_df[label_col]
        if y_tr.sum() < 5 or y_val.sum() < 1:
            continue
        model = fit_model(X_tr, y_tr, X_val, y_val)
        p_oos = model.predict_proba(X_oos)[:, 1]
        auc = (roc_auc_score(y_oos, p_oos) if y_oos.nunique() > 1
                  else np.nan)
        fold_records.append({
            "month": str(scoring_month), "auc": float(auc),
        })
        for k in range(len(oos_df)):
            oos_records.append({
                "close_ts_ns": int(oos_df["close_ts_ns"].iloc[k]),
                "direction": int(oos_df["candidate_direction"].iloc[k]),
                "year": int(oos_df["year"].iloc[k]),
                "p_score": float(p_oos[k]),
                "label": int(y_oos.iloc[k]),
            })
    return pd.DataFrame(fold_records), pd.DataFrame(oos_records)


def quick_lift(oos):
    base = oos["label"].mean()
    auc = (roc_auc_score(oos["label"], oos["p_score"])
              if oos["label"].nunique() > 1 else np.nan)
    lifts = {}
    for q in [0.01, 0.02, 0.05, 0.10]:
        thresh = oos["p_score"].quantile(1 - q)
        kept = oos[oos["p_score"] >= thresh]
        prec = kept["label"].mean()
        lifts[q] = prec / max(base, 1e-9)
    return auc, base, lifts


def load_va_lookup():
    rows = []
    for yr in [2024, 2025, 2026]:
        snap = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet",
            columns=["kind", "decision_ts", "direction", "became_trade",
                       "session"])
        trades = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/trades.parquet",
            columns=["decision_ts", "direction", "exit_ts",
                       "exit_price", "session"])
        b1 = snap[(snap["kind"] == "bar1_check")
                    & (snap["became_trade"])
                    & (snap["session"] == "RTH")].copy()
        b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
        m = b1.merge(
            trades[trades["session"] == "RTH"][[
                "decision_ts", "direction", "exit_ts", "exit_price"]],
            on=["decision_ts", "direction"], how="inner")
        rows.append(m[[
            "flip_bar_close_ts", "direction", "exit_ts", "exit_price"]])
    va = pd.concat(rows, ignore_index=True).drop_duplicates(
        subset=["flip_bar_close_ts", "direction"])
    return va.set_index(["flip_bar_close_ts", "direction"])


def load_bars_by_year():
    out = {}
    for yr in [2024, 2025, 2026]:
        p = f"data/raw/NQ_v0_1s_{yr}{'_ytd' if yr == 2026 else ''}.parquet"
        df = pq.read_table(p, columns=["ts_event", "open"]).to_pandas()
        if "ts_event" not in df.columns:
            df = df.reset_index()
        df = df.sort_values("ts_event").reset_index(drop=True)
        if df["ts_event"].dt.tz is None:
            df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
        ts = df["ts_event"].dt.tz_localize(None
            ).astype("datetime64[ns]").astype("int64")
        out[yr] = {"ts": ts.to_numpy(), "o": df["open"].to_numpy()}
    return out


def trade_sim_top(oos, horizon, va_lookup, bars_by_year, q=0.10):
    thresh = oos["p_score"].quantile(1 - q)
    fired = oos[oos["p_score"] >= thresh]
    rows = []
    for _, fr in fired.iterrows():
        cts = int(fr["close_ts_ns"])
        d = int(fr["direction"])
        yr = int(fr["year"])
        bars = bars_by_year[yr]
        bars_ts = bars["ts"]; bars_o = bars["o"]
        i_entry = int(np.searchsorted(bars_ts, cts, side="left"))
        if i_entry >= len(bars_ts):
            continue
        entry_px = float(bars_o[i_entry])
        target_ts = cts + horizon * 60_000_000_000
        try:
            va = va_lookup.loc[(target_ts, d)]
            exit_px = float(va["exit_price"])
            is_va = True
        except KeyError:
            i_exit = int(np.searchsorted(bars_ts, target_ts, side="left"))
            if i_exit >= len(bars_ts):
                continue
            exit_px = float(bars_o[i_exit])
            is_va = False
        pnl = (exit_px - entry_px) * d * NQ_MULT - 2 * COMMISSION_ONE_WAY
        rows.append({"year": yr, "pnl": pnl, "is_va": is_va})
    sim = pd.DataFrame(rows)
    if len(sim) == 0:
        return {"n": 0, "total": 0, "mean": 0, "wr": 0,
                "va_rate": 0, "y24": 0, "y25": 0, "y26": 0}
    return {
        "n": len(sim),
        "total": float(sim["pnl"].sum()),
        "mean": float(sim["pnl"].mean()),
        "wr": float((sim["pnl"] > 0).mean()),
        "va_rate": float(sim["is_va"].mean()),
        "y24": float(sim[sim["year"] == 2024]["pnl"].sum()),
        "y25": float(sim[sim["year"] == 2025]["pnl"].sum()),
        "y26": float(sim[sim["year"] == 2026]["pnl"].sum()),
    }


def main():
    t0 = time.time()
    print("=" * 78)
    print("FEATURE REDUCTION SWEEP — augmented (97f) → 50/40/30/20")
    print("=" * 78)

    df = pd.read_parquet(OUT / "pre_flip_candidates_augmented.parquet")
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    print(f"\nLoaded {len(df):,} augmented candidates")
    all_feats = feature_columns(df)
    print(f"  full feature count: {len(all_feats)}")

    # Initial FS ranking per horizon
    rankings = {}
    for H in [1, 2, 3]:
        print(f"\n  Computing FS ranking for T-{H}...", flush=True)
        rankings[H] = initial_feature_ranking(
            df, all_feats, f"label_T{H}")
        print(f"    top 10 features:")
        for _, row in rankings[H].head(10).iterrows():
            print(f"      {row['feat']:<42}  gain={row['gain']:>8.0f}")

    va_lookup = load_va_lookup()
    bars_by_year = load_bars_by_year()
    print(f"\n  V_A flip outcomes: {len(va_lookup):,}")

    summary_rows = []
    # Run full-97 baseline + reduced N values
    for H in [1, 2, 3]:
        print(f"\n{'='*78}\nHORIZON T-{H}\n{'='*78}")
        for N in [len(all_feats)] + N_VALUES:
            if N == len(all_feats):
                feats = all_feats
                tag = "full"
            else:
                feats = rankings[H].head(N)["feat"].tolist()
                tag = f"top{N}"
            t1 = time.time()
            folds, oos = walk_forward(df, feats, f"label_T{H}")
            auc, base, lifts = quick_lift(oos)
            sim10 = trade_sim_top(oos, H, va_lookup, bars_by_year, 0.10)
            sim5 = trade_sim_top(oos, H, va_lookup, bars_by_year, 0.05)
            print(f"\n  N={N} ({tag})  AUC={auc:.4f}  "
                  f"top10_lift={lifts[0.10]:.2f}x  "
                  f"top5_lift={lifts[0.05]:.2f}x  "
                  f"top10_PnL=${sim10['total']:+,.0f} "
                  f"(${sim10['mean']:+.2f}/tr)  "
                  f"({time.time()-t1:.0f}s)")
            print(f"    2024 ${sim10['y24']:+,.0f}  "
                  f"2025 ${sim10['y25']:+,.0f}  "
                  f"2026 ${sim10['y26']:+,.0f}")
            summary_rows.append({
                "horizon": H, "N": N, "tag": tag, "auc": auc,
                "base_rate": base,
                "lift_1p": lifts[0.01], "lift_2p": lifts[0.02],
                "lift_5p": lifts[0.05], "lift_10p": lifts[0.10],
                "sim10_n": sim10["n"], "sim10_total": sim10["total"],
                "sim10_mean": sim10["mean"], "sim10_wr": sim10["wr"],
                "sim10_va_rate": sim10["va_rate"],
                "sim10_y24": sim10["y24"], "sim10_y25": sim10["y25"],
                "sim10_y26": sim10["y26"],
                "sim5_n": sim5["n"], "sim5_total": sim5["total"],
                "sim5_mean": sim5["mean"],
                "sim5_y26": sim5["y26"],
            })

    # Final summary table
    print(f"\n{'='*78}\nFEATURE REDUCTION SUMMARY\n{'='*78}")
    print(f"  {'H':>3}  {'N':>4}  {'AUC':>6}  {'lift10':>6}  "
          f"{'lift5':>6}  {'PnL_t10':>9}  {'$/tr_t10':>9}  "
          f"{'VA%':>5}  {'2026_t10':>9}  {'2026_t5':>9}")
    for r in summary_rows:
        print(f"  T-{r['horizon']:<1}  {r['N']:>4}  {r['auc']:>6.4f}  "
              f"{r['lift_10p']:>5.2f}x  {r['lift_5p']:>5.2f}x  "
              f"${r['sim10_total']:>+7,.0f}  ${r['sim10_mean']:>+7.2f}  "
              f"{r['sim10_va_rate']*100:>4.1f}%  "
              f"${r['sim10_y26']:>+7,.0f}  ${r['sim5_y26']:>+7,.0f}")

    sdf = pd.DataFrame(summary_rows)
    sdf.to_csv(OUT / "pre_flip_feature_sweep_summary.csv", index=False)
    print(f"\nSaved: {OUT / 'pre_flip_feature_sweep_summary.csv'}")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
