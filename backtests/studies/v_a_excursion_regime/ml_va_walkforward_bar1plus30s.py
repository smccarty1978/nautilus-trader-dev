"""ML at bar1+30s: temporally consistent prediction + fill at the same point.

Hypothesis: deliberately waiting 30s after bar1 close before deciding
gives ML 30s of additional price action to evaluate whether the trade
will reach 0.75 ATR unrealized PnL at +5m from this (delayed) entry.
This explicitly trades 30s of edge for 30s of additional information.

Temporal triple (consistent — matches deployment intent):
  T_F  (feature snapshot) = bar1_close + 30s = decision_ts + 29s
  T_E  (simulated fill)   = bar1_close + 30s = decision_ts + 29s
                            (uses WITH-DELAY trades.parquet entry_ts)
  T_L  (label outcome)    = T_E + 300s = bar1_close + 5:30

Data sources:
  - WITH-DELAY snapshots_with_vol_vwap.parquet (bar1_check rows, RTH,
    became_trade). Snapshot features are as-of decision_ts (bar1_close+1s),
    29s stale relative to T_F but causally valid.
  - WITH-DELAY trades.parquet (entry_ts = bar1_close + 30s).
  - 1s OHLCV for the 30s post-bar1 micro-features AND the label
    computation at entry_ts + 300s.

NEW features (p30_* = "post-bar1 30-second window") added at T_F:
  p30_range_atr, p30_body_dir_atr, p30_close_vs_open_dir_atr,
  p30_mfe_dir_atr, p30_mae_dir_atr, p30_volume,
  p30_vol_imbalance_dir, p30_close_vs_flip_close_dir_atr,
  p30_close_vs_bar1_close_dir_atr, p30_extension_past_flip_dir_atr,
  p30_velocity_last5s_dir_atr, p30_close_loc_in_range

Reports head-to-head comparison vs:
  - WITH-DELAY V_A-anchor at bar1+1s (old "phantom" result)
  - NO-DELAY V_A-anchor at bar1+1s (cleanest baseline)
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
# WITH-DELAY data (snapshots + trades). Matches bar1+30s entry.
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

CP_OFFSET_S = 300            # +5m from T_E
P30_WINDOW_S = 30            # 30-second post-bar1 window
THRESHOLD_ATR = 0.75
SEED = 42
VAL_FRAC = 0.20
N_BOOT = 2000


def load_1s_ohlcv(path: str) -> pd.DataFrame:
    df = pq.read_table(
        path,
        columns=["ts_event", "open", "high", "low", "close", "volume"],
    ).to_pandas()
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


def compute_p30_features(b1_trades: pd.DataFrame, bars: pd.DataFrame):
    """Compute 30-second post-bar1 micro features at T_F.

    Window: 1s bars with ts_event in [decision_ts, decision_ts + 30s).
    All bars in this window have ts_event < T_F = decision_ts + 30s,
    so they are causally available at T_F.
    """
    bars_ts = bars["ts_event_ns"].to_numpy()
    bars_o = bars["open"].to_numpy()
    bars_h = bars["high"].to_numpy()
    bars_l = bars["low"].to_numpy()
    bars_c = bars["close"].to_numpy()
    bars_v = bars["volume"].to_numpy().astype(np.float64)

    n = len(b1_trades)
    cols = [
        "p30_range_atr", "p30_body_dir_atr",
        "p30_mfe_dir_atr", "p30_mae_dir_atr",
        "p30_volume", "p30_vol_imbalance_dir",
        "p30_close_vs_flip_close_dir_atr",
        "p30_close_vs_bar1_close_dir_atr",
        "p30_extension_past_flip_dir_atr",
        "p30_velocity_last5s_dir_atr",
        "p30_close_loc_in_range", "p30_bars_in_window",
    ]
    out = {c: np.full(n, np.nan) for c in cols}
    out["p30_volume"] = np.zeros(n)
    out["p30_bars_in_window"] = np.zeros(n, dtype=int)

    decision_ts_arr = b1_trades["decision_ts"].to_numpy(dtype=np.int64)
    direction = b1_trades["direction"].to_numpy(dtype=np.int64)
    atr = b1_trades["atr_1m"].to_numpy()
    flip_bar_c = b1_trades["flip_bar_c"].to_numpy()
    bar1_c = b1_trades["bar1_c"].to_numpy()
    flip_bar_h = b1_trades["flip_bar_h"].to_numpy()
    flip_bar_l = b1_trades["flip_bar_l"].to_numpy()

    for k in range(n):
        a = float(atr[k])
        if not (np.isfinite(a) and a > 0):
            continue
        T_start = int(decision_ts_arr[k])
        T_end = T_start + P30_WINDOW_S * 1_000_000_000
        i_start = int(np.searchsorted(bars_ts, T_start, side="left"))
        i_end = int(np.searchsorted(bars_ts, T_end, side="left"))
        if i_end <= i_start:
            continue
        d = int(direction[k])
        seg_o = bars_o[i_start:i_end]
        seg_h = bars_h[i_start:i_end]
        seg_l = bars_l[i_start:i_end]
        seg_c = bars_c[i_start:i_end]
        seg_v = bars_v[i_start:i_end]
        o0 = float(seg_o[0])
        c_last = float(seg_c[-1])
        hh = float(seg_h.max())
        ll = float(seg_l.min())
        v_total = float(seg_v.sum())
        bull_mask = seg_c > seg_o
        bear_mask = seg_c < seg_o
        bull_v = float(seg_v[bull_mask].sum())
        bear_v = float(seg_v[bear_mask].sum())

        out["p30_range_atr"][k] = (hh - ll) / a
        out["p30_body_dir_atr"][k] = (c_last - o0) * d / a
        if d == 1:
            mfe = hh - o0
            mae = o0 - ll
        else:
            mfe = o0 - ll
            mae = hh - o0
        out["p30_mfe_dir_atr"][k] = mfe / a
        out["p30_mae_dir_atr"][k] = mae / a
        out["p30_volume"][k] = v_total
        if v_total > 0:
            out["p30_vol_imbalance_dir"][k] = (
                (bull_v - bear_v) * d / v_total)
        out["p30_close_vs_flip_close_dir_atr"][k] = (
            (c_last - float(flip_bar_c[k])) * d / a)
        out["p30_close_vs_bar1_close_dir_atr"][k] = (
            (c_last - float(bar1_c[k])) * d / a)
        if d == 1:
            ext = hh - float(flip_bar_h[k])
        else:
            ext = float(flip_bar_l[k]) - ll
        out["p30_extension_past_flip_dir_atr"][k] = ext / a
        # 5s velocity at end of window
        if len(seg_c) >= 5:
            c_5s_ago = float(seg_c[-5])
            out["p30_velocity_last5s_dir_atr"][k] = (
                (c_last - c_5s_ago) * d / a)
        if hh > ll:
            out["p30_close_loc_in_range"][k] = (c_last - ll) / (hh - ll)
        out["p30_bars_in_window"][k] = i_end - i_start

    return pd.DataFrame(out)


def compute_label_unr_5m(b1_trades: pd.DataFrame, bars: pd.DataFrame):
    """Label: (price_at(entry_ts + 300s) - fill_price) * direction
              / atr_at_signal >= 0.75
    Matches checkpoint_filter_search convention: 1s bar OPEN at-or-after
    entry_ts + 300s.

    Censoring policy (matches V_A C's 'alive at +5m' filter):
      - Trades that exit before T_E + 300s get label = 0 (couldn't pass
        the filter regardless of price). unr_5m_atr remains NaN for
        these rows.
      - Trades with invalid ATR or no 1s bar at cp_ts: label = 0.
    Returns label, unr_atr, AND counters for the censoring breakdown.
    """
    bars_ts = bars["ts_event_ns"].to_numpy()
    bars_o = bars["open"].to_numpy()
    n = len(b1_trades)
    label = np.zeros(n, dtype=int)
    unr_atr = np.full(n, np.nan)
    counters = {"valid": 0, "early_exit": 0, "no_bar": 0, "bad_atr": 0}
    entry_ts = b1_trades["entry_ts"].to_numpy(dtype=np.int64)
    fill_price = b1_trades["fill_price"].to_numpy()
    direction = b1_trades["direction"].to_numpy(dtype=np.int64)
    atr = b1_trades["atr_at_signal"].to_numpy()
    exit_ts = b1_trades["exit_ts"].to_numpy(dtype=np.int64)
    for k in range(n):
        a = float(atr[k])
        if not (np.isfinite(a) and a > 0):
            counters["bad_atr"] += 1
            continue
        cp_ts = int(entry_ts[k]) + CP_OFFSET_S * 1_000_000_000
        if cp_ts >= int(exit_ts[k]):
            counters["early_exit"] += 1
            continue
        i_hi = int(np.searchsorted(bars_ts, cp_ts, side="left"))
        if i_hi >= len(bars_ts):
            counters["no_bar"] += 1
            continue
        price = float(bars_o[i_hi])
        pnl_atr = (price - float(fill_price[k])) * int(direction[k]) / a
        unr_atr[k] = pnl_atr
        label[k] = int(pnl_atr >= THRESHOLD_ATR)
        counters["valid"] += 1
    return label, unr_atr, counters


def load_bar1_trades_with_p30(year: int) -> pd.DataFrame:
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

    # Verify with-delay: entry_ts - decision_ts should be ~29s
    diffs = (merged["entry_ts"] - merged["decision_ts"]) // 10**9
    print(f"  entry-decision (sec) — min={diffs.min()}  "
          f"med={diffs.median():.0f}  mode={diffs.mode().iloc[0]}  "
          f"max={diffs.max()} (expect ~29 for with-delay)")

    bars = load_1s_ohlcv(ONE_S_PATHS[year])
    p30_df = compute_p30_features(merged, bars)
    merged = pd.concat([merged.reset_index(drop=True), p30_df], axis=1)
    label, unr_atr, counters = compute_label_unr_5m(merged, bars)
    merged["target_unr075"] = label
    merged["unr_5m_atr"] = unr_atr
    merged["year"] = year
    total = sum(counters.values())
    print(f"  label censoring: valid={counters['valid']:,} "
          f"({counters['valid']/total:.1%})  "
          f"early_exit={counters['early_exit']:,}  "
          f"no_bar={counters['no_bar']:,}  bad_atr={counters['bad_atr']:,}")
    return merged


def make_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    direction = df["direction"]
    atr = df["atr_1m"]
    atr_ok = atr > 0

    # Existing flip bar / bar1 derived features (same as prior runs)
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
        # Label / outcomes (must not survive)
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


def evaluate(model, X_oos, y_oos, pnl_oos, year):
    p = model.predict_proba(X_oos)[:, 1]
    auc = roc_auc_score(y_oos, p) if y_oos.nunique() > 1 else np.nan
    df = pd.DataFrame({"p": p, "y": y_oos.values, "pnl": pnl_oos.values})
    df["decile"] = pd.qcut(df["p"].rank(method="first"), 10,
                              labels=False, duplicates="drop")
    base_mean = float(pnl_oos.mean())
    base_total = float(pnl_oos.sum())
    print(f"\n  OOS {year}: AUC={auc:.4f}  baseline mean=${base_mean:+.2f}  "
          f"total=${base_total:+,.0f}  n={len(df):,}")
    print(f"    {'dec':>4}  {'n':>5}  {'p':>7}  {'mean_$':>9}  "
          f"{'p05':>9}  {'p95':>9}  {'total':>10}  {'WR':>5}")
    for dec, grp in df.groupby("decile"):
        bs = bootstrap_mean(grp["pnl"].to_numpy())
        wr = (grp["pnl"] > 0).mean()
        pm = grp["p"].mean()
        print(f"    d{int(dec)+1:>2}    {bs['n']:>5,}  {pm:>7.4f}  "
              f"${bs['mean']:>+7.2f}  ${bs['p05']:>+7.2f}  "
              f"${bs['p95']:>+7.2f}  ${bs['total']:>+8,.0f}  "
              f"{wr:>4.1%}")
    print(f"\n    {'gate':<22}  {'kept':>5}  {'mean_$':>9}  "
          f"{'p05':>9}  {'total':>10}  {'vs_base':>9}")
    res = {"auc": auc, "base_mean": base_mean, "base_total": base_total,
           "n": len(df), "df": df, "p_oos": p}
    for q in [0.50, 0.30, 0.20, 0.10]:
        thresh = df["p"].quantile(1 - q)
        kept = df[df["p"] >= thresh]
        bs = bootstrap_mean(kept["pnl"].to_numpy())
        wr = (kept["pnl"] > 0).mean()
        print(f"    top {q*100:>3.0f}% (p>={thresh:.4f})  "
              f"{len(kept):>5,}  ${bs['mean']:>+7.2f}  "
              f"${bs['p05']:>+7.2f}  ${bs['total']:>+8,.0f}  "
              f"${bs['mean']-base_mean:>+7.2f}")
        res[f"top{int(q*100)}_mean"] = bs["mean"]
        res[f"top{int(q*100)}_total"] = bs["total"]
        res[f"top{int(q*100)}_p05"] = bs["p05"]
        res[f"top{int(q*100)}_wr"] = wr
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("ML AT bar1+30s  —  predict 0.75-ATR (T_F == T_E, with-delay data)")
    print("=" * 78)

    all_rows = []
    for yr in YEARS:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        df = load_bar1_trades_with_p30(yr)
        unr_pass = df["target_unr075"].mean()
        print(f"  V_A confirmed RTH (with-delay): {len(df):,}  "
              f"({time.time()-t0:.0f}s)")
        print(f"  0.75ATR pass: {unr_pass:.3%}  "
              f"trade WR: {(df['net_pnl']>0).mean():.3%}  "
              f"mean=${df['net_pnl'].mean():+.2f}  "
              f"total=${df['net_pnl'].sum():+,.0f}")
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
    yr_col = all_df["year"]
    forbidden = {"target_unr075", "unr_5m_atr", "net_pnl", "gross_pnl",
                 "hold_s", "exit_reason", "running_mfe", "running_mae",
                 "entry_ts", "fill_price", "exit_ts", "exit_price",
                 "atr_at_signal", "year", "confirmed", "became_trade"}
    leaked = forbidden.intersection(X.columns)
    assert not leaked, f"Label leak: {leaked}"
    print(f"\nFeature matrix shape: {X.shape}")
    p30_feats = [c for c in X.columns if c.startswith("p30_")]
    print(f"New p30_* features ({len(p30_feats)}): {sorted(p30_feats)}")

    results = {}
    for name, train_years, eval_years in [
        ("Config A: train 2024, score 2025", [2024], [2025]),
        ("Config B: train 2024+2025, score 2026", [2024, 2025], [2026]),
    ]:
        print(f"\n{'='*78}\n{name}\n{'='*78}")
        tr_mask = yr_col.isin(train_years).values
        ev_mask = yr_col.isin(eval_years).values
        X_tr_full = X[tr_mask]
        y_tr_full = y[tr_mask]
        tr_dt = all_df.loc[tr_mask, "decision_ts"].to_numpy()
        order = np.argsort(tr_dt, kind="mergesort")
        X_tr_full = X_tr_full.iloc[order].reset_index(drop=True)
        y_tr_full = y_tr_full.iloc[order].reset_index(drop=True)
        tr_dt = tr_dt[order]
        n_val = int(len(X_tr_full) * VAL_FRAC)
        n_tr = len(X_tr_full) - n_val
        X_tr = X_tr_full.iloc[:n_tr]
        y_tr = y_tr_full.iloc[:n_tr]
        X_val = X_tr_full.iloc[n_tr:]
        y_val = y_tr_full.iloc[n_tr:]
        print(f"  train n={n_tr:,}  val n={n_val:,}  eval n={ev_mask.sum():,}")
        model = fit_model(X_tr, y_tr, X_val, y_val)
        tr_auc = roc_auc_score(y_tr, model.predict_proba(X_tr)[:, 1])
        v_auc = roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])
        print(f"  best iter: {model.best_iteration_}  "
              f"train AUC={tr_auc:.4f}  val AUC={v_auc:.4f}")
        res = evaluate(model, X[ev_mask], y[ev_mask], pnl[ev_mask],
                          eval_years[0])
        # Importance ranking
        imp = pd.DataFrame({
            "feat": X.columns,
            "gain": model.booster_.feature_importance(importance_type="gain"),
        }).sort_values("gain", ascending=False).reset_index(drop=True)
        print(f"\n  Top 15 features (gain):")
        for _, row in imp.head(15).iterrows():
            tag = "  <NEW>" if row["feat"].startswith("p30_") else ""
            print(f"    {row['feat']:<42}  {row['gain']:>8.0f}{tag}")
        # Count of p30 features in top 20
        top20 = imp.head(20)
        n_p30_top20 = top20["feat"].str.startswith("p30_").sum()
        print(f"\n  p30_* features in top 20: {n_p30_top20} / 12")
        results[eval_years[0]] = res

    # Combined
    print(f"\n{'='*78}\nCOMBINED 2025+2026\n{'='*78}")
    combined = pd.concat([
        results[2025]["df"].assign(year=2025),
        results[2026]["df"].assign(year=2026),
    ], ignore_index=True)
    base_total = combined["pnl"].sum()
    base_mean = combined["pnl"].mean()
    print(f"  Baseline 2025+2026: n={len(combined):,}  "
          f"mean=${base_mean:+.2f}  total=${base_total:+,.0f}")
    print(f"\n  Global ML filter:")
    print(f"    {'gate':<24}  {'kept':>5}  {'mean':>9}  "
          f"{'total':>10}  {'2025':>10}  {'2026':>10}")
    for q in [0.50, 0.30, 0.20, 0.10]:
        thresh = combined["p"].quantile(1 - q)
        kept = combined[combined["p"] >= thresh]
        y25 = kept[kept["year"] == 2025]["pnl"].sum()
        y26 = kept[kept["year"] == 2026]["pnl"].sum()
        print(f"    top {q*100:>3.0f}% (p>={thresh:.4f})  "
              f"{len(kept):>5,}  ${kept['pnl'].mean():>+7.2f}  "
              f"${kept['pnl'].sum():>+8,.0f}  "
              f"${y25:>+8,.0f}  ${y26:>+8,.0f}")

    print(f"\n{'='*78}\nSUMMARY  —  bar1+30s ML (with-delay trades, T_F=T_E)")
    print(f"{'='*78}")
    for yr, res in results.items():
        print(f"  OOS {yr}: AUC={res['auc']:.4f}  "
              f"baseline=${res['base_total']:+,.0f}  "
              f"top30=${res['top30_total']:+,.0f}  "
              f"top10=${res['top10_total']:+,.0f}")
    print(f"\n  Combined 2025+2026 baseline:    ${base_total:+,.0f}")


if __name__ == "__main__":
    main()
