"""RTH/ETH split for the long-fade after L bear bars in bear regime trade.

Same trade rule as scan_fade_bear_in_bear_regime.py. Splits results by
session (RTH = 08:30-15:00 CT, ETH = otherwise) at the streak end and
forward window.

Causal-by-construction notes:
  - All forward-window resolution uses bars [i+1..i+FORWARD_BARS]; entry
    state (close_i, atr_i, regime_i, session_i) is fixed at the streak
    end and not modified afterward.
  - ATR is Wilder's, computed strictly from completed bars [0..i] (no
    centering, no future inclusion).
  - Regime EMAs use pandas .ewm(adjust=False) which is recursive and
    only sees [0..i] at index i.
  - All forward bars must be 60s-consecutive AND in the same session
    bucket as the streak end (already filtered).

Output:
  studies/reversion_after_5_streak/results/fade_bear_rth_split.csv
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
# Bracket grid focused on candidates that pooled positive previously
BRACKET_GRID = [
    (1.0, 1.0),   # symmetric 1:1
    (1.5, 1.0),   # >1:1 RR (user's primary ask)
    (1.0, 1.5),   # fade-typical, wider stop
    (1.0, 2.0),   # fade-typical, wider stop
    (2.0, 1.0),   # >1:1 RR aggressive
    (0.5, 1.0),   # tight target, fast exit
]
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
    # Sort by ts_init (close time) - canonical NT order. For uniform 1m bars
    # in this catalog ts_init = ts_event + 60s, so this matches the OPEN
    # ordering identically while making the temporal-order intent explicit.
    return df.sort_values("ts_init").reset_index(drop=True)


def compute_atr_wilder(df, period):
    """Wilder's ATR. Causal: tr[i] uses prev_close[i-1] only."""
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
    """Sticky 1m regime per indicators/regime/indicator_v2.py.
    Uses pandas .ewm(adjust=False) which is the standard recursive EMA -
    only sees data [0..i] at index i."""
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
    """Long fade after bear streak; returns per-trade arrays.

    Non-overlapping rule (per audit C3): once an entry is taken at index
    i, the next eligible candidate must have index >= i + forward_bars + 1.
    This both reflects realistic single-position-at-a-time live behavior
    and produces statistically independent observations for the bootstrap.
    """
    close = df["close"].to_numpy()
    high  = df["high"].to_numpy()
    low   = df["low"].to_numpy()
    ts    = df["ts_init"].to_numpy()  # close-time (canonical NT) for gap check
    sess  = session_of_close_ct(df["ts_init"].to_numpy())
    years = pd.to_datetime(df["ts_init"].to_numpy(), unit="ns", utc=True)\
              .tz_convert("America/Chicago").year.to_numpy()
    out_year, out_sess, out_atr, out_kind = [], [], [], []
    last_taken = -10**12     # well before any valid index
    for i in ends:
        if i <= last_taken + forward_bars:
            continue          # overlap with prior accepted entry
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
        pt_px = c0 + pt * a
        sl_px = c0 - sl * a
        kind = "neither"; outcome_atr = 0.0
        for k in range(1, forward_bars + 1):
            bh = high[i + k]; bl = low[i + k]
            pt_t = bh >= pt_px
            sl_t = bl <= sl_px
            # Same-bar tie: SL first (conservative).
            if sl_t:
                kind = "sl"; outcome_atr = -sl; break
            if pt_t:
                kind = "pt"; outcome_atr = +pt; break
        if kind == "neither":
            c_end = close[i + forward_bars]
            mtm = (c_end - c0) / a
            outcome_atr = mtm
        out_year.append(int(years[i]))
        out_sess.append(str(sess[i]))
        out_atr.append(outcome_atr)
        out_kind.append(kind)
        last_taken = i
    return (np.array(out_year), np.array(out_sess),
            np.array(out_atr), np.array(out_kind))


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
    # Use ts_init (close-time) consistently with per_trade_long_fade so the
    # 60s gap check semantics match across helpers.
    ts    = df["ts_init"].to_numpy()

    rows = []
    for L in STREAK_LENS:
        ends = find_bear_streak_ends(close, openp, ts, L)
        for pt, sl in BRACKET_GRID:
            yr, ss, oat, kk = per_trade_long_fade(
                df, atr, regime, ends, pt, sl, FORWARD_BARS)
            if len(oat) == 0:
                continue
            for sess_label in ("ALL", "RTH", "ETH"):
                if sess_label == "ALL":
                    mask = np.ones(len(ss), dtype=bool)
                else:
                    mask = ss == sess_label
                sub_a = oat[mask]; sub_k = kk[mask]; sub_y = yr[mask]
                agg = aggregate(sub_a, sub_k)
                if agg is None or agg["n"] == 0:
                    continue
                lo, hi = bootstrap_ci(sub_a)
                rows.append({
                    "L": L, "session": sess_label, "year": "ALL",
                    "PT_atr": pt, "SL_atr": sl, "RR": pt / sl,
                    **agg, "ci_lo": lo, "ci_hi": hi,
                    "ci_pos": int(lo > 0),
                })
                for y in sorted(set(sub_y.tolist())):
                    m2 = sub_y == y
                    a2 = aggregate(sub_a[m2], sub_k[m2])
                    if a2 is None or a2["n"] == 0:
                        continue
                    lo2, hi2 = bootstrap_ci(sub_a[m2])
                    rows.append({
                        "L": L, "session": sess_label, "year": int(y),
                        "PT_atr": pt, "SL_atr": sl, "RR": pt / sl,
                        **a2, "ci_lo": lo2, "ci_hi": hi2,
                        "ci_pos": int(lo2 > 0),
                    })

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "fade_bear_rth_split.csv", index=False)

    # Pooled by session
    print("\n=== POOLED 2020-2026 BY SESSION ===")
    pooled = out[out["year"] == "ALL"].sort_values(
        ["L", "session", "PT_atr", "SL_atr"])
    with pd.option_context("display.max_columns", None,
                           "display.width", 220,
                           "display.float_format", "{:.3f}".format):
        cols = ["L", "session", "PT_atr", "SL_atr", "RR", "n",
                "pct_pt", "pct_sl", "wr_resolved",
                "E_atr", "ci_lo", "ci_hi", "ci_pos"]
        print(pooled[cols].to_string(index=False))

    # RTH only - per year for top brackets
    print("\n=== PER-YEAR FOR RTH-ONLY (top pooled by E_atr) ===")
    rth_pooled = out[(out["year"] == "ALL") & (out["session"] == "RTH")]
    rth_top = rth_pooled.sort_values("E_atr", ascending=False).head(8)
    for _, r in rth_top.iterrows():
        L = int(r["L"]); pt = r["PT_atr"]; sl = r["SL_atr"]
        sub = out[(out["L"] == L) & (out["session"] == "RTH")
                  & (out["PT_atr"] == pt) & (out["SL_atr"] == sl)
                  & (out["year"] != "ALL")].copy()
        sub["year"] = sub["year"].astype(int)
        sub = sub.sort_values("year")
        print(f"\n--- L={L} PT={pt} SL={sl} RTH "
              f"pooled E={r['E_atr']:.4f} CI=[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}] ---")
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.float_format", "{:.3f}".format):
            cols = ["year", "n", "wr_resolved", "E_atr",
                    "ci_lo", "ci_hi", "ci_pos"]
            print(sub[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'fade_bear_rth_split.csv'}")


if __name__ == "__main__":
    main()
