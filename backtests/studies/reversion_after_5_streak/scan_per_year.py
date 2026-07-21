"""Per-year stability check for continuation brackets.

Runs continuation simulation (bull streak -> long, bear streak -> short)
with PT=SL=1.0 ATR symmetric bracket, max hold 10 bars, intra-bar OHLC,
SL-first tie convention. Splits results by calendar year of streak end
(ts_init in America/Chicago) across 2020-01-01 to 2026-04-30.

Outputs per-(L, side, year): n, PT-first %, SL-first %, expectancy ATR,
bootstrap 95% CI on expectancy.

Output:
  studies/reversion_after_5_streak/results/per_year_continuation.csv
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
FORWARD_BARS = 10
STREAK_LENS = [6, 7, 8, 9, 10]
PT = 1.0
SL = 1.0
N_BOOTSTRAP = 1000
RNG_SEED = 42
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


def find_streak_ends(close, openp, ts, streak_len):
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


def per_trade_outcomes(df, atr, ends, side, pt, sl, forward_bars):
    """Return per-trade (year, outcome_atr) for continuation trades.
    outcome_atr: +pt for PT-first, -sl for SL-first, mtm/atr for neither."""
    long_side = (side == "bull")
    close = df["close"].to_numpy()
    high  = df["high"].to_numpy()
    low   = df["low"].to_numpy()
    ts    = df["ts_event"].to_numpy()
    sess  = session_of_close_ct(df["ts_init"].to_numpy())
    ts_init_dt = pd.to_datetime(df["ts_init"].to_numpy(), unit="ns", utc=True)\
                   .tz_convert("America/Chicago")
    years = ts_init_dt.year.to_numpy()

    out_year, out_atr, out_kind = [], [], []
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

        c0 = close[i]
        if long_side:
            pt_px = c0 + pt * a; sl_px = c0 - sl * a
        else:
            pt_px = c0 - pt * a; sl_px = c0 + sl * a

        kind = "neither"
        outcome_atr = 0.0
        for k in range(1, forward_bars + 1):
            bh = high[i + k]; bl = low[i + k]
            if long_side:
                pt_t = bh >= pt_px; sl_t = bl <= sl_px
            else:
                pt_t = bl <= pt_px; sl_t = bh >= sl_px
            if sl_t:
                kind = "sl"; outcome_atr = -sl; break
            if pt_t:
                kind = "pt"; outcome_atr = +pt; break
        if kind == "neither":
            c_end = close[i + forward_bars]
            mtm = ((c_end - c0) if long_side else (c0 - c_end)) / a
            outcome_atr = mtm
        out_year.append(years[i])
        out_atr.append(outcome_atr)
        out_kind.append(kind)
    return (np.array(out_year), np.array(out_atr), np.array(out_kind))


def bootstrap_ci(arr, n_boot=N_BOOTSTRAP, seed=RNG_SEED, ci=(0.025, 0.975)):
    if len(arr) < 5:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(np.quantile(means, ci[0])), float(np.quantile(means, ci[1]))


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
        for side, ends in [("bull", bull_ends), ("bear", bear_ends)]:
            yr, oat, kind = per_trade_outcomes(df, atr, ends, side, PT, SL, FORWARD_BARS)
            for y in sorted(set(yr.tolist())):
                mask = yr == y
                sub = oat[mask]
                kk = kind[mask]
                if len(sub) == 0:
                    continue
                lo, hi = bootstrap_ci(sub)
                rows.append({
                    "L": L, "side": side, "year": int(y),
                    "n": len(sub),
                    "pct_pt": (kk == "pt").mean() * 100,
                    "pct_sl": (kk == "sl").mean() * 100,
                    "pct_neither": (kk == "neither").mean() * 100,
                    "wr_resolved": ((kk == "pt").sum() / max((kk != "neither").sum(), 1)) * 100,
                    "E_atr": sub.mean(),
                    "E_atr_ci_lo": lo,
                    "E_atr_ci_hi": hi,
                    "ci_pos": int(lo > 0),
                })
            # Also pooled across years for context
            lo, hi = bootstrap_ci(oat)
            rows.append({
                "L": L, "side": side, "year": "ALL",
                "n": len(oat),
                "pct_pt": (kind == "pt").mean() * 100,
                "pct_sl": (kind == "sl").mean() * 100,
                "pct_neither": (kind == "neither").mean() * 100,
                "wr_resolved": ((kind == "pt").sum() / max((kind != "neither").sum(), 1)) * 100,
                "E_atr": oat.mean(),
                "E_atr_ci_lo": lo,
                "E_atr_ci_hi": hi,
                "ci_pos": int(lo > 0),
            })

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "per_year_continuation.csv", index=False)

    print("\n=== PER-YEAR EXPECTANCY (PT=SL=1.0 ATR, continuation) ===")
    with pd.option_context("display.max_columns", None,
                           "display.width", 220,
                           "display.float_format", "{:.3f}".format):
        cols = ["L", "side", "year", "n", "wr_resolved",
                "E_atr", "E_atr_ci_lo", "E_atr_ci_hi", "ci_pos"]
        for L in STREAK_LENS:
            for side in ["bull", "bear"]:
                sub = out[(out["L"] == L) & (out["side"] == side)]
                if not len(sub):
                    continue
                print(f"\n--- L={L} {side} ---")
                print(sub[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'per_year_continuation.csv'}")


if __name__ == "__main__":
    main()
