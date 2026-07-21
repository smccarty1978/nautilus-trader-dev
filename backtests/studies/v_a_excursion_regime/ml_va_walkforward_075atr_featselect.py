"""Feature-reduction study on the 0.75-ATR walk-forward ML.

For each N in {78 (full), 25, 20, 15, 10}, retrain the walk-forward
model using only the top-N features (selected by gain importance from
the full-feature Config B model) and report:
  - AUC train/val/OOS for Config A and Config B
  - Top-30% filter PnL on OOS 2025 and OOS 2026
  - Combined 2025+2026 with global threshold
  - Feature list at each N

Goal: see how aggressively we can shrink the input space without
hurting the OOS PnL signal we found in the full-feature run.

Reuses label and feature-engineering from
`ml_va_walkforward_075atr.py` (uses the same target_unr075 label
computed from 1s bar open at entry_ts + 300s).
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


YEARS = [2024, 2025, 2026]
SNAP_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet"
    for yr in YEARS
}
TRADE_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/trades.parquet"
    for yr in YEARS
}
ONE_S_PATHS = {
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}
OUT = Path("studies/v_a_excursion_regime/results_v0")

CP_OFFSET_S = 300
THRESHOLD_ATR = 0.75
SEED = 42
VAL_FRAC = 0.20
N_BOOT = 2000
FEATURE_COUNTS = [25, 20, 15, 10]   # plus full pass at the start


def load_1s_oc(path: str) -> pd.DataFrame:
    df = pq.read_table(path, columns=["ts_event", "open"]).to_pandas()
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    else:
        df["ts_event"] = df["ts_event"].dt.tz_convert("UTC")
    df["ts_event_ns"] = df["ts_event"].dt.tz_localize(None
        ).astype("datetime64[ns]").astype("int64")
    assert df["ts_event_ns"].iloc[0] > 1_500_000_000_000_000_000
    return df


def compute_label_unr_5m(b1_trades: pd.DataFrame, bars: pd.DataFrame):
    bars_ts = bars["ts_event_ns"].to_numpy()
    bars_o = bars["open"].to_numpy()
    n = len(b1_trades)
    label = np.zeros(n, dtype=int)
    unr_atr = np.full(n, np.nan)
    entry_ts = b1_trades["entry_ts"].to_numpy(dtype=np.int64)
    fill_price = b1_trades["fill_price"].to_numpy()
    direction = b1_trades["direction"].to_numpy(dtype=np.int64)
    atr = b1_trades["atr_at_signal"].to_numpy()
    exit_ts = b1_trades["exit_ts"].to_numpy(dtype=np.int64)
    for k in range(n):
        a = float(atr[k])
        if not (np.isfinite(a) and a > 0):
            continue
        cp_ts = int(entry_ts[k]) + CP_OFFSET_S * 1_000_000_000
        if cp_ts >= int(exit_ts[k]):
            continue
        i_hi = int(np.searchsorted(bars_ts, cp_ts, side="left"))
        if i_hi >= len(bars_ts):
            continue
        price = float(bars_o[i_hi])
        pnl_atr = (price - float(fill_price[k])) * int(direction[k]) / a
        unr_atr[k] = pnl_atr
        label[k] = int(pnl_atr >= THRESHOLD_ATR)
    return label, unr_atr


def load_bar1_trades(year: int) -> pd.DataFrame:
    snap = pd.read_parquet(SNAP_PATHS[year])
    b1 = snap[(snap["kind"] == "bar1_check")
                & (snap["became_trade"])
                & (snap["session"] == "RTH")].copy().reset_index(drop=True)
    trades = pd.read_parquet(TRADE_PATHS[year])
    trades_rth = trades[trades["session"] == "RTH"][[
        "decision_ts", "direction", "entry_ts", "fill_price", "exit_ts",
        "exit_price", "atr_at_signal", "net_pnl", "gross_pnl", "hold_s",
        "exit_reason", "running_mfe", "running_mae",
    ]].copy()
    merged = b1.merge(
        trades_rth, on=["decision_ts", "direction"], how="inner")
    bars = load_1s_oc(ONE_S_PATHS[year])
    label, unr_atr = compute_label_unr_5m(merged, bars)
    merged["target_unr075"] = label
    merged["unr_5m_atr"] = unr_atr
    merged["year"] = year
    return merged


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
        np.nan)
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
                  df["flip_bar_l"] - df["bar1_l"]) / atr, np.nan)
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
        "target_unr075", "unr_5m_atr",
        "entry_ts", "fill_price", "exit_ts", "exit_price",
        "atr_at_signal", "net_pnl", "gross_pnl", "hold_s",
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


def split_train_val(X_full: pd.DataFrame, y_full: pd.Series, dt: np.ndarray):
    order = np.argsort(dt, kind="mergesort")
    X = X_full.iloc[order].reset_index(drop=True)
    y = y_full.iloc[order].reset_index(drop=True)
    n_val = int(len(X) * VAL_FRAC)
    n_tr = len(X) - n_val
    return (X.iloc[:n_tr], y.iloc[:n_tr], X.iloc[n_tr:], y.iloc[n_tr:],
              dt[order], n_tr)


def evaluate(model, X_oos: pd.DataFrame, y_oos: pd.Series,
              pnl_oos: pd.Series, year: int) -> dict:
    p = model.predict_proba(X_oos)[:, 1]
    auc = roc_auc_score(y_oos, p) if y_oos.nunique() > 1 else np.nan
    df = pd.DataFrame({"p": p, "y_unr": y_oos.values,
                          "pnl": pnl_oos.values})
    # Compute per-decile and top-30% filter
    df["decile"] = pd.qcut(df["p"].rank(method="first"), 10,
                              labels=False, duplicates="drop")
    base_mean = float(pnl_oos.mean())
    base_total = float(pnl_oos.sum())
    top30 = df.nlargest(int(len(df) * 0.30), "p")
    top20 = df.nlargest(int(len(df) * 0.20), "p")
    top10 = df.nlargest(int(len(df) * 0.10), "p")
    return {
        "year": year,
        "auc": auc,
        "base_mean": base_mean,
        "base_total": base_total,
        "n_oos": len(df),
        "p_oos": p,
        "top30_n": len(top30),
        "top30_mean": float(top30["pnl"].mean()),
        "top30_total": float(top30["pnl"].sum()),
        "top30_wr": float((top30["pnl"] > 0).mean()),
        "top30_unr_pass": float(top30["y_unr"].mean()),
        "top20_n": len(top20),
        "top20_total": float(top20["pnl"].sum()),
        "top20_mean": float(top20["pnl"].mean()),
        "top10_n": len(top10),
        "top10_total": float(top10["pnl"].sum()),
        "top10_mean": float(top10["pnl"].mean()),
        "df": df,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("FEATURE-REDUCTION STUDY  —  0.75-ATR walk-forward ML")
    print("=" * 78)

    # --- Load data once ---
    all_rows = []
    for yr in YEARS:
        df = load_bar1_trades(yr)
        all_rows.append(df)
        print(f"  YEAR {yr}: {len(df):,} trades  "
              f"0.75ATR pass={df['target_unr075'].mean():.3%}  "
              f"PnL mean=${df['net_pnl'].mean():+.2f}  "
              f"total=${df['net_pnl'].sum():+,.0f}")
    all_df = pd.concat(all_rows, ignore_index=True)
    n_pre = len(all_df)
    all_df = all_df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset=["decision_ts", "direction"], keep="first"
        ).reset_index(drop=True)
    print(f"\nDedupe: {n_pre:,} -> {len(all_df):,}")

    X_full = make_feature_matrix(all_df)
    y = all_df["target_unr075"]
    pnl = all_df["net_pnl"]
    yr_col = all_df["year"]
    forbidden = {"target_unr075", "unr_5m_atr", "net_pnl", "gross_pnl",
                 "hold_s", "exit_reason", "running_mfe", "running_mae",
                 "entry_ts", "fill_price", "exit_ts", "exit_price",
                 "atr_at_signal", "year", "confirmed", "became_trade"}
    leaked = forbidden.intersection(X_full.columns)
    assert not leaked, f"Label leak: {leaked}"
    print(f"\nFull feature matrix: {X_full.shape}")

    # --- Step 1: Train Config B with all features to derive importance ---
    is_mask = yr_col.isin([2024, 2025]).values
    oos_b_mask = (yr_col == 2026).values
    is_a_mask = (yr_col == 2024).values
    oos_a_mask = (yr_col == 2025).values

    print(f"\n{'='*78}")
    print(f"STEP 1: Train full-feature Config B (2024+25 -> 2026) "
          f"for importance ranking")
    print(f"{'='*78}")
    dt_is_b = all_df.loc[is_mask, "decision_ts"].to_numpy()
    X_tr_b, y_tr_b, X_val_b, y_val_b, _, _ = split_train_val(
        X_full[is_mask], y[is_mask], dt_is_b)
    full_model_b = fit_model(X_tr_b, y_tr_b, X_val_b, y_val_b)
    importance = pd.DataFrame({
        "feat": X_full.columns,
        "gain": full_model_b.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    importance.to_csv(OUT / "ml_va_walkforward_075atr_featimp.csv",
                       index=False)
    print(f"\n  Top 25 features by gain (training set: 2024+2025):")
    print(f"    {'rank':>4}  {'feature':<42}  {'gain':>9}")
    for i, row in importance.head(25).iterrows():
        print(f"    {i+1:>4}  {row['feat']:<42}  {row['gain']:>9.0f}")

    # --- Step 2: Loop over feature counts ---
    summary_rows = []
    full_n = X_full.shape[1]
    for N in [full_n] + FEATURE_COUNTS:
        feats = importance.head(N)["feat"].tolist() if N < full_n \
            else X_full.columns.tolist()
        X_sub = X_full[feats]
        print(f"\n{'='*78}")
        print(f"  N = {N} features  ({'full' if N == full_n else 'top ' + str(N)})")
        print(f"{'='*78}")

        # Config A: train 2024 -> score 2025
        dt_a = all_df.loc[is_a_mask, "decision_ts"].to_numpy()
        X_tr_a, y_tr_a, X_val_a, y_val_a, _, _ = split_train_val(
            X_sub[is_a_mask], y[is_a_mask], dt_a)
        model_a = fit_model(X_tr_a, y_tr_a, X_val_a, y_val_a)
        train_auc_a = roc_auc_score(
            y_tr_a, model_a.predict_proba(X_tr_a)[:, 1])
        val_auc_a = roc_auc_score(
            y_val_a, model_a.predict_proba(X_val_a)[:, 1])
        res_a = evaluate(model_a, X_sub[oos_a_mask], y[oos_a_mask],
                            pnl[oos_a_mask], 2025)
        print(f"\n  Config A (train 2024 -> score 2025)  "
              f"best iter {model_a.best_iteration_}")
        print(f"    AUC  train={train_auc_a:.4f}  val={val_auc_a:.4f}  "
              f"oos={res_a['auc']:.4f}")
        print(f"    Top 30% kept: n={res_a['top30_n']}  "
              f"mean=${res_a['top30_mean']:+.2f}  "
              f"total=${res_a['top30_total']:+,.0f}  "
              f"WR={res_a['top30_wr']:.1%}  "
              f"vs base=${res_a['top30_mean']-res_a['base_mean']:+.2f}")

        # Config B: train 2024+2025 -> score 2026
        X_tr_b, y_tr_b, X_val_b, y_val_b, _, _ = split_train_val(
            X_sub[is_mask], y[is_mask], dt_is_b)
        model_b = fit_model(X_tr_b, y_tr_b, X_val_b, y_val_b)
        train_auc_b = roc_auc_score(
            y_tr_b, model_b.predict_proba(X_tr_b)[:, 1])
        val_auc_b = roc_auc_score(
            y_val_b, model_b.predict_proba(X_val_b)[:, 1])
        res_b = evaluate(model_b, X_sub[oos_b_mask], y[oos_b_mask],
                            pnl[oos_b_mask], 2026)
        print(f"\n  Config B (train 2024+25 -> score 2026)  "
              f"best iter {model_b.best_iteration_}")
        print(f"    AUC  train={train_auc_b:.4f}  val={val_auc_b:.4f}  "
              f"oos={res_b['auc']:.4f}")
        print(f"    Top 30% kept: n={res_b['top30_n']}  "
              f"mean=${res_b['top30_mean']:+.2f}  "
              f"total=${res_b['top30_total']:+,.0f}  "
              f"WR={res_b['top30_wr']:.1%}  "
              f"vs base=${res_b['top30_mean']-res_b['base_mean']:+.2f}")

        # Combined
        combined_df = pd.concat([
            res_a["df"].assign(year=2025),
            res_b["df"].assign(year=2026),
        ], ignore_index=True)
        comb_thresh_30 = combined_df["p"].quantile(0.70)
        kept_30 = combined_df[combined_df["p"] >= comb_thresh_30]
        comb_thresh_10 = combined_df["p"].quantile(0.90)
        kept_10 = combined_df[combined_df["p"] >= comb_thresh_10]
        y25_30 = kept_30[kept_30["year"] == 2025]["pnl"].sum()
        y26_30 = kept_30[kept_30["year"] == 2026]["pnl"].sum()
        y25_10 = kept_10[kept_10["year"] == 2025]["pnl"].sum()
        y26_10 = kept_10[kept_10["year"] == 2026]["pnl"].sum()
        print(f"\n  Combined 2025+2026 with global threshold:")
        print(f"    top 30%:  n={len(kept_30):,}  "
              f"mean=${kept_30['pnl'].mean():+.2f}  "
              f"total=${kept_30['pnl'].sum():+,.0f}  "
              f"(2025=${y25_30:+,.0f}, 2026=${y26_30:+,.0f})")
        print(f"    top 10%:  n={len(kept_10):,}  "
              f"mean=${kept_10['pnl'].mean():+.2f}  "
              f"total=${kept_10['pnl'].sum():+,.0f}  "
              f"(2025=${y25_10:+,.0f}, 2026=${y26_10:+,.0f})")

        summary_rows.append({
            "N": N,
            "feats": ",".join(feats[:5]) + ("..." if N > 5 else ""),
            "auc_train_a": train_auc_a, "auc_val_a": val_auc_a,
            "auc_oos_a": res_a["auc"],
            "auc_train_b": train_auc_b, "auc_val_b": val_auc_b,
            "auc_oos_b": res_b["auc"],
            "best_iter_a": model_a.best_iteration_,
            "best_iter_b": model_b.best_iteration_,
            "y25_top30_total": res_a["top30_total"],
            "y26_top30_total": res_b["top30_total"],
            "comb_top30_total": float(kept_30["pnl"].sum()),
            "comb_top30_2025": float(y25_30),
            "comb_top30_2026": float(y26_30),
            "comb_top10_total": float(kept_10["pnl"].sum()),
            "comb_top10_2025": float(y25_10),
            "comb_top10_2026": float(y26_10),
        })

    # --- Final summary table ---
    print(f"\n{'='*78}")
    print(f"SUMMARY  —  feature count vs OOS performance")
    print(f"{'='*78}")
    print(f"  {'N':>4}  {'AUC_A':>6}  {'AUC_B':>6}  "
          f"{'25_t30':>9}  {'26_t30':>9}  "
          f"{'comb_t30':>10}  {'2025':>9}  {'2026':>9}  "
          f"{'comb_t10':>10}")
    for r in summary_rows:
        print(f"  {r['N']:>4}  {r['auc_oos_a']:>6.4f}  {r['auc_oos_b']:>6.4f}  "
              f"${r['y25_top30_total']:>+7,.0f}  "
              f"${r['y26_top30_total']:>+7,.0f}  "
              f"${r['comb_top30_total']:>+8,.0f}  "
              f"${r['comb_top30_2025']:>+7,.0f}  "
              f"${r['comb_top30_2026']:>+7,.0f}  "
              f"${r['comb_top10_total']:>+8,.0f}")

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(
        OUT / "ml_va_walkforward_075atr_featselect_summary.csv",
        index=False)
    print(f"\nWrote:")
    print(f"  {OUT/'ml_va_walkforward_075atr_featimp.csv'}")
    print(f"  {OUT/'ml_va_walkforward_075atr_featselect_summary.csv'}")


if __name__ == "__main__":
    main()
