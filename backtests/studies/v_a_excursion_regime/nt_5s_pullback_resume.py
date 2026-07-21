"""5s pullback-resume entry within bar1-confirmed 1m regime.

Hypothesis: on a bar1-confirmed 1m flip, a 5s pullback against the 1m
direction followed by a 5s resume *in* the 1m direction is a higher-
quality entry than entering immediately at bar1 close. The pullback
shakes weak hands; the resume confirms the move's continuation.

For each bar1-confirmed NT 1m flip (~45K events 2020-2026):
  1. Start tracking from bar1 close (T + 60s).
  2. Within the 1m regime window (until next 1m regime flip), watch
     the 5s regime.
  3. Find the FIRST transition where 5s flips INTO alignment with the
     1m direction (i.e., previous 5s != d and current 5s == d).
     This is the "pullback then resume" event.
  4. Entry price = close of that 5s bar (observable at 5s bar close).
  5. Outcomes:
        A. Regime-exit: PnL from entry to the (same) 1m regime-exit
           close that the original cohort already had.
        B. +1 / -1 ATR first-touch on 1s bars (unbounded; tie=loss).

Causality: ALL inputs (bar1-confirm, 5s regime sequence) are
observable at decision time. Entry triggers strictly at the 5s
resume bar's close, which is in the future relative to bar1 close.
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

NS = 1_000_000_000
PERIOD_5S_NS = 5 * NS
ATR_PERIOD = 14
ALPHA_EMA3 = 0.5
ALPHA_EMA9 = 0.2

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
PRODUCT_DATA = {
    "NQ": {"raw": {**{y: f"data/raw/NQ_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet"},
            "regime_exit": "studies/v_a_excursion_regime/results_v0/nt_regime_exit_nq.parquet",
            "mult": 20.0},
    "ES": {"raw": {**{y: f"data/raw/ES_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/ES_v0_1s_2026_ytd.parquet"},
            "regime_exit": "studies/v_a_excursion_regime/results_v0/nt_regime_exit_es.parquet",
            "mult": 50.0},
}
PD = PRODUCT_DATA[PRODUCT]
OUT = Path("studies/v_a_excursion_regime/results_v0")
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)


@njit
def compute_5s_regime(h5, l5, c5):
    n = len(c5)
    reg = np.zeros(n, dtype=np.int64)
    e3h = e9h = e3l = e9l = 0.0
    cur = 0
    for i in range(n):
        if i == 0:
            e3h = h5[i]; e9h = h5[i]; e3l = l5[i]; e9l = l5[i]
        else:
            e3h = ALPHA_EMA3 * h5[i] + (1.0 - ALPHA_EMA3) * e3h
            e9h = ALPHA_EMA9 * h5[i] + (1.0 - ALPHA_EMA9) * e9h
            e3l = ALPHA_EMA3 * l5[i] + (1.0 - ALPHA_EMA3) * e3l
            e9l = ALPHA_EMA9 * l5[i] + (1.0 - ALPHA_EMA9) * e9l
        new_reg = cur
        if c5[i] > e3h and c5[i] > e9h:
            new_reg = 1
        elif c5[i] < e3l and c5[i] < e9l:
            new_reg = -1
        reg[i] = new_reg
        cur = new_reg
    return reg


@njit
def race_unbounded(start_ts, anchor_px, d, atr, ts, hi, lo):
    if not (anchor_px == anchor_px) or atr <= 0:
        return -1
    j = np.searchsorted(ts, start_ts, side="left")
    if d == 1:
        tgt, stp = anchor_px + atr, anchor_px - atr
    else:
        tgt, stp = anchor_px - atr, anchor_px + atr
    while j < len(ts):
        h, l = hi[j], lo[j]
        if d == 1:
            ht, hs = h >= tgt, l <= stp
        else:
            ht, hs = l <= tgt, h >= stp
        if ht and hs:
            return 0
        if ht:
            return 1
        if hs:
            return 0
        j += 1
    return -1


def aggregate_5s(bars_1s):
    ts = bars_1s.index.values.astype(np.int64)
    bucket = (ts // PERIOD_5S_NS) * PERIOD_5S_NS
    g = pd.DataFrame({
        "b": bucket,
        "o": bars_1s["open"].values,
        "h": bars_1s["high"].values,
        "l": bars_1s["low"].values,
        "c": bars_1s["close"].values})
    return g.groupby("b").agg(
        o=("o", "first"), h=("h", "max"),
        l=("l", "min"), c=("c", "last"))


def process_year(year, sub):
    """sub = bar1-confirmed flips for this year, with their exit_ts/exit_px."""
    parts = []
    for y in (year - 1, year, year + 1):
        p = PD["raw"].get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["open", "high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    ts_1s = bars.index.values.astype(np.int64)
    o_1s = bars["open"].to_numpy(np.float64)
    h_1s = bars["high"].to_numpy(np.float64)
    l_1s = bars["low"].to_numpy(np.float64)

    five = aggregate_5s(bars)
    ts5 = five.index.values.astype(np.int64)
    o5 = five["o"].to_numpy(np.float64)
    h5 = five["h"].to_numpy(np.float64)
    l5 = five["l"].to_numpy(np.float64)
    c5 = five["c"].to_numpy(np.float64)
    reg5 = compute_5s_regime(h5, l5, c5)

    ets   = sub["entry_ts"].to_numpy(np.int64)
    drs   = sub["signal_direction"].to_numpy(np.int64)
    atrs  = sub["entry_atr"].to_numpy(np.float64)
    exts  = sub["exit_ts"].to_numpy(np.int64)
    expxs = sub["exit_px"].to_numpy(np.float64)
    n = len(sub)

    pb_entry_ts = np.full(n, -1, dtype=np.int64)
    pb_entry_px = np.full(n, np.nan)
    pb_found    = np.zeros(n, dtype=bool)
    pb_lag_s    = np.full(n, np.nan)
    bracket_hit = np.full(n, -1, dtype=np.int64)
    regime_pnl  = np.full(n, np.nan)

    for k in range(n):
        T = int(ets[k]); d = int(drs[k]); atr = float(atrs[k])
        ext_ts = int(exts[k])
        if ext_ts < 0:
            continue
        bar1_close_ts = T + 60 * NS
        # 5s window: from bar1 close to regime exit (exclusive)
        i_lo = np.searchsorted(ts5, bar1_close_ts, side="left")
        i_hi = np.searchsorted(ts5, ext_ts, side="left")  # exclusive
        if i_hi <= i_lo + 1:
            continue
        # Find first transition INTO alignment: prev != d, cur == d
        # We require the FIRST such transition; the prev bar can be 0 or -d
        # (so this covers both "pullback then resume" and "wait then align")
        found_i = -1
        for q in range(i_lo + 1, i_hi):
            if reg5[q] == d and reg5[q - 1] != d:
                found_i = q
                break
        if found_i < 0:
            continue
        pb_found[k]    = True
        pb_entry_ts[k] = ts5[found_i]
        pb_entry_px[k] = c5[found_i]  # close of the resuming 5s bar
        pb_lag_s[k]    = (ts5[found_i] - bar1_close_ts) / NS

        # Regime-exit PnL (close at exit_px)
        regime_pnl[k] = (float(expxs[k]) - pb_entry_px[k]) * d

        # +/- 1 ATR first-touch from pb entry
        # Anchor at pb_entry_px (close of 5s bar at found_i)
        # Race from next 1s bar after that 5s bar close
        race_start = ts5[found_i] + 5 * NS  # start of next 5s window
        bracket_hit[k] = race_unbounded(race_start, pb_entry_px[k],
                                         d, atr, ts_1s, h_1s, l_1s)

    out = pd.DataFrame(index=sub.index)
    out["pb_found"]    = pb_found
    out["pb_entry_ts"] = pb_entry_ts
    out["pb_entry_px"] = pb_entry_px
    out["pb_lag_s"]    = pb_lag_s
    out["bracket_hit"] = bracket_hit
    out["regime_pnl_pts"] = regime_pnl
    return out


def main():
    t0 = time.time()
    print(f"PRODUCT={PRODUCT}")
    re = pd.read_parquet(PD["regime_exit"])
    re["entry_ts"] = re["entry_ts"].astype(np.int64)
    re["signal_direction"] = re["signal_direction"].astype(np.int64)
    print(f"  regime-exit parquet: {len(re):,} rows")
    base = re[re["bar1_confirm"] & re["resolved"]].copy()
    print(f"  bar1-confirm & resolved: {len(base):,}")

    parts = []
    for y in sorted(base["year"].unique()):
        sub = base[base["year"] == y]
        t1 = time.time()
        addl = process_year(int(y), sub)
        parts.append(addl)
        print(f"  {y}: {len(sub):,}  ({time.time()-t1:.0f}s)")
    feats = pd.concat(parts)
    df = pd.concat([base, feats], axis=1)

    out_p = OUT / f"nt_5s_pullback_resume_{PRODUCT.lower()}.parquet"
    df.to_parquet(out_p, index=False)
    print(f"\n  saved {out_p}")

    # ── Report ──
    found = df[df["pb_found"]].copy()
    found["regime_pnl_atr"] = found["regime_pnl_pts"] / found["entry_atr"]
    found["regime_win"] = (found["regime_pnl_pts"] > 0).astype(int)
    found["bracket_win"] = (found["bracket_hit"] == 1).astype(int)
    found["bracket_resolved"] = found["bracket_hit"] >= 0

    print(f"\n{'='*78}")
    print(f"5S PULLBACK-RESUME ENTRY on bar1-confirmed 1m flips ({PRODUCT})")
    print(f"{'='*78}")
    print(f"  bar1-confirmed cohort:           {len(base):,}")
    print(f"  pullback-resume entry FOUND:     {len(found):,}  "
          f"({len(found)/len(base):.1%})")
    print(f"  median lag from bar1 close (s):  "
          f"{found['pb_lag_s'].median():.0f}s")
    print(f"  mean lag from bar1 close (s):    "
          f"{found['pb_lag_s'].mean():.0f}s")

    print(f"\n  ── REGIME-EXIT outcome ──")
    print(f"    win rate:           {found['regime_win'].mean():.1%}")
    print(f"    mean PnL (ATR):    "
          f"{found['regime_pnl_atr'].mean():+.3f}")
    print(f"    median PnL (ATR):  "
          f"{found['regime_pnl_atr'].median():+.3f}")
    mean_atr = found["entry_atr"].mean()
    dollars = found["regime_pnl_atr"].mean() * mean_atr * PD['mult'] - 5
    print(f"    $/trade (net):      {dollars:+.2f}")

    print(f"\n  ── +/-1 ATR first-touch (1s) ──")
    br = found[found["bracket_resolved"]]
    print(f"    resolved:           {len(br):,} / {len(found):,}  "
          f"({len(br)/max(len(found),1):.1%})")
    print(f"    bracket win rate:   {br['bracket_win'].mean():.1%}")
    # $: win = +1 ATR, loss = -1 ATR -1tick slip
    br = br.copy()
    br["bracket_pnl_pts"] = np.where(br["bracket_hit"] == 1,
                                       br["entry_atr"],
                                       -br["entry_atr"] - 0.25)
    br["bracket_pnl_atr"] = br["bracket_pnl_pts"] / br["entry_atr"]
    br_mean_atr = br["entry_atr"].mean()
    br_dollars = br["bracket_pnl_atr"].mean() * br_mean_atr * PD['mult'] - 5
    print(f"    mean PnL (ATR):    "
          f"{br['bracket_pnl_atr'].mean():+.3f}")
    print(f"    $/trade (net, $5 comm + 1tk slip): {br_dollars:+.2f}")

    # By year
    print(f"\n  Year-by-year (REGIME-EXIT):")
    print(f"  {'year':<6}{'n':>6}{'win%':>8}{'meanATR':>10}{'medATR':>10}"
          f"{'$/tr':>10}{'tag':>6}")
    for y in range(2020, 2027):
        g = found[found["year"] == y]
        if len(g) < 5:
            continue
        tag = "IS" if y in IS_YEARS else "OOS"
        ma = g["entry_atr"].mean()
        dol = g["regime_pnl_atr"].mean() * ma * PD['mult'] - 5
        print(f"  {y:<6}{len(g):>6}"
              f"{g['regime_win'].mean():>7.1%}"
              f"{g['regime_pnl_atr'].mean():>+10.3f}"
              f"{g['regime_pnl_atr'].median():>+10.3f}"
              f"{dol:>+10.2f}{tag:>6}")

    print(f"\n  Year-by-year (+1/-1 ATR bracket):")
    print(f"  {'year':<6}{'n':>6}{'win%':>8}{'$/tr':>10}{'tag':>6}")
    for y in range(2020, 2027):
        g = br[br["year"] == y]
        if len(g) < 5:
            continue
        tag = "IS" if y in IS_YEARS else "OOS"
        ma = g["entry_atr"].mean()
        dol = g["bracket_pnl_atr"].mean() * ma * PD['mult'] - 5
        print(f"  {y:<6}{len(g):>6}"
              f"{g['bracket_win'].mean():>7.1%}"
              f"{dol:>+10.2f}{tag:>6}")

    # By direction
    print(f"\n  By direction (REGIME-EXIT):")
    for d, dn in ((1, "long"), (-1, "short")):
        g = found[found["signal_direction"] == d]
        ma = g["entry_atr"].mean()
        dol = g["regime_pnl_atr"].mean() * ma * PD['mult'] - 5
        print(f"    {dn:<6} n={len(g):>5,}  "
              f"win={g['regime_win'].mean():.1%}  "
              f"meanATR={g['regime_pnl_atr'].mean():+.3f}  "
              f"$/tr={dol:+.2f}")

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
