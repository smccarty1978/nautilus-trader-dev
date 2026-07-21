"""Tick-NT validation with REAL bid/ask fills (no spread approximation).

Per memory rule feedback_real_fills_from_top_of_book.md: when MBP-1 data
with bid_px_00 / ask_px_00 is available, use top-of-book directly to
model fills rather than trade-print prices plus a flat spread tax.

Trade rule (unchanged from prior validators):
  - L=4 bear bars in 1m sticky regime = -1, RTH session.
  - Long fade. PT = entry_ask + 1.0 * ATR(14). SL = entry_ask - 2.0 * ATR(14).
  - Max hold 10 minutes. Non-overlap dedup. 60s-consecutive + same-session forward window.

Fill mechanics (realistic limit/market order semantics):
  - ENTRY (market BUY at signal close): fill at ask_px_00 of the first
    T row at-or-after signal_ts. This establishes the cost basis;
    PT and SL are computed relative to this fill price.
  - EXIT - PT (resting LIMIT SELL at pt_px): triggered when trade price
    (T row's price) reaches pt_px (someone crossed our level). Fill at
    pt_px EXACTLY - a limit order fills at its limit, no slippage on
    the favorable side.
  - EXIT - SL (stop-MARKET SELL): triggered when trade price <= sl_px.
    Fill at the BID at the trigger row. If bid < sl_px (price gapped
    through), the gap is captured as adverse slippage.
  - TIMEOUT: at 10-min boundary, market sell at the last bid in the
    window. Pays the spread on exit.

Cost model:
  - $5 round-trip commission only. NO spread tax (already in bid/ask).

Runs on both 2025 (NQ.c.0 ticks, roll-filtered ±3d around 2025 quarterly
rolls) and 2026 (NQ.v.0 ticks, no roll filter needed).

Output: studies/reversion_after_5_streak/results/tick_realfills_{year}.csv
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
FORWARD_BARS = 10
HOLDING_NS = FORWARD_BARS * 60 * 1_000_000_000
NQ_MULT = 20.0
COMMISSION_RT = 5.0
RTH_RANGE = (8 * 60 + 30, 15 * 60)

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


# ----- Signal generation (identical to audited scan_fade_rth_split logic) ---
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
    rth = (minutes >= RTH_RANGE[0]) & (minutes < RTH_RANGE[1])
    return np.where(rth, "RTH", "ETH")


def is_near_roll(ts_ns, roll_dates, roll_filter_days):
    if not roll_dates: return False
    ts = pd.Timestamp(ts_ns, tz="UTC")
    for roll in roll_dates:
        if abs((ts - roll).total_seconds()) <= roll_filter_days * 86400:
            return True
    return False


def find_signals(df, roll_dates, roll_filter_days):
    atr = compute_atr_wilder(df, ATR_PERIOD)
    regime = compute_regime(df)
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
    n_pre_roll = 0
    last_taken = -10**12
    for i in range(STREAK_LEN - 1, len(df)):
        if i <= last_taken + FORWARD_BARS:
            continue
        if i + FORWARD_BARS >= len(df):
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
        ok = True
        for k in range(1, FORWARD_BARS + 1):
            if ts[i + k] - ts[i + k - 1] != 60_000_000_000:
                ok = False; break
            if sess[i + k] != "RTH":
                ok = False; break
        if not ok:
            continue
        n_pre_roll += 1
        if is_near_roll(int(ts[i]), roll_dates, roll_filter_days):
            last_taken = i
            continue
        # Bar-mode outcome (for reference comparison)
        c0 = close[i]
        pt_px_b = c0 + PT_ATR * a
        sl_px_b = c0 - SL_ATR * a
        bar_kind = "neither"; bar_outcome_atr = 0.0
        for k in range(1, FORWARD_BARS + 1):
            bh = high[i + k]; bl = low[i + k]
            pt_t = bh >= pt_px_b
            sl_t = bl <= sl_px_b
            if sl_t:
                bar_kind = "sl"; bar_outcome_atr = -SL_ATR; break
            if pt_t:
                bar_kind = "pt"; bar_outcome_atr = PT_ATR; break
        if bar_kind == "neither":
            c_end = close[i + FORWARD_BARS]
            bar_outcome_atr = (c_end - c0) / a
        out.append({
            "i": i, "signal_ts": int(ts[i]),
            "close_at_signal": float(c0), "atr_at_signal": float(a),
            "bar_kind": bar_kind, "bar_outcome_atr": float(bar_outcome_atr),
        })
        last_taken = i
    return out, n_pre_roll


# ----- Tick load: T rows with bid/ask context -------------------------------
def load_trade_rows_with_quotes(tick_files, win_lo_ns, win_hi_ns):
    """Load action='T' rows with price + bid_px_00 + ask_px_00. Returns
    sorted (ts, price, bid, ask) numpy arrays."""
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


def replay_realfills(signal, ts_arr, px_arr, bid_arr, ask_arr):
    sig_ts = signal["signal_ts"]
    a = signal["atr_at_signal"]
    end_ts = sig_ts + HOLDING_NS

    # Entry: first T row at-or-after signal_ts. Buy fills at the ASK.
    i_entry = np.searchsorted(ts_arr, sig_ts, side="left")
    if i_entry >= len(ts_arr) or ts_arr[i_entry] > end_ts:
        return {**signal,
                "entry_fill_ts": -1, "entry_fill_px": np.nan,
                "entry_ask": np.nan, "entry_bid": np.nan,
                "exit_ts": -1, "exit_px": np.nan,
                "exit_reason": "no_entry_ticks",
                "tick_outcome_atr": np.nan, "tick_outcome_pts": np.nan,
                "entry_slip_pts": np.nan,
                "spread_at_entry": np.nan,
                "n_ticks_in_window": 0}

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
    # Spread guarded: only valid when both sides have finite, positive values.
    if entry_ask_patched or entry_bid_bad:
        spread_at_entry = np.nan
    else:
        spread_at_entry = entry_ask - entry_bid

    # Forward window (exclusive of entry tick)
    i_end = np.searchsorted(ts_arr, end_ts, side="right")
    seg_ts  = ts_arr[i_entry + 1:i_end]
    seg_px  = px_arr[i_entry + 1:i_end]
    seg_bid = bid_arr[i_entry + 1:i_end]
    seg_ask = ask_arr[i_entry + 1:i_end]
    n_ticks = len(seg_ts)

    exit_reason = "timeout"; exit_ts = -1; exit_fill = np.nan
    exit_bid_patched = False
    if n_ticks > 0:
        # PT: resting limit SELL at pt_px. Fills at pt_px exactly when trade
        # price reaches pt_px (someone crossed our level). No spread cost on
        # PT - the spread is captured by sitting on the ask.
        hit_pt = seg_px >= pt_px
        # SL: stop-MARKET SELL triggered by trade price <= sl_px. Fills at
        # the bid at trigger (market order hits the bid, eats the spread).
        hit_sl = seg_px <= sl_px
        if hit_pt.any() or hit_sl.any():
            i_pt = int(np.argmax(hit_pt)) if hit_pt.any() else 10**9
            i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10**9
            if i_sl <= i_pt:
                exit_reason = "sl"; idx = i_sl
                exit_ts = int(seg_ts[idx])
                # Market sell -> bid at trigger row
                if np.isfinite(seg_bid[idx]) and seg_bid[idx] > 0:
                    exit_fill = float(seg_bid[idx])
                else:
                    exit_fill = float(seg_px[idx])
                    exit_bid_patched = True
            else:
                exit_reason = "pt"; idx = i_pt
                exit_ts = int(seg_ts[idx])
                # Limit fill at exact pt_px (no slippage on favorable side)
                exit_fill = float(pt_px)
        else:
            # Timeout: market sell at last bid in window
            exit_ts = int(seg_ts[-1])
            last_bid = seg_bid[-1]
            if np.isfinite(last_bid) and last_bid > 0:
                exit_fill = float(last_bid)
            else:
                exit_fill = float(seg_px[-1])
                exit_bid_patched = True
    elif n_ticks == 0:
        exit_ts = entry_ts
        exit_fill = fill_buy   # no movement possible
    tick_pts = exit_fill - fill_buy
    tick_outcome_atr = tick_pts / a if a > 0 else np.nan

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
            "n_ticks_in_window": int(n_ticks)}


def run_one_year(year):
    cfg = YEAR_CONFIG[year]
    print("\n" + "=" * 70, flush=True)
    print(f"YEAR {year}", flush=True)
    print(f"  data: {cfg['data_warning']}", flush=True)
    print("=" * 70, flush=True)

    df = load_1m_df(cfg["sig_start"], cfg["sig_end"])
    signals, n_pre_roll = find_signals(df, cfg["roll_dates"], cfg["roll_filter_days"])
    print(f"  pre-roll-filter signals:  {n_pre_roll:,}", flush=True)
    print(f"  post-roll-filter signals: {len(signals):,}", flush=True)
    if not signals:
        print("  No signals."); return

    sig_ts_arr = np.array([s["signal_ts"] for s in signals], dtype=np.int64)
    win_lo = int(sig_ts_arr.min())
    win_hi = int(sig_ts_arr.max() + HOLDING_NS + 60_000_000_000)

    ts_arr, px_arr, bid_arr, ask_arr = load_trade_rows_with_quotes(
        cfg["tick_files"], win_lo, win_hi)
    print(f"  total T rows: {len(ts_arr):,}", flush=True)

    rows = []
    t0 = time.time()
    for n, s in enumerate(signals, 1):
        rows.append(replay_realfills(s, ts_arr, px_arr, bid_arr, ask_arr))
        if n % 500 == 0:
            print(f"  {n}/{len(signals)} ({time.time()-t0:.0f}s)", flush=True)

    out = pd.DataFrame(rows)
    out["gross_pnl_dollars"] = out["tick_outcome_pts"] * NQ_MULT
    out["net_pnl_dollars"] = out["gross_pnl_dollars"] - COMMISSION_RT
    out["bar_pnl_dollars"] = out["bar_outcome_atr"] * out["atr_at_signal"] * NQ_MULT
    out.to_csv(OUT / f"tick_realfills_{year}.csv", index=False)

    valid = out[out["exit_reason"] != "no_entry_ticks"].copy()
    valid = valid.sort_values("entry_fill_ts").reset_index(drop=True)
    valid["cum_net"] = valid["net_pnl_dollars"].cumsum()
    valid["peak"] = valid["cum_net"].cummax()
    valid["dd"] = valid["cum_net"] - valid["peak"]

    n_v = len(valid)
    pt = (valid["exit_reason"] == "pt").sum()
    sl = (valid["exit_reason"] == "sl").sum()
    to = (valid["exit_reason"] == "timeout").sum()
    n_resolved = pt + sl
    wr_resolved = pt / n_resolved * 100 if n_resolved else np.nan
    wr_full = (valid["net_pnl_dollars"] > 0).sum() / n_v * 100

    print(f"\n--- {year} RESULT (real bid/ask fills, $5 RT commission only) ---")
    print(f"trades              : {n_v:,}")
    print(f"PT-first / SL-first / timeout : {pt} / {sl} / {to}")
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
    n_entry_patched = int(valid["entry_ask_patched"].sum())
    n_exit_patched  = int(valid["exit_bid_patched"].sum())
    n_spread_nan    = int(valid["spread_at_entry"].isna().sum())
    print(f"Bad-quote fallbacks:")
    print(f"  entry ask patched -> trade px : {n_entry_patched} / {n_v} "
          f"({100*n_entry_patched/max(n_v,1):.2f}%)")
    print(f"  exit  bid patched -> trade px : {n_exit_patched} / {n_v} "
          f"({100*n_exit_patched/max(n_v,1):.2f}%)")
    print(f"  spread_at_entry NaN           : {n_spread_nan} / {n_v}")
    sp = valid["spread_at_entry"].dropna()
    print(f"Spread at entry (pts, clean rows only, n={len(sp)}):")
    if len(sp):
        print(f"  mean   : {sp.mean():+.3f}")
        print(f"  median : {sp.median():+.3f}")
        print(f"  p90    : {sp.quantile(0.9):+.3f}")
    print()
    print(f"Entry slip (fill_ask - close_at_signal, pts):")
    print(f"  mean   : {valid['entry_slip_pts'].mean():+.3f}")
    print(f"  median : {valid['entry_slip_pts'].median():+.3f}")
    print()
    print(f"Comparison to bar-mode (matched cohort):")
    print(f"  bar mean    : {valid['bar_outcome_atr'].mean():+.4f} ATR  "
          f"= {valid['bar_pnl_dollars'].mean():+.2f} $/trade")
    print(f"  tick mean   : {valid['tick_outcome_atr'].mean():+.4f} ATR  "
          f"= {valid['gross_pnl_dollars'].mean():+.2f} $/trade gross")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for year in [2026, 2025]:
        run_one_year(year)
    print("\n\nWrote: tick_realfills_2025.csv, tick_realfills_2026.csv")


if __name__ == "__main__":
    main()
