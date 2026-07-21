"""Build pre-flip candidate table for V_A-confirmed flip prediction.

Phase 1 of the pre-flip ML pipeline. Produces a per-candidate feature
table with labels for the three horizon models (T-1, T-2, T-3).

For each 1m bar close at time t and each candidate direction d in
{+1, -1}, the bar is a candidate-d iff (regime_1m(t) != d) AND ANY of:
  (1) Faster-TF alignment: regime_5s(t) == d OR regime_15s(t) == d
      OR regime_30s(t) == d
  (2) Threshold proximity:
      dist_to_1m_flip_threshold_atr(t, d) <= 0.50

Labels per candidate-d:
  - label_T1 = (V_A-confirmed flip in direction d at exactly t + 60s)
  - label_T2 = (V_A-confirmed flip in direction d at exactly t + 120s)
  - label_T3 = (V_A-confirmed flip in direction d at exactly t + 180s)

Features per candidate (direction-aware where appropriate):

Existing (from snapshots_with_vol_vwap.parquet, snapshot at t):
  - Multi-TF (30s/1m/3m/5m): regime, bars_in_regime, atr, close,
    dist_close_to_ema*_h/l_atr
  - Volume: vol_bull/bear/total/delta/imbalance over 1m/5m/15m
  - VWAP: vwap_value, vwap_sigma, dist to bands ±1/2/3 sigma
  - OBV session, cum_vol_session
  - Calendar: hour_ct, minute_ct, day_of_week, minutes_since_rth_open

NEW sub-1m TF features (computed inline from 1s data):
  - regime_5s, bars_in_regime_5s, atr_5s, close_5s,
    dist_close_to_ema3/9_h/l_5s_atr
  - regime_15s, bars_in_regime_15s, atr_15s, close_15s,
    dist_close_to_ema3/9_h/l_15s_atr
  - micro_net_move_5s/15s/30s_dir_atr (direction-aware)
  - micro_mfe/mae_5s/15s/30s_dir_atr
  - micro_close_loc_5s/15s/30s
  - dist_to_1m_flip_threshold_atr_dir (direction-aware)

NEW direction-aware composite:
  - micro_alignment_score = count of {regime_5s, 15s, 30s, 1m == d}

NEW current-1m-regime maturity features:
  - current_regime_max_mfe_atr (max favorable excursion since regime start)
  - current_regime_max_mae_atr (deepest counter-excursion within regime)
  - current_regime_range_atr (total H-L range)
  - current_regime_close_loc (close position 0..1 in regime range)
  - current_regime_giveback_atr (retreat from regime peak)
  - current_regime_efficiency (net move / sum of |h-l|)
  - current_regime_close_vs_start_atr (signed by regime direction)

Output: studies/v_a_excursion_regime/results_v0/pre_flip_candidates.parquet
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
NQ_MULT = 20.0
EMA_SHORT = 3
EMA_LONG = 9
ATR_PERIOD = 14
RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60

ONE_S_PATHS = {
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}
SNAP_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet"
    for yr in [2024, 2025, 2026]
}
TRADE_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/trades.parquet"
    for yr in [2024, 2025, 2026]
}

# Candidate filter constants
THRESHOLD_PROXIMITY_ATR = 0.50    # |close - flip_threshold| / atr_1m <= this


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


def aggregate_to_tf(df_1s: pd.DataFrame, period_s: int) -> pd.DataFrame:
    """Aggregate 1s bars to TF bars using closed='left' (ts_event = bar OPEN).

    period_s is in seconds (5, 15, 30, 60).
    Returns a DataFrame indexed by ts_event_ns of the bar's OPEN time.
    """
    s = pd.Series(df_1s["ts_event_ns"].values, name="ts_event_ns")
    # Bin by floor of ts_event_ns to period
    period_ns = period_s * 1_000_000_000
    bin_ts = (s // period_ns) * period_ns
    g = df_1s.assign(_bin=bin_ts.values).groupby("_bin", sort=True)
    bars = pd.DataFrame({
        "ts_event_ns": g["_bin"].first().values,
        "open": g["open"].first().values,
        "high": g["high"].max().values,
        "low": g["low"].min().values,
        "close": g["close"].last().values,
        "volume": g["volume"].sum().values,
    })
    bars["ts_init_ns"] = bars["ts_event_ns"] + period_ns
    return bars.reset_index(drop=True)


def compute_atr_wilder(high: np.ndarray, low: np.ndarray,
                          close: np.ndarray, period: int) -> np.ndarray:
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


def compute_sticky_regime(close: np.ndarray, ema3_h: np.ndarray,
                              ema9_h: np.ndarray, ema3_l: np.ndarray,
                              ema9_l: np.ndarray) -> np.ndarray:
    """Sticky regime per V_A convention.

    +1 if close > ema3_h AND close > ema9_h
    -1 if close < ema3_l AND close < ema9_l
    else carry the previous regime forward (sticky)
    """
    n = len(close)
    r = np.zeros(n, dtype=np.int8)
    cur = 0
    for i in range(n):
        if close[i] > ema3_h[i] and close[i] > ema9_h[i]:
            cur = 1
        elif close[i] < ema3_l[i] and close[i] < ema9_l[i]:
            cur = -1
        r[i] = cur
    return r


def compute_bars_in_regime(regime: np.ndarray) -> np.ndarray:
    n = len(regime)
    bars = np.zeros(n, dtype=np.int32)
    for i in range(n):
        if i == 0 or regime[i] != regime[i - 1]:
            bars[i] = 1
        else:
            bars[i] = bars[i - 1] + 1
    return bars


def compute_tf_state(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute EMA3/9 of high and low, ATR, sticky regime, bars_in_regime.

    Returns the bars DataFrame with additional columns:
      ema3_h, ema9_h, ema3_l, ema9_l, atr, regime, bars_in_regime
    """
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


def latest_state_at(tf_bars: pd.DataFrame, query_ts_ns: np.ndarray
                      ) -> dict[str, np.ndarray]:
    """For each query_ts_ns (a 1m bar close time), return the latest
    fully-completed TF bar's state (ts_init <= query_ts).

    Returns a dict of arrays aligned to query_ts_ns.
    """
    # Use ts_init_ns (= bar close + 1s for 1s convention; period_ns later)
    ts_init = tf_bars["ts_init_ns"].to_numpy()
    n_q = len(query_ts_ns)
    # For each query time, find the index of the latest TF bar with ts_init <= query
    idx = np.searchsorted(ts_init, query_ts_ns, side="right") - 1
    cols = {}
    for c in ["close", "high", "low", "ema3_h", "ema9_h", "ema3_l", "ema9_l",
                "atr", "regime", "bars_in_regime"]:
        arr = tf_bars[c].to_numpy()
        out = np.full(n_q, np.nan if arr.dtype != np.int8 and
                       arr.dtype != np.int32 else 0)
        valid = idx >= 0
        out[valid] = arr[idx[valid]]
        cols[c] = out
    return cols


def compute_current_regime_maturity(one_m_bars: pd.DataFrame) -> pd.DataFrame:
    """For each 1m bar, compute features of the CURRENT 1m regime
    (the one that's potentially about to flip).

    Tracks regime_start_close, running_max_high, running_min_low since
    the current regime began. Computes max_mfe, max_mae, range, close_loc,
    giveback, efficiency, close_vs_start.
    """
    n = len(one_m_bars)
    high = one_m_bars["high"].to_numpy()
    low = one_m_bars["low"].to_numpy()
    close = one_m_bars["close"].to_numpy()
    regime = one_m_bars["regime"].to_numpy()
    atr = one_m_bars["atr"].to_numpy()

    max_mfe = np.zeros(n)
    max_mae = np.zeros(n)
    range_atr = np.zeros(n)
    close_loc = np.full(n, 0.5)
    giveback = np.zeros(n)
    efficiency = np.zeros(n)
    close_vs_start = np.zeros(n)

    regime_start_close = close[0]
    run_max_h = high[0]
    run_min_l = low[0]
    cum_abs_range = abs(high[0] - low[0])
    bars_since_start = 1

    for i in range(n):
        if i > 0 and regime[i] != regime[i - 1]:
            # Reset on regime flip
            regime_start_close = close[i]
            run_max_h = high[i]
            run_min_l = low[i]
            cum_abs_range = abs(high[i] - low[i])
            bars_since_start = 1
        else:
            run_max_h = max(run_max_h, high[i])
            run_min_l = min(run_min_l, low[i])
            cum_abs_range += abs(high[i] - low[i])
            bars_since_start += 1

        a = atr[i] if np.isfinite(atr[i]) and atr[i] > 0 else np.nan
        r = regime[i]

        # MFE in regime direction
        if r == 1:
            mfe = run_max_h - regime_start_close
            mae = regime_start_close - run_min_l
            gb = run_max_h - close[i]
            cvs = close[i] - regime_start_close
        elif r == -1:
            mfe = regime_start_close - run_min_l
            mae = run_max_h - regime_start_close
            gb = close[i] - run_min_l
            cvs = regime_start_close - close[i]
        else:
            mfe = 0.0
            mae = 0.0
            gb = 0.0
            cvs = 0.0

        if not np.isnan(a):
            max_mfe[i] = mfe / a
            max_mae[i] = mae / a
            range_atr[i] = (run_max_h - run_min_l) / a
            giveback[i] = gb / a
            close_vs_start[i] = cvs / a
            if cum_abs_range > 0:
                efficiency[i] = abs(close[i] - regime_start_close) / cum_abs_range
        rg = run_max_h - run_min_l
        if rg > 0:
            close_loc[i] = (close[i] - run_min_l) / rg

    one_m_bars["current_regime_max_mfe_atr"] = max_mfe
    one_m_bars["current_regime_max_mae_atr"] = max_mae
    one_m_bars["current_regime_range_atr"] = range_atr
    one_m_bars["current_regime_close_loc"] = close_loc
    one_m_bars["current_regime_giveback_atr"] = giveback
    one_m_bars["current_regime_efficiency"] = efficiency
    one_m_bars["current_regime_close_vs_start_atr"] = close_vs_start
    return one_m_bars


def micro_window_features(bars_1s: pd.DataFrame, query_ts_ns: np.ndarray,
                              window_s: int, direction: np.ndarray
                              ) -> dict[str, np.ndarray]:
    """Direction-aware micro features over the last `window_s` of 1s bars
    ending strictly before each query_ts (= 1m bar close).
    """
    bars_ts = bars_1s["ts_event_ns"].to_numpy()
    bars_h = bars_1s["high"].to_numpy()
    bars_l = bars_1s["low"].to_numpy()
    bars_c = bars_1s["close"].to_numpy()
    bars_o = bars_1s["open"].to_numpy()
    n_q = len(query_ts_ns)
    net_move = np.full(n_q, np.nan)
    mfe = np.full(n_q, np.nan)
    mae = np.full(n_q, np.nan)
    close_loc = np.full(n_q, np.nan)
    window_ns = window_s * 1_000_000_000
    for k in range(n_q):
        t_end = query_ts_ns[k]
        t_start = t_end - window_ns
        d = direction[k]
        i_s = int(np.searchsorted(bars_ts, t_start, side="left"))
        i_e = int(np.searchsorted(bars_ts, t_end, side="left"))
        if i_e <= i_s:
            continue
        seg_h = bars_h[i_s:i_e]
        seg_l = bars_l[i_s:i_e]
        seg_o = bars_o[i_s:i_e]
        seg_c = bars_c[i_s:i_e]
        o0 = float(seg_o[0])
        c_last = float(seg_c[-1])
        hh = float(seg_h.max())
        ll = float(seg_l.min())
        net_move[k] = (c_last - o0) * d
        if d == 1:
            mfe[k] = hh - o0
            mae[k] = o0 - ll
        else:
            mfe[k] = o0 - ll
            mae[k] = hh - o0
        if hh > ll:
            cl = (c_last - ll) / (hh - ll)
            close_loc[k] = cl if d == 1 else (1.0 - cl)
    return {"net_move": net_move, "mfe": mfe, "mae": mae,
              "close_loc": close_loc}


def load_va_confirmed_flips(year: int) -> pd.DataFrame:
    """Load V_A-confirmed flips: bar1_check rows with became_trade=True
    in RTH. Returns DataFrame with the FLIP BAR's close time and direction.

    The flip bar is the 1m bar BEFORE bar1_check. Its close time =
    bar1_check.decision_ts - 60s.
    """
    snap = pd.read_parquet(SNAP_PATHS[year])
    b1 = snap[(snap["kind"] == "bar1_check")
                & (snap["became_trade"])
                & (snap["session"] == "RTH")].copy()
    # bar1_check.decision_ts = bar1's ts_init + 1s = bar1_close + 1s.
    # bar1_close = flip_bar_close + 60s. So flip_bar_close = ds - 61s.
    b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
    b1["year"] = year
    return b1[["flip_bar_close_ts", "direction", "year"]].copy()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("BUILD PRE-FLIP CANDIDATES")
    print("=" * 78)

    all_candidates = []
    for yr in [2024, 2025, 2026]:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        bars_1s = load_1s(ONE_S_PATHS[yr])
        print(f"  1s bars: {len(bars_1s):,}  ({time.time()-t0:.0f}s)",
              flush=True)

        # Aggregate to 5s, 15s, 30s, 1m
        print(f"  aggregating to 5s/15s/30s/1m...", flush=True)
        tf_5s = compute_tf_state(aggregate_to_tf(bars_1s, 5))
        tf_15s = compute_tf_state(aggregate_to_tf(bars_1s, 15))
        tf_30s = compute_tf_state(aggregate_to_tf(bars_1s, 30))
        tf_1m = compute_tf_state(aggregate_to_tf(bars_1s, 60))
        print(f"    5s={len(tf_5s):,}  15s={len(tf_15s):,}  "
              f"30s={len(tf_30s):,}  1m={len(tf_1m):,}  "
              f"({time.time()-t0:.0f}s)", flush=True)

        # Compute current-regime maturity on 1m bars
        tf_1m = compute_current_regime_maturity(tf_1m)
        print(f"  computed current-regime maturity  "
              f"({time.time()-t0:.0f}s)", flush=True)

        # For each 1m bar, snapshot state at its close (= ts_init)
        # query_ts_ns = ts_init = ts_event + 60s (1m bar close + 1s, NT
        # convention)
        # Actually, V_A uses decision_ts = ts_event + 61s for the FIRST 1s
        # bar after the 1m close. For consistency with the snapshot
        # framework, snapshot at ts_event + 60s (= 1m bar's hard close).
        query_ts = tf_1m["ts_init_ns"].to_numpy()

        # Get latest 5s/15s/30s state at each 1m close
        state_5s = latest_state_at(tf_5s, query_ts)
        state_15s = latest_state_at(tf_15s, query_ts)
        state_30s = latest_state_at(tf_30s, query_ts)

        # Build per-1m-bar feature table
        df = pd.DataFrame({
            "ts_event_ns": tf_1m["ts_event_ns"].to_numpy(),
            "close_ts_ns": query_ts,
            "open_1m": tf_1m["open"].to_numpy(),
            "high_1m": tf_1m["high"].to_numpy(),
            "low_1m": tf_1m["low"].to_numpy(),
            "close_1m": tf_1m["close"].to_numpy(),
            "atr_1m": tf_1m["atr"].to_numpy(),
            "regime_1m": tf_1m["regime"].to_numpy(),
            "bars_in_regime_1m": tf_1m["bars_in_regime"].to_numpy(),
            "ema3_h_1m": tf_1m["ema3_h"].to_numpy(),
            "ema9_h_1m": tf_1m["ema9_h"].to_numpy(),
            "ema3_l_1m": tf_1m["ema3_l"].to_numpy(),
            "ema9_l_1m": tf_1m["ema9_l"].to_numpy(),
            "current_regime_max_mfe_atr": tf_1m["current_regime_max_mfe_atr"],
            "current_regime_max_mae_atr": tf_1m["current_regime_max_mae_atr"],
            "current_regime_range_atr": tf_1m["current_regime_range_atr"],
            "current_regime_close_loc": tf_1m["current_regime_close_loc"],
            "current_regime_giveback_atr": tf_1m["current_regime_giveback_atr"],
            "current_regime_efficiency": tf_1m["current_regime_efficiency"],
            "current_regime_close_vs_start_atr":
                tf_1m["current_regime_close_vs_start_atr"],
        })
        for tf_lbl, st in [("5s", state_5s), ("15s", state_15s),
                              ("30s", state_30s)]:
            atr_tf = st["atr"]
            close_tf = st["close"]
            df[f"regime_{tf_lbl}"] = st["regime"].astype(np.int8)
            df[f"bars_in_regime_{tf_lbl}"] = st["bars_in_regime"].astype(np.int32)
            df[f"atr_{tf_lbl}"] = atr_tf
            df[f"close_{tf_lbl}"] = close_tf
            df[f"dist_close_to_ema3_h_{tf_lbl}_atr"] = (
                (close_tf - st["ema3_h"]) / atr_tf)
            df[f"dist_close_to_ema9_h_{tf_lbl}_atr"] = (
                (close_tf - st["ema9_h"]) / atr_tf)
            df[f"dist_close_to_ema3_l_{tf_lbl}_atr"] = (
                (close_tf - st["ema3_l"]) / atr_tf)
            df[f"dist_close_to_ema9_l_{tf_lbl}_atr"] = (
                (close_tf - st["ema9_l"]) / atr_tf)
        # EMA distances on 1m (matches snapshot convention)
        df["dist_close_to_ema3_h_1m_atr"] = (
            (df["close_1m"] - df["ema3_h_1m"]) / df["atr_1m"])
        df["dist_close_to_ema9_h_1m_atr"] = (
            (df["close_1m"] - df["ema9_h_1m"]) / df["atr_1m"])
        df["dist_close_to_ema3_l_1m_atr"] = (
            (df["close_1m"] - df["ema3_l_1m"]) / df["atr_1m"])
        df["dist_close_to_ema9_l_1m_atr"] = (
            (df["close_1m"] - df["ema9_l_1m"]) / df["atr_1m"])

        # Filter to RTH only AND drop EMA/ATR warmup bars (need ATR converged)
        ct = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True
                              ).dt.tz_convert("America/Chicago")
        minutes = ct.dt.hour * 60 + ct.dt.minute
        rth_mask = (minutes >= RTH_START_MIN) & (minutes < RTH_END_MIN)
        atr_ok = df["atr_1m"].notna() & (df["atr_1m"] > 0)
        df = df[rth_mask & atr_ok].copy().reset_index(drop=True)
        df["year"] = yr
        print(f"  RTH 1m bars (ATR-warm): {len(df):,}", flush=True)

        # ===== Candidate generation =====
        # For each 1m bar, generate up to 2 candidates: d=+1 and d=-1
        cands = []
        for d in [+1, -1]:
            # Candidate-d: regime_1m != d AND
            # (any faster TF == d OR threshold proximity in d direction <= 0.50)
            regime_ok = df["regime_1m"] != d
            faster_aligned = ((df["regime_5s"] == d)
                                | (df["regime_15s"] == d)
                                | (df["regime_30s"] == d))
            # Threshold proximity: for d=+1, close needs to reach max(ema3_h, ema9_h)
            # so the threshold = max(ema3_h, ema9_h). dist = (threshold - close) / atr
            # For d=-1, threshold = min(ema3_l, ema9_l). dist = (close - threshold) / atr
            if d == 1:
                thr = np.maximum(df["ema3_h_1m"], df["ema9_h_1m"])
                dist_to_thr = (thr - df["close_1m"]) / df["atr_1m"]
            else:
                thr = np.minimum(df["ema3_l_1m"], df["ema9_l_1m"])
                dist_to_thr = (df["close_1m"] - thr) / df["atr_1m"]
            # Positive dist = close is BELOW threshold (for d=+1) — i.e., still has
            # to move UP. Negative = already past threshold (regime should fire next bar).
            prox_ok = (dist_to_thr >= 0) & (dist_to_thr <= THRESHOLD_PROXIMITY_ATR)
            cand_mask = regime_ok & (faster_aligned | prox_ok)
            sub = df[cand_mask].copy()
            sub["candidate_direction"] = d
            sub["dist_to_1m_flip_threshold_atr_dir"] = dist_to_thr[cand_mask].values
            cands.append(sub)
        cdf = pd.concat(cands, ignore_index=True)
        print(f"  Candidates (both directions): {len(cdf):,}",
              flush=True)

        # Direction-aware features (post-candidate)
        d_arr = cdf["candidate_direction"].to_numpy()
        # Micro alignment score: count of faster TFs aligned with d
        cdf["micro_alignment_score"] = (
            (cdf["regime_5s"] == d_arr).astype(int)
            + (cdf["regime_15s"] == d_arr).astype(int)
            + (cdf["regime_30s"] == d_arr).astype(int)
            + (cdf["regime_1m"] == d_arr).astype(int)  # always 0 (filter)
        )

        # Micro window features (5s, 15s, 30s direction-aware)
        print(f"  computing micro-window features at each candidate...",
              flush=True)
        cand_ts = cdf["close_ts_ns"].to_numpy()
        for ws in [5, 15, 30]:
            feats = micro_window_features(bars_1s, cand_ts, ws, d_arr)
            cdf[f"micro_net_move_{ws}s_dir"] = feats["net_move"]
            cdf[f"micro_mfe_{ws}s_dir"] = feats["mfe"]
            cdf[f"micro_mae_{ws}s_dir"] = feats["mae"]
            cdf[f"micro_close_loc_{ws}s_dir"] = feats["close_loc"]
            # ATR-normalize the move/mfe/mae
            with np.errstate(divide='ignore', invalid='ignore'):
                cdf[f"micro_net_move_{ws}s_dir_atr"] = (
                    cdf[f"micro_net_move_{ws}s_dir"] / cdf["atr_1m"])
                cdf[f"micro_mfe_{ws}s_dir_atr"] = (
                    cdf[f"micro_mfe_{ws}s_dir"] / cdf["atr_1m"])
                cdf[f"micro_mae_{ws}s_dir_atr"] = (
                    cdf[f"micro_mae_{ws}s_dir"] / cdf["atr_1m"])
        # Drop the raw-point versions
        cdf = cdf.drop(columns=[c for c in cdf.columns
                                  if c.endswith("_dir") and
                                     ("net_move" in c or "mfe" in c
                                       or "mae" in c)])
        print(f"  micro features done ({time.time()-t0:.0f}s)",
              flush=True)

        # ===== Labels =====
        # Load V_A-confirmed flips for this year
        va_flips = load_va_confirmed_flips(yr)
        print(f"  V_A-confirmed flips (RTH): {len(va_flips):,}",
              flush=True)
        # Index by (flip_bar_close_ts, direction) for fast lookup
        flip_set = set(
            zip(va_flips["flip_bar_close_ts"].astype(np.int64).to_numpy(),
                  va_flips["direction"].astype(np.int64).to_numpy()))
        # For each candidate, check label_T1/T2/T3
        cand_close_ts = cdf["close_ts_ns"].to_numpy(dtype=np.int64)
        cand_d = cdf["candidate_direction"].to_numpy(dtype=np.int64)
        for X in [1, 2, 3]:
            target_ts = cand_close_ts + X * 60_000_000_000
            labels = np.array([
                int((int(target_ts[k]), int(cand_d[k])) in flip_set)
                for k in range(len(cdf))
            ], dtype=np.int8)
            cdf[f"label_T{X}"] = labels
        print(f"  labels: T1 pos={cdf['label_T1'].sum():,}  "
              f"T2 pos={cdf['label_T2'].sum():,}  "
              f"T3 pos={cdf['label_T3'].sum():,}  "
              f"({time.time()-t0:.0f}s)", flush=True)

        all_candidates.append(cdf)

    full = pd.concat(all_candidates, ignore_index=True)
    out_path = OUT / "pre_flip_candidates.parquet"
    full.to_parquet(out_path)
    print(f"\n{'='*78}")
    print(f"Wrote {len(full):,} candidates to {out_path}")
    print(f"  Per year: " + str(full.groupby("year").size().to_dict()))
    print(f"  Per direction: " + str(
        full.groupby("candidate_direction").size().to_dict()))
    print(f"  Label rates:")
    for X in [1, 2, 3]:
        pos = full[f"label_T{X}"].sum()
        print(f"    T{X}: {pos:,} / {len(full):,} ({pos/len(full):.2%})")
    print(f"  Feature columns: {len(full.columns) - 7}")  # rough estimate
    print(f"\n[done]")


if __name__ == "__main__":
    main()
