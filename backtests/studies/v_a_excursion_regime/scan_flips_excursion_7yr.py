"""7-year robustness gate for the compression -> flip -> 1ATR idea.

Extends scan_all_flips_1atr.py to 2020-2026.  For every raw 1m regime
flip (v2 collector snapshots), measures the +1.0 ATR / -1.0 ATR
first-touch race on 1s bars (unbounded; anchor = close of the 1s bar
just before the flip signal = flip-bar entry).  Computes the backward
total-excursion features for fast(5m)/medium(15m)/slow(30m) windows.

Gate question: does LOW total_excursion_slow (compression) produce a
higher +1ATR win rate, and does it hold year by year?

Tertile cuts are FIXED from 2020-2022 (IS); win rate is reported by
bucket for every year so 2023-2026 are true OOS.  No NT, no
commission -- a directional robustness screen only.
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
from numba import njit

SNAP = "studies/1m_regime_collector_v2/results/v2_feature_snapshots_{}.parquet"
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
OUT = Path("studies/v_a_excursion_regime/results_v0")
IS_YEARS = (2020, 2021, 2022)


@njit
def scan(signal_times, directions, atrs,
         ts, opens, highs, lows, closes):
    N = len(signal_times)
    tot_fast = np.full(N, np.nan)
    tot_med = np.full(N, np.nan)
    tot_slow = np.full(N, np.nan)
    hit = np.full(N, -1)
    for i in range(N):
        dts = signal_times[i]
        d = directions[i]
        atr = atrs[i]
        i_hi = np.searchsorted(ts, dts, side="left")
        if i_hi == 0 or i_hi >= len(ts) or atr <= 0:
            continue
        anchor = closes[i_hi - 1]
        for w_idx, w_secs in ((0, 300), (1, 900), (2, 1800)):
            i_lo = np.searchsorted(ts, dts - w_secs * 1_000_000_000,
                                   side="left")
            if i_hi - i_lo < 10:
                continue
            w_anchor = opens[i_lo]
            h_max = np.max(highs[i_lo:i_hi])
            l_min = np.min(lows[i_lo:i_hi])
            if d == 1:
                mfe = h_max - w_anchor
                mae = w_anchor - l_min
            else:
                mfe = w_anchor - l_min
                mae = h_max - w_anchor
            tot = mfe + mae
            if w_idx == 0:
                tot_fast[i] = tot
            elif w_idx == 1:
                tot_med[i] = tot
            else:
                tot_slow[i] = tot
        if d == 1:
            tgt, stp = anchor + atr, anchor - atr
        else:
            tgt, stp = anchor - atr, anchor + atr
        j = i_hi
        while j < len(ts):
            h, l = highs[j], lows[j]
            if d == 1:
                ht, hs = h >= tgt, l <= stp
            else:
                ht, hs = l <= tgt, h >= stp
            if ht and hs:
                hit[i] = 0
                break
            if ht:
                hit[i] = 1
                break
            if hs:
                hit[i] = 0
                break
            j += 1
    return tot_fast, tot_med, tot_slow, hit


def load_1s(year):
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["open", "high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars


def process(year):
    fp = Path(SNAP.format(year))
    if not fp.exists():
        return None
    df = pd.read_parquet(fp, columns=["signal_time", "signal_direction",
                                      "atr_at_signal",
                                      "bar1_confirmed_hh_ll"])
    df = df.drop_duplicates(subset=["signal_time",
                                    "signal_direction"]).copy()
    bars = load_1s(year)
    ts = bars.index.astype("int64").to_numpy()
    o = bars["open"].to_numpy(np.float64)
    h = bars["high"].to_numpy(np.float64)
    l = bars["low"].to_numpy(np.float64)
    c = bars["close"].to_numpy(np.float64)
    st = (df["signal_time"].astype("int64").to_numpy()
          if not pd.api.types.is_numeric_dtype(df["signal_time"])
          else df["signal_time"].to_numpy(np.int64))
    dr = df["signal_direction"].to_numpy(np.int64)
    at = df["atr_at_signal"].to_numpy(np.float64)
    tf, tm, tsl, hit = scan(st, dr, at, ts, o, h, l, c)
    df["tot_fast"], df["tot_med"], df["tot_slow"] = tf, tm, tsl
    df["hit"] = hit
    df["year"] = year
    return df[df["hit"] != -1].copy()


def main():
    t0 = time.time()
    dfs = []
    for y in range(2020, 2027):
        d = process(y)
        if d is not None:
            dfs.append(d)
            print(f"  {y}: {len(d):,} flips  win {d['hit'].mean():.2%}")
    df = pd.concat(dfs, ignore_index=True)
    print(f"\nTotal flips 2020-2026: {len(df):,}  "
          f"overall win {df['hit'].mean():.2%}")

    is_df = df[df["year"].isin(IS_YEARS)]
    for feat in ("tot_slow", "tot_med"):
        v = is_df[is_df[feat].notna()]
        c1, c2 = v[feat].quantile([1/3, 2/3]).values
        df[f"{feat}_bkt"] = pd.cut(
            df[feat], [-np.inf, c1, c2, np.inf],
            labels=["low", "mid", "high"])
        print(f"\n{'='*64}")
        print(f"{feat}  (IS 2020-2022 tertile cuts: {c1:.1f}, {c2:.1f})")
        print(f"{'='*64}")
        print(f"  {'year':<7}{'low n':>8}{'low win%':>10}"
              f"{'mid win%':>10}{'high win%':>11}{'low-high':>10}")
        for y in range(2020, 2027):
            g = df[df["year"] == y]
            r = {}
            for b in ("low", "mid", "high"):
                gb = g[g[f"{feat}_bkt"] == b]
                r[b] = (len(gb), gb["hit"].mean() if len(gb) else np.nan)
            tag = " (IS)" if y in IS_YEARS else ""
            print(f"  {y:<7}{r['low'][0]:>8,}{r['low'][1]:>9.1%}"
                  f"{r['mid'][1]:>10.1%}{r['high'][1]:>10.1%}"
                  f"{r['low'][1]-r['high'][1]:>+9.1%}{tag}")

    # low-slow split by direction and bar1-confirm, OOS pooled 2023-2026
    oos = df[df["year"] >= 2023]
    low = oos[oos["tot_slow_bkt"] == "low"]
    print(f"\n{'='*64}")
    print(f"LOW tot_slow, OOS 2023-2026 pooled  (n={len(low):,})")
    print(f"{'='*64}")
    for d, dn in ((1, "long"), (-1, "short")):
        gd = low[low["signal_direction"] == d]
        print(f"  {dn:<6} n={len(gd):>6,}  win {gd['hit'].mean():.1%}")
    for cf, cn in ((True, "bar1-confirmed"), (False, "not confirmed")):
        gc = low[low["bar1_confirmed_hh_ll"] == cf]
        if len(gc):
            print(f"  {cn:<16} n={len(gc):>6,}  win {gc['hit'].mean():.1%}")

    df.to_parquet(OUT / "flips_excursion_7yr.parquet", index=False)
    print(f"\n[done] {time.time()-t0:.0f}s  -> flips_excursion_7yr.parquet")


if __name__ == "__main__":
    main()
