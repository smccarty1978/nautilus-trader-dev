"""Generate fade signals + 28 regime features per signal, 2020-2026.

Signal logic (unchanged): L=4 bear bars in 1m sticky regime = -1, RTH only.
Long fade, PT=1 ATR / SL=2 ATR computed from entry close (bar-mode proxy
for entry_ask), EOD-flatten at 15:00 CT, single-position dedup by actual
bar-mode exit bar.

Rolling regime features at signal bar (causal, lookback strictly through
the signal bar itself; rolling-window semantics like an EMA — each entry
bar looks back N minutes including itself):

  Windows: xfast=3m, fast=5m, medium=15m, slow=30m
  (xfast=3m is the closest integer multiple of 1m to the spec's 2.5m)

  Per window, 7 metrics computed from start-of-window OPEN:
    mfe          = max(high[t-N+1..t]) - open[t-N+1]      (>= 0)
    mae          = open[t-N+1] - min(low[t-N+1..t])       (>= 0)
    net_move     = close[t] - open[t-N+1]                  (signed)
    total_excursion = mfe + mae                            (>= 0)
    ratio        = mfe / max(mae, eps)                     (>= 0)
    efficiency   = net_move / max(total_excursion, eps)    (-1 to +1)
    close_loc    = (close[t] - min_low) / max(high_range, eps)  (0 to 1)

  28 features per signal (4 windows × 7 metrics).

Causal-by-construction:
  - All windows use bars [t-N+1 .. t] inclusive — only completed bars
    through the signal bar t. No bars after t.
  - The signal bar itself IS included in the lookback (per user spec:
    "rolling calculations like an EMA or SMA" — the current bar contributes).

Output: studies/reversion_after_5_streak/results/feature_signals.parquet
        with per-trade record: signal_ts, entry/exit details, bar outcome,
        and all 20 features.
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
from nautilus_trader.persistence.catalog import ParquetDataCatalog


CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
START = "2020-01-01"
END = "2026-04-30 23:59:59"
ATR_PERIOD = 14
EMA_SHORT = 3
EMA_LONG = 9
STREAK_LEN = 4
PT_ATR = 1.0
SL_ATR = 2.0
NQ_MULT = 20.0
RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60
EPS = 1e-9

# Feature windows in 1m bars (xfast=3m rounded up from 2.5m spec)
WINDOWS = {"xfast": 3, "fast": 5, "medium": 15, "slow": 30}
OUT = Path("studies/reversion_after_5_streak/results")


def load_1m_df():
    print(f"Loading {BAR_TYPE} {START} -> {END}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(
        bar_types=[BAR_TYPE],
        start=pd.Timestamp(START, tz="UTC"),
        end=pd.Timestamp(END, tz="UTC"),
    )
    df = pd.DataFrame({
        "ts_init":  [b.ts_init  for b in bars],
        "open":     [float(b.open)  for b in bars],
        "high":     [float(b.high)  for b in bars],
        "low":      [float(b.low)   for b in bars],
        "close":    [float(b.close) for b in bars],
    })
    print(f"  {len(df):,} bars in {time.time()-t0:.0f}s", flush=True)
    return df.sort_values("ts_init").reset_index(drop=True)


def compute_atr_wilder(df, period):
    high = df["high"].to_numpy(); low = df["low"].to_numpy(); close = df["close"].to_numpy()
    n = len(df); tr = np.empty(n); tr[0] = high[0] - low[0]
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


def compute_regime(df):
    high = df["high"]; low = df["low"]; close = df["close"]
    sH = high.ewm(span=EMA_SHORT, adjust=False).mean().to_numpy()
    lH = high.ewm(span=EMA_LONG,  adjust=False).mean().to_numpy()
    sL = low.ewm(span=EMA_SHORT,  adjust=False).mean().to_numpy()
    lL = low.ewm(span=EMA_LONG,   adjust=False).mean().to_numpy()
    c = close.to_numpy()
    n = len(df); regime = np.zeros(n, dtype=np.int8); cur = 0
    for i in range(n):
        if c[i] > sH[i] and c[i] > lH[i]: cur = 1
        elif c[i] < sL[i] and c[i] < lL[i]: cur = -1
        regime[i] = cur
    return regime


def session_of_close_ct(ts_init_ns):
    dt = pd.to_datetime(ts_init_ns, unit="ns", utc=True).tz_convert("America/Chicago")
    minutes = dt.hour * 60 + dt.minute
    rth = (minutes >= RTH_START_MIN) & (minutes < RTH_END_MIN)
    return np.where(rth, "RTH", "ETH")


def session_end_ts(ts_init_ns: int) -> int:
    dt = pd.Timestamp(ts_init_ns, tz="UTC").tz_convert("America/Chicago")
    eod_ct = dt.replace(hour=15, minute=0, second=0, microsecond=0, nanosecond=0)
    return int(eod_ct.tz_convert("UTC").value)


def compute_rolling_features(open_arr, high_arr, low_arr, close_arr,
                              ts_arr, windows_dict):
    """For each window length N (in 1m bars), compute the 5 features at
    every bar i using bars [i-N+1 .. i]. Returns dict of dicts:
        features[name][window_label] = np.array of len = len(bars).

    Causal: each bar i uses only bars up to and including i.
    NaN for i < N-1 (not enough lookback history).
    Also NaN when any bar in the window is not 60s-consecutive with the
    next (we wouldn't trust a window spanning the 16:00-17:00 CT pause).
    """
    n = len(open_arr)
    # Pre-compute consecutive flags: consec[i] True if ts[i] - ts[i-1] == 60s
    consec = np.zeros(n, dtype=bool)
    consec[1:] = (ts_arr[1:] - ts_arr[:-1]) == 60_000_000_000

    feats = {}
    for label, N in windows_dict.items():
        if N < 1:
            continue
        # For each window length N, vectorized rolling extrema would be
        # faster, but the windows are small (<= 30) and we want correctness.
        # Loop is fine.
        mfe = np.full(n, np.nan)
        mae = np.full(n, np.nan)
        net_move = np.full(n, np.nan)
        total_exc = np.full(n, np.nan)
        ratio = np.full(n, np.nan)
        efficiency = np.full(n, np.nan)
        close_loc = np.full(n, np.nan)
        for i in range(N - 1, n):
            # Window: bars [i-N+1 .. i] inclusive.
            lo = i - N + 1
            # Require all bars in window to be 60s-consecutive with prior.
            # consec[lo+1..i] must all be True (skip if window spans a gap).
            if N > 1 and not consec[lo + 1:i + 1].all():
                continue
            start_open = open_arr[lo]
            w_high = high_arr[lo:i + 1].max()
            w_low  = low_arr[lo:i + 1].min()
            c_now  = close_arr[i]
            f_mfe = w_high - start_open
            f_mae = start_open - w_low
            mfe[i] = f_mfe
            mae[i] = f_mae
            net_move[i] = c_now - start_open
            total_exc[i] = f_mfe + f_mae
            ratio[i] = f_mfe / max(f_mae, EPS)
            efficiency[i] = (c_now - start_open) / max(total_exc[i], EPS)
            high_range = w_high - w_low
            close_loc[i] = (c_now - w_low) / max(high_range, EPS)
        feats[label] = {
            "mfe": mfe, "mae": mae, "net_move": net_move,
            "total_exc": total_exc, "ratio": ratio,
            "efficiency": efficiency, "close_loc": close_loc,
        }
    return feats


def find_signals_with_features(df, atr, regime, feats):
    """Find fade signals; for each, snapshot the 20 features.
    Single-position dedup uses bar-mode exit (the bar where PT/SL/EOD hits).
    """
    sess = session_of_close_ct(df["ts_init"].to_numpy())
    close = df["close"].to_numpy()
    openp = df["open"].to_numpy()
    high  = df["high"].to_numpy()
    low   = df["low"].to_numpy()
    ts    = df["ts_init"].to_numpy()
    bear = (close < openp)
    consec = np.zeros(len(df), dtype=bool)
    consec[1:] = (ts[1:] - ts[:-1]) == 60_000_000_000

    out = []
    n = len(df)
    last_exit_bar = -10**12   # index of the last accepted trade's exit bar

    for i in range(STREAK_LEN - 1, n):
        if i <= last_exit_bar:
            continue
        if not bear[i - STREAK_LEN + 1:i + 1].all():
            continue
        if not consec[i - STREAK_LEN + 2:i + 1].all():
            continue
        if regime[i] != -1:
            continue
        if sess[i] != "RTH":
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        sig_ts = int(ts[i])
        eod_ts = session_end_ts(sig_ts)
        if eod_ts - sig_ts < 60_000_000_000:
            continue
        # Bar-mode bracket simulation: walk forward bars i+1..i+K where
        # bars stay in RTH same session (i.e., ts_init < eod_ts).
        c0 = float(close[i])
        pt_px = c0 + PT_ATR * a
        sl_px = c0 - SL_ATR * a
        exit_kind = "eod"; exit_bar = None; exit_atr_outcome = 0.0
        j = i + 1
        last_bar_in_session = i
        while j < n and ts[j] < eod_ts:
            # Forward bars must be 60s-consec (no gap) and same RTH session.
            if ts[j] - ts[j - 1] != 60_000_000_000 or sess[j] != "RTH":
                break
            bh = float(high[j]); bl = float(low[j])
            # SL-first tie
            if bl <= sl_px:
                exit_kind = "sl"; exit_bar = j; exit_atr_outcome = -SL_ATR
                break
            if bh >= pt_px:
                exit_kind = "pt"; exit_bar = j; exit_atr_outcome = PT_ATR
                break
            last_bar_in_session = j
            j += 1
        if exit_bar is None:
            # EOD-flatten: use last in-session bar's close.
            # If the forward loop never produced any valid in-session bar
            # (e.g., signal at 14:58 CT with i+1 already in ETH, or a data
            # gap right after the signal), then exit at the signal bar
            # itself with no P&L. This avoids silently using an ETH bar.
            if last_bar_in_session > i and last_bar_in_session < n:
                exit_bar = last_bar_in_session
                exit_atr_outcome = (float(close[exit_bar]) - c0) / a
            else:
                exit_bar = i           # no valid forward RTH bar at all
                exit_atr_outcome = 0.0
            exit_kind = "eod"

        # Snapshot features at signal bar i
        row = {
            "signal_idx": i,
            "signal_ts": sig_ts,
            "exit_bar_idx": int(exit_bar),
            "exit_kind_bar": exit_kind,
            "bar_outcome_atr": float(exit_atr_outcome),
            "bar_outcome_pts": float(exit_atr_outcome * a),
            "close_at_signal": c0,
            "atr_at_signal": float(a),
            "year": int(pd.Timestamp(sig_ts, tz="UTC").tz_convert("America/Chicago").year),
        }
        for w_label, w_feats in feats.items():
            for fname, arr in w_feats.items():
                row[f"{fname}_{w_label}"] = float(arr[i]) if np.isfinite(arr[i]) else np.nan
        out.append(row)
        last_exit_bar = int(exit_bar)

    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_1m_df()

    print("Computing ATR(14) and 1m sticky regime...", flush=True)
    atr = compute_atr_wilder(df, ATR_PERIOD)
    regime = compute_regime(df)

    print(f"Computing rolling features for windows {WINDOWS}...", flush=True)
    t0 = time.time()
    feats = compute_rolling_features(
        df["open"].to_numpy(),
        df["high"].to_numpy(),
        df["low"].to_numpy(),
        df["close"].to_numpy(),
        df["ts_init"].to_numpy(),
        WINDOWS,
    )
    print(f"  features computed in {time.time()-t0:.0f}s", flush=True)
    for w, fd in feats.items():
        n_finite = int(np.isfinite(fd["total_exc"]).sum())
        print(f"  {w}: total_exc finite on {n_finite:,} bars", flush=True)

    print("Finding signals + snapshotting features...", flush=True)
    t0 = time.time()
    rows = find_signals_with_features(df, atr, regime, feats)
    print(f"  {len(rows):,} signals in {time.time()-t0:.0f}s", flush=True)

    out_df = pd.DataFrame(rows)
    out_df.to_parquet(OUT / "feature_signals.parquet")

    # Quick summary
    print()
    print("Per-year signal counts:")
    for yr in sorted(out_df["year"].unique()):
        sub = out_df[out_df["year"] == yr]
        n = len(sub)
        pt = (sub["exit_kind_bar"] == "pt").sum()
        sl = (sub["exit_kind_bar"] == "sl").sum()
        eod = (sub["exit_kind_bar"] == "eod").sum()
        e_atr = sub["bar_outcome_atr"].mean()
        e_dollars = (sub["bar_outcome_atr"] * sub["atr_at_signal"] * NQ_MULT).mean()
        print(f"  {yr}: n={n:>5}  pt={pt:>4} sl={sl:>4} eod={eod:>4}  "
              f"WR_res={pt/max(pt+sl,1)*100:.1f}%  E={e_atr:+.4f} ATR  ${e_dollars:+.2f}/trade")

    print()
    print(f"Wrote: {OUT/'feature_signals.parquet'}")
    print(f"Columns: {list(out_df.columns)}")


if __name__ == "__main__":
    main()
