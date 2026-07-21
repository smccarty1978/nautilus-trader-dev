"""Augment pre-flip candidate table with the features missing from
the first round (volume, VWAP, OBV, calendar, 3m/5m TF state).

Reads `pre_flip_candidates.parquet` and adds:
  - Volume features at 1m/5m/15m windows:
    vol_bull/bear/total/delta/imbalance for each window (15 features)
  - VWAP features (CME globex session-anchored at 17:00 CT):
    vwap_value (raw — flagged year-proxy; will drop in feature matrix)
    vwap_sigma, dist_close_to_vwap_atr, dist to ±1/2/3σ bands ATR-norm
    (raw distances also computed but flagged for drop)
  - OBV session, cum_vol_session
  - Calendar: hour_ct, minute_ct, day_of_week, minutes_since_rth_open
  - Direction-aware: dist_to_vwap_dir_atr, vol_imbalance_dir_1m/5m/15m
  - 3m and 5m TF state: regime, bars_in_regime, atr (raw, will drop),
    close (raw, will drop), dist_close_to_ema3/9_h/l_TF_atr per TF

Output: `pre_flip_candidates_augmented.parquet` (existing 60 columns
+ ~46 new = ~106 total).

Causality: same as original build — every feature at a candidate's
close_ts uses only 1s bars with ts_event < close_ts.
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


OUT = Path("studies/v_a_excursion_regime/results_v0")
EMA_SHORT = 3
EMA_LONG = 9
ATR_PERIOD = 14
RTH_OPEN_MIN = 8 * 60 + 30

ONE_S_PATHS = {
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}

VOL_WINDOWS_S = [60, 300, 900]   # 1m, 5m, 15m
VOL_LABELS = ["1m", "5m", "15m"]


def load_1s(path: str) -> pd.DataFrame:
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
    return df


def session_id_for_ts(ts_event_utc: pd.Series) -> pd.Series:
    """CME globex session id: bars between (D-1) 17:00 CT and D 17:00 CT
    belong to session 'D'. Date-shifted by -17 hours."""
    ct = ts_event_utc.dt.tz_convert("America/Chicago")
    shifted = ct - pd.Timedelta(hours=17)
    return shifted.dt.date.astype(str)


def precompute_vol_vwap_state(bars: pd.DataFrame) -> tuple[dict, dict]:
    """Per-1s-bar:
      - bull_vol, bear_vol, total_vol, signed_vol (for OBV)
      - typical * volume, typical^2 * volume (for VWAP variance)
      - session_id
    Returns:
      - cum: dict of cumulative-sum arrays for rolling windows
      - sess_cols: pandas Series in bars dict (cum_p_vol_sess etc.)
    """
    open_ = bars["open"].to_numpy()
    close = bars["close"].to_numpy()
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    vol = bars["volume"].to_numpy().astype(np.float64)

    bar_dir = np.zeros(len(bars), dtype=np.int8)
    bar_dir[close > open_] = 1
    bar_dir[close < open_] = -1
    bull_vol = np.where(bar_dir == 1, vol, 0.0)
    bear_vol = np.where(bar_dir == -1, vol, 0.0)
    signed_vol = bull_vol - bear_vol
    typical = (high + low + close) / 3.0
    p_vol = typical * vol
    p2_vol = typical * typical * vol

    bars["bull_vol"] = bull_vol
    bars["bear_vol"] = bear_vol
    bars["total_vol"] = vol
    bars["signed_vol"] = signed_vol
    bars["p_vol"] = p_vol
    bars["p2_vol"] = p2_vol
    bars["session_id"] = session_id_for_ts(bars["ts_event"])

    cum = {
        "cum_bull":  np.concatenate([[0.0], bull_vol.cumsum()]),
        "cum_bear":  np.concatenate([[0.0], bear_vol.cumsum()]),
        "cum_total": np.concatenate([[0.0], vol.cumsum()]),
    }
    # Session-cumulative state for VWAP and OBV (reset at 17:00 CT)
    grp = bars.groupby("session_id", sort=False, observed=True)
    bars["cum_p_vol_sess"] = grp["p_vol"].cumsum()
    bars["cum_p2_vol_sess"] = grp["p2_vol"].cumsum()
    bars["cum_vol_sess"] = grp["total_vol"].cumsum()
    bars["cum_signed_sess"] = grp["signed_vol"].cumsum()
    return cum, bars


def compute_vol_vwap_at_ts(bars: pd.DataFrame, cum: dict,
                                event_ts_ns: np.ndarray) -> pd.DataFrame:
    """For each event timestamp, compute vol/VWAP features causally
    (using only 1s bars with ts_event_ns < event_ts).
    """
    bars_ts = bars["ts_event_ns"].to_numpy()
    cum_p_vol = bars["cum_p_vol_sess"].to_numpy()
    cum_p2_vol = bars["cum_p2_vol_sess"].to_numpy()
    cum_vol = bars["cum_vol_sess"].to_numpy()
    cum_signed = bars["cum_signed_sess"].to_numpy()

    n = len(event_ts_ns)
    out: dict[str, np.ndarray] = {}
    for lab in VOL_LABELS:
        out[f"vol_bull_{lab}"] = np.zeros(n)
        out[f"vol_bear_{lab}"] = np.zeros(n)
        out[f"vol_total_{lab}"] = np.zeros(n)
        out[f"vol_delta_{lab}"] = np.zeros(n)
        out[f"vol_imbalance_{lab}"] = np.full(n, np.nan)
    out["vwap_value"] = np.full(n, np.nan)
    out["vwap_sigma"] = np.full(n, np.nan)
    out["obv_session"] = np.zeros(n)
    out["cum_vol_session"] = np.zeros(n)
    for k in range(n):
        T = int(event_ts_ns[k])
        i_end = int(np.searchsorted(bars_ts, T, side="left"))
        if i_end == 0:
            continue
        for W, lab in zip(VOL_WINDOWS_S, VOL_LABELS):
            T_start = T - W * 1_000_000_000
            i_start = int(np.searchsorted(bars_ts, T_start, side="left"))
            bull = cum["cum_bull"][i_end] - cum["cum_bull"][i_start]
            bear = cum["cum_bear"][i_end] - cum["cum_bear"][i_start]
            tot = cum["cum_total"][i_end] - cum["cum_total"][i_start]
            out[f"vol_bull_{lab}"][k] = bull
            out[f"vol_bear_{lab}"][k] = bear
            out[f"vol_total_{lab}"][k] = tot
            out[f"vol_delta_{lab}"][k] = bull - bear
            if tot > 0:
                out[f"vol_imbalance_{lab}"][k] = (bull - bear) / tot
        last_i = i_end - 1
        vol_sess = cum_vol[last_i]
        if vol_sess > 0:
            vwap = cum_p_vol[last_i] / vol_sess
            e_p2 = cum_p2_vol[last_i] / vol_sess
            sigma = float(np.sqrt(max(e_p2 - vwap * vwap, 0.0)))
            out["vwap_value"][k] = vwap
            out["vwap_sigma"][k] = sigma
            out["cum_vol_session"][k] = vol_sess
            out["obv_session"][k] = cum_signed[last_i]
    return pd.DataFrame(out)


def compute_atr_wilder(high, low, close, period):
    n = len(high)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    if n > 1:
        prev_close = close[:-1]
        tr[1:] = np.maximum.reduce([
            high[1:] - low[1:],
            np.abs(high[1:] - prev_close),
            np.abs(low[1:] - prev_close),
        ])
    atr = np.full(n, np.nan)
    if n >= period:
        atr[period - 1] = tr[:period].mean()
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def compute_sticky_regime(close, e3h, e9h, e3l, e9l):
    n = len(close)
    r = np.zeros(n, dtype=np.int8)
    cur = 0
    for i in range(n):
        if close[i] > e3h[i] and close[i] > e9h[i]:
            cur = 1
        elif close[i] < e3l[i] and close[i] < e9l[i]:
            cur = -1
        r[i] = cur
    return r


def compute_bars_in_regime(regime):
    n = len(regime)
    bars = np.zeros(n, dtype=np.int32)
    for i in range(n):
        if i == 0 or regime[i] != regime[i - 1]:
            bars[i] = 1
        else:
            bars[i] = bars[i - 1] + 1
    return bars


def aggregate_to_tf(df_1s: pd.DataFrame, period_s: int) -> pd.DataFrame:
    period_ns = period_s * 1_000_000_000
    bin_ts = (df_1s["ts_event_ns"].values // period_ns) * period_ns
    g = df_1s.assign(_bin=bin_ts).groupby("_bin", sort=True)
    bars = pd.DataFrame({
        "ts_event_ns": g["_bin"].first().values,
        "high": g["high"].max().values,
        "low": g["low"].min().values,
        "close": g["close"].last().values,
    })
    bars["ts_init_ns"] = bars["ts_event_ns"] + period_ns
    return bars.reset_index(drop=True)


def compute_tf_state(bars: pd.DataFrame) -> pd.DataFrame:
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    s_h = pd.Series(high).ewm(span=EMA_SHORT, adjust=False).mean().to_numpy()
    l_h = pd.Series(high).ewm(span=EMA_LONG, adjust=False).mean().to_numpy()
    s_l = pd.Series(low).ewm(span=EMA_SHORT, adjust=False).mean().to_numpy()
    l_l = pd.Series(low).ewm(span=EMA_LONG, adjust=False).mean().to_numpy()
    atr = compute_atr_wilder(high, low, close, ATR_PERIOD)
    regime = compute_sticky_regime(close, s_h, l_h, s_l, l_l)
    bir = compute_bars_in_regime(regime)
    bars["ema3_h"] = s_h
    bars["ema9_h"] = l_h
    bars["ema3_l"] = s_l
    bars["ema9_l"] = l_l
    bars["atr"] = atr
    bars["regime"] = regime
    bars["bars_in_regime"] = bir
    return bars


def latest_state_at(tf_bars: pd.DataFrame, query_ts_ns: np.ndarray) -> dict:
    ts_init = tf_bars["ts_init_ns"].to_numpy()
    n_q = len(query_ts_ns)
    idx = np.searchsorted(ts_init, query_ts_ns, side="right") - 1
    cols = {}
    for c in ["close", "high", "low", "ema3_h", "ema9_h", "ema3_l", "ema9_l",
                "atr", "regime", "bars_in_regime"]:
        arr = tf_bars[c].to_numpy()
        out = np.full(n_q, np.nan if arr.dtype != np.int8
                       and arr.dtype != np.int32 else 0)
        valid = idx >= 0
        out[valid] = arr[idx[valid]]
        cols[c] = out
    return cols


def compute_calendar(close_ts_ns: np.ndarray) -> pd.DataFrame:
    ct = pd.to_datetime(close_ts_ns, unit="ns", utc=True
                          ).tz_convert("America/Chicago")
    return pd.DataFrame({
        "hour_ct": ct.hour.astype(int).to_numpy(),
        "minute_ct": ct.minute.astype(int).to_numpy(),
        "day_of_week": ct.dayofweek.astype(int).to_numpy(),
        "minutes_since_rth_open":
            (ct.hour * 60 + ct.minute - RTH_OPEN_MIN
              ).astype(int).to_numpy(),
    })


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("AUGMENT PRE-FLIP CANDIDATES with vol/VWAP/calendar/3m+5m TF")
    print("=" * 78)

    cdf = pd.read_parquet(OUT / "pre_flip_candidates.parquet")
    print(f"\n  Loaded {len(cdf):,} candidates")

    # Process per year
    all_aug = []
    for yr in [2024, 2025, 2026]:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        bars_1s = load_1s(ONE_S_PATHS[yr])
        print(f"  1s bars: {len(bars_1s):,}  ({time.time()-t0:.0f}s)",
              flush=True)
        cum, bars_1s = precompute_vol_vwap_state(bars_1s)
        print(f"  precomputed vol/VWAP state  ({time.time()-t0:.0f}s)",
              flush=True)

        # 3m and 5m TF aggregation
        tf_3m = compute_tf_state(aggregate_to_tf(bars_1s, 180))
        tf_5m = compute_tf_state(aggregate_to_tf(bars_1s, 300))
        print(f"  3m bars: {len(tf_3m):,}  5m bars: {len(tf_5m):,}"
              f"  ({time.time()-t0:.0f}s)", flush=True)

        # Filter candidates to this year
        cdf_yr = cdf[cdf["year"] == yr].copy().reset_index(drop=True)
        query_ts = cdf_yr["close_ts_ns"].to_numpy(dtype=np.int64)
        print(f"  candidates this year: {len(cdf_yr):,}", flush=True)

        # Vol/VWAP features
        vv = compute_vol_vwap_at_ts(bars_1s, cum, query_ts)
        # Calendar features
        cal = compute_calendar(query_ts)
        # 3m, 5m TF state
        st_3m = latest_state_at(tf_3m, query_ts)
        st_5m = latest_state_at(tf_5m, query_ts)
        print(f"  features computed  ({time.time()-t0:.0f}s)", flush=True)

        # Direction-aware derivatives
        d = cdf_yr["candidate_direction"].to_numpy()
        atr_1m = cdf_yr["atr_1m"].to_numpy()
        atr_ok = atr_1m > 0
        close_1m = cdf_yr["close_1m"].to_numpy()

        # VWAP distance ATR-normalized
        vwap = vv["vwap_value"].to_numpy()
        sigma = vv["vwap_sigma"].to_numpy()
        dist_atr = np.where(atr_ok, (close_1m - vwap) / atr_1m, np.nan)
        vv["dist_close_to_vwap_atr"] = dist_atr
        for k in (1, 2, 3):
            upper = vwap + k * sigma
            lower = vwap - k * sigma
            vv[f"dist_close_to_vwap_upper_{k}sd_atr"] = np.where(
                atr_ok, (close_1m - upper) / atr_1m, np.nan)
            vv[f"dist_close_to_vwap_lower_{k}sd_atr"] = np.where(
                atr_ok, (close_1m - lower) / atr_1m, np.nan)
        vv["dist_to_vwap_dir_atr"] = -dist_atr * d
        for lab in VOL_LABELS:
            vv[f"vol_imbalance_dir_{lab}"] = (
                vv[f"vol_imbalance_{lab}"] * d)

        # TF distance ATR-normalized
        for tf_lbl, st in [("3m", st_3m), ("5m", st_5m)]:
            atr_tf = st["atr"]
            close_tf = st["close"]
            cdf_yr[f"regime_{tf_lbl}"] = st["regime"].astype(np.int8)
            cdf_yr[f"bars_in_regime_{tf_lbl}"] = st["bars_in_regime"
                                                            ].astype(np.int32)
            cdf_yr[f"atr_{tf_lbl}"] = atr_tf
            cdf_yr[f"close_{tf_lbl}"] = close_tf
            cdf_yr[f"dist_close_to_ema3_h_{tf_lbl}_atr"] = (
                (close_tf - st["ema3_h"]) / atr_tf)
            cdf_yr[f"dist_close_to_ema9_h_{tf_lbl}_atr"] = (
                (close_tf - st["ema9_h"]) / atr_tf)
            cdf_yr[f"dist_close_to_ema3_l_{tf_lbl}_atr"] = (
                (close_tf - st["ema3_l"]) / atr_tf)
            cdf_yr[f"dist_close_to_ema9_l_{tf_lbl}_atr"] = (
                (close_tf - st["ema9_l"]) / atr_tf)

        # Stitch vol/VWAP/calendar features in
        for col in vv.columns:
            cdf_yr[col] = vv[col].values
        for col in cal.columns:
            cdf_yr[col] = cal[col].values
        all_aug.append(cdf_yr)

    full = pd.concat(all_aug, ignore_index=True)
    out_path = OUT / "pre_flip_candidates_augmented.parquet"
    full.to_parquet(out_path)
    print(f"\n{'='*78}")
    print(f"Wrote {len(full):,} augmented candidates to {out_path}")
    print(f"  Total columns: {len(full.columns)}")
    new_cols = sorted([c for c in full.columns
                          if c not in pd.read_parquet(
                              OUT / "pre_flip_candidates.parquet").columns])
    print(f"  New columns added: {len(new_cols)}")
    for c in new_cols:
        print(f"    {c}")
    print(f"\n[done]")


if __name__ == "__main__":
    main()
