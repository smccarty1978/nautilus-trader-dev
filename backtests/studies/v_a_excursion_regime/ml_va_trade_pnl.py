"""ML on V_A trade PnL — direct PnL prediction at bar1_check time.

Population: V_A confirmed RTH trades (kind='bar1_check' AND
            became_trade=True), joined to trades.parquet for the
            ground-truth net_pnl.

Label:      target_va_win = (net_pnl > 0)  -- binary classification.

Features at bar1_check time (= trade-decision moment, just before
V_A entry fires 60s later at the next 1s bar):
  - Multi-TF regime state, EMA distances, ATR (snapshot at bar1 close)
  - Flip bar shape (h, l, c — the 1m bar BEFORE bar1)
  - Bar1 shape (h, l, o, c — the confirmation bar; new info vs flip-time)
  - Direction-aware bar1 features: body/ATR, HH/LL extent past flip bar,
    wicks with/against direction, follow-through close vs flip close
  - Volume / VWAP / OBV (causal at decision_ts, from
    `compute_volume_vwap_features.py`)
  - Calendar (hour, minute, day-of-week, minutes since RTH open)

Train/test:
  IS  = 2024 + 2025 V_A confirmed RTH trades
  OOS = 2026 V_A confirmed RTH trades
  Temporal internal val = last 20% of IS by decision_ts (for early stop).

Model: LightGBM, same hyperparams as prior runs (max_depth=6,
num_leaves=31, lr=0.05, min_data_in_leaf=50).

Outputs OOS decile PnL (mean / total / WR / bootstrap 95% CI) and
filter variants (top 50/30/20/10/5%).
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
from sklearn.metrics import roc_auc_score, brier_score_loss


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
    """Join bar1_check confirmed RTH snapshots to trades.parquet PnL."""
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
        return {"n": 0, "mean": np.nan, "p05": np.nan,
                "p95": np.nan, "total": 0.0}
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

    # ---- Flip bar shape (1m bar before bar1) ----
    fb_rng = df["flip_bar_h"] - df["flip_bar_l"]
    df["fb_loc_in_range"] = np.where(
        fb_rng > 0, (df["flip_bar_c"] - df["flip_bar_l"]) / fb_rng, 0.5)
    df["fb_range_atr"] = np.where(atr_ok, fb_rng / atr, np.nan)
    fb_uw = df["flip_bar_h"] - df["flip_bar_c"]
    fb_lw = df["flip_bar_c"] - df["flip_bar_l"]
    df["fb_wick_against_atr"] = np.where(
        atr_ok,
        np.where(direction == 1, fb_uw, fb_lw) / atr, np.nan)
    df["fb_wick_with_atr"] = np.where(
        atr_ok,
        np.where(direction == 1, fb_lw, fb_uw) / atr, np.nan)
    df["fb_close_minus_mid_atr"] = np.where(
        atr_ok,
        (df["flip_bar_c"] - (df["flip_bar_h"] + df["flip_bar_l"]) / 2) / atr,
        np.nan,
    )

    # ---- Bar1 shape (the confirmation bar) ----
    b1_rng = df["bar1_h"] - df["bar1_l"]
    df["b1_loc_in_range"] = np.where(
        b1_rng > 0, (df["bar1_c"] - df["bar1_l"]) / b1_rng, 0.5)
    df["b1_range_atr"] = np.where(atr_ok, b1_rng / atr, np.nan)
    df["b1_body_atr"] = np.where(
        atr_ok, (df["bar1_c"] - df["bar1_o"]) * direction / atr, np.nan)
    # Direction-aware "follow-through" (bar1 close past flip close, in ATR)
    df["b1_close_vs_flip_close_atr"] = np.where(
        atr_ok, (df["bar1_c"] - df["flip_bar_c"]) * direction / atr, np.nan)
    # HH/LL extent past flip bar
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
        atr_ok,
        np.where(direction == 1, b1_uw, b1_lw) / atr, np.nan)
    df["b1_wick_with_atr"] = np.where(
        atr_ok,
        np.where(direction == 1, b1_lw, b1_uw) / atr, np.nan)
    # Bar1 range relative to flip bar range (expansion)
    df["b1_to_fb_range_ratio"] = np.where(
        fb_rng > 0, b1_rng / fb_rng, np.nan)

    # ---- HTF alignment ----
    for tf in ["30s", "1m", "3m", "5m"]:
        df[f"aligned_{tf}"] = (df[f"regime_{tf}"] == direction).astype(int)
    df["htf_alignment_score"] = (
        df["aligned_30s"] + df["aligned_1m"]
        + df["aligned_3m"] + df["aligned_5m"]
    )

    # ---- Calendar (CT) ----
    ct = pd.to_datetime(df["decision_ts"], unit="ns", utc=True
                          ).dt.tz_convert("America/Chicago")
    df["hour_ct"] = ct.dt.hour.astype(int)
    df["minute_ct"] = ct.dt.minute.astype(int)
    df["day_of_week"] = ct.dt.dayofweek.astype(int)
    df["minutes_since_rth_open"] = (
        ct.dt.hour.astype(int) * 60 + ct.dt.minute.astype(int)
        - (8 * 60 + 30)).astype(int)

    # ---- Direction-aware VWAP / volume ----
    df["dist_to_vwap_dir_atr"] = (
        -df["dist_close_to_vwap_atr"] * direction)
    for lab in ["1m", "5m", "15m"]:
        df[f"vol_imbalance_dir_{lab}"] = (
            df[f"vol_imbalance_{lab}"] * direction)

    # ---- Drop ----
    drop_cols = [
        # Identifiers / timestamps / categorical
        "decision_ts", "bar_ts_event", "kind", "event_id",
        "session", "is_rth",
        # Constants in confirmed-trade population
        "hhll_ok", "momentum_ok", "confirmed", "became_trade",
        # Raw OHLC (replaced by derived)
        "flip_bar_h", "flip_bar_l", "flip_bar_c",
        "bar1_h", "bar1_l", "bar1_o", "bar1_c",
        # Trade-side fields (NaN/0/-1 at bar1_check before fill)
        "trade_event_id", "trade_direction", "trade_fill_price",
        "trade_fill_ts", "trade_atr_at_signal",
        "elapsed_s", "cur_pnl_atr", "cur_mfe_atr", "cur_mae_atr",
        "cur_giveback_atr", "cur_close_price",
        # Misc collector-only timestamps
        "last_30s_close_ts", "last_1m_close_ts",
        "last_3m_close_ts", "last_5m_close_ts",
        "flip_direction",
        "event_close_px", "cum_vol_session",
        # Absolute price columns (year-proxy risk)
        "close_30s", "close_1m", "close_3m", "close_5m",
        "vwap_value",
        "dist_close_to_vwap",
        "dist_close_to_vwap_upper_1sd", "dist_close_to_vwap_lower_1sd",
        "dist_close_to_vwap_upper_2sd", "dist_close_to_vwap_lower_2sd",
        "dist_close_to_vwap_upper_3sd", "dist_close_to_vwap_lower_3sd",
        # Raw direction main effect
        "direction",
        # Year column
        "year",
        # Label / trade outcomes (must NEVER be in X)
        "target_va_win", "net_pnl", "gross_pnl", "hold_s", "exit_reason",
        "running_mfe", "running_mae",
    ]
    drop_cols = [c for c in drop_cols if c in df.columns]
    df = df.drop(columns=drop_cols)
    obj_cols = [c for c in df.columns if df[c].dtype == "object"]
    if obj_cols:
        df = df.drop(columns=obj_cols)
    return df


def train_eval(X_tr, y_tr, X_val, y_val, X_oos, y_oos, name: str):
    print(f"\n{'-'*78}")
    print(f"  {name}")
    print(f"{'-'*78}")
    print(f"  train n={len(X_tr):,}  pos rate={y_tr.mean():.3%}")
    print(f"  val   n={len(X_val):,}  pos rate={y_val.mean():.3%}")
    print(f"  oos   n={len(X_oos):,}  pos rate={y_oos.mean():.3%}")
    model = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1, verbose=-1)
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(50, verbose=False),
                          lgb.log_evaluation(0)])
    p_tr = model.predict_proba(X_tr)[:, 1]
    p_val = model.predict_proba(X_val)[:, 1]
    p_oos = model.predict_proba(X_oos)[:, 1]
    auc_tr = roc_auc_score(y_tr, p_tr)
    auc_val = roc_auc_score(y_val, p_val)
    auc_oos = roc_auc_score(y_oos, p_oos)
    base_oos = y_oos.mean()
    print(f"\n  AUC train={auc_tr:.4f}  val={auc_val:.4f}  oos={auc_oos:.4f}")
    print(f"  Base OOS win-rate={base_oos:.3%}  best iter: {model.best_iteration_}")

    imp = pd.DataFrame({
        "feat": X_tr.columns,
        "gain": model.booster_.feature_importance(importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    print(f"\n  Top 15 features by gain:")
    for _, row in imp.head(15).iterrows():
        print(f"    {row['feat']:<42}  {row['gain']:>8.0f}")

    return {"model": model, "p_oos": p_oos,
            "auc_train": auc_tr, "auc_val": auc_val, "auc_oos": auc_oos,
            "base_oos": base_oos, "imp": imp}


def report_oos_pnl(p_oos: np.ndarray, pnl_oos: np.ndarray):
    df = pd.DataFrame({"p": p_oos, "pnl": pnl_oos})
    df["decile"] = pd.qcut(df["p"].rank(method="first"), 10,
                              labels=False, duplicates="drop")
    print(f"\n  OOS decile PnL  (V_A trade net_pnl, $):")
    print(f"    {'dec':>4}  {'n':>5}  {'p_mean':>7}  "
          f"{'mean_$':>9}  {'p05':>9}  {'p95':>9}  "
          f"{'total':>10}  {'WR':>5}")
    for dec, grp in df.groupby("decile"):
        bs = bootstrap_mean(grp["pnl"].to_numpy())
        wr = (grp["pnl"] > 0).mean()
        pm = grp["p"].mean()
        print(f"    d{int(dec)+1:>2}    {bs['n']:>5,}  {pm:>7.4f}  "
              f"${bs['mean']:>+7.2f}  ${bs['p05']:>+7.2f}  "
              f"${bs['p95']:>+7.2f}  ${bs['total']:>+8,.0f}  "
              f"{wr:>4.1%}")

    print(f"\n  Filter variants — keep flips where p >= quantile:")
    print(f"    {'gate':<22}  {'kept':>5}  {'kept%':>6}  "
          f"{'mean_$':>9}  {'p05':>9}  {'p95':>9}  "
          f"{'total':>10}  {'WR':>5}")
    for q_keep in [0.50, 0.30, 0.20, 0.10, 0.05]:
        thresh = df["p"].quantile(1 - q_keep)
        kept = df[df["p"] >= thresh]
        bs = bootstrap_mean(kept["pnl"].to_numpy())
        wr = (kept["pnl"] > 0).mean()
        print(f"    top {q_keep*100:>3.0f}% (p>={thresh:.4f})  "
              f"{len(kept):>5,}  {len(kept)/len(df):>5.1%}  "
              f"${bs['mean']:>+7.2f}  ${bs['p05']:>+7.2f}  "
              f"${bs['p95']:>+7.2f}  ${bs['total']:>+8,.0f}  "
              f"{wr:>4.1%}")

    # Bottom-decile screening: skip these trades?
    print(f"\n  Bottom-decile screening — skip flips where p < quantile:")
    print(f"    {'gate':<22}  {'skipped':>7}  "
          f"{'kept_mean':>9}  {'kept_total':>10}  "
          f"{'orig_mean':>9}")
    orig_mean = df["pnl"].mean()
    orig_total = df["pnl"].sum()
    for q_skip in [0.10, 0.20, 0.30]:
        thresh = df["p"].quantile(q_skip)
        kept = df[df["p"] >= thresh]
        bs = bootstrap_mean(kept["pnl"].to_numpy())
        print(f"    skip bot {q_skip*100:>3.0f}% (p<{thresh:.4f})  "
              f"{len(df)-len(kept):>7,}  "
              f"${bs['mean']:>+7.2f}  ${bs['total']:>+8,.0f}  "
              f"${orig_mean:>+7.2f}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("ML PREDICTING V_A TRADE PNL  (label = net_pnl > 0)")
    print("=" * 78)

    all_rows = []
    for yr in YEARS:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        df = load_bar1_trades(yr)
        df["target_va_win"] = (df["net_pnl"] > 0).astype(int)
        print(f"  V_A confirmed RTH trades: {len(df):,} ({time.time()-t0:.0f}s)")
        print(f"  WR: {df['target_va_win'].mean():.3%}  "
              f"mean PnL: ${df['net_pnl'].mean():+.2f}  "
              f"total: ${df['net_pnl'].sum():+,.0f}")
        all_rows.append(df)

    all_df = pd.concat(all_rows, ignore_index=True)
    n_pre = len(all_df)
    all_df = all_df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset=["decision_ts", "direction"], keep="first"
        ).reset_index(drop=True)
    print(f"\nDedupe cross-year: {n_pre:,} -> {len(all_df):,}")

    # Build feature matrix
    X = make_feature_matrix(all_df)
    y = all_df["target_va_win"]
    pnl = all_df["net_pnl"]
    yr_col = all_df["year"]

    forbidden = {
        "target_va_win", "net_pnl", "gross_pnl", "hold_s", "exit_reason",
        "running_mfe", "running_mae", "year", "confirmed", "became_trade",
    }
    leaked = forbidden.intersection(X.columns)
    assert not leaked, f"Label leak: {leaked}"

    print(f"\nFeature matrix shape: {X.shape}")
    print(f"Features ({X.shape[1]}):")
    for c in sorted(X.columns):
        print(f"  {c}")

    is_mask = yr_col.isin([2024, 2025])
    oos_mask = yr_col == 2026
    X_is, X_oos = X[is_mask], X[oos_mask]
    y_is, y_oos = y[is_mask], y[oos_mask]
    pnl_oos = pnl[oos_mask]

    is_dt = all_df.loc[is_mask.values, "decision_ts"].to_numpy()
    order = np.argsort(is_dt, kind="mergesort")
    X_is = X_is.iloc[order].reset_index(drop=True)
    y_is = y_is.iloc[order].reset_index(drop=True)
    is_dt = is_dt[order]
    n_val = int(len(X_is) * VAL_FRAC)
    n_tr = len(X_is) - n_val
    tr_idx = np.arange(n_tr)
    val_idx = np.arange(n_tr, len(X_is))
    print(f"\nIS temporal split: train n={n_tr:,}  val n={n_val:,}  "
          f"oos n={len(X_oos):,}")
    print(f"  train range: {pd.Timestamp(is_dt[0], unit='ns')} .. "
          f"{pd.Timestamp(is_dt[n_tr-1], unit='ns')}")
    print(f"  val   range: {pd.Timestamp(is_dt[n_tr], unit='ns')} .. "
          f"{pd.Timestamp(is_dt[-1], unit='ns')}")

    res = train_eval(
        X_is.iloc[tr_idx], y_is.iloc[tr_idx],
        X_is.iloc[val_idx], y_is.iloc[val_idx],
        X_oos, y_oos,
        name="V_A trade PnL — predict (net_pnl > 0) at bar1_check time")

    # OOS PnL by decile
    print(f"\n{'='*78}")
    print(f"OOS PnL ANALYSIS (V_A trades 2026 RTH)")
    print(f"{'='*78}")
    print(f"  OOS sample: n={len(X_oos):,}  base WR={res['base_oos']:.3%}  "
          f"mean=${pnl_oos.mean():+.2f}  "
          f"total=${pnl_oos.sum():+,.0f}")
    report_oos_pnl(res["p_oos"], pnl_oos.to_numpy())

    # Save
    pred = pd.DataFrame({
        "decision_ts": all_df["decision_ts"].values,
        "year": yr_col.values,
        "direction": all_df["direction"].values,
        "target_va_win": y.values,
        "net_pnl": pnl.values,
    })
    pred["p_va_win_oos"] = np.nan
    pred.loc[oos_mask.values, "p_va_win_oos"] = res["p_oos"]
    pred.to_parquet(OUT / "ml_va_trade_pnl_predictions.parquet", index=False)
    res["imp"].to_csv(OUT / "ml_va_trade_pnl_feat_imp.csv", index=False)
    print(f"\n{'='*78}")
    print(f"SUMMARY  —  Predicting V_A trade WIN at bar1_check time")
    print(f"{'='*78}")
    print(f"  train AUC {res['auc_train']:.4f}  val "
          f"{res['auc_val']:.4f}  OOS {res['auc_oos']:.4f}")
    print(f"  Base WR OOS: {res['base_oos']:.3%}")
    print(f"\nWrote:")
    print(f"  {OUT/'ml_va_trade_pnl_predictions.parquet'}")
    print(f"  {OUT/'ml_va_trade_pnl_feat_imp.csv'}")


if __name__ == "__main__":
    main()
