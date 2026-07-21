"""Walk-forward ML predicting V_A C's new ATR-normalized filter outcome.

Target (new): at bar1_check time, predict whether the trade will have
unrealized PnL >= 0.75 ATR at +5m from V_A entry.

  unr_pnl_5m_atr = (price_at_5m - fill_price) * direction / atr_at_signal
  label = (unr_pnl_5m_atr >= 0.75)

Why: V_A C now uses an ATR-normalized filter (unr >= 0.75 ATR at +5m)
instead of fixed $325. If ML at bar1_check predicts which trades will
pass that filter, we can:
  (a) Pre-skip trades unlikely to pass — save the +5m observation cost
  (b) Confirm V_A C's filter mechanic is predictable from flip-time +
       bar1 features alone

`price_at_5m` is the OPEN of the first 1s bar at-or-after
`entry_ts + 300_000_000_000`, matching `checkpoint_filter_search.py`
convention. `fill_price`, `entry_ts`, `direction`, `atr_at_signal`
all come from `trades.parquet`. The legacy 30s entry delay is present
in the data but baked into both this label and V_A C's filter, so
they're directly comparable.

Walk-forward:
  Config A: train 2024, score 2025
  Config B: train 2024+2025, score 2026

Outputs:
  - AUC on the new 0.75-ATR target
  - V_A net_pnl by ML decile (does predicting the filter outcome
    translate to PnL lift?)
  - Filter variants vs baseline V_A
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

CP_OFFSET_S = 300            # +5m from entry
THRESHOLD_ATR = 0.75         # 0.75 ATR unrealized PnL threshold
NQ_MULT = 20.0
SEED = 42
VAL_FRAC = 0.20
N_BOOT = 2000


def load_1s_oc(path: str) -> pd.DataFrame:
    df = pq.read_table(path, columns=["ts_event", "open", "close"]).to_pandas()
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
    """Label = (unr_pnl_5m / atr_at_signal) >= THRESHOLD_ATR.

    Price at +5m = OPEN of first 1s bar at-or-after entry_ts + 300s.
    Matches `checkpoint_filter_search.py` convention.
    """
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
        # If the trade already exited before +5m, no measurement is possible.
        # Match V_A C semantics: such trades fail the filter.
        if cp_ts >= int(exit_ts[k]):
            unr_atr[k] = np.nan
            label[k] = 0  # didn't survive +5m -> doesn't pass filter
            continue
        i_hi = int(np.searchsorted(bars_ts, cp_ts, side="left"))
        if i_hi >= len(bars_ts):
            unr_atr[k] = np.nan
            label[k] = 0
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

    # Compute the new label from 1s data
    bars = load_1s_oc(ONE_S_PATHS[year])
    label, unr_atr = compute_label_unr_5m(merged, bars)
    merged["target_unr075"] = label
    merged["unr_5m_atr"] = unr_atr
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
        "n": n, "mean": float(values.mean()),
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
        # Label / outcomes / trade-side fields merged from trades.parquet
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


def evaluate_oos(model, X_oos, y_oos, pnl_oos, label_oos, name: str) -> dict:
    p_oos = model.predict_proba(X_oos)[:, 1]
    auc = roc_auc_score(y_oos, p_oos) if y_oos.nunique() > 1 else np.nan
    base_unr_rate = float(y_oos.mean())
    base_mean = float(pnl_oos.mean())
    base_total = float(pnl_oos.sum())

    df = pd.DataFrame({
        "p": p_oos, "y_unr": y_oos.values, "pnl": pnl_oos.values,
    })
    df["decile"] = pd.qcut(df["p"].rank(method="first"), 10,
                              labels=False, duplicates="drop")

    print(f"\n  {name}")
    print(f"  AUC on +5m unr>=0.75ATR target: {auc:.4f}")
    print(f"  Base 0.75ATR pass rate: {base_unr_rate:.3%}")
    print(f"  Base PnL: mean=${base_mean:+.2f}  total=${base_total:+,.0f}")

    print(f"\n  Decile: ML score vs realized PnL AND 0.75-ATR pass rate:")
    print(f"    {'dec':>4}  {'n':>5}  {'p':>7}  {'unr_pass':>8}  "
          f"{'mean_$':>9}  {'p05_$':>9}  {'p95_$':>9}  {'total':>10}  {'WR':>5}")
    for dec, grp in df.groupby("decile"):
        bs = bootstrap_mean(grp["pnl"].to_numpy())
        wr = (grp["pnl"] > 0).mean()
        unr_pass = grp["y_unr"].mean()
        pm = grp["p"].mean()
        print(f"    d{int(dec)+1:>2}    {bs['n']:>5,}  {pm:>7.4f}  "
              f"{unr_pass:>7.1%}   ${bs['mean']:>+7.2f}  "
              f"${bs['p05']:>+7.2f}  ${bs['p95']:>+7.2f}  "
              f"${bs['total']:>+8,.0f}  {wr:>4.1%}")

    print(f"\n  Filter variants (apply ML score as gate at bar1_check):")
    print(f"    {'gate':<25}  {'kept':>5}  {'kept%':>6}  "
          f"{'unr_pass':>8}  {'mean_$':>9}  {'p05_$':>9}  "
          f"{'total':>10}  {'WR':>5}  {'vs_base':>9}")
    for q_keep in [0.50, 0.30, 0.20, 0.10]:
        thresh = df["p"].quantile(1 - q_keep)
        kept = df[df["p"] >= thresh]
        bs = bootstrap_mean(kept["pnl"].to_numpy())
        wr = (kept["pnl"] > 0).mean()
        unr_pass = kept["y_unr"].mean()
        print(f"    top {q_keep*100:>3.0f}% (p>={thresh:.4f})    "
              f"{len(kept):>5,}  {len(kept)/len(df):>5.1%}  "
              f"{unr_pass:>7.1%}   ${bs['mean']:>+7.2f}  "
              f"${bs['p05']:>+7.2f}  ${bs['total']:>+8,.0f}  "
              f"{wr:>4.1%}  ${bs['mean']-base_mean:>+7.2f}")

    return {
        "name": name, "auc": auc, "base_mean": base_mean,
        "base_total": base_total, "n": len(df), "df": df, "p_oos": p_oos,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("WALK-FORWARD ML: predict +5m unr-PnL >= 0.75 ATR at bar1_check")
    print("=" * 78)

    all_rows = []
    for yr in YEARS:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        df = load_bar1_trades(yr)
        unr_pass = df["target_unr075"].mean()
        wr = (df["net_pnl"] > 0).mean()
        print(f"  V_A confirmed RTH trades: {len(df):,} ({time.time()-t0:.0f}s)")
        print(f"  0.75-ATR pass rate: {unr_pass:.3%}  "
              f"trade WR: {wr:.3%}  "
              f"trade mean: ${df['net_pnl'].mean():+.2f}  "
              f"total: ${df['net_pnl'].sum():+,.0f}")
        # Quick reasonableness: pass-rate should match other-agent
        # (44.5% for ATR>=0.5, 36.2% for ATR>=0.75 per the user's table)
        all_rows.append(df)

    all_df = pd.concat(all_rows, ignore_index=True)
    n_pre = len(all_df)
    all_df = all_df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset=["decision_ts", "direction"], keep="first"
        ).reset_index(drop=True)
    print(f"\nDedupe: {n_pre:,} -> {len(all_df):,}")

    X = make_feature_matrix(all_df)
    y = all_df["target_unr075"]
    pnl = all_df["net_pnl"]
    unr = all_df["unr_5m_atr"]
    yr_col = all_df["year"]

    forbidden = {
        "target_unr075", "unr_5m_atr", "net_pnl", "gross_pnl", "hold_s",
        "exit_reason", "running_mfe", "running_mae", "entry_ts",
        "fill_price", "exit_ts", "exit_price", "atr_at_signal",
        "year", "confirmed", "became_trade",
    }
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
        unr_eval = unr[ev_mask]
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
        print(f"  train pos rate (unr>=0.75): {y_tr.mean():.3%}  "
              f"val pos rate: {y_val.mean():.3%}  "
              f"eval pos rate: {y_eval.mean():.3%}")

        model = fit_model(X_tr, y_tr, X_val, y_val)
        p_train_auc = roc_auc_score(y_tr, model.predict_proba(X_tr)[:, 1])
        p_val_auc = roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])
        print(f"  best iter: {model.best_iteration_}  "
              f"train AUC={p_train_auc:.4f}  val AUC={p_val_auc:.4f}")

        res = evaluate_oos(model, X_eval, y_eval, pnl_eval, unr_eval,
                              name=f"OOS {eval_years[0]}")
        results[eval_years[0]] = res

    # Combined view
    print(f"\n{'='*78}")
    print(f"COMBINED 2025+2026 with single global ML threshold")
    print(f"{'='*78}")
    combined = pd.concat([
        results[2025]["df"].assign(year=2025),
        results[2026]["df"].assign(year=2026),
    ], ignore_index=True)
    base_total = combined["pnl"].sum()
    base_mean = combined["pnl"].mean()
    print(f"  Baseline (no ML, all V_A 2025+2026): n={len(combined):,}  "
          f"mean=${base_mean:+.2f}  total=${base_total:+,.0f}")

    print(f"\n  Global ML filter (threshold from pooled distribution):")
    print(f"    {'gate':<24}  {'kept':>5}  {'mean_$':>9}  "
          f"{'total':>10}  {'2025':>10}  {'2026':>10}")
    for q in [0.50, 0.30, 0.20, 0.10]:
        thresh = combined["p"].quantile(1 - q)
        kept = combined[combined["p"] >= thresh]
        if len(kept) == 0: continue
        y25 = kept[kept["year"] == 2025]["pnl"].sum()
        y26 = kept[kept["year"] == 2026]["pnl"].sum()
        print(f"    top {q*100:>3.0f}% (p>={thresh:.4f})  "
              f"{len(kept):>5,}  ${kept['pnl'].mean():>+7.2f}  "
              f"${kept['pnl'].sum():>+8,.0f}  "
              f"${y25:>+8,.0f}  ${y26:>+8,.0f}")

    # Save predictions
    pred = pd.DataFrame({
        "decision_ts": all_df["decision_ts"].values,
        "year": yr_col.values,
        "direction": all_df["direction"].values,
        "target_unr075": y.values,
        "unr_5m_atr": unr.values,
        "net_pnl": pnl.values,
    })
    pred["p_unr075_oos"] = np.nan
    for yr, res in results.items():
        m = (yr_col == yr).values
        pred.loc[m, "p_unr075_oos"] = res["p_oos"]
    pred.to_parquet(OUT / "ml_va_walkforward_075atr_predictions.parquet",
                      index=False)
    print(f"\n{'='*78}")
    print(f"SUMMARY")
    print(f"{'='*78}")
    for yr, res in results.items():
        print(f"  OOS {yr}: AUC={res['auc']:.4f}  "
              f"baseline mean=${res['base_mean']:+.2f}  "
              f"baseline total=${res['base_total']:+,.0f}  n={res['n']:,}")
    print(f"\n  Combined 2025+2026 baseline: ${base_total:+,.0f}")
    print(f"  Wrote: {OUT/'ml_va_walkforward_075atr_predictions.parquet'}")


if __name__ == "__main__":
    main()
