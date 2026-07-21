"""Fade bear streaks in bear regime, NQ 1m, 2020-2026.

Motivation:
  In scan_regime_filtered.py we found that going SHORT (continuation) after
  L bear bars in bear regime is statistically a loser at every bracket
  geometry (n ~600k, 95% CI excludes zero negative). The mirror trade -
  going LONG (fade) under the same conditions - is therefore the candidate
  with positive expectancy. This scan tests it directly.

Trade rule:
  - Find streak ends i where bars [i-L+1..i] all have close < open (bear).
  - Filter: regime[i] == -1 (sticky 1m regime is bear).
  - Enter LONG at close[i].
  - PT favorable (up): close[i] + PT * ATR(14)[i]
  - SL adverse  (down): close[i] - SL * ATR(14)[i]

Bracket grid:
  Symmetric: PT=SL in {0.25, 0.5, 1.0, 1.5}
  Fade-typical (PT < SL):     (0.25, 0.5), (0.25, 1.0),
                               (0.5, 1.0), (0.5, 1.5),
                               (1.0, 1.5), (1.0, 2.0)
  Greater-than-1:1 RR (PT > SL): (1.5, 1.0), (2.0, 1.0), (2.0, 1.5)

Resolution: intra-bar OHLC, max 10 bars hold, SL-first same-bar tie.
Session: forward bars must be 60s-consecutive AND in the same session as
streak end (RTH 08:30-15:00 CT, else ETH).

Output:
  studies/reversion_after_5_streak/results/fade_bear_in_bear_regime.csv
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
SYMMETRIC = [0.25, 0.5, 1.0, 1.5]
FADE_TYPICAL = [(0.25, 0.5), (0.25, 1.0), (0.5, 1.0), (0.5, 1.5),
                (1.0, 1.5), (1.0, 2.0)]
GT_1_TO_1 = [(1.5, 1.0), (2.0, 1.0), (2.0, 1.5)]
N_BOOTSTRAP = 1000
RNG_SEED = 42
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


def compute_regime(df):
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


def find_bear_streak_ends(close, openp, ts, streak_len):
    bear = (close < openp)
    consec = np.zeros(len(close), dtype=bool)
    consec[1:] = (ts[1:] - ts[:-1]) == 60_000_000_000
    ends = []
    n = len(close)
    if n < streak_len:
        return np.array([], int)
    for i in range(streak_len - 1, n):
        slc = slice(i - streak_len + 1, i + 1)
        gap_ok = (consec[i - streak_len + 2:i + 1].all()
                  if streak_len > 1 else True)
        if not gap_ok:
            continue
        if bear[slc].all():
            ends.append(i)
    return np.array(ends, int)


def per_trade_long_fade(df, atr, regime, ends, pt, sl, forward_bars):
    """LONG fade after bear streak. PT above entry (favorable), SL below."""
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
        if regime[i] != -1:
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
        pt_px = c0 + pt * a   # long fade: favorable up
        sl_px = c0 - sl * a   # long fade: adverse down
        kind = "neither"; outcome_atr = 0.0
        for k in range(1, forward_bars + 1):
            bh = high[i + k]; bl = low[i + k]
            pt_t = bh >= pt_px
            sl_t = bl <= sl_px
            if sl_t:
                kind = "sl"; outcome_atr = -sl; break
            if pt_t:
                kind = "pt"; outcome_atr = +pt; break
        if kind == "neither":
            c_end = close[i + forward_bars]
            mtm = (c_end - c0) / a
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


def aggregate(atr_arr, kind_arr):
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
    close = df["close"].to_numpy()
    openp = df["open"].to_numpy()
    ts    = df["ts_event"].to_numpy()

    rows = []
    bracket_grid = ([(x, x) for x in SYMMETRIC]
                    + FADE_TYPICAL + GT_1_TO_1)

    for L in STREAK_LENS:
        ends = find_bear_streak_ends(close, openp, ts, L)
        for pt, sl in bracket_grid:
            yr, oat, kk = per_trade_long_fade(
                df, atr, regime, ends, pt, sl, FORWARD_BARS)
            agg = aggregate(oat, kk)
            if agg is None or agg["n"] == 0:
                continue
            lo, hi = bootstrap_ci(oat)
            rows.append({
                "L": L, "year": "ALL",
                "PT_atr": pt, "SL_atr": sl, "RR": pt / sl,
                **agg, "ci_lo": lo, "ci_hi": hi,
                "ci_pos": int(lo > 0),
            })
            for y in sorted(set(yr.tolist())):
                m = yr == y
                a2 = aggregate(oat[m], kk[m])
                lo2, hi2 = bootstrap_ci(oat[m])
                rows.append({
                    "L": L, "year": int(y),
                    "PT_atr": pt, "SL_atr": sl, "RR": pt / sl,
                    **a2, "ci_lo": lo2, "ci_hi": hi2,
                    "ci_pos": int(lo2 > 0),
                })

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "fade_bear_in_bear_regime.csv", index=False)

    pooled = out[out["year"] == "ALL"].sort_values(
        ["L", "PT_atr", "SL_atr"]).copy()
    pooled["dollars_per_trade"] = pooled["E_atr"] * 200   # rough: ATR ~10pt * $20 mult

    print("\n=== POOLED 2020-2026 (long fade after bear streak in bear regime) ===")
    with pd.option_context("display.max_columns", None,
                           "display.width", 220,
                           "display.float_format", "{:.3f}".format):
        cols = ["L", "PT_atr", "SL_atr", "RR", "n",
                "pct_pt", "pct_sl", "pct_neither", "wr_resolved",
                "E_atr", "ci_lo", "ci_hi", "ci_pos"]
        print(pooled[cols].to_string(index=False))

    # Sort positive pooled rows
    pos = pooled[pooled["E_atr"] > 0].sort_values("E_atr", ascending=False)
    print("\n=== POOLED ROWS WITH POSITIVE EXPECTANCY (sorted) ===")
    if len(pos):
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.float_format", "{:.3f}".format):
            cols = ["L", "PT_atr", "SL_atr", "RR", "n",
                    "wr_resolved", "E_atr", "ci_lo", "ci_hi", "ci_pos"]
            print(pos[cols].to_string(index=False))
    else:
        print("  (none)")

    # Per-year detail for top candidates with positive 95% CI
    sig = pooled[pooled["ci_pos"] == 1].sort_values("E_atr", ascending=False)
    if len(sig) == 0:
        print("\n=== NO POOLED ROWS WITH 95% CI > 0 ===")
        sig = pooled.sort_values("E_atr", ascending=False).head(8)
    else:
        sig = sig.head(10)

    print(f"\n=== PER-YEAR DETAIL FOR TOP CANDIDATES (n={len(sig)}) ===")
    for _, r in sig.iterrows():
        L = int(r["L"]); pt = r["PT_atr"]; sl = r["SL_atr"]
        sub = out[(out["L"] == L) & (out["PT_atr"] == pt)
                  & (out["SL_atr"] == sl) & (out["year"] != "ALL")].copy()
        sub["year"] = sub["year"].astype(int)
        sub = sub.sort_values("year")
        n_pos_yr = int((sub["E_atr"] > 0).sum())
        n_total_yr = len(sub)
        n_ci_pos = int(sub["ci_pos"].sum())
        print(f"\n--- L={L} PT={pt} SL={sl} (RR={r['RR']:.2f}) "
              f"pooled E={r['E_atr']:.4f} CI=[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}] "
              f"| {n_pos_yr}/{n_total_yr} years E>0, {n_ci_pos} years 95%CI>0 ---")
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.float_format", "{:.3f}".format):
            cols = ["year", "n", "wr_resolved", "E_atr",
                    "ci_lo", "ci_hi", "ci_pos"]
            print(sub[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'fade_bear_in_bear_regime.csv'}")


if __name__ == "__main__":
    main()
