"""RTH-only ML on flip-time features + bootstrap robustness on deciles.

Two changes vs `ml_flip_predictions.py`:
  1. Filter regime_flips to session == 'RTH' BEFORE training.
  2. Bootstrap OOS top/bottom decile metrics to test whether lift is
     statistically robust or noise.

Targets unchanged:
  - TARGET 1: predict bar1 confirmation
  - TARGET 2: predict 1-ATR MFE from flip_bar_c within 360s

Bootstrap design:
  - For each of N_BOOTSTRAP resamples (default 2,000):
      * Resample (with replacement) the rows inside each decile of
        OOS predictions, keeping the decile membership fixed.
      * Compute the metric mean (confirm rate / MFE rate / mean MFE).
  - Report 5th, 50th, 95th percentile of the bootstrap distribution.
  - Robustness test: top-decile bootstrap 5th-percentile > base rate?

Output:
  - ml_flip_rth_predictions.parquet  (OOS per-row predictions)
  - ml_rth_target1_feat_imp.csv      (gain importances)
  - ml_rth_target2_feat_imp.csv
  - ml_flip_rth_bootstrap.log        (stdout)
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
from sklearn.metrics import roc_auc_score, brier_score_loss


YEARS = [2024, 2025, 2026]
SNAP_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet"
    for yr in YEARS
}
ONE_S_PATHS = {
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}
OUT = Path("studies/v_a_excursion_regime/results_v0")

TARGET2_WINDOW_S = 360
TARGET2_MFE_THRESHOLD_ATR = 1.0
VAL_FRAC = 0.20
SEED = 42
N_BOOTSTRAP = 2000


def load_1s_hl(path: str) -> pd.DataFrame:
    df = pq.read_table(path, columns=["ts_event", "high", "low"]).to_pandas()
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    else:
        df["ts_event"] = df["ts_event"].dt.tz_convert("UTC")
    ts_naive = df["ts_event"].dt.tz_localize(None)
    df["ts_event_ns"] = ts_naive.astype("datetime64[ns]").astype("int64")
    assert df["ts_event_ns"].iloc[0] > 1_500_000_000_000_000_000
    return df


def compute_target1(snap: pd.DataFrame) -> pd.DataFrame:
    rf = snap.loc[snap["kind"] == "regime_flip",
                   ["decision_ts", "direction"]].copy().reset_index(drop=True)
    b1 = snap.loc[snap["kind"] == "bar1_check",
                   ["decision_ts", "direction", "confirmed"]].copy()
    b1 = b1.rename(columns={"decision_ts": "_b1_ts"})
    rf["_exp_b1_ts"] = rf["decision_ts"] + 60_000_000_000
    merged = rf.merge(
        b1, left_on=["_exp_b1_ts", "direction"],
        right_on=["_b1_ts", "direction"], how="left")
    merged["target_confirmed"] = merged["confirmed"].fillna(False).astype(int)
    return merged[["decision_ts", "direction", "target_confirmed"]]


def compute_target2(flips: pd.DataFrame, bars: pd.DataFrame):
    bars_ts = bars["ts_event_ns"].to_numpy()
    bars_h = bars["high"].to_numpy()
    bars_l = bars["low"].to_numpy()
    n = len(flips)
    label = np.zeros(n, dtype=int)
    mfe_atr = np.full(n, np.nan)
    dec_ts = flips["decision_ts"].to_numpy(dtype=np.int64)
    direction = flips["direction"].to_numpy(dtype=np.int64)
    atr = flips["atr_1m"].to_numpy()
    fbc = flips["flip_bar_c"].to_numpy()
    for k in range(n):
        T = int(dec_ts[k]); a = float(atr[k])
        if not (np.isfinite(a) and a > 0): continue
        T_end = T + TARGET2_WINDOW_S * 1_000_000_000
        i_s = int(np.searchsorted(bars_ts, T, side="left"))
        i_e = int(np.searchsorted(bars_ts, T_end, side="left"))
        if i_e <= i_s: continue
        c = float(fbc[k])
        if direction[k] == 1:
            mfe = float(bars_h[i_s:i_e].max()) - c
        else:
            mfe = c - float(bars_l[i_s:i_e].min())
        m_atr = mfe / a
        mfe_atr[k] = m_atr
        label[k] = int(m_atr >= TARGET2_MFE_THRESHOLD_ATR)
    return label, mfe_atr


def make_feature_matrix(flips: pd.DataFrame) -> pd.DataFrame:
    df = flips.copy().reset_index(drop=True)
    rng = df["flip_bar_h"] - df["flip_bar_l"]
    df["flip_bar_loc_in_range"] = np.where(
        rng > 0, (df["flip_bar_c"] - df["flip_bar_l"]) / rng, 0.5)
    df["flip_bar_range_atr"] = np.where(
        df["atr_1m"] > 0, rng / df["atr_1m"], np.nan)
    df["flip_close_minus_mid_atr"] = np.where(
        df["atr_1m"] > 0,
        (df["flip_bar_c"] - (df["flip_bar_h"] + df["flip_bar_l"]) / 2)
            / df["atr_1m"],
        np.nan,
    )
    upper_wick = df["flip_bar_h"] - df["flip_bar_c"]
    lower_wick = df["flip_bar_c"] - df["flip_bar_l"]
    df["wick_against_atr"] = np.where(
        df["atr_1m"] > 0,
        np.where(df["direction"] == 1, upper_wick, lower_wick) / df["atr_1m"],
        np.nan,
    )
    df["wick_with_atr"] = np.where(
        df["atr_1m"] > 0,
        np.where(df["direction"] == 1, lower_wick, upper_wick) / df["atr_1m"],
        np.nan,
    )
    for tf in ["30s", "1m", "3m", "5m"]:
        df[f"aligned_{tf}"] = (df[f"regime_{tf}"] == df["direction"]).astype(int)
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
        -df["dist_close_to_vwap_atr"] * df["direction"])
    for lab in ["1m", "5m", "15m"]:
        df[f"vol_imbalance_dir_{lab}"] = (
            df[f"vol_imbalance_{lab}"] * df["direction"])

    drop_cols = [
        "decision_ts", "bar_ts_event", "kind", "event_id",
        "session", "is_rth",  # constant after RTH filter
        "flip_bar_h", "flip_bar_l", "flip_bar_c",
        "bar1_h", "bar1_l", "bar1_o", "bar1_c",
        "hhll_ok", "momentum_ok", "confirmed", "became_trade",
        "trade_event_id", "trade_direction", "trade_fill_price",
        "trade_fill_ts", "trade_atr_at_signal",
        "elapsed_s", "cur_pnl_atr", "cur_mfe_atr", "cur_mae_atr",
        "cur_giveback_atr", "cur_close_price",
        "last_30s_close_ts", "last_1m_close_ts",
        "last_3m_close_ts", "last_5m_close_ts",
        "flip_direction",
        "event_close_px", "cum_vol_session",
        "close_30s", "close_1m", "close_3m", "close_5m",
        "vwap_value",
        "dist_close_to_vwap",
        "dist_close_to_vwap_upper_1sd", "dist_close_to_vwap_lower_1sd",
        "dist_close_to_vwap_upper_2sd", "dist_close_to_vwap_lower_2sd",
        "dist_close_to_vwap_upper_3sd", "dist_close_to_vwap_lower_3sd",
        "direction",
        "target_confirmed", "target_mfe_1atr_6bar", "mfe_atr_6bar",
        "year",
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
    print(f"  Base OOS={base_oos:.3%}  best iter: {model.best_iteration_}")

    df = pd.DataFrame({"p": p_oos, "y": y_oos.values})
    df["decile"] = pd.qcut(df["p"].rank(method="first"), 10,
                              labels=False, duplicates="drop")
    print(f"\n  OOS decile lift:")
    print(f"    {'dec':>4}  {'n':>5}  {'p_mean':>8}  {'rate':>8}  {'lift':>6}")
    for dec, grp in df.groupby("decile"):
        rate = grp["y"].mean()
        p_mean = grp["p"].mean()
        lift = rate / base_oos if base_oos > 0 else np.nan
        print(f"    d{int(dec)+1:>2}    {len(grp):>5,}  "
              f"{p_mean:>8.4f}  {rate:>7.3%}  {lift:>5.2f}x")

    imp = pd.DataFrame({
        "feat": X_tr.columns,
        "gain": model.booster_.feature_importance(importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    print(f"\n  Top 15 features:")
    for _, row in imp.head(15).iterrows():
        print(f"    {row['feat']:<42}  {row['gain']:>8.0f}")

    return {"model": model, "p_oos": p_oos, "df_decile": df,
            "auc_train": auc_tr, "auc_val": auc_val, "auc_oos": auc_oos,
            "base_oos": base_oos, "imp": imp}


def bootstrap_metric(values: np.ndarray, n_boot: int = N_BOOTSTRAP,
                       seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": np.nan, "p05": np.nan,
                "p50": np.nan, "p95": np.nan}
    boot = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot[b] = values[idx].mean()
    return {
        "n": n,
        "mean": float(values.mean()),
        "p05": float(np.percentile(boot, 5)),
        "p50": float(np.percentile(boot, 50)),
        "p95": float(np.percentile(boot, 95)),
    }


def report_bootstrap(name: str, df_decile: pd.DataFrame, base: float,
                       value_col: str, n_boot: int = N_BOOTSTRAP):
    print(f"\n{'-'*78}")
    print(f"  Bootstrap (n={n_boot}) — {name}")
    print(f"{'-'*78}")
    print(f"  Base (whole OOS): {base:.4f}")
    print(f"    {'dec':>4}  {'n':>5}  {'mean':>9}  {'p05':>9}  {'p95':>9}  "
          f"{'lift_mean':>9}  {'lift_p05':>9}")
    for dec_target in [0, 4, 8, 9]:
        sub = df_decile[df_decile["decile"] == dec_target]
        if not len(sub):
            continue
        bs = bootstrap_metric(sub[value_col].to_numpy(), n_boot=n_boot)
        lift_mean = bs["mean"] / base if base > 0 else np.nan
        lift_p05 = bs["p05"] / base if base > 0 else np.nan
        print(f"    d{dec_target+1:>2}    {bs['n']:>5,}  "
              f"{bs['mean']:>9.4f}  {bs['p05']:>9.4f}  {bs['p95']:>9.4f}  "
              f"{lift_mean:>8.2f}x  {lift_p05:>8.2f}x")
    # Robustness verdicts
    top = df_decile[df_decile["decile"] == 9]
    if len(top):
        bs = bootstrap_metric(top[value_col].to_numpy(), n_boot=n_boot)
        if bs["p05"] > base:
            verdict = "PASS  — top-decile 5th-pct > base"
        elif bs["p95"] < base:
            verdict = "INVERSE — top decile robustly below base"
        else:
            verdict = "FRAGILE — bootstrap CI straddles base"
        print(f"\n  Top-decile verdict: {verdict}")
    bot = df_decile[df_decile["decile"] == 0]
    if len(bot):
        bs = bootstrap_metric(bot[value_col].to_numpy(), n_boot=n_boot)
        if bs["p95"] < base:
            verdict = "PASS  — bottom-decile 95th-pct < base"
        else:
            verdict = "WEAK  — bottom-decile CI straddles base"
        print(f"  Bottom-decile verdict: {verdict}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("RTH-ONLY ML + BOOTSTRAP  —  TARGETS 1 (confirm) & 2 (1ATR/6bar)")
    print("=" * 78)

    all_flips = []
    for yr in YEARS:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        snap = pd.read_parquet(SNAP_PATHS[yr])
        flips = snap[(snap["kind"] == "regime_flip")
                    & (snap["session"] == "RTH")].reset_index(drop=True)
        print(f"  {len(flips):,} RTH regime_flips loaded "
              f"({time.time()-t0:.0f}s)")

        t1_df = compute_target1(snap)
        flips = flips.merge(t1_df, on=["decision_ts", "direction"], how="left")
        flips["target_confirmed"] = flips["target_confirmed"].fillna(0).astype(int)
        print(f"  target1 pos rate: {flips['target_confirmed'].mean():.3%}")

        bars = load_1s_hl(ONE_S_PATHS[yr])
        print(f"  loaded {len(bars):,} 1s bars ({time.time()-t0:.0f}s)")
        y2, mfe_atr = compute_target2(flips, bars)
        flips["target_mfe_1atr_6bar"] = y2
        flips["mfe_atr_6bar"] = mfe_atr
        print(f"  target2 pos rate: "
              f"{flips['target_mfe_1atr_6bar'].mean():.3%}")
        print(f"  target2 mean MFE/ATR: "
              f"{np.nanmean(flips['mfe_atr_6bar']):.4f}")
        flips["year"] = yr
        all_flips.append(flips)
        del bars

    all_df = pd.concat(all_flips, ignore_index=True)
    n_pre = len(all_df)
    all_df = all_df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset=["decision_ts", "direction"], keep="first").reset_index(
        drop=True)
    print(f"\nDedupe cross-year: {n_pre:,} -> {len(all_df):,}")

    X = make_feature_matrix(all_df)
    y1 = all_df["target_confirmed"]
    y2 = all_df["target_mfe_1atr_6bar"]
    yr_col = all_df["year"]

    forbidden = {
        "target_confirmed", "target_mfe_1atr_6bar", "mfe_atr_6bar",
        "year", "confirmed", "became_trade",
    }
    leaked = forbidden.intersection(X.columns)
    assert not leaked, f"Label leak: {leaked}"

    print(f"\nFeature matrix shape: {X.shape}")

    is_mask = yr_col.isin([2024, 2025])
    oos_mask = yr_col == 2026
    X_is, X_oos = X[is_mask], X[oos_mask]
    y1_is, y1_oos = y1[is_mask], y1[oos_mask]
    y2_is, y2_oos = y2[is_mask], y2[oos_mask]

    # Temporal val split inside IS
    is_dt = all_df.loc[is_mask.values, "decision_ts"].to_numpy()
    order = np.argsort(is_dt, kind="mergesort")
    X_is = X_is.iloc[order].reset_index(drop=True)
    y1_is = y1_is.iloc[order].reset_index(drop=True)
    y2_is = y2_is.iloc[order].reset_index(drop=True)
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

    oos_df = all_df.loc[oos_mask.values].reset_index(drop=True)

    res1 = train_eval(
        X_is.iloc[tr_idx], y1_is.iloc[tr_idx],
        X_is.iloc[val_idx], y1_is.iloc[val_idx],
        X_oos, y1_oos,
        name="TARGET 1 (RTH): predict bar1 confirmation")
    res2 = train_eval(
        X_is.iloc[tr_idx], y2_is.iloc[tr_idx],
        X_is.iloc[val_idx], y2_is.iloc[val_idx],
        X_oos, y2_oos,
        name="TARGET 2 (RTH): predict 1-ATR MFE within 6 bars from flip close")

    # Augment decile dataframes with mfe_atr_6bar (positional alignment).
    res1["df_decile"]["mfe_atr_6bar"] = oos_df["mfe_atr_6bar"].to_numpy()
    res2["df_decile"]["mfe_atr_6bar"] = oos_df["mfe_atr_6bar"].to_numpy()

    print(f"\n{'='*78}")
    print(f"BOOTSTRAP ROBUSTNESS (N={N_BOOTSTRAP})")
    print(f"{'='*78}")
    report_bootstrap(
        "Target 1 — confirm rate per decile (binary y)",
        res1["df_decile"], res1["base_oos"], "y")
    report_bootstrap(
        "Target 2 — 1-ATR MFE rate per decile (binary y)",
        res2["df_decile"], res2["base_oos"], "y")

    # Continuous economic metric: mean MFE/ATR per Target 2 decile
    base_mfe = np.nanmean(res2["df_decile"]["mfe_atr_6bar"])
    report_bootstrap(
        "Target 2 — MEAN MFE/ATR per decile (continuous)",
        res2["df_decile"], base_mfe, "mfe_atr_6bar")

    pred_df = pd.DataFrame({
        "decision_ts": all_df["decision_ts"].values,
        "year": yr_col.values,
        "direction": all_df["direction"].values,
        "target_confirmed": y1.values,
        "target_mfe_1atr_6bar": y2.values,
        "mfe_atr_6bar": all_df["mfe_atr_6bar"].values,
    })
    pred_df["p_confirm_oos"] = np.nan
    pred_df["p_mfe1atr_oos"] = np.nan
    pred_df.loc[oos_mask.values, "p_confirm_oos"] = res1["p_oos"]
    pred_df.loc[oos_mask.values, "p_mfe1atr_oos"] = res2["p_oos"]
    pred_df.to_parquet(OUT / "ml_flip_rth_predictions.parquet", index=False)
    res1["imp"].to_csv(OUT / "ml_rth_target1_feat_imp.csv", index=False)
    res2["imp"].to_csv(OUT / "ml_rth_target2_feat_imp.csv", index=False)

    print(f"\n{'='*78}")
    print("SUMMARY (RTH-only)")
    print(f"{'='*78}")
    print(f"Target 1: train AUC {res1['auc_train']:.4f}  val "
          f"{res1['auc_val']:.4f}  OOS {res1['auc_oos']:.4f}")
    print(f"Target 2: train AUC {res2['auc_train']:.4f}  val "
          f"{res2['auc_val']:.4f}  OOS {res2['auc_oos']:.4f}")


if __name__ == "__main__":
    main()
