"""1s-bar replay for 2025 using NQ.v.0 (volume-continuous) 1s OHLC bars.

Hypothesis: the c.0 tick result for 2025 (-$12.5k NET on 655 trades with
PT=1.5/SL=3.0 + F4) was contaminated by c.0/v.0 contract mismatch. The
v.0 1s bars (matching the catalog used for signal generation) should
give a cleaner answer — and per the 2026 reconciliation (98.2% exit
agreement), 1s ≈ MBP-1 tick.

Same trade rule:
  - L=4 bear streak in 1m sticky regime = -1, RTH session.
  - F4 filter: total_exc_fast (5-min lookback) >= 57.75 at signal bar.
  - Long fade: PT = entry + 1.5 * ATR (limit), SL = entry - 3.0 * ATR (stop-market).
  - EOD-flatten at 15:00 CT.
  - Single-position dedup by 1s exit timestamp.

Fill model (same as 1s validator that reconciled to tick within 98%):
  - ENTRY: 1s bar open at first bar at-or-after signal_ts.
  - PT: trigger when bar high >= pt_px; fill at pt_px (limit).
  - SL: trigger when bar low <= sl_px; fill at max(sl_px - 1 tick, bar low).
  - EOD: market sell at close of last in-session 1s bar, minus 1 tick.

Output: studies/reversion_after_5_streak/results/onesec_2025_v0.csv
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
from nautilus_trader.persistence.catalog import ParquetDataCatalog


CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
ATR_PERIOD = 14
EMA_SHORT = 3
EMA_LONG = 9
STREAK_LEN = 4
PT_ATR = 1.5
SL_ATR = 3.0
F4_CUTOFF = 57.75
FAST_WINDOW = 5
NQ_MULT = 20.0
MNQ_MULT = 2.0
COMMISSION_RT_NQ = 5.0
COMMISSION_RT_MNQ = 2.50
SLIPPAGE_TICKS = 1.0
TICK_SIZE = 0.25
RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60

ONE_S_PATH = "data/raw/NQ_v0_1s_2025.parquet"
SIG_START = "2025-01-01"
SIG_END = "2025-12-31 23:59:59"
OUT = Path("studies/reversion_after_5_streak/results")


def load_1m_df():
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(
        bar_types=[BAR_TYPE],
        start=pd.Timestamp(SIG_START, tz="UTC"),
        end=pd.Timestamp(SIG_END, tz="UTC"),
    )
    df = pd.DataFrame({
        "ts_init":  [b.ts_init  for b in bars],
        "open":     [float(b.open)  for b in bars],
        "high":     [float(b.high)  for b in bars],
        "low":      [float(b.low)   for b in bars],
        "close":    [float(b.close) for b in bars],
    })
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


def compute_total_exc_fast(open_arr, high_arr, low_arr, close_arr, ts_arr,
                              window=FAST_WINDOW):
    n = len(open_arr)
    consec = np.zeros(n, dtype=bool)
    consec[1:] = (ts_arr[1:] - ts_arr[:-1]) == 60_000_000_000
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        lo = i - window + 1
        if not consec[lo + 1:i + 1].all():
            continue
        start_open = open_arr[lo]
        w_high = high_arr[lo:i + 1].max()
        w_low  = low_arr[lo:i + 1].min()
        out[i] = (w_high - start_open) + (start_open - w_low)
    return out


def session_of_close_ct(ts_init_ns):
    dt = pd.to_datetime(ts_init_ns, unit="ns", utc=True).tz_convert("America/Chicago")
    minutes = dt.hour * 60 + dt.minute
    rth = (minutes >= RTH_START_MIN) & (minutes < RTH_END_MIN)
    return np.where(rth, "RTH", "ETH")


def session_end_ts(ts_init_ns: int) -> int:
    dt = pd.Timestamp(ts_init_ns, tz="UTC").tz_convert("America/Chicago")
    eod_ct = dt.replace(hour=15, minute=0, second=0, microsecond=0, nanosecond=0)
    return int(eod_ct.tz_convert("UTC").value)


def find_signals(df, atr, regime, tef):
    sess = session_of_close_ct(df["ts_init"].to_numpy())
    close = df["close"].to_numpy()
    openp = df["open"].to_numpy()
    ts    = df["ts_init"].to_numpy()
    bear = (close < openp)
    consec = np.zeros(len(df), dtype=bool)
    consec[1:] = (ts[1:] - ts[:-1]) == 60_000_000_000

    out = []
    for i in range(STREAK_LEN - 1, len(df)):
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
        f4_val = tef[i]
        if not np.isfinite(f4_val) or f4_val < F4_CUTOFF:
            continue
        out.append({
            "i": i, "signal_ts": sig_ts, "session_end_ts": eod_ts,
            "close_at_signal": float(close[i]), "atr_at_signal": float(a),
            "total_exc_fast": float(f4_val),
        })
    return out


def load_1s_bars(path):
    print(f"Loading {path}...", flush=True)
    df = pq.read_table(path,
                         columns=["ts_event", "open", "high", "low", "close"]
                         ).to_pandas()
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["ts_event_ns"] = df["ts_event"].astype("int64")
    print(f"  {len(df):,} 1s bars  "
          f"range: {df['ts_event'].iloc[0]} -> {df['ts_event'].iloc[-1]}",
          flush=True)
    return df


def replay_1s(signal, bars_ts, bars_open, bars_high, bars_low, bars_close):
    sig_ts = signal["signal_ts"]
    eod_ts = signal["session_end_ts"]
    atr_i = signal["atr_at_signal"]

    i_entry = np.searchsorted(bars_ts, sig_ts, side="left")
    if i_entry >= len(bars_ts) or bars_ts[i_entry] >= eod_ts:
        return None
    entry_ts = int(bars_ts[i_entry])
    fill_buy = float(bars_open[i_entry])
    pt_px = fill_buy + PT_ATR * atr_i
    sl_px = fill_buy - SL_ATR * atr_i

    i_end = np.searchsorted(bars_ts, eod_ts, side="left")
    if i_end <= i_entry + 1:
        return {
            **signal,
            "entry_fill_ts": entry_ts, "entry_fill_px": fill_buy,
            "exit_ts": entry_ts, "exit_px": fill_buy,
            "exit_reason": "eod_no_ticks",
            "tick_outcome_pts": 0.0, "tick_outcome_atr": 0.0,
            "hold_seconds": 0,
        }
    seg_h = bars_high[i_entry + 1:i_end]
    seg_l = bars_low[i_entry + 1:i_end]
    seg_c = bars_close[i_entry + 1:i_end]
    seg_ts = bars_ts[i_entry + 1:i_end]
    hit_pt = seg_h >= pt_px
    hit_sl = seg_l <= sl_px
    if hit_pt.any() or hit_sl.any():
        i_pt = int(np.argmax(hit_pt)) if hit_pt.any() else 10**9
        i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10**9
        if i_sl <= i_pt:
            idx = i_sl
            exit_px = max(sl_px - SLIPPAGE_TICKS * TICK_SIZE, float(seg_l[idx]))
            exit_reason = "sl"
        else:
            idx = i_pt
            exit_px = pt_px
            exit_reason = "pt"
        exit_ts = int(seg_ts[idx])
    else:
        idx = len(seg_ts) - 1
        exit_px = float(seg_c[idx]) - SLIPPAGE_TICKS * TICK_SIZE
        exit_ts = int(seg_ts[idx])
        exit_reason = "eod"

    tick_pts = exit_px - fill_buy
    return {
        **signal,
        "entry_fill_ts": entry_ts, "entry_fill_px": fill_buy,
        "exit_ts": exit_ts, "exit_px": float(exit_px),
        "exit_reason": exit_reason,
        "tick_outcome_pts": float(tick_pts),
        "tick_outcome_atr": float(tick_pts / atr_i) if atr_i > 0 else np.nan,
        "hold_seconds": float(max(exit_ts - entry_ts, 0) / 1e9),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("Step 1: generate signals from 1m bars (2025 v.0)...", flush=True)
    df = load_1m_df()
    atr = compute_atr_wilder(df, ATR_PERIOD)
    regime = compute_regime(df)
    tef = compute_total_exc_fast(
        df["open"].to_numpy(),
        df["high"].to_numpy(),
        df["low"].to_numpy(),
        df["close"].to_numpy(),
        df["ts_init"].to_numpy(),
    )
    signals = find_signals(df, atr, regime, tef)
    print(f"  {len(signals):,} F4-filtered signals", flush=True)

    print("\nStep 2: load 1s bars (v.0)...", flush=True)
    bars = load_1s_bars(ONE_S_PATH)
    bars_ts = bars["ts_event_ns"].to_numpy()
    bars_open = bars["open"].to_numpy()
    bars_high = bars["high"].to_numpy()
    bars_low = bars["low"].to_numpy()
    bars_close = bars["close"].to_numpy()

    print("\nStep 3: replay each signal with single-position dedup...",
          flush=True)
    t0 = time.time()
    rows = []
    last_exit_ts = -10**18
    n_skipped = 0
    for s in signals:
        if s["signal_ts"] <= last_exit_ts:
            n_skipped += 1
            continue
        r = replay_1s(s, bars_ts, bars_open, bars_high, bars_low, bars_close)
        if r is None:
            continue
        rows.append(r)
        if r["exit_ts"] > 0:
            last_exit_ts = r["exit_ts"]
    print(f"  {len(rows):,} taken, {n_skipped:,} skipped overlap "
          f"({time.time()-t0:.0f}s)", flush=True)

    out = pd.DataFrame(rows)
    out["gross_pnl_nq"] = out["tick_outcome_pts"] * NQ_MULT
    out["gross_pnl_mnq"] = out["tick_outcome_pts"] * MNQ_MULT
    out["net_pnl_nq"] = out["gross_pnl_nq"] - COMMISSION_RT_NQ
    out["net_pnl_mnq"] = out["gross_pnl_mnq"] - COMMISSION_RT_MNQ
    out.to_csv(OUT / "onesec_2025_v0.csv", index=False)

    valid = out[~out["exit_reason"].isin(["no_entry_ticks"])].copy()
    valid = valid.sort_values("entry_fill_ts").reset_index(drop=True)
    valid["cum_nq"] = valid["net_pnl_nq"].cumsum()
    valid["dd_nq"] = valid["cum_nq"] - valid["cum_nq"].cummax()
    valid["cum_mnq"] = valid["net_pnl_mnq"].cumsum()
    valid["dd_mnq"] = valid["cum_mnq"] - valid["cum_mnq"].cummax()
    n_v = len(valid)
    pt = (valid["exit_reason"] == "pt").sum()
    sl = (valid["exit_reason"] == "sl").sum()
    eod = (valid["exit_reason"].isin(["eod", "eod_no_ticks"])).sum()
    wr = pt / max(pt + sl, 1) * 100

    print(f"\n--- 2025 v.0 1s RESULT (PT=1.5/SL=3.0 + F4) ---")
    print(f"  trades        : {n_v:,}")
    print(f"  PT / SL / EOD : {pt} / {sl} / {eod}")
    print(f"  WR resolved   : {wr:.2f}%")
    print(f"  WR full(NET>0): {(valid['net_pnl_nq'] > 0).sum() / n_v * 100:.2f}%")
    print()
    print(f"  NQ (per contract, -$5 comm):")
    print(f"    Mean gross  : {valid['gross_pnl_nq'].mean():+.2f}")
    print(f"    Mean NET    : {valid['net_pnl_nq'].mean():+.2f}")
    print(f"    Total NET   : {valid['net_pnl_nq'].sum():+,.0f}")
    print(f"    Max DD      : {valid['dd_nq'].min():+,.0f}")
    print(f"    Worst trade : {valid['net_pnl_nq'].min():+,.2f}")
    print(f"    Best trade  : {valid['net_pnl_nq'].max():+,.2f}")
    print()
    print(f"  MNQ (per contract, -$2.50 comm):")
    print(f"    Mean gross  : {valid['gross_pnl_mnq'].mean():+.2f}")
    print(f"    Mean NET    : {valid['net_pnl_mnq'].mean():+.2f}")
    print(f"    Total NET   : {valid['net_pnl_mnq'].sum():+,.0f}")
    print(f"    Max DD      : {valid['dd_mnq'].min():+,.0f}")
    print()
    print(f"  Hold seconds  : mean={valid['hold_seconds'].mean():.0f}  "
          f"median={valid['hold_seconds'].median():.0f}  "
          f"p90={valid['hold_seconds'].quantile(0.9):.0f}")

    # === Comparison row ===
    print("\n=== 2025 RESULTS HEAD-TO-HEAD ===")
    print("                            n   WR_res   Mean $/trade NET   Total NET")
    print(f"  bar mode (1m, v.0)      {len(df[df['ts_init'].notna()]):>4}   (not directly comparable, see grid)")
    print(f"  c.0 MBP-1 tick (DIRTY)  655    64.89%    -$19.12          -$12,521")
    print(f"  v.0 1s bars (CLEAN)     {n_v:>3}    {wr:.2f}%    "
          f"{valid['net_pnl_nq'].mean():+.2f}          "
          f"{valid['net_pnl_nq'].sum():+,.0f}")


if __name__ == "__main__":
    main()
