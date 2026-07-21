"""Phase 1 (5m) — 5m-cadence features for regime classification.

Aggregates 1s bars to 5m bars, computes 24 causal features using scaled
windows, and saves to results/features_nq_5m.parquet.
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
ATR_PERIOD = 14
ET = pytz.timezone("America/New_York")
CT = pytz.timezone("America/Chicago")
RTH_START_ET = (9 * 3600) + (30 * 60)
RTH_END_ET   = 16 * 3600

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
PRODUCT_DATA = {
    "NQ": {**{y: f"data/raw/NQ_v0_1s_{y}.parquet"
              for y in range(2019, 2026)},
            2026: "data/raw/NQ_v0_1s_2026_ytd.parquet"},
    "ES": {**{y: f"data/raw/ES_v0_1s_{y}.parquet"
              for y in range(2019, 2026)},
            2026: "data/raw/ES_v0_1s_2026_ytd.parquet"},
}
RAW = PRODUCT_DATA[PRODUCT]
OUT = Path("studies/regime_classification/results")

FEATURE_COLS = [
    "ret_25s", "ret_150s", "ret_300s", "ret_1500s", "cum_abs_300s",
    "rv_150s", "rv_1500s",
    "range_atr_300s", "range_atr_1500s", "range_atr_9000s",
    "vol_expansion",
    "efficiency_1500s", "chop_ratio_1500s", "n_dir_changes_300s",
    "body_ratio", "upper_wick", "lower_wick", "close_location",
    "vwap_z_signed", "vwap_z_abs", "vwap_slope_25m_atr", "session_pos",
    "range_pct_300s_vs_5h", "compress_drift",
]


def load_all_1s(years):
    parts = []
    for y in years:
        p = RAW.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["open", "high", "low", "close", "volume"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars


def build_5m_bars(bars_1s):
    """Epoch-floor 5m bars from 1s. Returns DataFrame indexed by bucket
    open ts (= 5m bar open time)."""
    ts = bars_1s.index.values.astype(np.int64)
    bucket = (ts // (300 * NS)) * (300 * NS)
    g = pd.DataFrame({
        "b": bucket,
        "o": bars_1s["open"].values,
        "h": bars_1s["high"].values,
        "l": bars_1s["low"].values,
        "c": bars_1s["close"].values,
        "v": bars_1s["volume"].values})
    return g.groupby("b").agg(
        o=("o", "first"), h=("h", "max"),
        l=("l", "min"), c=("c", "last"), v=("v", "sum"))


@njit
def wilder_atr(h, l, c, period):
    n = len(c)
    atr = np.full(n, np.nan)
    if n < period:
        return atr
    tr_sum = 0.0
    for i in range(period):
        if i == 0:
            tr = h[i] - l[i]
        else:
            tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        tr_sum += tr
    atr[period - 1] = tr_sum / period
    for i in range(period, n):
        tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        atr[i] = (atr[i-1] * (period - 1) + tr) / period
    return atr


def session_vwap(bars_1s):
    """Session-anchored cumulative VWAP and sigma. CT 17:00 anchor."""
    ct_idx = bars_1s.index.tz_convert(CT)
    ct_hour = ct_idx.hour.values
    ct_date = pd.to_datetime(ct_idx.date)
    sess_id = ct_date.copy()
    sess_id = sess_id.where(ct_hour < 17, sess_id + pd.Timedelta(days=1))
    sid = sess_id.view("int64")
    h = bars_1s["high"].to_numpy(np.float64)
    l = bars_1s["low"].to_numpy(np.float64)
    c = bars_1s["close"].to_numpy(np.float64)
    v = bars_1s["volume"].to_numpy(np.float64)
    p = (h + l + c) / 3.0
    pv = p * v
    p2v = p * p * v
    f = pd.DataFrame({"sid": sid, "pv": pv, "p2v": p2v, "v": v})
    cum_pv  = f.groupby("sid")["pv"].cumsum().to_numpy()
    cum_p2v = f.groupby("sid")["p2v"].cumsum().to_numpy()
    cum_v   = f.groupby("sid")["v"].cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap  = np.where(cum_v > 0, cum_pv / cum_v, np.nan)
        var   = np.where(cum_v > 0, cum_p2v / cum_v - vwap * vwap, 0.0)
        sigma = np.sqrt(np.maximum(var, 0.0))
    return vwap, sigma, sid


def session_hl(bars_1s):
    """Cumulative session high / low (RTH-anchored: resets at 09:30 ET)."""
    et_idx = bars_1s.index.tz_convert(ET)
    et_date_dt = pd.to_datetime(et_idx.date)
    h = bars_1s["high"].to_numpy(np.float64)
    l = bars_1s["low"].to_numpy(np.float64)
    f = pd.DataFrame({"date": et_date_dt, "h": h, "l": l})
    sess_high = f.groupby("date")["h"].cummax().to_numpy()
    sess_low  = f.groupby("date")["l"].cummin().to_numpy()
    return sess_high, sess_low


@njit
def per_5m_features(m_ts, m_o, m_h, m_l, m_c, m_atr,
                    ts_1s, c_1s, h_1s, l_1s,
                    vwap_1s, sigma_1s, sess_high, sess_low):
    """Compute the 24-feature vector for each 5m bar at close time
    m_ts[i] + 300s. Returns a 2D array [n_bars, 24].
    """
    n_bars = len(m_ts)
    n_feat = 24
    out = np.full((n_bars, n_feat), np.nan)
    for i in range(n_bars):
        close_ts = m_ts[i] + 300 * NS  # 5m bar close moment
        j_end = np.searchsorted(ts_1s, close_ts, side="left")
        if j_end <= 0:
            continue
        cur_close = c_1s[j_end - 1]
        atr = m_atr[i]
        if not np.isfinite(atr) or atr <= 0:
            continue

        # ── Returns (log) ──
        # ret_25s, ret_150s, ret_300s, ret_1500s
        for w_idx, wsec in enumerate((25, 150, 300, 1500)):
            j_lo = np.searchsorted(ts_1s, close_ts - wsec * NS, side="left")
            if j_lo > 0 and j_lo < j_end:
                px0 = c_1s[j_lo - 1]
                if px0 > 0 and cur_close > 0:
                    out[i, w_idx] = np.log(cur_close / px0)

        # cum_abs_300s = sum |1s log returns| over last 300s
        j300 = np.searchsorted(ts_1s, close_ts - 300 * NS, side="left")
        if j300 > 0 and j300 < j_end:
            cum_abs = 0.0
            for q in range(j300, j_end):
                if c_1s[q - 1] > 0 and c_1s[q] > 0:
                    cum_abs += abs(np.log(c_1s[q] / c_1s[q - 1]))
            out[i, 4] = cum_abs

        # ── Realized vol ──
        for w_idx, (wsec, col) in enumerate(((150, 5), (1500, 6))):
            j_lo = np.searchsorted(ts_1s, close_ts - wsec * NS, side="left")
            if j_lo > 0 and j_lo < j_end:
                sumsq = 0.0
                for q in range(j_lo, j_end):
                    if c_1s[q - 1] > 0 and c_1s[q] > 0:
                        lr = np.log(c_1s[q] / c_1s[q - 1])
                        sumsq += lr * lr
                out[i, col] = np.sqrt(sumsq)

        # ── Range / ATR ──
        for w_idx, (wsec, col) in enumerate(((300, 7), (1500, 8), (9000, 9))):
            j_lo = np.searchsorted(ts_1s, close_ts - wsec * NS, side="left")
            if j_lo < j_end and j_lo >= 0:
                seg_h = h_1s[j_lo:j_end]
                seg_l = l_1s[j_lo:j_end]
                if len(seg_h) > 0:
                    rng = seg_h.max() - seg_l.min()
                    out[i, col] = rng / atr

        # vol_expansion = rv_150s / rv_1500s
        if np.isfinite(out[i, 5]) and np.isfinite(out[i, 6]) and out[i, 6] > 0:
            out[i, 10] = out[i, 5] / out[i, 6]

        # ── Path / efficiency over 1500s ──
        j1500 = np.searchsorted(ts_1s, close_ts - 1500 * NS, side="left")
        if j1500 > 0 and j1500 < j_end:
            start_px = c_1s[j1500 - 1]
            net_move = abs(cur_close - start_px)
            total_path = 0.0
            for q in range(j1500, j_end):
                total_path += abs(c_1s[q] - c_1s[q - 1])
            if total_path > 0:
                eff = net_move / total_path
                out[i, 11] = eff
                out[i, 12] = min(1.0 / max(eff, 0.1), 10.0)

        # ── n_dir_changes_300s ──
        j300 = np.searchsorted(ts_1s, close_ts - 300 * NS, side="left")
        if j300 > 0 and j300 < j_end:
            n_changes = 0
            prev_sign = 0
            for q in range(j300, j_end):
                step = c_1s[q] - c_1s[q - 1]
                s = 1 if step > 0 else (-1 if step < 0 else 0)
                if s != 0 and prev_sign != 0 and s != prev_sign:
                    n_changes += 1
                if s != 0:
                    prev_sign = s
            out[i, 13] = float(n_changes)

        # ── Candle structure (this 5m bar) ──
        rng_5m = m_h[i] - m_l[i]
        if rng_5m > 0:
            out[i, 14] = abs(m_c[i] - m_o[i]) / rng_5m
            out[i, 15] = (m_h[i] - max(m_o[i], m_c[i])) / rng_5m
            out[i, 16] = (min(m_o[i], m_c[i]) - m_l[i]) / rng_5m
            out[i, 17] = (m_c[i] - m_l[i]) / rng_5m

        # ── VWAP / session ──
        if j_end > 0:
            vw = vwap_1s[j_end - 1]
            sg = sigma_1s[j_end - 1]
            if sg > 0 and np.isfinite(vw):
                z = (cur_close - vw) / sg
                out[i, 18] = z
                out[i, 19] = abs(z)
                # vwap slope over last 25m (1500s)
                j25m = np.searchsorted(ts_1s, close_ts - 1500 * NS, side="left")
                if j25m > 0 and j25m < j_end:
                    vw25 = vwap_1s[j25m - 1]
                    if np.isfinite(vw25):
                        out[i, 20] = (vw - vw25) / atr
            sh = sess_high[j_end - 1]
            sl = sess_low[j_end - 1]
            if sh > sl:
                out[i, 21] = (cur_close - sl) / (sh - sl)
    return out


def add_rolling_compression_features(df):
    """Compute the rolling 5m window compression features."""
    r300 = df["range_atr_300s"]
    df["range_pct_300s_vs_5h"] = r300.rolling(60, min_periods=20).rank(pct=True)
    r9000 = df["range_atr_9000s"]
    df["compress_drift"] = r9000 - r9000.rolling(120, min_periods=30).mean()
    return df


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    years = list(range(2019, 2027))
    print(f"PRODUCT={PRODUCT}")
    print(f"Loading 1s bars for {years[0]}-{years[-1]} ...")
    bars = load_all_1s(years)
    print(f"  {len(bars):,} 1s bars")

    print("Building 5m bars ...")
    five_m = build_5m_bars(bars)
    m_ts = five_m.index.values.astype(np.int64)
    m_o = five_m["o"].to_numpy(np.float64)
    m_h = five_m["h"].to_numpy(np.float64)
    m_l = five_m["l"].to_numpy(np.float64)
    m_c = five_m["c"].to_numpy(np.float64)
    print(f"  {len(five_m):,} 5m bars")

    print("Computing Wilder ATR-14 (5m) ...")
    m_atr = wilder_atr(m_h, m_l, m_c, ATR_PERIOD)

    print("Computing session VWAP and session H/L ...")
    vwap_1s, sigma_1s, sid = session_vwap(bars)
    sess_high, sess_low = session_hl(bars)
    ts_1s = bars.index.values.astype(np.int64)
    c_1s = bars["close"].to_numpy(np.float64)
    h_1s = bars["high"].to_numpy(np.float64)
    l_1s = bars["low"].to_numpy(np.float64)

    print("Computing per-5m features ...")
    feats = per_5m_features(m_ts, m_o, m_h, m_l, m_c, m_atr,
                              ts_1s, c_1s, h_1s, l_1s,
                              vwap_1s, sigma_1s, sess_high, sess_low)
    df = pd.DataFrame(feats, columns=FEATURE_COLS,
                       index=pd.to_datetime(m_ts, unit="ns", utc=True))
    df.index.name = "ts_5m_open"
    df["atr_5m"] = m_atr

    print("Computing rolling compression features ...")
    df = add_rolling_compression_features(df)

    # Calendar columns
    et_idx = df.index.tz_convert(ET)
    df["year"] = et_idx.year
    df["et_hour"] = et_idx.hour
    df["et_minute"] = et_idx.minute
    et_sod = et_idx.hour * 3600 + et_idx.minute * 60 + et_idx.second
    df["in_rth"] = ((et_sod >= RTH_START_ET) & (et_sod < RTH_END_ET))

    # Filter to 2020-2026 (drop 2019 lead-in)
    df = df[df["year"].between(2020, 2026)]
    print(f"  rows in 2020-2026 window: {len(df):,}")
    print(f"  rows with full feature vector (no NaN): "
          f"{df[FEATURE_COLS].notna().all(axis=1).sum():,}")

    out_p = OUT / f"features_{PRODUCT.lower()}_5m.parquet"
    df.to_parquet(out_p)
    print(f"  saved {out_p}")
    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
