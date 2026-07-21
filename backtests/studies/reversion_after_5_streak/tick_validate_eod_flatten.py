"""Tick-NT validation with EOD-flatten exit (no fixed-bar timeout).

Same setup as tick_validate_realfills.py, BUT:
  - Trades hold until PT or SL hits, OR until 15:00 CT (RTH session close).
  - At session close, market sell at the last bid before 15:00 CT.
  - No artificial 10-bar holding cap.
  - Signal-side filter: streak end must be in RTH at session_close > signal_ts.
    The forward bars don't need to be same-session anymore (we'd just
    flatten at EOD).
  - Non-overlap dedup uses the ACTUAL exit_ts of the prior trade — single
    position, no stacking. Variable holding time per trade.

Fill mechanics (unchanged from corrected realfills model):
  - Entry: ask_px_00 of first T row at-or-after signal_ts.
  - PT: trade price >= pt_px triggers; fill at pt_px exactly (limit semantics).
  - SL: trade price <= sl_px triggers; fill at bid_px_00 at trigger row.
  - EOD: at session close, fill at last bid_px_00 in the window.

Output: studies/reversion_after_5_streak/results/tick_eod_{year}.csv
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
PT_ATR = 1.0
SL_ATR = 2.0
NQ_MULT = 20.0
COMMISSION_RT = 5.0
RTH_START_MIN = 8 * 60 + 30      # 08:30 CT
RTH_END_MIN   = 15 * 60          # 15:00 CT — also EOD-flatten time

YEAR_CONFIG = {
    2025: {
        "sig_start": "2025-01-01",
        "sig_end":   "2025-12-31 23:59:59",
        "tick_files": [
            "data/raw/legacy_c0/NQ_mbp1_2025_Q1.parquet",
            "data/raw/legacy_c0/NQ_mbp1_2025_Q2.parquet",
            "data/raw/legacy_c0/NQ_mbp1_2025_Q3.parquet",
            "data/raw/legacy_c0/NQ_mbp1_2025_Q4.parquet",
        ],
        "roll_dates": [
            pd.Timestamp("2025-03-20", tz="UTC"),
            pd.Timestamp("2025-06-19", tz="UTC"),
            pd.Timestamp("2025-09-18", tz="UTC"),
            pd.Timestamp("2025-12-18", tz="UTC"),
        ],
        "roll_filter_days": 3,
        "data_warning": "NQ.c.0 ticks vs NQ.v.0 bars - roll filter ±3d applied.",
    },
    2026: {
        "sig_start": "2026-01-01",
        "sig_end":   "2026-04-30 23:59:59",
        "tick_files": [
            "data/raw/NQ_v0_mbp1_2026_01.parquet",
            "data/raw/NQ_v0_mbp1_2026_02.parquet",
            "data/raw/NQ_v0_mbp1_2026_03.parquet",
            "data/raw/NQ_v0_mbp1_2026_04.parquet",
        ],
        "roll_dates": [],
        "roll_filter_days": 0,
        "data_warning": "NQ.v.0 ticks vs NQ.v.0 bars - aligned, no roll filter.",
    },
}
OUT = Path("studies/reversion_after_5_streak/results")


def load_1m_df(sig_start, sig_end):
    print(f"Loading {BAR_TYPE} {sig_start} -> {sig_end}...", flush=True)
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(
        bar_types=[BAR_TYPE],
        start=pd.Timestamp(sig_start, tz="UTC"),
        end=pd.Timestamp(sig_end, tz="UTC"),
    )
    df = pd.DataFrame({
        "ts_init":  [b.ts_init  for b in bars],
        "open":     [float(b.open)  for b in bars],
        "high":     [float(b.high)  for b in bars],
        "low":      [float(b.low)   for b in bars],
        "close":    [float(b.close) for b in bars],
    })
    print(f"  {len(df):,} 1m bars", flush=True)
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
    """Return the UTC ns timestamp of the next 15:00 CT after ts_init_ns.
    The signal must be in RTH; session_end is same-day 15:00 CT."""
    dt = pd.Timestamp(ts_init_ns, tz="UTC").tz_convert("America/Chicago")
    # The day's 15:00 CT close
    eod_ct = dt.replace(hour=15, minute=0, second=0, microsecond=0, nanosecond=0)
    return int(eod_ct.tz_convert("UTC").value)


def is_near_roll(ts_ns, roll_dates, roll_filter_days):
    if not roll_dates: return False
    ts = pd.Timestamp(ts_ns, tz="UTC")
    for roll in roll_dates:
        if abs((ts - roll).total_seconds()) <= roll_filter_days * 86400:
            return True
    return False


def find_signals(df, roll_dates, roll_filter_days):
    """Generate candidate signals. No forward-window same-session check
    (we flatten at EOD). Non-overlap dedup is deferred to the replay
    stage where we use the actual exit_ts."""
    atr = compute_atr_wilder(df, ATR_PERIOD)
    regime = compute_regime(df)
    sess = session_of_close_ct(df["ts_init"].to_numpy())
    close = df["close"].to_numpy()
    openp = df["open"].to_numpy()
    ts    = df["ts_init"].to_numpy()
    bear = (close < openp)
    consec = np.zeros(len(df), dtype=bool)
    consec[1:] = (ts[1:] - ts[:-1]) == 60_000_000_000

    out = []
    n_pre_roll = 0
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
        # Signal must have at least some time before EOD to be tradable.
        # We require >= 60 seconds remaining.
        sig_ts = int(ts[i])
        end_ts = session_end_ts(sig_ts)
        if end_ts - sig_ts < 60_000_000_000:
            continue
        n_pre_roll += 1
        if is_near_roll(sig_ts, roll_dates, roll_filter_days):
            continue
        out.append({
            "i": i, "signal_ts": sig_ts, "session_end_ts": end_ts,
            "close_at_signal": float(close[i]), "atr_at_signal": float(a),
        })
    return out, n_pre_roll


def load_trade_rows_with_quotes(tick_files, win_lo_ns, win_hi_ns):
    print(f"Loading T rows + quotes for [{pd.Timestamp(win_lo_ns)}, "
          f"{pd.Timestamp(win_hi_ns)}]...", flush=True)
    parts = []
    for path in tick_files:
        if not Path(path).exists():
            print(f"  MISSING: {path}", flush=True); continue
        t0 = time.time()
        flt = [
            ("action", "=", "T"),
            ("ts_event", ">=", pd.Timestamp(win_lo_ns)),
            ("ts_event", "<=", pd.Timestamp(win_hi_ns)),
        ]
        cols = ["ts_event", "price", "bid_px_00", "ask_px_00"]
        try:
            df = pq.read_table(path, columns=cols, filters=flt).to_pandas()
        except Exception as e:
            print(f"  filter-read failed on {path}: {e}, falling back",
                  flush=True)
            tab = pq.read_table(path, columns=cols + ["action"])
            df = tab.to_pandas()
            df = df[(df["action"] == "T")
                    & (df["ts_event"].astype("int64") >= win_lo_ns)
                    & (df["ts_event"].astype("int64") <= win_hi_ns)]
            df = df[cols]
        if len(df) == 0:
            print(f"  {path}: 0 T rows ({time.time()-t0:.0f}s)", flush=True)
            continue
        parts.append(df)
        print(f"  {path}: {len(df):,} T rows ({time.time()-t0:.0f}s)",
              flush=True)
    if not parts:
        return (np.array([], dtype=np.int64),) * 4
    big = pd.concat(parts, ignore_index=True)
    big = big.sort_values("ts_event", kind="stable").reset_index(drop=True)
    ts  = big["ts_event"].astype("int64").to_numpy()
    px  = big["price"].astype(np.float64).to_numpy()
    bid = big["bid_px_00"].astype(np.float64).to_numpy()
    ask = big["ask_px_00"].astype(np.float64).to_numpy()
    return ts, px, bid, ask


def replay_signal(signal, ts_arr, px_arr, bid_arr, ask_arr):
    """Replay one signal: enter at ask, hold until PT/SL/EOD."""
    sig_ts = signal["signal_ts"]
    eod_ts = signal["session_end_ts"]
    a = signal["atr_at_signal"]

    i_entry = np.searchsorted(ts_arr, sig_ts, side="left")
    if i_entry >= len(ts_arr) or ts_arr[i_entry] >= eod_ts:
        return {**signal,
                "entry_fill_ts": -1, "entry_fill_px": np.nan,
                "entry_ask": np.nan, "entry_bid": np.nan,
                "exit_ts": -1, "exit_px": np.nan,
                "exit_reason": "no_entry_ticks",
                "tick_outcome_atr": np.nan, "tick_outcome_pts": np.nan,
                "entry_slip_pts": np.nan, "spread_at_entry": np.nan,
                "entry_ask_patched": False, "exit_bid_patched": False,
                "n_ticks_in_window": 0, "hold_seconds": 0}

    entry_ts  = int(ts_arr[i_entry])
    raw_ask = float(ask_arr[i_entry])
    raw_bid = float(bid_arr[i_entry])
    entry_ask_patched = not (np.isfinite(raw_ask) and raw_ask > 0)
    entry_bid_bad = not (np.isfinite(raw_bid) and raw_bid > 0)
    entry_ask = float(px_arr[i_entry]) if entry_ask_patched else raw_ask
    entry_bid = raw_bid
    fill_buy = entry_ask
    pt_px = fill_buy + PT_ATR * a
    sl_px = fill_buy - SL_ATR * a
    spread_at_entry = (entry_ask - entry_bid
                       if not (entry_ask_patched or entry_bid_bad) else np.nan)

    # Forward window: from entry_idx+1 up to (but not including) the first tick at-or-after eod_ts
    i_end = np.searchsorted(ts_arr, eod_ts, side="left")
    seg_ts  = ts_arr[i_entry + 1:i_end]
    seg_px  = px_arr[i_entry + 1:i_end]
    seg_bid = bid_arr[i_entry + 1:i_end]
    n_ticks = len(seg_ts)

    exit_reason = "eod"; exit_ts = -1; exit_fill = np.nan
    exit_bid_patched = False
    if n_ticks > 0:
        hit_pt = seg_px >= pt_px
        hit_sl = seg_px <= sl_px
        if hit_pt.any() or hit_sl.any():
            i_pt = int(np.argmax(hit_pt)) if hit_pt.any() else 10**9
            i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10**9
            if i_sl <= i_pt:
                exit_reason = "sl"; idx = i_sl
                exit_ts = int(seg_ts[idx])
                if np.isfinite(seg_bid[idx]) and seg_bid[idx] > 0:
                    exit_fill = float(seg_bid[idx])
                else:
                    exit_fill = float(seg_px[idx])
                    exit_bid_patched = True
            else:
                exit_reason = "pt"; idx = i_pt
                exit_ts = int(seg_ts[idx])
                exit_fill = float(pt_px)
        else:
            # EOD flatten at last bid in window
            exit_ts = int(seg_ts[-1])
            last_bid = seg_bid[-1]
            if np.isfinite(last_bid) and last_bid > 0:
                exit_fill = float(last_bid)
            else:
                exit_fill = float(seg_px[-1])
                exit_bid_patched = True
    elif n_ticks == 0:
        # No ticks between entry and EOD; assume no movement, exit at entry bid
        exit_ts = entry_ts
        if np.isfinite(entry_bid) and entry_bid > 0:
            exit_fill = float(entry_bid)
        else:
            exit_fill = fill_buy
        exit_reason = "eod_no_ticks"

    tick_pts = exit_fill - fill_buy
    tick_outcome_atr = tick_pts / a if a > 0 else np.nan
    hold_seconds = max((exit_ts - entry_ts) / 1e9, 0.0) if exit_ts > 0 else 0.0

    return {**signal,
            "entry_fill_ts": entry_ts, "entry_fill_px": fill_buy,
            "entry_ask": entry_ask, "entry_bid": entry_bid,
            "exit_ts": exit_ts, "exit_px": exit_fill,
            "exit_reason": exit_reason,
            "tick_outcome_atr": float(tick_outcome_atr),
            "tick_outcome_pts": float(tick_pts),
            "entry_slip_pts": float(fill_buy - signal["close_at_signal"]),
            "spread_at_entry": float(spread_at_entry) if np.isfinite(spread_at_entry) else np.nan,
            "entry_ask_patched": bool(entry_ask_patched),
            "exit_bid_patched": bool(exit_bid_patched),
            "n_ticks_in_window": int(n_ticks),
            "hold_seconds": float(hold_seconds)}


def replay_with_singleposition(signals, ts_arr, px_arr, bid_arr, ask_arr):
    """Walk signals chronologically; skip any whose signal_ts falls before
    the prior accepted trade's exit_ts (single position at a time)."""
    rows = []
    last_exit_ts = -10**18
    n_skipped_overlap = 0
    for s in signals:
        if s["signal_ts"] <= last_exit_ts:
            n_skipped_overlap += 1
            continue
        out = replay_signal(s, ts_arr, px_arr, bid_arr, ask_arr)
        rows.append(out)
        if out["exit_ts"] > 0:
            last_exit_ts = out["exit_ts"]
    return rows, n_skipped_overlap


def run_one_year(year):
    cfg = YEAR_CONFIG[year]
    print("\n" + "=" * 70, flush=True)
    print(f"YEAR {year}", flush=True)
    print(f"  data: {cfg['data_warning']}", flush=True)
    print("=" * 70, flush=True)

    df = load_1m_df(cfg["sig_start"], cfg["sig_end"])
    signals, n_pre_roll = find_signals(df, cfg["roll_dates"], cfg["roll_filter_days"])
    print(f"  candidate signals (pre-overlap, post-roll-filter): {len(signals):,}",
          flush=True)
    if not signals:
        print("  No signals."); return

    # Determine tick load window
    sig_ts_arr = np.array([s["signal_ts"] for s in signals], dtype=np.int64)
    eod_ts_arr = np.array([s["session_end_ts"] for s in signals], dtype=np.int64)
    win_lo = int(sig_ts_arr.min())
    win_hi = int(eod_ts_arr.max() + 60_000_000_000)

    ts_arr, px_arr, bid_arr, ask_arr = load_trade_rows_with_quotes(
        cfg["tick_files"], win_lo, win_hi)
    print(f"  total T rows: {len(ts_arr):,}", flush=True)

    t0 = time.time()
    rows, n_overlap = replay_with_singleposition(
        signals, ts_arr, px_arr, bid_arr, ask_arr)
    print(f"  single-position replay: {len(rows):,} taken, "
          f"{n_overlap:,} skipped for overlap ({time.time()-t0:.0f}s)",
          flush=True)

    out = pd.DataFrame(rows)
    out["gross_pnl_dollars"] = out["tick_outcome_pts"] * NQ_MULT
    out["net_pnl_dollars"] = out["gross_pnl_dollars"] - COMMISSION_RT
    out.to_csv(OUT / f"tick_eod_{year}.csv", index=False)

    valid = out[~out["exit_reason"].isin(["no_entry_ticks"])].copy()
    valid = valid.sort_values("entry_fill_ts").reset_index(drop=True)
    valid["cum_net"] = valid["net_pnl_dollars"].cumsum()
    valid["peak"] = valid["cum_net"].cummax()
    valid["dd"] = valid["cum_net"] - valid["peak"]

    n_v = len(valid)
    pt = (valid["exit_reason"] == "pt").sum()
    sl = (valid["exit_reason"] == "sl").sum()
    eod = (valid["exit_reason"].isin(["eod", "eod_no_ticks"])).sum()
    n_resolved = pt + sl
    wr_resolved = pt / n_resolved * 100 if n_resolved else np.nan
    wr_full = (valid["net_pnl_dollars"] > 0).sum() / n_v * 100

    print(f"\n--- {year} RESULT (real bid/ask fills, EOD-flatten, $5 RT comm) ---")
    print(f"trades              : {n_v:,}  (skipped {n_overlap:,} overlap)")
    print(f"PT / SL / EOD       : {pt} / {sl} / {eod}")
    print(f"WR resolved (PT vs SL)  : {wr_resolved:.2f}%")
    print(f"WR full (NET > 0)       : {wr_full:.2f}%")
    print()
    print(f"Mean $/trade (gross)    : {valid['gross_pnl_dollars'].mean():+.2f}")
    print(f"Mean $/trade (NET, -$5) : {valid['net_pnl_dollars'].mean():+.2f}")
    print(f"Total NET               : {valid['net_pnl_dollars'].sum():+,.0f}")
    print(f"Max drawdown (NET)      : {valid['dd'].min():+,.0f}")
    print(f"DD/Total ratio          : {abs(valid['dd'].min()) / max(valid['net_pnl_dollars'].sum(), 1):.2f}")
    print(f"Worst single trade NET  : {valid['net_pnl_dollars'].min():+,.2f}")
    print(f"Best single trade NET   : {valid['net_pnl_dollars'].max():+,.2f}")
    print()
    print(f"Holding time (seconds):")
    print(f"  mean   : {valid['hold_seconds'].mean():.0f}")
    print(f"  median : {valid['hold_seconds'].median():.0f}")
    print(f"  p90    : {valid['hold_seconds'].quantile(0.9):.0f}")
    print()
    print(f"Per-exit-reason breakdown:")
    for reason in ["pt", "sl", "eod", "eod_no_ticks"]:
        sub = valid[valid["exit_reason"] == reason]
        if len(sub) == 0: continue
        print(f"  {reason:14s}: n={len(sub):>5}  "
              f"mean=${sub['net_pnl_dollars'].mean():+8.2f}  "
              f"median=${sub['net_pnl_dollars'].median():+8.2f}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for year in [2026, 2025]:
        run_one_year(year)
    print("\n\nWrote: tick_eod_2025.csv, tick_eod_2026.csv")


if __name__ == "__main__":
    main()
