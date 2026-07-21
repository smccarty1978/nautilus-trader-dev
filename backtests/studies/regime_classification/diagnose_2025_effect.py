"""Diagnose why hmm_4 state 3 pays in 2025 but not 2023/2024.

Compares NT-validated trades inside the hmm_4 state-3 cohort across
profitable (2025) vs unprofitable (2023+2024) OOS years.

For each trade compute:
  - gross PnL (pts and ATR)
  - MFE ATR / MAE ATR during trade (1s walk)
  - hold minutes
  - state at entry, +5m, +10m, +15m  (1m-aligned)
  - state duration BEFORE the flip (consecutive state-3 bars pre-flip)
  - state persistence flags after entry
  - session features: ET time-of-day, distance from PDH/PDL/ONH/ONL
  - All 24 state features at entry-bar

Then answer the user's 5 questions:
  Q1 — more trades won in 2025?
  Q2 — winners much larger in 2025?
  Q3 — losers smaller in 2025?
  Q4 — state persisted longer in 2025?
  Q5 — different session/time/location context?
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
import pytz
from numba import njit

NS = 1_000_000_000
ET = pytz.timezone("America/New_York")
RTH_START_ET = (9 * 3600) + (30 * 60)
RTH_END_ET = 16 * 3600
PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
OUT = Path("studies/regime_classification/results")
ONE_S = {y: f"data/raw/{PRODUCT}_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = f"data/raw/{PRODUCT}_v0_1s_2026_ytd.parquet"

# Group years
PROFITABLE = (2025, 2026)
UNPROFITABLE = (2023, 2024)
ALL_OOS = (2023, 2024, 2025, 2026)
TARGET_STATE = 3
STATE_COL = "hmm_4"

FEATURE_COLS = [
    "ret_5s", "ret_30s", "ret_60s", "ret_300s", "cum_abs_60s",
    "rv_30s", "rv_300s",
    "range_atr_60s", "range_atr_300s", "range_atr_1800s",
    "vol_expansion",
    "efficiency_300s", "chop_ratio_300s", "n_dir_changes_60s",
    "body_ratio", "upper_wick", "lower_wick", "close_location",
    "vwap_z_signed", "vwap_z_abs", "vwap_slope_5m_atr", "session_pos",
    "range_pct_60s_vs_1h", "compress_drift",
]


@njit
def compute_mfe_mae(entry_ts, exit_ts, entry_px, dir_arr, atr_arr,
                     ts_1s, h_1s, l_1s):
    n = len(entry_ts)
    mfe = np.full(n, np.nan)
    mae = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; T1 = exit_ts[k]
        if T0 < 0 or T1 <= T0 or not np.isfinite(entry_px[k]) or atr_arr[k] <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, T1, side="left")
        if i_hi <= i_lo:
            continue
        ep = entry_px[k]; d = dir_arr[k]
        seg_h = h_1s[i_lo:i_hi]; seg_l = l_1s[i_lo:i_hi]
        if d == 1:
            best = seg_h.max() - ep
            worst = ep - seg_l.min()
        else:
            best = ep - seg_l.min()
            worst = seg_h.max() - ep
        mfe[k] = max(best, 0.0) / atr_arr[k]
        mae[k] = max(worst, 0.0) / atr_arr[k]
    return mfe, mae


def compute_session_HL_table(start_y=2019, end_y=2026):
    parts = []
    for y in range(start_y, end_y + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(p, columns=["high", "low"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    et = bars.index.tz_convert(ET)
    et_sod = et.hour * 3600 + et.minute * 60 + et.second
    is_rth = (et_sod >= RTH_START_ET) & (et_sod < RTH_END_ET)
    is_post_close = et_sod >= RTH_END_ET
    et_date_dt = pd.to_datetime(et.date)
    eth_dates_dt = et_date_dt.copy()
    eth_dates_dt = eth_dates_dt.where(~is_post_close,
                                       eth_dates_dt + pd.Timedelta(days=1))
    rth_df = pd.DataFrame({
        "date": et_date_dt[is_rth],
        "high": bars["high"].values[is_rth],
        "low":  bars["low"].values[is_rth]})
    rth = rth_df.groupby("date").agg(rth_high=("high", "max"),
                                      rth_low=("low",  "min"))
    eth_df = pd.DataFrame({
        "date": eth_dates_dt[~is_rth],
        "high": bars["high"].values[~is_rth],
        "low":  bars["low"].values[~is_rth]})
    eth = eth_df.groupby("date").agg(eth_high=("high", "max"),
                                      eth_low=("low",  "min"))
    return rth.join(eth, how="outer").sort_index()


def attach_levels(df, hl_table):
    df = df.copy()
    df["et_date"] = pd.to_datetime(
        pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
          .dt.tz_convert(ET).dt.date)
    rth_dates = pd.to_datetime(hl_table.dropna(subset=["rth_high"]).index)
    rth_dates_arr = rth_dates.to_numpy()
    rth_dates_arr.sort()
    flip_dates = df["et_date"].to_numpy()
    idx = np.searchsorted(rth_dates_arr, flip_dates, side="left") - 1
    prior_dates = pd.Series(
        np.where(idx >= 0, rth_dates_arr[np.clip(idx, 0, None)], pd.NaT),
        index=df.index)
    df["prior_date"] = pd.to_datetime(prior_dates)
    df["pdh"] = hl_table["rth_high"].reindex(df["prior_date"].values).values
    df["pdl"] = hl_table["rth_low"].reindex(df["prior_date"].values).values
    df["onh"] = hl_table["eth_high"].reindex(df["et_date"].values).values
    df["onl"] = hl_table["eth_low"].reindex(df["et_date"].values).values
    return df


def lookup_state(target_ts_arr, state_ts_arr, state_arr, exact=True):
    state_arr = np.asarray(state_arr).flatten().astype(np.int64)
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    if exact:
        i = np.searchsorted(state_ts_arr, target_ts_arr, side="left")
        valid = (i < len(state_ts_arr)) & \
                (state_ts_arr[np.clip(i, 0, len(state_ts_arr)-1)]
                  == target_ts_arr)
        out[valid] = state_arr[i[valid]]
    else:
        i = np.searchsorted(state_ts_arr, target_ts_arr, side="right") - 1
        valid = i >= 0
        out[valid] = state_arr[i[valid]]
    return out


@njit
def state_duration_before(flip_open_ts_arr, state_ts_arr, state_arr,
                            target_state):
    """For each flip, count consecutive state==target bars ending at the
    flip bar (inclusive). Returns counts (1 means only the flip itself
    is in target state)."""
    n = len(flip_open_ts_arr)
    out = np.zeros(n, dtype=np.int64)
    for k in range(n):
        T = flip_open_ts_arr[k]
        i = np.searchsorted(state_ts_arr, T, side="left")
        if i >= len(state_ts_arr) or state_ts_arr[i] != T:
            continue
        cnt = 0
        j = i
        while j >= 0 and state_arr[j] == target_state:
            cnt += 1
            j -= 1
        out[k] = cnt
    return out


def load_trades(years):
    parts = []
    for y in years:
        p = Path(f"backtests/hmm_state_filtered/results/"
                 f"nq_{STATE_COL}_s{TARGET_STATE}_{y}/trades.parquet")
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        d["year"] = y
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def main():
    t0 = time.time()
    print(f"PRODUCT={PRODUCT}  state={STATE_COL}=={TARGET_STATE}")
    df = load_trades(ALL_OOS)
    df["entry_ts"] = df["entry_ts"].astype(np.int64)
    df["exit_ts"]  = df["exit_ts"].astype(np.int64)
    df["signal_direction"] = df["signal_direction"].astype(np.int64)
    print(f"  OOS trades: {len(df):,}")

    # Per-trade gross PnL
    df["pnl_pts"] = (df["exit_px"] - df["entry_px"]) * df["signal_direction"]
    df["pnl_atr"] = df["pnl_pts"] / df["entry_atr"]
    df["win"] = (df["pnl_pts"] > 0).astype(int)
    df["hold_min"] = (df["exit_ts"] - df["entry_ts"]) / (60 * NS)

    # MFE / MAE per trade (1s walk)
    print("Computing MFE / MAE per trade ...")
    mfe_all = np.full(len(df), np.nan)
    mae_all = np.full(len(df), np.nan)
    for y in sorted(df["year"].unique()):
        sub_idx = df.index[df["year"] == y]
        bars_parts = []
        for yy in (y - 1, y, y + 1):
            p = ONE_S.get(yy)
            if p and Path(p).exists():
                bars_parts.append(pd.read_parquet(p, columns=["high", "low"]))
        bars = pd.concat(bars_parts).sort_index()
        bars = bars[~bars.index.duplicated(keep="first")]
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        ts_1s = bars.index.values.astype(np.int64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        sub = df.loc[sub_idx]
        mfe_y, mae_y = compute_mfe_mae(
            sub["entry_ts"].to_numpy(np.int64),
            sub["exit_ts"].to_numpy(np.int64),
            sub["entry_px"].to_numpy(np.float64),
            sub["signal_direction"].to_numpy(np.int64),
            sub["entry_atr"].to_numpy(np.float64),
            ts_1s, h_1s, l_1s)
        mfe_all[sub_idx.values - df.index.min()] = mfe_y
        mae_all[sub_idx.values - df.index.min()] = mae_y
        print(f"  MFE/MAE {y}: {len(sub):,}")
    df["mfe_atr"] = mfe_all
    df["mae_atr"] = mae_all

    # Session levels
    print("Computing session H/L table + distances ...")
    hl = compute_session_HL_table()
    df = attach_levels(df, hl)
    df["dist_pdh_atr"] = (df["entry_px"] - df["pdh"]) / df["entry_atr"]
    df["dist_pdl_atr"] = (df["entry_px"] - df["pdl"]) / df["entry_atr"]
    df["dist_onh_atr"] = (df["entry_px"] - df["onh"]) / df["entry_atr"]
    df["dist_onl_atr"] = (df["entry_px"] - df["onl"]) / df["entry_atr"]

    # ET time-of-day
    et_dt = pd.to_datetime(df["entry_ts"], unit="ns", utc=True).dt.tz_convert(ET)
    df["et_hour"] = et_dt.dt.hour
    df["et_minute_of_day"] = et_dt.dt.hour * 60 + et_dt.dt.minute
    df["in_rth"] = (et_dt.dt.hour * 3600 + et_dt.dt.minute * 60 >= RTH_START_ET) & \
                    (et_dt.dt.hour * 3600 + et_dt.dt.minute * 60 < RTH_END_ET)
    df["in_first_hour"] = ((et_dt.dt.hour == 9) & (et_dt.dt.minute >= 30)) | \
                            (et_dt.dt.hour == 10) & (et_dt.dt.minute < 30)

    # State features + future-state persistence
    print("Loading state classifications ...")
    states_df = pd.read_parquet(OUT / f"states_{PRODUCT.lower()}_1m.parquet")
    state_ts = states_df.index.values.astype(np.int64)
    state_arr = states_df[STATE_COL].to_numpy(np.int64)

    # Entry at bar1-close → bar1's open_ts = entry_ts - 60s, flip-bar's = entry_ts - 120s.
    # State features come from the bar that just closed at entry = bar with open_ts = entry_ts - 60s.
    feature_ts_at_entry = df["entry_ts"].to_numpy(np.int64) - 60 * NS
    # Lookup features
    print("Looking up state features at entry ...")
    feature_lookup_idx = np.searchsorted(state_ts, feature_ts_at_entry, side="left")
    valid = (feature_lookup_idx < len(state_ts)) & \
             (state_ts[np.clip(feature_lookup_idx, 0, len(state_ts)-1)] == feature_ts_at_entry)
    for c in FEATURE_COLS:
        col_arr = states_df[c].to_numpy(np.float64)
        out_arr = np.full(len(df), np.nan)
        out_arr[valid] = col_arr[feature_lookup_idx[valid]]
        df[f"feat_{c}"] = out_arr

    # State at +5m, +10m, +15m (bars closing at entry+5m, +10m, +15m → open_ts = entry+5m-60s etc.)
    for lag_min in (5, 10, 15):
        target = df["entry_ts"].to_numpy(np.int64) + (lag_min - 1) * 60 * NS
        df[f"state_plus_{lag_min}m"] = lookup_state(target, state_ts, state_arr)
        df[f"persist_{lag_min}m"] = (df[f"state_plus_{lag_min}m"] == TARGET_STATE).astype(int)

    # State duration BEFORE the flip bar
    # Flip-bar open_ts = entry_ts - 120s (since entry is bar1 close, flip bar is the one before)
    flip_open_ts = df["entry_ts"].to_numpy(np.int64) - 2 * 60 * NS
    df["state_dur_before"] = state_duration_before(flip_open_ts, state_ts,
                                                     state_arr, TARGET_STATE)

    out_p = OUT / f"diagnose_2025_{PRODUCT.lower()}.parquet"
    df.to_parquet(out_p, index=False)
    print(f"  saved {out_p}")

    # ── REPORT ──
    def yearset_label(years):
        return "+".join(str(y) for y in years)

    GROUPS = [
        ("UNPROF (23+24)", df[df["year"].isin(UNPROFITABLE)]),
        ("PROF (25)",      df[df["year"] == 2025]),
        ("PROF (26)",      df[df["year"] == 2026]),
    ]

    print(f"\n{'='*92}\nQ1: Win rate by group\n{'='*92}")
    print(f"  {'group':<18}{'n':>7}{'win%':>9}{'mean ATR':>11}"
          f"{'median ATR':>13}{'long n':>9}{'short n':>10}")
    for label, sub in GROUPS:
        wr = sub["win"].mean()
        ma = sub["pnl_atr"].mean()
        mm = sub["pnl_atr"].median()
        ln = (sub["signal_direction"] == 1).sum()
        sn = (sub["signal_direction"] == -1).sum()
        print(f"  {label:<18}{len(sub):>7}{wr:>8.1%}{ma:>+11.3f}"
              f"{mm:>+13.3f}{ln:>9}{sn:>10}")

    print(f"\n{'='*92}\nQ2: Winner / loser size by group (ATR units)\n{'='*92}")
    print(f"  {'group':<18}{'win mean':>10}{'win med':>10}{'win 90%':>10}"
          f"{'loss mean':>11}{'loss med':>10}{'loss 10%':>10}")
    for label, sub in GROUPS:
        wins = sub.loc[sub["win"] == 1, "pnl_atr"]
        losses = sub.loc[sub["win"] == 0, "pnl_atr"]
        print(f"  {label:<18}{wins.mean():>+10.3f}{wins.median():>+10.3f}"
              f"{wins.quantile(0.9):>+10.3f}"
              f"{losses.mean():>+11.3f}{losses.median():>+10.3f}"
              f"{losses.quantile(0.1):>+10.3f}")

    # Decompose EV: EV = win_rate × mean_winner + loss_rate × mean_loser
    print(f"\n  EV decomposition:")
    print(f"  {'group':<18}{'wr':>7}{'mean win':>10}{'mean loss':>11}"
          f"{'wr×win':>10}{'lr×loss':>10}{'EV':>10}")
    for label, sub in GROUPS:
        wr = sub["win"].mean()
        wm = sub.loc[sub["win"] == 1, "pnl_atr"].mean()
        lm = sub.loc[sub["win"] == 0, "pnl_atr"].mean()
        a = wr * wm
        b = (1 - wr) * lm
        print(f"  {label:<18}{wr:>6.1%}{wm:>+10.3f}{lm:>+11.3f}"
              f"{a:>+10.3f}{b:>+10.3f}{a+b:>+10.3f}")

    print(f"\n{'='*92}\nQ3: MFE/MAE by group\n{'='*92}")
    print(f"  {'group':<18}{'MFE mean':>10}{'MFE med':>10}{'MFE 90%':>10}"
          f"{'MAE mean':>11}{'MAE med':>10}{'MAE 90%':>10}")
    for label, sub in GROUPS:
        m_f = sub["mfe_atr"].dropna()
        m_a = sub["mae_atr"].dropna()
        print(f"  {label:<18}{m_f.mean():>+10.3f}{m_f.median():>+10.3f}"
              f"{m_f.quantile(0.9):>+10.3f}{m_a.mean():>+11.3f}"
              f"{m_a.median():>+10.3f}{m_a.quantile(0.9):>+10.3f}")

    print(f"\n{'='*92}\nQ4: State duration / persistence by group\n{'='*92}")
    print(f"  {'group':<18}{'dur_before':>13}{'persist+5m':>13}"
          f"{'persist+10m':>14}{'persist+15m':>14}{'hold_med (min)':>17}")
    for label, sub in GROUPS:
        print(f"  {label:<18}{sub['state_dur_before'].mean():>12.1f}"
              f"{sub['persist_5m'].mean():>12.1%}"
              f"{sub['persist_10m'].mean():>13.1%}"
              f"{sub['persist_15m'].mean():>13.1%}"
              f"{sub['hold_min'].median():>16.1f}")

    print(f"\n{'='*92}\nQ5: Session/time/location context by group\n{'='*92}")
    print(f"  {'group':<18}{'in_rth%':>9}{'first_hr%':>11}{'med hour':>10}"
          f"{'PDH dist':>10}{'PDL dist':>10}{'ONH dist':>10}{'ONL dist':>10}")
    for label, sub in GROUPS:
        print(f"  {label:<18}{sub['in_rth'].mean():>8.1%}"
              f"{sub['in_first_hour'].mean():>10.1%}"
              f"{sub['et_hour'].median():>10.1f}"
              f"{sub['dist_pdh_atr'].median():>+10.3f}"
              f"{sub['dist_pdl_atr'].median():>+10.3f}"
              f"{sub['dist_onh_atr'].median():>+10.3f}"
              f"{sub['dist_onl_atr'].median():>+10.3f}")

    # Q5b: State features at entry — find which features differ most
    print(f"\n{'='*92}\nQ5b: State feature signatures at entry "
          f"(top features by |mean delta|)\n{'='*92}")
    unprof = df[df["year"].isin(UNPROFITABLE)]
    prof25 = df[df["year"] == 2025]
    rows = []
    for c in FEATURE_COLS:
        fc = f"feat_{c}"
        u_mean = unprof[fc].mean()
        p_mean = prof25[fc].mean()
        u_std = unprof[fc].std()
        delta_z = ((p_mean - u_mean) / u_std) if u_std > 0 else float("nan")
        rows.append((c, u_mean, p_mean, p_mean - u_mean, delta_z))
    rows.sort(key=lambda r: -abs(r[4]) if not np.isnan(r[4]) else 0)
    print(f"  {'feature':<26}{'UNPROF':>11}{'PROF25':>11}{'delta':>11}"
          f"{'delta z-score':>15}")
    for c, um, pm, d, dz in rows[:12]:
        print(f"  {c:<26}{um:>+11.3f}{pm:>+11.3f}{d:>+11.3f}{dz:>+15.3f}")

    # Q5c: For winners only — same comparison
    print(f"\n  Among WINNERS only (PROF25 vs UNPROF wins):")
    rows = []
    for c in FEATURE_COLS:
        fc = f"feat_{c}"
        u = unprof.loc[unprof["win"] == 1, fc]
        p = prof25.loc[prof25["win"] == 1, fc]
        if len(u) < 30 or len(p) < 30:
            continue
        u_std = u.std()
        delta_z = ((p.mean() - u.mean()) / u_std) if u_std > 0 else float("nan")
        rows.append((c, u.mean(), p.mean(), p.mean() - u.mean(), delta_z))
    rows.sort(key=lambda r: -abs(r[4]) if not np.isnan(r[4]) else 0)
    print(f"  {'feature':<26}{'UNPROF win':>13}{'PROF25 win':>13}"
          f"{'delta':>11}{'delta z':>11}")
    for c, um, pm, d, dz in rows[:10]:
        print(f"  {c:<26}{um:>+13.3f}{pm:>+13.3f}{d:>+11.3f}{dz:>+11.3f}")

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
