"""Pre-entry feature collector for momentum-confirm 2026 anatomy.

For each V_A and V_B momentum-confirm trade, compute extensive
pre-entry / at-entry features (volatility, chop, confirmation
quality, pre-signal structure, session, multi-tf, HMM). Joins with
existing path_diagnostics labels (max MFE, max MAE, time-to-max,
etc.) by matching on (mode, year, fill_ts).

Output: features_<mode>_<year>.parquet — one row per trade with all
pre-entry features + path labels merged.
"""

from __future__ import annotations
import os, sys, time, argparse, pickle
from pathlib import Path
import numpy as np
import pandas as pd
import pytz
from collections import deque

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "studies/hmm_5s_v1"))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from hmm_pipeline import (  # noqa
    SimpleRegimeTracker, compute_5s_features, FEATURE_COLS,
    aggregate_1s_to_5s,
)

OUT = Path("studies/momentum_2026_anatomy_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
PATH_OUT = Path("studies/momentum_confirm_path_v1/results")
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
CT = pytz.timezone("America/Chicago")


def compute_atr_series(h, l, c, period=14):
    n = len(c)
    tr = np.empty(n, dtype=float)
    tr[0] = h[0] - l[0]
    prev_c = c[:-1]
    tr[1:] = np.maximum.reduce([
        h[1:] - l[1:], np.abs(h[1:] - prev_c), np.abs(l[1:] - prev_c)])
    atr = np.full(n, np.nan, dtype=float)
    if n < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def enumerate_flips_with_index(bars_h, bars_l, bars_c, bars_ts,
                                  bars_init):
    """Returns flips DataFrame (all flips, no RTH filter) and a
    per-bar regime array."""
    tracker = SimpleRegimeTracker()
    flips = []
    regime_at_close = np.zeros(len(bars_c), dtype=int)
    for i in range(len(bars_c)):
        flipped = tracker.update(bars_h[i], bars_l[i], bars_c[i])
        regime_at_close[i] = tracker.regime
        if flipped:
            flips.append({
                "flip_bar_idx": i,
                "flip_bar_ts_event": int(bars_ts[i]),
                "flip_bar_ts_init": int(bars_init[i]),
                "flip_bar_h": float(bars_h[i]),
                "flip_bar_l": float(bars_l[i]),
                "flip_bar_c": float(bars_c[i]),
                "new_regime": int(tracker.regime),
            })
    return pd.DataFrame(flips), regime_at_close


def main(year: int, mode: str):
    print("=" * 72)
    print(f"ANATOMY COLLECTOR — YEAR {year} MODE {mode}")
    print("=" * 72)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")

    # ----- Load 1m bars (with warmup) -----
    print(f"\nLoading 1m bars...")
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC")
              - pd.Timedelta(days=30),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_1m_ts = np.array([b.ts_event for b in bars_1m])
    bars_1m_init = np.array([b.ts_init for b in bars_1m])
    bars_1m_o = np.array([float(b.open) for b in bars_1m])
    bars_1m_h = np.array([float(b.high) for b in bars_1m])
    bars_1m_l = np.array([float(b.low) for b in bars_1m])
    bars_1m_c = np.array([float(b.close) for b in bars_1m])
    bars_1m_v = np.array([float(b.volume) if hasattr(b, "volume")
                            else 0.0 for b in bars_1m])
    print(f"  {len(bars_1m):,} 1m bars")

    # ----- Compute ATR series + percentile -----
    print("Computing ATR + ATR percentile rolling...")
    atr_series = compute_atr_series(bars_1m_h, bars_1m_l, bars_1m_c)
    # Rolling 500-bar ATR percentile (~8 hours of data)
    atr_pct = np.full(len(atr_series), np.nan)
    win = 500
    for i in range(win, len(atr_series)):
        slice_atr = atr_series[i - win:i + 1]
        if np.isnan(slice_atr).any():
            continue
        atr_pct[i] = (slice_atr <= atr_series[i]).mean()

    # ATR slope (ATR[now] - ATR[10 bars ago]) / ATR[10 bars ago]
    atr_slope = np.full(len(atr_series), np.nan)
    for i in range(10, len(atr_series)):
        if not np.isnan(atr_series[i]) and not np.isnan(
                atr_series[i - 10]) and atr_series[i - 10] > 0:
            atr_slope[i] = ((atr_series[i] - atr_series[i - 10])
                             / atr_series[i - 10])

    # ----- 1m regime time series + flip indices -----
    print("Enumerating 1m regime flips...")
    flips_all, regime_1m_at_close = enumerate_flips_with_index(
        bars_1m_h, bars_1m_l, bars_1m_c, bars_1m_ts, bars_1m_init)
    flip_indices_1m = flips_all["flip_bar_idx"].values

    # Pre-compute "regime flips in last N bars" series
    # For each bar idx, count flips with idx_flip in (i-N, i]
    flip_count_30 = np.zeros(len(bars_1m), dtype=int)
    flip_count_60 = np.zeros(len(bars_1m), dtype=int)
    j = 0
    for i in range(len(bars_1m)):
        while j < len(flip_indices_1m) and flip_indices_1m[j] <= i:
            j += 1
        # flips with idx in (i - 60, i]
        # find first flip_idx > i - 60
        lo60 = np.searchsorted(flip_indices_1m, i - 60, side="right")
        lo30 = np.searchsorted(flip_indices_1m, i - 30, side="right")
        flip_count_60[i] = j - lo60
        flip_count_30[i] = j - lo30

    # Avg regime duration of last 5 regimes (in bars)
    # For each flip, duration = next flip idx - this flip idx
    flip_indices_arr = flip_indices_1m
    durations = np.diff(flip_indices_arr).astype(float)
    # avg_dur[k] = mean of durations[max(0,k-5):k]
    avg_dur_last5 = np.full(len(flip_indices_arr), np.nan)
    for k in range(1, len(flip_indices_arr)):
        lo = max(0, k - 5)
        if k > lo:
            avg_dur_last5[k] = durations[lo:k].mean()

    # ----- Load 5m bars -----
    print(f"\nLoading 5m bars...")
    bars_5m = catalog.bars(
        bar_types=["NQ.XCME-5-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC")
              - pd.Timedelta(days=30),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    if len(bars_5m) == 0:
        print("  WARN: no 5m bars; aggregating from 1m...")
        # Aggregate 1m -> 5m
        df_1m = pd.DataFrame({
            "ts_event": bars_1m_ts,
            "open": bars_1m_o, "high": bars_1m_h,
            "low": bars_1m_l, "close": bars_1m_c,
        })
        df_1m["ts_dt"] = pd.to_datetime(
            df_1m["ts_event"], unit="ns", utc=True)
        df_1m = df_1m.set_index("ts_dt")
        df_5m_agg = df_1m.resample(
            "5min", label="left", closed="left").agg({
                "open": "first", "high": "max",
                "low": "min", "close": "last"}).dropna()
        df_5m_agg["ts_event_ns"] = df_5m_agg.index.view("int64")
        bars_5m_ts = df_5m_agg["ts_event_ns"].values.astype("int64")
        bars_5m_h = df_5m_agg["high"].values
        bars_5m_l = df_5m_agg["low"].values
        bars_5m_c = df_5m_agg["close"].values
    else:
        bars_5m_ts = np.array([b.ts_event for b in bars_5m])
        bars_5m_h = np.array([float(b.high) for b in bars_5m])
        bars_5m_l = np.array([float(b.low) for b in bars_5m])
        bars_5m_c = np.array([float(b.close) for b in bars_5m])
    print(f"  {len(bars_5m_ts):,} 5m bars")

    print("Computing 5m regime time series...")
    tracker_5m = SimpleRegimeTracker()
    regime_5m_at_close = np.zeros(len(bars_5m_ts), dtype=int)
    flip_5m_indices = []
    for i in range(len(bars_5m_ts)):
        flipped = tracker_5m.update(
            bars_5m_h[i], bars_5m_l[i], bars_5m_c[i])
        regime_5m_at_close[i] = tracker_5m.regime
        if flipped:
            flip_5m_indices.append(i)
    flip_5m_indices = np.array(flip_5m_indices)

    # ----- Load 1s bars (for confirmation candle features) -----
    print(f"\nLoading 1s bars...")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC"),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_1s])
    bars_h = np.array([float(b.high) for b in bars_1s])
    bars_l = np.array([float(b.low) for b in bars_1s])
    bars_o = np.array([float(b.open) for b in bars_1s])
    bars_c = np.array([float(b.close) for b in bars_1s])
    bars_v = np.array([float(b.volume) if hasattr(b, "volume")
                          else 0.0 for b in bars_1s])
    print(f"  {len(bars_1s):,} 1s bars")

    # ----- HMM state series -----
    print("\nComputing 5s HMM state series...")
    with open("studies/hmm_5s_v1/results/hmm_model.pkl", "rb") as f:
        hmm_data = pickle.load(f)
    hmm_model = hmm_data["model"]
    hmm_means = hmm_data["means"]
    hmm_stds = hmm_data["stds"]
    feat_cols = hmm_data["feature_cols"]

    df_1s = pd.DataFrame({
        "ts_event": bars_ts, "open": bars_o, "high": bars_h,
        "low": bars_l, "close": bars_c,
        "volume": bars_v,
    })
    df_5s = aggregate_1s_to_5s(df_1s)
    feats_5s = compute_5s_features(df_5s)
    X = feats_5s[feat_cols].fillna(0.0).values
    valid = feats_5s[feat_cols].notna().all(axis=1).values
    X_norm = (X - hmm_means) / hmm_stds
    states_5s = hmm_model.predict(X_norm)
    state_probs_5s = hmm_model.predict_proba(X_norm)
    states_5s_ts = feats_5s["ts_event_ns"].values.astype("int64")
    states_5s = np.where(valid, states_5s, -1).astype("int64")
    state_probs_5s = np.where(valid[:, None], state_probs_5s, np.nan)
    n_hmm_states = state_probs_5s.shape[1]

    # CAUSAL HMM lookup: 5s state at index i is computed from
    # 5s bar i's full H/L/C; bar closes at ts_event + 5s. Lookup
    # by close time = ts_event + 5s.
    states_5s_close_ts = states_5s_ts + 5 * int(1e9)

    def hmm_lookup(ts_ns: int):
        idx = int(np.searchsorted(
            states_5s_close_ts, ts_ns, side="right")) - 1
        if idx < 0:
            return -1, np.full(n_hmm_states, np.nan), np.nan
        st = int(states_5s[idx])
        probs = state_probs_5s[idx]
        if not np.isnan(probs).any():
            p = probs[probs > 1e-12]
            ent = float(-(p * np.log(p)).sum())
        else:
            ent = float("nan")
        return st, probs, ent

    # ----- Pre-compute 1m volume z-score (vs 20-bar avg) -----
    print("\nComputing 1m volume z-score...")
    vol_mean_20 = pd.Series(bars_1m_v).rolling(20).mean().values
    vol_std_20 = pd.Series(bars_1m_v).rolling(20).std().values

    # ----- RTH session bounds (rolling per session day) -----
    print("Computing session bounds...")
    ts_ct = pd.to_datetime(bars_1m_ts, unit="ns", utc=True).tz_convert(CT)
    minutes_arr = (ts_ct.hour * 60 + ts_ct.minute)
    if hasattr(minutes_arr, "values"):
        minutes_arr = minutes_arr.values
    in_rth_1m = (minutes_arr >= 510) & (minutes_arr < 900)
    # Per session: cumulative high/low since session open (RTH open)
    session_high = np.full(len(bars_1m), np.nan)
    session_low = np.full(len(bars_1m), np.nan)
    cur_h = -np.inf
    cur_l = np.inf
    in_session = False
    for i in range(len(bars_1m)):
        if in_rth_1m[i]:
            if not in_session:
                cur_h = bars_1m_h[i]
                cur_l = bars_1m_l[i]
                in_session = True
            else:
                cur_h = max(cur_h, bars_1m_h[i])
                cur_l = min(cur_l, bars_1m_l[i])
            session_high[i] = cur_h
            session_low[i] = cur_l
        else:
            in_session = False

    # ----- Load existing path-diagnostics labels for join -----
    print(f"\nLoading existing path labels for {mode} {year}...")
    path_labels_path = (PATH_OUT / f"trades_{mode}_{year}.parquet")
    path_paths_path = (PATH_OUT / f"paths_{mode}_{year}.parquet")
    if not path_labels_path.exists():
        print(f"  ERROR: {path_labels_path} not found")
        return
    path_labels = pd.read_parquet(path_labels_path)
    path_paths = pd.read_parquet(path_paths_path)
    print(f"  {len(path_labels):,} path-label rows")

    # ----- Walk RTH HH/LL flips, compute features -----
    print(f"\nProcessing {mode} flips...")
    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    rows = []
    t0 = time.time()

    for _, row in flips_all.iterrows():
        flip_ts = int(row["flip_bar_ts_event"])
        if flip_ts < year_start_ns:
            continue
        d = int(row["new_regime"])
        flip_idx = int(row["flip_bar_idx"])
        flip_init = int(row["flip_bar_ts_init"])
        flip_h = float(row["flip_bar_h"])
        flip_l = float(row["flip_bar_l"])

        # RTH check
        flip_ct = pd.Timestamp(flip_ts, tz="UTC").tz_convert(CT)
        m = flip_ct.hour * 60 + flip_ct.minute
        if not (510 <= m < 900):
            continue

        if flip_idx + 1 >= len(bars_1m):
            continue
        b1_idx = flip_idx + 1
        atr = float(atr_series[b1_idx])
        if not np.isfinite(atr) or atr <= 0:
            continue

        # ----- Confirmation per mode + HH/LL + momentum check -----
        if mode == "1m_momentum":
            b1_o = float(bars_1m_o[b1_idx])
            b1_h = float(bars_1m_h[b1_idx])
            b1_l = float(bars_1m_l[b1_idx])
            b1_c = float(bars_1m_c[b1_idx])
            b1_v = float(bars_1m_v[b1_idx])
            if d == 1:
                hhll = b1_h > flip_h
                mom = b1_c > b1_o
                hhll_amount = (b1_h - flip_h) / atr if hhll else 0.0
            else:
                hhll = b1_l < flip_l
                mom = b1_c < b1_o
                hhll_amount = (flip_l - b1_l) / atr if hhll else 0.0
            if not (hhll and mom):
                continue
            confirm_o, confirm_h = b1_o, b1_h
            confirm_l, confirm_c = b1_l, b1_c
            confirm_v = b1_v
            confirm_vol_z = (
                (b1_v - vol_mean_20[b1_idx]) / vol_std_20[b1_idx]
                if not np.isnan(vol_std_20[b1_idx])
                and vol_std_20[b1_idx] > 0
                else float("nan"))
            signal_time = flip_init + 60 * int(1e9)
            fill_ts_target = signal_time + 30 * int(1e9)
        else:  # 30s_momentum
            signal_time = flip_init + 30 * int(1e9)
            cw_lo = np.searchsorted(bars_ts, flip_init, side="left")
            cw_hi = np.searchsorted(bars_ts, signal_time, side="left")
            if cw_hi <= cw_lo:
                continue
            confirm_o = float(bars_o[cw_lo])
            confirm_c = float(bars_c[cw_hi - 1])
            confirm_h = float(bars_h[cw_lo:cw_hi].max())
            confirm_l = float(bars_l[cw_lo:cw_hi].min())
            confirm_v = float(bars_v[cw_lo:cw_hi].sum())
            if d == 1:
                hhll = confirm_h > flip_h
                mom = confirm_c > confirm_o
                hhll_amount = (
                    (confirm_h - flip_h) / atr if hhll else 0.0)
            else:
                hhll = confirm_l < flip_l
                mom = confirm_c < confirm_o
                hhll_amount = (
                    (flip_l - confirm_l) / atr if hhll else 0.0)
            if not (hhll and mom):
                continue
            confirm_vol_z = float("nan")  # 30s vol context not built
            fill_ts_target = signal_time + 30 * int(1e9)

        # Get fill bar
        fi = np.searchsorted(bars_ts, fill_ts_target, side="left")
        if fi >= len(bars_ts):
            continue
        actual_fill_ts = int(bars_ts[fi])
        if actual_fill_ts - fill_ts_target > 60 * int(1e9):
            continue
        fill_price = float(bars_o[fi])

        # ----- Compute confirmation candle features -----
        c_range = max(1e-9, confirm_h - confirm_l)
        c_body = abs(confirm_c - confirm_o)
        confirm_body_pct = c_body / c_range
        confirm_range_atr = c_range / atr
        confirm_close_loc = (confirm_c - confirm_l) / c_range
        if d == 1:
            opp_wick = confirm_l - min(confirm_o, confirm_c) * -1
            opp_wick = (min(confirm_o, confirm_c) - confirm_l)
        else:
            opp_wick = confirm_h - max(confirm_o, confirm_c)
        confirm_wickiness = opp_wick / c_range
        # close_through: how far past flip H/L the confirm CLOSE was
        if d == 1:
            close_through_amt = max(0.0, confirm_c - flip_h) / atr
        else:
            close_through_amt = max(0.0, flip_l - confirm_c) / atr

        # ----- Volatility / chop -----
        atr_pct_val = float(atr_pct[b1_idx])
        atr_slope_val = float(atr_slope[b1_idx])
        # Realized range last 5/10/20 minutes (1m bars)
        def realized_range(N):
            lo_idx = max(0, b1_idx - N + 1)
            return (bars_1m_h[lo_idx:b1_idx + 1].max()
                      - bars_1m_l[lo_idx:b1_idx + 1].min()) / atr
        rr_5 = realized_range(5)
        rr_10 = realized_range(10)
        rr_20 = realized_range(20)
        # Chop score: realized range / |net move|
        net_move_5 = abs(bars_1m_c[b1_idx]
                            - bars_1m_o[max(0, b1_idx - 4)]) / atr
        chop_5 = rr_5 / max(0.01, net_move_5)
        net_move_10 = abs(bars_1m_c[b1_idx]
                             - bars_1m_o[max(0, b1_idx - 9)]) / atr
        chop_10 = rr_10 / max(0.01, net_move_10)
        # Bar overlap last 10: sum of |overlap_i| / total_range
        if b1_idx >= 10:
            overlaps = []
            for k in range(b1_idx - 9, b1_idx + 1):
                if k <= 0:
                    continue
                ov = max(0,
                          min(bars_1m_h[k], bars_1m_h[k - 1])
                          - max(bars_1m_l[k], bars_1m_l[k - 1]))
                overlaps.append(ov)
            total_range = (bars_1m_h[b1_idx - 9:b1_idx + 1].max()
                              - bars_1m_l[b1_idx - 9:b1_idx + 1].min())
            bar_overlap_pct = (sum(overlaps) / total_range
                                  if total_range > 0
                                  else float("nan"))
        else:
            bar_overlap_pct = float("nan")

        flip_count_30m = int(flip_count_30[b1_idx])
        flip_count_60m = int(flip_count_60[b1_idx])
        # Avg regime duration of last 5 regimes (bars)
        flip_arr_idx = np.searchsorted(flip_indices_arr, flip_idx)
        if flip_arr_idx < len(avg_dur_last5):
            avg_dur_5_bars = float(avg_dur_last5[flip_arr_idx])
        else:
            avg_dur_5_bars = float("nan")

        # ----- Pre-signal structure -----
        def prior_net_move(N):
            if b1_idx - N < 0:
                return float("nan")
            return ((bars_1m_c[b1_idx - 1]
                       - bars_1m_o[b1_idx - N]) / atr) * d
        prior_3 = prior_net_move(3)
        prior_5 = prior_net_move(5)
        prior_10 = prior_net_move(10)
        # Efficiency = |net move| / sum |bar moves|
        def efficiency(N):
            if b1_idx - N < 0:
                return float("nan")
            net = abs(bars_1m_c[b1_idx - 1] - bars_1m_o[b1_idx - N])
            total = sum(abs(bars_1m_c[k] - bars_1m_o[k])
                          for k in range(b1_idx - N, b1_idx))
            return net / total if total > 0 else float("nan")
        eff_5 = efficiency(5)
        eff_10 = efficiency(10)
        # Distance from recent 20-bar high/low
        if b1_idx >= 20:
            recent_h = bars_1m_h[b1_idx - 20:b1_idx].max()
            recent_l = bars_1m_l[b1_idx - 20:b1_idx].min()
            dist_recent_h_atr = (recent_h - bars_1m_c[b1_idx]) / atr
            dist_recent_l_atr = (bars_1m_c[b1_idx] - recent_l) / atr
            r_range = recent_h - recent_l
            position_in_range = (
                (bars_1m_c[b1_idx] - recent_l) / r_range
                if r_range > 0 else float("nan"))
        else:
            dist_recent_h_atr = float("nan")
            dist_recent_l_atr = float("nan")
            position_in_range = float("nan")

        # ----- Session / location -----
        sig_ct = pd.Timestamp(signal_time,
                                  tz="UTC").tz_convert(CT)
        minute_of_day_ct = sig_ct.hour * 60 + sig_ct.minute
        minutes_since_open = minute_of_day_ct - 510
        if not np.isnan(session_high[b1_idx]):
            sess_h = float(session_high[b1_idx])
            sess_l = float(session_low[b1_idx])
            sess_mid = (sess_h + sess_l) / 2
            dist_sess_h_atr = (sess_h - bars_1m_c[b1_idx]) / atr
            dist_sess_l_atr = (bars_1m_c[b1_idx] - sess_l) / atr
            dist_sess_mid_atr = (
                (bars_1m_c[b1_idx] - sess_mid) / atr)
            sess_range_atr = (sess_h - sess_l) / atr
        else:
            dist_sess_h_atr = float("nan")
            dist_sess_l_atr = float("nan")
            dist_sess_mid_atr = float("nan")
            sess_range_atr = float("nan")
        if minutes_since_open <= 60:
            session_block = "morning"
        elif minutes_since_open <= 240:
            session_block = "midday"
        else:
            session_block = "afternoon"

        # ----- Multi-timeframe (5m) — CAUSAL -----
        # Use the latest 5m bar whose CLOSE <= signal_time. The
        # 5m bar with ts_event = T_open closes at T_open + 5min.
        # Banned: searchsorted(bars_5m_ts, signal_time) - 1
        # because that returns the bar with OPEN <= signal_time,
        # exposing up to 5min of intra-bar lookahead.
        # Fix: use bars_5m_close_ts = bars_5m_ts + 5min as the key.
        bars_5m_close_ts = bars_5m_ts + 5 * 60 * int(1e9)
        idx_5m = int(np.searchsorted(
            bars_5m_close_ts, signal_time, side="right")) - 1
        if idx_5m >= 0 and idx_5m < len(bars_5m_ts):
            regime_5m = int(regime_5m_at_close[idx_5m])
            regime_5m_aligned = int(regime_5m == d)
            past_flips_5m = flip_5m_indices[
                flip_5m_indices <= idx_5m]
            if len(past_flips_5m) > 0:
                last_5m_flip_idx = int(past_flips_5m[-1])
                regime_5m_age_5m_bars = (idx_5m
                                              - last_5m_flip_idx)
            else:
                regime_5m_age_5m_bars = -1
        else:
            regime_5m = 0
            regime_5m_aligned = -1
            regime_5m_age_5m_bars = -1

        # ----- HMM features -----
        st_flip, _, _ = hmm_lookup(flip_ts)
        st_signal, probs_signal, ent_signal = hmm_lookup(
            signal_time)
        hmm_state_changed = int(
            st_flip != st_signal and st_flip >= 0
            and st_signal >= 0)

        rec = {
            "year": year, "mode": mode,
            "fill_ts": actual_fill_ts,
            "fill_price": fill_price,
            "direction": d,
            "atr_at_signal": atr,
            # Volatility / chop
            "atr_pct_500": atr_pct_val,
            "atr_slope_10": atr_slope_val,
            "rr_5_atr": rr_5, "rr_10_atr": rr_10,
            "rr_20_atr": rr_20,
            "chop_5": chop_5, "chop_10": chop_10,
            "bar_overlap_pct": bar_overlap_pct,
            "flip_count_30m": flip_count_30m,
            "flip_count_60m": flip_count_60m,
            "avg_dur_5_bars": avg_dur_5_bars,
            # Confirmation candle
            "confirm_body_pct": confirm_body_pct,
            "confirm_range_atr": confirm_range_atr,
            "confirm_close_loc": confirm_close_loc,
            "confirm_wickiness": confirm_wickiness,
            "confirm_vol_z": confirm_vol_z,
            "hhll_amount_atr": hhll_amount,
            "close_through_amt_atr": close_through_amt,
            # Pre-signal
            "prior_3_net_move_atr": prior_3,
            "prior_5_net_move_atr": prior_5,
            "prior_10_net_move_atr": prior_10,
            "eff_5": eff_5, "eff_10": eff_10,
            "dist_recent_h_atr": dist_recent_h_atr,
            "dist_recent_l_atr": dist_recent_l_atr,
            "position_in_range": position_in_range,
            # Session
            "minute_of_day_ct": minute_of_day_ct,
            "minutes_since_open": minutes_since_open,
            "dist_sess_h_atr": dist_sess_h_atr,
            "dist_sess_l_atr": dist_sess_l_atr,
            "dist_sess_mid_atr": dist_sess_mid_atr,
            "sess_range_atr": sess_range_atr,
            "session_block": session_block,
            # Multi-tf
            "regime_5m": regime_5m,
            "regime_5m_aligned": regime_5m_aligned,
            "regime_5m_age_5m_bars": regime_5m_age_5m_bars,
            # HMM
            "hmm_state_at_flip": st_flip,
            "hmm_state_at_signal": st_signal,
            "hmm_state_changed": hmm_state_changed,
            "hmm_state_prob_3": (
                float(probs_signal[3])
                if not np.isnan(probs_signal[3])
                else float("nan")),
            "hmm_entropy": ent_signal,
        }
        rows.append(rec)

    df = pd.DataFrame(rows)
    elapsed = time.time() - t0
    print(f"  {len(df):,} feature rows in {elapsed:.0f}s")

    # ----- Join with path labels by fill_ts -----
    print("\nJoining with path labels by fill_ts...")
    keep_path_cols = [
        "fill_ts", "final_net_pnl", "is_winner_net",
        "max_mfe_atr", "max_mae_atr", "time_to_max_mfe_s",
        "time_to_max_mae_s", "duration_s",
        "peak_giveback_atr", "mfe_capture_ratio",
        "final_pnl_atr",
        "t_mfe_025_s", "t_mfe_050_s", "t_mfe_075_s",
        "t_mfe_100_s", "t_mfe_150_s", "t_mfe_200_s",
        "t_mae_025_s", "t_mae_050_s", "t_mae_075_s",
        "t_mae_100_s",
    ]
    avail = [c for c in keep_path_cols if c in path_labels.columns]
    merged = df.merge(path_labels[avail], on="fill_ts", how="left")
    print(f"  Merged rows: {len(merged):,} "
           f"(matched: {merged['final_net_pnl'].notna().sum():,})")

    out_path = OUT / f"features_{mode}_{year}.parquet"
    merged.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")
    if len(merged):
        wr = merged["is_winner_net"].mean() * 100
        print(f"  WR: {wr:.1f}%, "
               f"mean ${merged['final_net_pnl'].mean():.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--mode", required=True,
                          choices=["1m_momentum", "30s_momentum"])
    args = parser.parse_args()
    main(args.year, args.mode)
