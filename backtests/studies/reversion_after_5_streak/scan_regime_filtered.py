"""Regime-filtered continuation bracket scan, NQ 1m, 2020-2026.

Adds the 1m sticky regime (matches indicators/regime/indicator_v2.py):

  short_ema_high = EMA(3, high)        long_ema_high = EMA(9, high)
  short_ema_low  = EMA(3, low)         long_ema_low  = EMA(9, low)

  regime[i] = +1 if close[i] > short_ema_high[i] AND close[i] > long_ema_high[i]
            = -1 if close[i] < short_ema_low[i]  AND close[i] < long_ema_low[i]
            else regime[i-1]   # sticky

Trade rule (continuation, regime-aligned):
  - Find streak ends (L consecutive bars same close>open / close<open).
  - Require regime[i] matches streak side (+1 for bull, -1 for bear).
  - Bull streak + regime +1  -> enter LONG  at close[i].
  - Bear streak + regime -1  -> enter SHORT at close[i].

Bracket grid:
  Symmetric        : PT=SL in {0.5, 1.0, 1.5}      (R/R = 1)
  Asymmetric (>1:1): (PT, SL) in {(1.5, 1.0), (2.0, 1.0), (2.0, 1.5),
                                  (3.0, 1.0), (3.0, 2.0)}

Resolution: intra-bar OHLC, max 10 forward bars, SL-first tie convention.

Per-year stability is reported for every (L, side, PT, SL).

Output:
  studies/reversion_after_5_streak/results/regime_filtered_continuation.csv
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
FORWARD_BARS = 10
STREAK_LENS = [2, 3, 4, 5]
SYMMETRIC = [0.5, 1.0, 1.5]
ASYMMETRIC = [(1.5, 1.0), (2.0, 1.0), (2.0, 1.5), (3.0, 1.0), (3.0, 2.0)]
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


def compute_regime(df: pd.DataFrame) -> np.ndarray:
    """Sticky 1m regime per indicator_v2.py rule."""
    high = df["high"]; low = df["low"]; close = df["close"]
    sH = high.ewm(span=EMA_SHORT, adjust=False).mean().to_numpy()
    lH = high.ewm(span=EMA_LONG,  adjust=False).mean().to_numpy()
    sL = low.ewm(span=EMA_SHORT,  adjust=False).mean().to_numpy()
    lL = low.ewm(span=EMA_LONG,   adjust=False).mean().to_numpy()
    c = close.to_numpy()
    n = len(df)
    regime = np.zeros(n, dtype=np.int8)
    cur = 0
    for i in range(n):
        if c[i] > sH[i] and c[i] > lH[i]:
            cur = 1
        elif c[i] < sL[i] and c[i] < lL[i]:
            cur = -1
        regime[i] = cur
    return regime


def session_of_close_ct(ts_init_ns):
    dt = pd.to_datetime(ts_init_ns, unit="ns", utc=True).tz_convert("America/Chicago")
    minutes = dt.hour * 60 + dt.minute
    rth = (minutes >= 8 * 60 + 30) & (minutes < 15 * 60)
    return np.where(rth, "RTH", "ETH")


def find_streak_ends(close, openp, ts, streak_len):
    bull = (close > openp); bear = (close < openp)
    consec = np.zeros(len(close), dtype=bool)
    consec[1:] = (ts[1:] - ts[:-1]) == 60_000_000_000
    bull_ends, bear_ends = [], []
    n = len(close)
    if n < streak_len:
        return np.array([], int), np.array([], int)
    for i in range(streak_len - 1, n):
        slc = slice(i - streak_len + 1, i + 1)
        gap_ok = (consec[i - streak_len + 2:i + 1].all()
                  if streak_len > 1 else True)
        if not gap_ok:
            continue
        if bull[slc].all():
            bull_ends.append(i)
        elif bear[slc].all():
            bear_ends.append(i)
    return np.array(bull_ends, int), np.array(bear_ends, int)


def per_trade_outcomes(df, atr, regime, ends, side, pt, sl, forward_bars):
    """Continuation, with regime alignment filter."""
    long_side = (side == "bull")
    desired_regime = +1 if long_side else -1
    close = df["close"].to_numpy()
    high  = df["high"].to_numpy()
    low   = df["low"].to_numpy()
    ts    = df["ts_event"].to_numpy()
    sess  = session_of_close_ct(df["ts_init"].to_numpy())
    years = pd.to_datetime(df["ts_init"].to_numpy(), unit="ns", utc=True)\
              .tz_convert("America/Chicago").year.to_numpy()

    out_year, out_atr, out_kind = [], [], []
    for i in ends:
        if i + forward_bars >= len(close):
            continue
        if regime[i] != desired_regime:
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        ok = True
        for k in range(1, forward_bars + 1):
            if ts[i + k] - ts[i + k - 1] != 60_000_000_000:
                ok = False; break
            if sess[i + k] != sess[i]:
                ok = False; break
        if not ok:
            continue
        c0 = close[i]
        if long_side:
            pt_px = c0 + pt * a; sl_px = c0 - sl * a
        else:
            pt_px = c0 - pt * a; sl_px = c0 + sl * a
        kind = "neither"; outcome_atr = 0.0
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
        out_year.append(int(years[i]))
        out_atr.append(outcome_atr)
        out_kind.append(kind)
    return np.array(out_year), np.array(out_atr), np.array(out_kind)


def bootstrap_ci(arr, n_boot=N_BOOTSTRAP, seed=RNG_SEED, ci=(0.025, 0.975)):
    if len(arr) < 5:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(np.quantile(means, ci[0])), float(np.quantile(means, ci[1]))


def aggregate(year_arr, atr_arr, kind_arr):
    n = len(atr_arr)
    if n == 0:
        return None
    pt = (kind_arr == "pt").sum(); sl = (kind_arr == "sl").sum()
    n_resolved = pt + sl
    return {
        "n": n,
        "pct_pt": pt / n * 100,
        "pct_sl": sl / n * 100,
        "pct_neither": (kind_arr == "neither").mean() * 100,
        "wr_resolved": (pt / n_resolved * 100) if n_resolved else np.nan,
        "E_atr": atr_arr.mean(),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_1m_df()
    atr = compute_atr_wilder(df, ATR_PERIOD)
    regime = compute_regime(df)
    print(f"Regime distribution: +1={int((regime==1).sum()):,}  "
          f"-1={int((regime==-1).sum()):,}  0={int((regime==0).sum()):,}",
          flush=True)
    close = df["close"].to_numpy()
    openp = df["open"].to_numpy()
    ts    = df["ts_event"].to_numpy()

    rows = []
    bracket_grid = [(x, x) for x in SYMMETRIC] + ASYMMETRIC

    for L in STREAK_LENS:
        bull_ends, bear_ends = find_streak_ends(close, openp, ts, L)
        for side, ends in [("bull", bull_ends), ("bear", bear_ends)]:
            for pt, sl in bracket_grid:
                yr, oat, kk = per_trade_outcomes(
                    df, atr, regime, ends, side, pt, sl, FORWARD_BARS)
                # Pooled
                agg = aggregate(yr, oat, kk)
                if agg is None or agg["n"] == 0:
                    continue
                lo, hi = bootstrap_ci(oat)
                rows.append({
                    "L": L, "side": side, "year": "ALL",
                    "PT_atr": pt, "SL_atr": sl, "RR": pt / sl,
                    **agg, "ci_lo": lo, "ci_hi": hi,
                    "ci_pos": int(lo > 0),
                })
                # Per-year
                for y in sorted(set(yr.tolist())):
                    m = yr == y
                    sub_a = oat[m]; sub_k = kk[m]
                    a2 = aggregate(yr[m], sub_a, sub_k)
                    lo2, hi2 = bootstrap_ci(sub_a)
                    rows.append({
                        "L": L, "side": side, "year": int(y),
                        "PT_atr": pt, "SL_atr": sl, "RR": pt / sl,
                        **a2, "ci_lo": lo2, "ci_hi": hi2,
                        "ci_pos": int(lo2 > 0),
                    })

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "regime_filtered_continuation.csv", index=False)

    # Pooled view: top of grid
    print("\n=== POOLED (2020-2026 YTD) — all (L, side, PT, SL) ===")
    pooled = out[out["year"] == "ALL"].copy()
    pooled = pooled.sort_values(["L", "side", "PT_atr", "SL_atr"])
    with pd.option_context("display.max_columns", None,
                           "display.width", 220,
                           "display.float_format", "{:.3f}".format):
        cols = ["L", "side", "PT_atr", "SL_atr", "RR", "n",
                "pct_pt", "pct_sl", "pct_neither", "wr_resolved",
                "E_atr", "ci_lo", "ci_hi", "ci_pos"]
        print(pooled[cols].to_string(index=False))

    # Promising rows: pooled E_atr > 0 (sorted by E_atr desc)
    promising = pooled[pooled["E_atr"] > 0].sort_values("E_atr", ascending=False)
    print("\n=== POOLED ROWS WITH POSITIVE EXPECTANCY (sorted) ===")
    if len(promising):
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.float_format", "{:.3f}".format):
            cols = ["L", "side", "PT_atr", "SL_atr", "RR", "n",
                    "wr_resolved", "E_atr", "ci_lo", "ci_hi", "ci_pos"]
            print(promising[cols].to_string(index=False))
    else:
        print("  (none)")

    # Per-year for top-3 by pooled E_atr that also have ci_pos==1
    top = pooled[pooled["ci_pos"] == 1].sort_values("E_atr", ascending=False).head(5)
    if len(top) == 0:
        print("\n=== NO POOLED ROWS WITH 95% CI > 0 ===")
        # Fall back: top 5 by E_atr
        top = pooled.sort_values("E_atr", ascending=False).head(5)

    print(f"\n=== PER-YEAR DETAIL FOR TOP-{len(top)} POOLED CANDIDATES ===")
    for _, r in top.iterrows():
        L, side = r["L"], r["side"]
        pt, sl = r["PT_atr"], r["SL_atr"]
        sub = out[(out["L"] == L) & (out["side"] == side)
                  & (out["PT_atr"] == pt) & (out["SL_atr"] == sl)
                  & (out["year"] != "ALL")].copy()
        sub["year"] = sub["year"].astype(int)
        sub = sub.sort_values("year")
        print(f"\n--- L={L} {side} PT={pt} SL={sl} (RR={r['RR']:.2f}) ---")
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.float_format", "{:.3f}".format):
            cols = ["year", "n", "wr_resolved", "E_atr",
                    "ci_lo", "ci_hi", "ci_pos"]
            print(sub[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'regime_filtered_continuation.csv'}")


if __name__ == "__main__":
    main()
