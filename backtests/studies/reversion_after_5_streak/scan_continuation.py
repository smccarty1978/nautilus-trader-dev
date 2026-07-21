"""Trade-WITH-trend continuation scan, NQ 1m bars 2024-2025.

Mirrors scan_streak_lengths.py but flips the trade direction:
  - After L consecutive bullish bars (close > open) -> enter LONG at close_L
  - After L consecutive bearish bars (close < open) -> enter SHORT at close_L
  - PT (favorable)  = continuation direction
  - SL (adverse)    = reversal direction
Resolution is intra-bar, bar by bar, max FORWARD_BARS bars.
Same-bar tie -> SL first (conservative).

Goal: find smallest streak length where a 1 ATR symmetric bracket is profitable.

Output:
  studies/reversion_after_5_streak/results/streak_length_continuation_scan.csv
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
START = "2024-01-01"
END = "2025-12-31 23:59:59"
ATR_PERIOD = 14
FORWARD_BARS = 10        # longer holding window for continuation (1 ATR PT
                          # often takes >2 bars at 1m)
STREAK_LENS = [4, 5, 6, 7, 8, 9, 10, 12]
SYMMETRIC_PT_SL = [0.5, 1.0, 1.5, 2.0]
PT_FIXED = 1.0
SL_VARIATIONS = [0.5, 1.0, 1.5, 2.0]
OUT = Path("studies/reversion_after_5_streak/results")


def load_1m_df() -> pd.DataFrame:
    print(f"Loading {BAR_TYPE} {START} -> {END}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(
        bar_types=[BAR_TYPE],
        start=pd.Timestamp(START, tz="UTC"),
        end=pd.Timestamp(END, tz="UTC"),
    )
    print(f"  {len(bars):,} bars in {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame({
        "ts_event": [b.ts_event for b in bars],
        "ts_init":  [b.ts_init  for b in bars],
        "open":     [float(b.open)  for b in bars],
        "high":     [float(b.high)  for b in bars],
        "low":      [float(b.low)   for b in bars],
        "close":    [float(b.close) for b in bars],
    })
    return df.sort_values("ts_event").reset_index(drop=True)


def compute_atr_wilder(df: pd.DataFrame, period: int) -> np.ndarray:
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
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


def session_of_close_ct(ts_init_ns: np.ndarray) -> np.ndarray:
    dt = pd.to_datetime(ts_init_ns, unit="ns", utc=True).tz_convert("America/Chicago")
    minutes = dt.hour * 60 + dt.minute
    rth = (minutes >= 8 * 60 + 30) & (minutes < 15 * 60)
    return np.where(rth, "RTH", "ETH")


def find_streak_ends(close: np.ndarray, openp: np.ndarray, ts: np.ndarray,
                      streak_len: int) -> tuple[np.ndarray, np.ndarray]:
    bull = (close > openp)
    bear = (close < openp)
    consec = np.zeros(len(close), dtype=bool)
    consec[1:] = (ts[1:] - ts[:-1]) == 60_000_000_000
    bull_ends, bear_ends = [], []
    n = len(close)
    if n < streak_len:
        return np.array([], int), np.array([], int)
    for i in range(streak_len - 1, n):
        slc = slice(i - streak_len + 1, i + 1)
        gap_ok = consec[i - streak_len + 2:i + 1].all()
        if not gap_ok:
            continue
        if bull[slc].all():
            bull_ends.append(i)
        elif bear[slc].all():
            bear_ends.append(i)
    return np.array(bull_ends, int), np.array(bear_ends, int)


def simulate_continuation(df: pd.DataFrame, atr: np.ndarray,
                           ends: np.ndarray, side: str,
                           pt: float, sl: float,
                           forward_bars: int) -> dict:
    """Continuation: bull streak -> long, bear streak -> short.
    PT in the continuation direction, SL in the reversal direction.
    Same-bar tie -> SL first (conservative)."""
    # sign: +1 for long (after bull streak), -1 for short (after bear streak)
    long_side = (side == "bull")
    close = df["close"].to_numpy()
    high  = df["high"].to_numpy()
    low   = df["low"].to_numpy()
    ts    = df["ts_event"].to_numpy()
    sess  = session_of_close_ct(df["ts_init"].to_numpy())

    pt_count = sl_count = neither_count = 0
    mtm_atr_sum = 0.0
    n_eligible = 0

    for i in ends:
        if i + forward_bars >= len(close):
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        ok = True
        for k in range(1, forward_bars + 1):
            if ts[i + k] - ts[i + k - 1] != 60_000_000_000:
                ok = False
                break
            if sess[i + k] != sess[i]:
                ok = False
                break
        if not ok:
            continue

        n_eligible += 1
        c0 = close[i]
        if long_side:
            pt_px = c0 + pt * a   # favorable = price goes up
            sl_px = c0 - sl * a
        else:
            pt_px = c0 - pt * a   # favorable = price goes down
            sl_px = c0 + sl * a

        resolved = False
        for k in range(1, forward_bars + 1):
            bh = high[i + k]
            bl = low[i + k]
            if long_side:
                pt_touched = bh >= pt_px
                sl_touched = bl <= sl_px
            else:
                pt_touched = bl <= pt_px
                sl_touched = bh >= sl_px
            if sl_touched:
                sl_count += 1
                resolved = True
                break
            if pt_touched:
                pt_count += 1
                resolved = True
                break
        if not resolved:
            c_end = close[i + forward_bars]
            if long_side:
                mtm = (c_end - c0) / a
            else:
                mtm = (c0 - c_end) / a
            neither_count += 1
            mtm_atr_sum += mtm

    if n_eligible == 0:
        return {"n": 0, "pct_pt": np.nan, "pct_sl": np.nan,
                "pct_neither": np.nan, "mean_mtm_neither": np.nan,
                "expectancy_atr": np.nan, "wr_resolved": np.nan}

    pct_pt = pt_count / n_eligible
    pct_sl = sl_count / n_eligible
    pct_neither = neither_count / n_eligible
    mean_mtm = (mtm_atr_sum / neither_count) if neither_count else 0.0
    expectancy = pct_pt * pt - pct_sl * sl + pct_neither * mean_mtm
    wr_resolved = pt_count / (pt_count + sl_count) if (pt_count + sl_count) > 0 else np.nan
    return {
        "n": n_eligible,
        "pct_pt": pct_pt * 100,
        "pct_sl": pct_sl * 100,
        "pct_neither": pct_neither * 100,
        "mean_mtm_neither": mean_mtm,
        "expectancy_atr": expectancy,
        "wr_resolved": wr_resolved * 100 if np.isfinite(wr_resolved) else np.nan,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_1m_df()
    atr = compute_atr_wilder(df, ATR_PERIOD)
    close = df["close"].to_numpy()
    openp = df["open"].to_numpy()
    ts    = df["ts_event"].to_numpy()

    rows = []
    for L in STREAK_LENS:
        bull_ends, bear_ends = find_streak_ends(close, openp, ts, L)
        print(f"L={L}: bull_ends={len(bull_ends):,} bear_ends={len(bear_ends):,}",
              flush=True)
        for side, ends in [("bull", bull_ends), ("bear", bear_ends)]:
            # Symmetric brackets
            for x in SYMMETRIC_PT_SL:
                stats = simulate_continuation(
                    df, atr, ends, side, x, x, FORWARD_BARS)
                rows.append({
                    "streak_len": L, "side": side,
                    "PT_atr": x, "SL_atr": x, "scheme": "symmetric",
                    **stats,
                })
            # PT=1.0, vary SL
            for slx in SL_VARIATIONS:
                if slx == 1.0:
                    continue   # already in symmetric set
                stats = simulate_continuation(
                    df, atr, ends, side, PT_FIXED, slx, FORWARD_BARS)
                rows.append({
                    "streak_len": L, "side": side,
                    "PT_atr": PT_FIXED, "SL_atr": slx, "scheme": "PT1_varSL",
                    **stats,
                })

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "streak_length_continuation_scan.csv", index=False)

    print("\n=== SYMMETRIC BRACKETS, CONTINUATION (PT=SL) ===")
    sym = out[out["scheme"] == "symmetric"]
    with pd.option_context("display.max_columns", None,
                           "display.width", 200,
                           "display.float_format", "{:.2f}".format):
        cols = ["streak_len", "side", "PT_atr", "n",
                "pct_pt", "pct_sl", "pct_neither", "wr_resolved",
                "mean_mtm_neither", "expectancy_atr"]
        print(sym[cols].to_string(index=False))

    print("\n=== PT=1.0 ATR, SL VARIATIONS, CONTINUATION ===")
    pt1 = out[out["PT_atr"] == 1.0]
    with pd.option_context("display.max_columns", None,
                           "display.width", 200,
                           "display.float_format", "{:.2f}".format):
        cols = ["streak_len", "side", "SL_atr", "n",
                "pct_pt", "pct_sl", "pct_neither", "wr_resolved",
                "expectancy_atr"]
        print(pt1[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'streak_length_continuation_scan.csv'}")


if __name__ == "__main__":
    main()
