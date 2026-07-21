"""Tick-level validation for 2025, long-fade after L=4 bear streak in
bear regime, RTH only.

WARNING — CONTRACT MISMATCH:
  - Signal source: 1m bars from data/catalog/NQ_v0_2020_2026 (NQ.v.0,
    volume-continuous).
  - Tick source:   data/raw/legacy_c0/NQ_mbp1_2025_Q[1-4].parquet (NQ.c.0,
    calendar-continuous).
  - Per memory rule (hhll_exit_overlay_finding.md): mixing v.0 bars with
    c.0 ticks produces 100-250 pt phantom gaps around quarterly rolls
    (3rd Thursday of Mar/Jun/Sep/Dec).
  - Remediation applied here: drop signals whose signal_ts is within
    ROLL_FILTER_DAYS of the 2025 quarterly roll dates. Documented in
    output and console.

What this does:
  Same logic as tick_validate_2026.py:
    1. Generate signals from 1m bars (audited scan_fade_rth_split logic).
    2. Apply ±3-day roll filter on signal_ts to avoid c.0/v.0 spread.
    3. Replay NQ.c.0 MBP-1 trade ticks (action='T') for each signal.
    4. Bracket: PT=1.0 ATR above entry, SL=2.0 ATR below, 10-min timeout.
    5. Compare bar-mode outcome (computed on v.0 bars) to tick outcome.

Output: studies/reversion_after_5_streak/results/tick_validate_2025.csv
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
SIG_START = "2025-01-01"
SIG_END   = "2025-12-31 23:59:59"
ATR_PERIOD = 14
EMA_SHORT = 3
EMA_LONG = 9
STREAK_LEN = 4
PT_ATR = 1.0
SL_ATR = 2.0
FORWARD_BARS = 10
HOLDING_NS = FORWARD_BARS * 60 * 1_000_000_000
NQ_MULT = 20.0
COMMISSION_RT = 5.0               # round-trip $ per contract
SPREAD_TICKS_RT = 1.0             # round-trip slip in NQ ticks (= $5)
RTH_RANGE = (8 * 60 + 30, 15 * 60)
TICK_FILES = [
    "data/raw/legacy_c0/NQ_mbp1_2025_Q1.parquet",
    "data/raw/legacy_c0/NQ_mbp1_2025_Q2.parquet",
    "data/raw/legacy_c0/NQ_mbp1_2025_Q3.parquet",
    "data/raw/legacy_c0/NQ_mbp1_2025_Q4.parquet",
]
# 2025 quarterly roll dates (3rd Thursday of Mar/Jun/Sep/Dec)
ROLL_DATES_2025 = [
    pd.Timestamp("2025-03-20", tz="UTC"),
    pd.Timestamp("2025-06-19", tz="UTC"),
    pd.Timestamp("2025-09-18", tz="UTC"),
    pd.Timestamp("2025-12-18", tz="UTC"),
]
ROLL_FILTER_DAYS = 3
OUT = Path("studies/reversion_after_5_streak/results")


# ----- Signal generation (identical to scan_fade_rth_split.py logic) --------
def load_1m_df():
    print(f"Loading {BAR_TYPE} {SIG_START} -> {SIG_END}...", flush=True)
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


def is_near_roll(ts_ns: int) -> bool:
    """True if ts is within ROLL_FILTER_DAYS of any 2025 quarterly roll."""
    ts = pd.Timestamp(ts_ns, tz="UTC")
    for roll in ROLL_DATES_2025:
        if abs((ts - roll).total_seconds()) <= ROLL_FILTER_DAYS * 86400:
            return True
    return False


def find_signals(df):
    """Returns (signals_all_dict_list, n_pre_roll, n_post_roll)."""
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
        # Roll filter (drop signals near c.0/v.0 contract switch)
        if is_near_roll(int(ts[i])):
            last_taken = i
            continue
        # Bar-mode outcome
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


# ----- Tick replay ----------------------------------------------------------
def load_trade_ticks(window_lo_ns: int, window_hi_ns: int):
    print(f"Loading trade ticks for [{pd.Timestamp(window_lo_ns)}, "
          f"{pd.Timestamp(window_hi_ns)}]...", flush=True)
    parts_ts, parts_px = [], []
    for path in TICK_FILES:
        if not Path(path).exists():
            print(f"  MISSING: {path}", flush=True)
            continue
        t0 = time.time()
        flt = [
            ("action", "=", "T"),
            ("ts_event", ">=", pd.Timestamp(window_lo_ns)),
            ("ts_event", "<=", pd.Timestamp(window_hi_ns)),
        ]
        try:
            df = pq.read_table(path, columns=["ts_event", "price"],
                                filters=flt).to_pandas()
        except Exception as e:
            print(f"  filter-read failed on {path}: {e}, falling back",
                  flush=True)
            tab = pq.read_table(path, columns=["ts_event", "action", "price"])
            df = tab.to_pandas()
            df = df[(df["action"] == "T")
                    & (df["ts_event"].astype("int64") >= window_lo_ns)
                    & (df["ts_event"].astype("int64") <= window_hi_ns)]
            df = df[["ts_event", "price"]]
        if len(df) == 0:
            print(f"  {path}: 0 ticks ({time.time()-t0:.0f}s)", flush=True)
            continue
        ts = df["ts_event"].astype("int64").to_numpy()
        px = df["price"].astype(np.float64).to_numpy()
        parts_ts.append(ts); parts_px.append(px)
        print(f"  {path}: {len(ts):,} ticks ({time.time()-t0:.0f}s)",
              flush=True)
    if not parts_ts:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)
    ts_all = np.concatenate(parts_ts)
    px_all = np.concatenate(parts_px)
    order = np.argsort(ts_all, kind="stable")
    return ts_all[order], px_all[order]


def replay_trade(signal, ts_arr, px_arr):
    sig_ts = signal["signal_ts"]
    a = signal["atr_at_signal"]
    end_ts = sig_ts + HOLDING_NS

    i_entry = np.searchsorted(ts_arr, sig_ts, side="left")
    if i_entry >= len(ts_arr) or ts_arr[i_entry] > end_ts:
        return {**signal,
                "entry_fill_ts": -1, "entry_fill_px": np.nan,
                "exit_ts": -1, "exit_px": np.nan,
                "exit_reason": "no_entry_ticks",
                "tick_outcome_atr": np.nan,
                "tick_outcome_pts": np.nan,
                "entry_slip_pts": np.nan,
                "n_ticks_in_window": 0}

    entry_ts = int(ts_arr[i_entry])
    entry_px = float(px_arr[i_entry])
    pt_px = entry_px + PT_ATR * a
    sl_px = entry_px - SL_ATR * a

    i_end = np.searchsorted(ts_arr, end_ts, side="right")
    seg_ts = ts_arr[i_entry + 1:i_end]
    seg_px = px_arr[i_entry + 1:i_end]
    n_ticks = len(seg_ts)

    exit_reason = "timeout"; exit_ts = -1; exit_px = np.nan; tick_pts = 0.0
    if n_ticks > 0:
        hit_pt = seg_px >= pt_px
        hit_sl = seg_px <= sl_px
        if hit_pt.any() or hit_sl.any():
            i_pt = int(np.argmax(hit_pt)) if hit_pt.any() else 10**9
            i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10**9
            if i_sl <= i_pt:
                exit_reason = "sl"; idx = i_sl
            else:
                exit_reason = "pt"; idx = i_pt
            exit_ts = int(seg_ts[idx]); exit_px = float(seg_px[idx])
            tick_pts = exit_px - entry_px
        else:
            exit_ts = int(seg_ts[-1]); exit_px = float(seg_px[-1])
            tick_pts = exit_px - entry_px
    elif n_ticks == 0:
        exit_ts = entry_ts; exit_px = entry_px; tick_pts = 0.0

    tick_outcome_atr = tick_pts / a if a > 0 else np.nan
    return {**signal,
            "entry_fill_ts": entry_ts, "entry_fill_px": entry_px,
            "exit_ts": exit_ts, "exit_px": exit_px,
            "exit_reason": exit_reason,
            "tick_outcome_atr": float(tick_outcome_atr),
            "tick_outcome_pts": float(tick_pts),
            "entry_slip_pts": float(entry_px - signal["close_at_signal"]),
            "n_ticks_in_window": int(n_ticks)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("*** WARNING: NQ.c.0 ticks vs NQ.v.0 bars. Roll filter ±3d applied. ***",
          flush=True)
    print("=== STEP 1: Generate signals from 1m bars ===", flush=True)
    df = load_1m_df()
    signals, n_pre_roll = find_signals(df)
    print(f"  pre-roll-filter:  {n_pre_roll:,} signals", flush=True)
    print(f"  post-roll-filter: {len(signals):,} signals "
          f"({len(signals)/max(n_pre_roll,1)*100:.1f}% retained)", flush=True)
    if not signals:
        print("  No signals; aborting."); return

    sig_ts_arr = np.array([s["signal_ts"] for s in signals], dtype=np.int64)
    win_lo = int(sig_ts_arr.min())
    win_hi = int(sig_ts_arr.max() + HOLDING_NS + 60_000_000_000)

    print(f"\n=== STEP 2: Load trade ticks ===", flush=True)
    ts_arr, px_arr = load_trade_ticks(win_lo, win_hi)
    print(f"  total ticks loaded: {len(ts_arr):,}")

    print(f"\n=== STEP 3: Replay each signal in ticks ===", flush=True)
    t0 = time.time()
    rows = []
    for n, s in enumerate(signals, 1):
        rows.append(replay_trade(s, ts_arr, px_arr))
        if n % 200 == 0:
            print(f"  {n}/{len(signals)} ({time.time()-t0:.0f}s)", flush=True)
    out = pd.DataFrame(rows)

    spread_cost_pts = SPREAD_TICKS_RT * 0.25
    spread_cost_dollars = spread_cost_pts * NQ_MULT
    out["gross_pnl_dollars"] = out["tick_outcome_pts"] * NQ_MULT
    out["net_pnl_dollars"] = (out["gross_pnl_dollars"]
                                - spread_cost_dollars - COMMISSION_RT)
    out["bar_pnl_dollars"] = out["bar_outcome_atr"] * out["atr_at_signal"] * NQ_MULT
    out["delta_atr"] = out["tick_outcome_atr"] - out["bar_outcome_atr"]
    out["delta_dollars"] = out["gross_pnl_dollars"] - out["bar_pnl_dollars"]
    out.to_csv(OUT / "tick_validate_2025.csv", index=False)

    n = len(out)
    valid = out[out["exit_reason"] != "no_entry_ticks"]
    n_v = len(valid)
    print("\n=== RESULT — TICK vs BAR (2025 RTH, roll-filtered, "
          f"L=4 bear/bear-regime, PT=1.0 SL=2.0 ATR) ===")
    print(f"signals (pre-roll-filter)  : {n_pre_roll:,}")
    print(f"signals (post-roll-filter) : {n:,}")
    print(f"signals with tick fill     : {n_v:,} "
          f"({100*n_v/max(n,1):.1f}%)")
    print()
    print("Outcome distribution (matched cohort):")
    print(f"  bar  : {(valid['bar_kind']=='pt').sum():>5} pt  "
          f"{(valid['bar_kind']=='sl').sum():>5} sl  "
          f"{(valid['bar_kind']=='neither').sum():>5} neither")
    print(f"  tick : {(valid['exit_reason']=='pt').sum():>5} pt  "
          f"{(valid['exit_reason']=='sl').sum():>5} sl  "
          f"{(valid['exit_reason']=='timeout').sum():>5} timeout")
    print()
    print("Expectancy (mean, matched cohort):")
    print(f"  bar     : {valid['bar_outcome_atr'].mean():+.4f} ATR  "
          f"= {valid['bar_pnl_dollars'].mean():+.2f} $/trade")
    print(f"  tick    : {valid['tick_outcome_atr'].mean():+.4f} ATR  "
          f"= {valid['gross_pnl_dollars'].mean():+.2f} $/trade gross")
    print(f"  tick net: {valid['net_pnl_dollars'].mean():+.2f} $/trade "
          f"(after $5 commission + $5 spread)")
    print(f"  delta   : {valid['delta_atr'].mean():+.4f} ATR  "
          f"= {valid['delta_dollars'].mean():+.2f} $/trade")
    print()
    print(f"Entry slip (pts, fill - close_at_signal):")
    print(f"  mean   : {valid['entry_slip_pts'].mean():+.3f} pts")
    print(f"  median : {valid['entry_slip_pts'].median():+.3f} pts")
    print(f"  p90    : {valid['entry_slip_pts'].abs().quantile(0.9):+.3f} pts |slip|")
    print()
    print(f"Total $ (matched cohort, n={n_v}):")
    print(f"  bar  gross: {valid['bar_pnl_dollars'].sum():+,.0f}")
    print(f"  tick gross: {valid['gross_pnl_dollars'].sum():+,.0f}")
    print(f"  tick net  : {valid['net_pnl_dollars'].sum():+,.0f}")
    excluded = n - n_v
    if excluded:
        print(f"\n  NB: {excluded} signal(s) excluded (no entry tick in window).")

    print(f"\nWrote: {OUT/'tick_validate_2025.csv'}")


if __name__ == "__main__":
    main()
