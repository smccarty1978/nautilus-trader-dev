"""Walk-forward V_A trade PnL ML — does ML add lift on 2024-2025?

Two non-overlapping out-of-sample evaluations:
  - Config A: train 2024, eval 2025   (2025 is a winning V_A year)
  - Config B: train 2024+2025, eval 2026   (same as ml_va_trade_pnl.py)

For each config, reports:
  - AUC train/val/OOS
  - OOS PnL by decile (mean, total, WR, bootstrap CI)
  - Filter variants (top 50/30/20/10/5%)
  - Combined cumulative PnL across 2025 and 2026 if we deployed
    the same filter (out-of-sample for both)

The aim is to test the user's hypothesis: does ML help where V_A is
already profitable (2024-2025) without destroying 2026?
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


YEARS = [2024, 2025, 2026]
SNAP_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet"
    for yr in YEARS
}
TRADE_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/trades.parquet"
    for yr in YEARS
}
OUT = Path("studies/v_a_excursion_regime/results_v0")
SEED = 42
VAL_FRAC = 0.20
N_BOOT = 2000


def load_bar1_trades(year: int) -> pd.DataFrame:
    snap = pd.read_parquet(SNAP_PATHS[year])
    b1 = snap[(snap["kind"] == "bar1_check")
                & (snap["became_trade"])
                & (snap["session"] == "RTH")].copy().reset_index(drop=True)
    trades = pd.read_parquet(TRADE_PATHS[year])
    trades_rth = trades[trades["session"] == "RTH"][[
        "decision_ts", "direction", "net_pnl", "gross_pnl", "hold_s",
        "exit_reason", "running_mfe", "running_mae",
    ]].copy()
    merged = b1.merge(
        trades_rth, on=["decision_ts", "direction"], how="inner")
    merged["year"] = year
    return merged


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
        "n": n,
        "mean": float(values.mean()),
        "total": float(values.sum()),
        "p05": float(np.percentile(boot, 5)),
        "p95": float(np.percentile(boot, 95)),
    }


def make_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    direction = df["direction"]
    atr = df["atr_1m"]
    atr_ok = atr > 0

    fb_rng = df["flip_bar_h"] - df["flip_bar_l"]
    df["fb_loc_in_range"] = np.where(
        fb_rng > 0, (df["flip_bar_c"] - df["flip_bar_l"]) / fb_rng, 0.5)
    df["fb_range_atr"] = np.where(atr_ok, fb_rng / atr, np.nan)
    fb_uw = df["flip_bar_h"] - df["flip_bar_c"]
    fb_lw = df["flip_bar_c"] - df["flip_bar_l"]
    df["fb_wick_against_atr"] = np.where(
        atr_ok, np.where(direction == 1, fb_uw, fb_lw) / atr, np.nan)
    df["fb_wick_with_atr"] = np.where(
        atr_ok, np.where(direction == 1, fb_lw, fb_uw) / atr, np.nan)
    df["fb_close_minus_mid_atr"] = np.where(
        atr_ok,
        (df["flip_bar_c"] - (df["flip_bar_h"] + df["flip_bar_l"]) / 2) / atr,
        np.nan,
    )
    b1_rng = df["bar1_h"] - df["bar1_l"]
    df["b1_loc_in_range"] = np.where(
        b1_rng > 0, (df["bar1_c"] - df["bar1_l"]) / b1_rng, 0.5)
    df["b1_range_atr"] = np.where(atr_ok, b1_rng / atr, np.nan)
    df["b1_body_atr"] = np.where(
        atr_ok, (df["bar1_c"] - df["bar1_o"]) * direction / atr, np.nan)
    df["b1_close_vs_flip_close_atr"] = np.where(
        atr_ok, (df["bar1_c"] - df["flip_bar_c"]) * direction / atr, np.nan)
    df["b1_hh_extent_atr"] = np.where(
        atr_ok,
        np.where(direction == 1,
                  df["bar1_h"] - df["flip_bar_h"],
                  df["flip_bar_l"] - df["bar1_l"]) / atr,
        np.nan,
    )
    b1_uw = df["bar1_h"] - df["bar1_c"]
    b1_lw = df["bar1_c"] - df["bar1_l"]
    df["b1_wick_against_atr"] = np.where(
        atr_ok, np.where(direction == 1, b1_uw, b1_lw) / atr, np.nan)
    df["b1_wick_with_atr"] = np.where(
        atr_ok, np.where(direction == 1, b1_lw, b1_uw) / atr, np.nan)
    df["b1_to_fb_range_ratio"] = np.where(
        fb_rng > 0, b1_rng / fb_rng, np.nan)

    for tf in ["30s", "1m", "3m", "5m"]:
        df[f"aligned_{tf}"] = (df[f"regime_{tf}"] == direction).astype(int)
    df["htf_alignment_score"] = (
        df["aligned_30s"] + df["aligned_1m"]
        + df["aligned_3m"] + df["aligned_5m"]
    )
    ct = pd.to_datetime(df["decision_ts"], unit="ns", utc=True
                          ).dt.tz_convert("America/Chicago")
    df["hour_ct"] = ct.dt.hour.astype(int)
    df["minute_ct"] = ct.dt.minute.astype(int)
    df["day_of_week"] = ct.dt.dayofweek.astype(int)
    df["minutes_since_rth_open"] = (
        ct.dt.hour.astype(int) * 60 + ct.dt.minute.astype(int)
        - (8 * 60 + 30)).astype(int)
    df["dist_to_vwap_dir_atr"] = (
        -df["dist_close_to_vwap_atr"] * direction)
    for lab in ["1m", "5m", "15m"]:
        df[f"vol_imbalance_dir_{lab}"] = (
            df[f"vol_imbalance_{lab}"] * direction)

    drop_cols = [
        "decision_ts", "bar_ts_event", "kind", "event_id",
        "session", "is_rth",
        "hhll_ok", "momentum_ok", "confirmed", "became_trade",
        "flip_bar_h", "flip_bar_l", "flip_bar_c",
        "bar1_h", "bar1_l", "bar1_o", "bar1_c",
        "trade_event_id", "trade_direction", "trade_fill_price",
        "trade_fill_ts", "trade_atr_at_signal",
        "elapsed_s", "cur_pnl_atr", "cur_mfe_atr", "cur_mae_atr",
        "cur_giveback_atr", "cur_close_price",
        "last_30s_close_ts", "last_1m_close_ts",
        "last_3m_close_ts", "last_5m_close_ts",
        "flip_direction",
        "event_close_px", "cum_vol_session",
        "close_30s", "close_1m", "close_3m", "close_5m",
        "vwap_value", "dist_close_to_vwap",
        "dist_close_to_vwap_upper_1sd", "dist_close_to_vwap_lower_1sd",
        "dist_close_to_vwap_upper_2sd", "dist_close_to_vwap_lower_2sd",
        "dist_close_to_vwap_upper_3sd", "dist_close_to_vwap_lower_3sd",
        "direction", "year",
        "target_va_win", "net_pnl", "gross_pnl", "hold_s",
        "exit_reason", "running_mfe", "running_mae",
    ]
    drop_cols = [c for c in drop_cols if c in df.columns]
    df = df.drop(columns=drop_cols)
    obj_cols = [c for c in df.columns if df[c].dtype == "object"]
    if obj_cols:
        df = df.drop(columns=obj_cols)
    return df


def fit_model(X_tr, y_tr, X_val, y_val):
    model = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1, verbose=-1)
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(50, verbose=False),
                          lgb.log_evaluation(0)])
    return model


def evaluate_oos(model, X_oos, y_oos, pnl_oos, name: str) -> dict:
    p_oos = model.predict_proba(X_oos)[:, 1]
    auc = roc_auc_score(y_oos, p_oos) if y_oos.nunique() > 1 else np.nan
    base_wr = float(y_oos.mean())
    base_mean = float(pnl_oos.mean())
    base_total = float(pnl_oos.sum())

    df = pd.DataFrame({"p": p_oos, "y": y_oos.values, "pnl": pnl_oos.values})
    df["decile"] = pd.qcut(df["p"].rank(method="first"), 10,
                              labels=False, duplicates="drop")

    print(f"\n  {name}")
    print(f"  AUC={auc:.4f}  base WR={base_wr:.3%}  "
          f"base mean=${base_mean:+.2f}  base total=${base_total:+,.0f}  "
          f"n={len(df):,}")

    print(f"\n  Decile PnL:")
    print(f"    {'dec':>4}  {'n':>5}  {'p':>7}  "
          f"{'mean_$':>9}  {'p05':>9}  {'p95':>9}  "
          f"{'total':>10}  {'WR':>5}")
    decile_rows = []
    for dec, grp in df.groupby("decile"):
        bs = bootstrap_mean(grp["pnl"].to_numpy())
        wr = (grp["pnl"] > 0).mean()
        pm = grp["p"].mean()
        print(f"    d{int(dec)+1:>2}    {bs['n']:>5,}  {pm:>7.4f}  "
              f"${bs['mean']:>+7.2f}  ${bs['p05']:>+7.2f}  "
              f"${bs['p95']:>+7.2f}  ${bs['total']:>+8,.0f}  "
              f"{wr:>4.1%}")
        decile_rows.append({"decile": int(dec) + 1, **bs, "wr": wr})

    print(f"\n  Filter variants:")
    print(f"    {'gate':<24}  {'kept':>5}  {'kept%':>6}  "
          f"{'mean_$':>9}  {'p05':>9}  {'p95':>9}  "
          f"{'total':>10}  {'WR':>5}  {'vs_base':>8}")
    filter_rows = []
    for q in [0.50, 0.30, 0.20, 0.10]:
        thresh = df["p"].quantile(1 - q)
        kept = df[df["p"] >= thresh]
        bs = bootstrap_mean(kept["pnl"].to_numpy())
        wr = (kept["pnl"] > 0).mean()
        vs_base = bs["mean"] - base_mean
        print(f"    top {q*100:>3.0f}% (p>={thresh:.4f})    "
              f"{len(kept):>5,}  {len(kept)/len(df):>5.1%}  "
              f"${bs['mean']:>+7.2f}  ${bs['p05']:>+7.2f}  "
              f"${bs['p95']:>+7.2f}  ${bs['total']:>+8,.0f}  "
              f"{wr:>4.1%}  ${vs_base:>+6.2f}")
        filter_rows.append({"gate": f"top_{int(q*100)}",
                              "kept_n": len(kept), **bs, "wr": wr,
                              "vs_base": vs_base, "thresh": thresh})

    return {
        "name": name, "auc": auc, "base_mean": base_mean,
        "base_total": base_total, "base_wr": base_wr, "n": len(df),
        "p_oos": p_oos, "pnl_oos": pnl_oos.values,
        "df": df, "decile_rows": decile_rows, "filter_rows": filter_rows,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("WALK-FORWARD V_A TRADE PNL ML  —  does ML help 2024-2025?")
    print("=" * 78)

    all_rows = []
    for yr in YEARS:
        df = load_bar1_trades(yr)
        df["target_va_win"] = (df["net_pnl"] > 0).astype(int)
        all_rows.append(df)
        print(f"  YEAR {yr}: {len(df):,} trades  "
              f"WR={df['target_va_win'].mean():.3%}  "
              f"mean=${df['net_pnl'].mean():+.2f}  "
              f"total=${df['net_pnl'].sum():+,.0f}")

    all_df = pd.concat(all_rows, ignore_index=True)
    n_pre = len(all_df)
    all_df = all_df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset=["decision_ts", "direction"], keep="first"
        ).reset_index(drop=True)
    print(f"\nDedupe: {n_pre:,} -> {len(all_df):,}")

    X = make_feature_matrix(all_df)
    y = all_df["target_va_win"]
    pnl = all_df["net_pnl"]
    yr_col = all_df["year"]

    forbidden = {"target_va_win", "net_pnl", "gross_pnl", "hold_s",
                  "exit_reason", "running_mfe", "running_mae",
                  "year", "confirmed", "became_trade"}
    leaked = forbidden.intersection(X.columns)
    assert not leaked, f"Label leak: {leaked}"
    print(f"\nFeature matrix shape: {X.shape}")

    results = {}

    for name, train_years, eval_years in [
        ("Config A: train 2024, score 2025", [2024], [2025]),
        ("Config B: train 2024+2025, score 2026", [2024, 2025], [2026]),
    ]:
        print(f"\n{'='*78}")
        print(f"{name}")
        print(f"{'='*78}")
        tr_mask = yr_col.isin(train_years)
        ev_mask = yr_col.isin(eval_years)
        X_train = X[tr_mask]
        y_train = y[tr_mask]
        X_eval = X[ev_mask]
        y_eval = y[ev_mask]
        pnl_eval = pnl[ev_mask]

        tr_dt = all_df.loc[tr_mask.values, "decision_ts"].to_numpy()
        order = np.argsort(tr_dt, kind="mergesort")
        X_train = X_train.iloc[order].reset_index(drop=True)
        y_train = y_train.iloc[order].reset_index(drop=True)
        tr_dt = tr_dt[order]

        n_val = int(len(X_train) * VAL_FRAC)
        n_tr = len(X_train) - n_val
        X_tr = X_train.iloc[:n_tr]
        y_tr = y_train.iloc[:n_tr]
        X_val = X_train.iloc[n_tr:]
        y_val = y_train.iloc[n_tr:]
        print(f"  train n={n_tr:,}  val n={n_val:,}  eval n={len(X_eval):,}")
        print(f"  train range: {pd.Timestamp(tr_dt[0], unit='ns')} .. "
              f"{pd.Timestamp(tr_dt[n_tr-1], unit='ns')}")
        print(f"  val   range: {pd.Timestamp(tr_dt[n_tr], unit='ns')} .. "
              f"{pd.Timestamp(tr_dt[-1], unit='ns')}")

        model = fit_model(X_tr, y_tr, X_val, y_val)
        p_train_auc = roc_auc_score(y_tr, model.predict_proba(X_tr)[:, 1])
        p_val_auc = roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])
        print(f"  best iter: {model.best_iteration_}  "
              f"train AUC={p_train_auc:.4f}  val AUC={p_val_auc:.4f}")

        res = evaluate_oos(model, X_eval, y_eval, pnl_eval,
                              name=f"OOS {eval_years[0]}")
        results[eval_years[0]] = res

    # ===== Combined across OOS years =====
    print(f"\n{'='*78}")
    print(f"COMBINED  —  applying ML filter across BOTH OOS years (2025+2026)")
    print(f"{'='*78}")
    combined_df = pd.concat([
        results[2025]["df"].assign(year=2025),
        results[2026]["df"].assign(year=2026),
    ], ignore_index=True)
    base_total = combined_df["pnl"].sum()
    base_mean = combined_df["pnl"].mean()
    base_wr = (combined_df["pnl"] > 0).mean()
    print(f"  Baseline (no ML, all trades 2025+2026): "
          f"n={len(combined_df):,}  mean=${base_mean:+.2f}  "
          f"total=${base_total:+,.0f}  WR={base_wr:.1%}")

    # Apply filter — using per-year threshold so each year's percentile is
    # consistent (Config A picks 2025's quantile, Config B picks 2026's).
    # Combine the kept rows.
    print(f"\n  Per-year filter (use each year's own quantile threshold):")
    print(f"    {'gate':<24}  {'kept':>5}  {'mean_$':>9}  "
          f"{'total':>10}  {'WR':>5}  {'2025':>10}  {'2026':>10}")
    for q in [0.50, 0.30, 0.20, 0.10]:
        kept_chunks = []
        for yr in [2025, 2026]:
            sub = results[yr]["df"]
            thresh = sub["p"].quantile(1 - q)
            kept_chunks.append(sub[sub["p"] >= thresh].assign(year=yr))
        kept = pd.concat(kept_chunks, ignore_index=True)
        if len(kept) == 0:
            continue
        wr = (kept["pnl"] > 0).mean()
        y25 = kept[kept["year"] == 2025]["pnl"].sum()
        y26 = kept[kept["year"] == 2026]["pnl"].sum()
        print(f"    top {q*100:>3.0f}%                {len(kept):>5,}  "
              f"${kept['pnl'].mean():>+7.2f}  "
              f"${kept['pnl'].sum():>+8,.0f}  "
              f"{wr:>4.1%}  ${y25:>+8,.0f}  ${y26:>+8,.0f}")

    # Apply filter using single global threshold (less common, but easier
    # to communicate: "set ML prob >= X")
    print(f"\n  Global filter (single threshold across both years):")
    print(f"    {'gate':<24}  {'kept':>5}  {'mean_$':>9}  "
          f"{'total':>10}  {'WR':>5}  {'2025':>10}  {'2026':>10}")
    for q in [0.50, 0.30, 0.20, 0.10]:
        thresh = combined_df["p"].quantile(1 - q)
        kept = combined_df[combined_df["p"] >= thresh]
        if len(kept) == 0: continue
        wr = (kept["pnl"] > 0).mean()
        y25 = kept[kept["year"] == 2025]["pnl"].sum()
        y26 = kept[kept["year"] == 2026]["pnl"].sum()
        print(f"    top {q*100:>3.0f}% (p>={thresh:.4f})  "
              f"{len(kept):>5,}  ${kept['pnl'].mean():>+7.2f}  "
              f"${kept['pnl'].sum():>+8,.0f}  "
              f"{wr:>4.1%}  ${y25:>+8,.0f}  ${y26:>+8,.0f}")

    print(f"\n{'='*78}")
    print(f"SUMMARY  —  V_A trade PnL ML, walk-forward")
    print(f"{'='*78}")
    for yr, res in results.items():
        print(f"  OOS {yr}: AUC={res['auc']:.4f}  "
              f"baseline mean=${res['base_mean']:+.2f}  "
              f"baseline total=${res['base_total']:+,.0f}  "
              f"baseline WR={res['base_wr']:.1%}  n={res['n']:,}")
    print(f"\n  Combined 2025+2026 baseline: "
          f"${base_total:+,.0f} (n={len(combined_df):,})")


if __name__ == "__main__":
    main()
