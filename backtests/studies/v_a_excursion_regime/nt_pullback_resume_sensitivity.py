"""5s/10s/15s micro-regime pullback-resume sensitivity.

Tests whether the prior 5s pullback-resume null was due to the 5s regime
being too noisy. Same universe (bar1-confirmed 1m flips), same exits
(regime-exit + 1ATR bracket); only the micro-regime definition varies.

Six configs:
  1. 5s  EMA3/9   (alpha 0.5 / 0.2)     — baseline (prior null)
  2. 5s  EMA13/20 (alpha 2/14 / 2/21)   — slower 5s
  3. 5s  EMA3/13                         — fast + slow blend
  4. 5s  EMA3/20                         — fast + slowest
  5. 10s EMA13/20                        — slower TF, slower EMAs
  6. 15s EMA13/20                        — slowest TF + EMAs

Pullback-quality filters (added vs prior run):
  - counter-regime must last >= 2 bars
  - counter move magnitude >= 0.25 * entry_atr (in PRICE points)
  - resume bar must close in the 1m direction (close > open for long)

Success criterion (user-specified):
  - Trigger frequency drops meaningfully (target: 20-50% from prior 91%)
  - AND regime-exit win/EV improves vs prior 33.6% / -$5.78/tr

If a config triggers on >70% of cohort with no EV improvement, kill it.
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

# Pullback-quality filter parameters
MIN_COUNTER_BARS = 2       # counter-regime persists ≥ 2 bars
MIN_COUNTER_ATR  = 0.25    # counter move magnitude ≥ 0.25 ATR (in pts)

CONFIGS = [
    ("5s_3_9",    5,  0.5,        0.2),
    ("5s_13_20",  5,  2.0/14.0,   2.0/21.0),
    ("5s_3_13",   5,  0.5,        2.0/14.0),
    ("5s_3_20",   5,  0.5,        2.0/21.0),
    ("10s_13_20", 10, 2.0/14.0,   2.0/21.0),
    ("15s_13_20", 15, 2.0/14.0,   2.0/21.0),
]


@njit
def compute_regime(h, l, c, alpha_fast, alpha_slow):
    n = len(c)
    reg = np.zeros(n, dtype=np.int64)
    e3h = e9h = e3l = e9l = 0.0
    cur = 0
    for i in range(n):
        if i == 0:
            e3h = h[i]; e9h = h[i]; e3l = l[i]; e9l = l[i]
        else:
            e3h = alpha_fast * h[i] + (1.0 - alpha_fast) * e3h
            e9h = alpha_slow * h[i] + (1.0 - alpha_slow) * e9h
            e3l = alpha_fast * l[i] + (1.0 - alpha_fast) * e3l
            e9l = alpha_slow * l[i] + (1.0 - alpha_slow) * e9l
        new_reg = cur
        if c[i] > e3h and c[i] > e9h:
            new_reg = 1
        elif c[i] < e3l and c[i] < e9l:
            new_reg = -1
        reg[i] = new_reg
        cur = new_reg
    return reg


@njit
def find_pullback_resume(reg, h, l, o, c,
                         start_idx, end_idx,
                         direction, atr,
                         min_counter_bars, min_counter_atr):
    """Find first qualifying pullback-resume in [start_idx, end_idx).

    Returns (entry_idx, counter_bars, counter_move_pts) or (-1, 0, 0).
    """
    counter_start = -1
    counter_extreme = 0.0
    counter_anchor = 0.0

    # Initialize: handle case where we START in counter regime
    if start_idx < end_idx and reg[start_idx] != direction:
        counter_start = start_idx
        # anchor = close of last aligned bar before counter; if none, use start bar's open
        if start_idx > 0:
            counter_anchor = c[start_idx - 1]
        else:
            counter_anchor = o[start_idx]
        if direction == 1:
            counter_extreme = l[start_idx]
        else:
            counter_extreme = h[start_idx]

    for q in range(start_idx + 1, end_idx):
        if reg[q] != direction:
            if counter_start < 0:
                counter_start = q
                counter_anchor = c[q - 1]
                if direction == 1:
                    counter_extreme = l[q]
                else:
                    counter_extreme = h[q]
            else:
                if direction == 1:
                    if l[q] < counter_extreme:
                        counter_extreme = l[q]
                else:
                    if h[q] > counter_extreme:
                        counter_extreme = h[q]
        else:
            # reg[q] == direction
            if counter_start < 0:
                continue
            counter_len = q - counter_start
            if direction == 1:
                counter_move = counter_anchor - counter_extreme
                close_in_trend = c[q] > o[q]
            else:
                counter_move = counter_extreme - counter_anchor
                close_in_trend = c[q] < o[q]
            if (counter_len >= min_counter_bars
                    and counter_move >= min_counter_atr * atr
                    and close_in_trend):
                return q, counter_len, counter_move
            counter_start = -1  # reset; this trend bar interrupted counter
    return -1, 0, 0.0


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


def aggregate_k_seconds(bars_1s, k_sec):
    ts = bars_1s.index.values.astype(np.int64)
    bucket = (ts // (k_sec * NS)) * (k_sec * NS)
    g = pd.DataFrame({
        "b": bucket,
        "o": bars_1s["open"].values,
        "h": bars_1s["high"].values,
        "l": bars_1s["low"].values,
        "c": bars_1s["close"].values})
    return g.groupby("b").agg(
        o=("o", "first"), h=("h", "max"),
        l=("l", "min"), c=("c", "last"))


def run_config_on_year(name, k_sec, alpha_fast, alpha_slow,
                       sub, bars_1s):
    """sub = bar1-confirmed cohort for this year (with exit_ts/px)."""
    ts_1s = bars_1s.index.values.astype(np.int64)
    h_1s = bars_1s["high"].to_numpy(np.float64)
    l_1s = bars_1s["low"].to_numpy(np.float64)
    agg = aggregate_k_seconds(bars_1s, k_sec)
    ts_k = agg.index.values.astype(np.int64)
    o_k = agg["o"].to_numpy(np.float64)
    h_k = agg["h"].to_numpy(np.float64)
    l_k = agg["l"].to_numpy(np.float64)
    c_k = agg["c"].to_numpy(np.float64)
    reg_k = compute_regime(h_k, l_k, c_k, alpha_fast, alpha_slow)

    ets   = sub["entry_ts"].to_numpy(np.int64)
    drs   = sub["signal_direction"].to_numpy(np.int64)
    atrs  = sub["entry_atr"].to_numpy(np.float64)
    exts  = sub["exit_ts"].to_numpy(np.int64)
    expxs = sub["exit_px"].to_numpy(np.float64)
    n = len(sub)

    pb_found    = np.zeros(n, dtype=bool)
    pb_entry_ts = np.full(n, -1, dtype=np.int64)
    pb_entry_px = np.full(n, np.nan)
    pb_lag_s    = np.full(n, np.nan)
    counter_len = np.full(n, 0, dtype=np.int64)
    counter_mov = np.full(n, np.nan)
    bracket_hit = np.full(n, -1, dtype=np.int64)
    regime_pnl  = np.full(n, np.nan)

    for k in range(n):
        T = int(ets[k]); d = int(drs[k]); atr = float(atrs[k])
        ext_ts = int(exts[k])
        if ext_ts < 0:
            continue
        bar1_close_ts = T + 60 * NS
        i_lo = np.searchsorted(ts_k, bar1_close_ts, side="left")
        i_hi = np.searchsorted(ts_k, ext_ts, side="left")
        if i_hi <= i_lo + 1:
            continue
        idx, clen, cmov = find_pullback_resume(
            reg_k, h_k, l_k, o_k, c_k,
            i_lo, i_hi, d, atr,
            MIN_COUNTER_BARS, MIN_COUNTER_ATR)
        if idx < 0:
            continue
        pb_found[k]    = True
        pb_entry_ts[k] = ts_k[idx]
        pb_entry_px[k] = c_k[idx]
        pb_lag_s[k]    = (ts_k[idx] - bar1_close_ts) / NS
        counter_len[k] = clen
        counter_mov[k] = cmov
        regime_pnl[k]  = (float(expxs[k]) - pb_entry_px[k]) * d
        race_start = ts_k[idx] + k_sec * NS
        bracket_hit[k] = race_unbounded(race_start, pb_entry_px[k],
                                         d, atr, ts_1s, h_1s, l_1s)

    out = pd.DataFrame(index=sub.index)
    out["pb_found"]       = pb_found
    out["pb_entry_px"]    = pb_entry_px
    out["pb_lag_s"]       = pb_lag_s
    out["counter_len"]    = counter_len
    out["counter_mov"]    = counter_mov
    out["bracket_hit"]    = bracket_hit
    out["regime_pnl_pts"] = regime_pnl
    out["config"]         = name
    out["entry_atr"]      = sub["entry_atr"].values
    out["year"]           = sub["year"].values
    out["signal_direction"] = sub["signal_direction"].values
    return out


def report_config(label, df_cfg, total_cohort_n):
    """Single-line summary per config."""
    found = df_cfg[df_cfg["pb_found"]].copy()
    n_found = len(found)
    if n_found == 0:
        print(f"  {label:<14}  no triggers")
        return
    trigger_rate = n_found / total_cohort_n
    found["regime_pnl_atr"] = found["regime_pnl_pts"] / found["entry_atr"]
    found["regime_win"]     = (found["regime_pnl_pts"] > 0).astype(int)
    rwin = found["regime_win"].mean()
    rmean = found["regime_pnl_atr"].mean()
    mean_atr = found["entry_atr"].mean()
    rdol = rmean * mean_atr * PD["mult"] - 5

    br = found[found["bracket_hit"] >= 0].copy()
    if len(br):
        bwin = (br["bracket_hit"] == 1).mean()
        br_pnl_pts = np.where(br["bracket_hit"] == 1,
                               br["entry_atr"],
                               -br["entry_atr"] - 0.25)
        br_pnl_atr = br_pnl_pts / br["entry_atr"]
        bmean_atr = br["entry_atr"].mean()
        bdol = br_pnl_atr.mean() * bmean_atr * PD["mult"] - 5
    else:
        bwin = float("nan"); bdol = float("nan")
    med_lag = found["pb_lag_s"].median()
    print(f"  {label:<14}  "
          f"trig={trigger_rate:>5.1%} (n={n_found:>5,})  "
          f"medLag={med_lag:>5.0f}s  "
          f"|  regime: win={rwin:>5.1%}  meanATR={rmean:>+6.3f}  ${rdol:>+7.2f}  "
          f"|  bracket: win={bwin:>5.1%}  ${bdol:>+7.2f}")


def main():
    t0 = time.time()
    print(f"PRODUCT={PRODUCT}")
    re = pd.read_parquet(PD["regime_exit"])
    re["entry_ts"] = re["entry_ts"].astype(np.int64)
    re["signal_direction"] = re["signal_direction"].astype(np.int64)
    base = re[re["bar1_confirm"] & re["resolved"]].copy()
    print(f"  bar1-confirm + resolved cohort: {len(base):,}")

    # Per-year, per-config: load 1s bars once, iterate over configs
    by_config = {name: [] for name, _, _, _ in CONFIGS}
    for y in sorted(base["year"].unique()):
        sub = base[base["year"] == y]
        t1 = time.time()
        parts = []
        for yy in (y - 1, y, y + 1):
            p = PD["raw"].get(yy)
            if p and Path(p).exists():
                parts.append(pd.read_parquet(
                    p, columns=["open", "high", "low", "close"]))
        bars = pd.concat(parts).sort_index()
        bars = bars[~bars.index.duplicated(keep="first")]
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        for name, k_sec, af, asl in CONFIGS:
            r = run_config_on_year(name, k_sec, af, asl, sub, bars)
            by_config[name].append(r)
        print(f"  {y}: {len(sub):,}  ({time.time()-t1:.0f}s)")

    print(f"\n{'='*102}")
    print(f"MICRO-REGIME SENSITIVITY  —  pullback ≥2 bars, ≥{MIN_COUNTER_ATR} ATR, "
          f"resume closes in trend ({PRODUCT})")
    print(f"{'='*102}")
    print(f"  cohort = bar1-confirmed + resolved   n={len(base):,}")
    print(f"  {'config':<14}  {'rates & outcomes':<80}")
    print(f"  {'-'*100}")
    for name, _, _, _ in CONFIGS:
        df_cfg = pd.concat(by_config[name])
        report_config(name, df_cfg, len(base))

    # Year-by-year for the BEST config (highest regime $/tr among triggers >= 30%)
    print(f"\n{'='*102}\nYEAR-BY-YEAR (best config by trigger-rate × EV)\n{'='*102}")
    summaries = []
    for name, _, _, _ in CONFIGS:
        df_cfg = pd.concat(by_config[name])
        found = df_cfg[df_cfg["pb_found"]]
        if len(found) == 0:
            continue
        found = found.copy()
        found["regime_pnl_atr"] = found["regime_pnl_pts"] / found["entry_atr"]
        rmean = found["regime_pnl_atr"].mean()
        ma = found["entry_atr"].mean()
        rdol = rmean * ma * PD["mult"] - 5
        trig = len(found) / len(base)
        summaries.append((rdol, trig, name, df_cfg))
    if summaries:
        summaries.sort(key=lambda x: -x[0])  # highest $/tr first
        best_dol, best_trig, best_name, best_df = summaries[0]
        print(f"\n  best by $/trade (regime-exit): {best_name}  "
              f"trig={best_trig:.1%}  ${best_dol:+.2f}")
        found = best_df[best_df["pb_found"]].copy()
        found["regime_pnl_atr"] = found["regime_pnl_pts"] / found["entry_atr"]
        found["regime_win"]     = (found["regime_pnl_pts"] > 0).astype(int)
        print(f"\n  {'year':<6}{'n':>6}{'win%':>8}{'meanATR':>10}"
              f"{'medATR':>10}{'$/tr':>10}{'tag':>6}")
        for y in range(2020, 2027):
            g = found[found["year"] == y]
            if len(g) < 5:
                continue
            tag = "IS" if y in IS_YEARS else "OOS"
            ma = g["entry_atr"].mean()
            dol = g["regime_pnl_atr"].mean() * ma * PD["mult"] - 5
            print(f"  {y:<6}{len(g):>6}{g['regime_win'].mean():>7.1%}"
                  f"{g['regime_pnl_atr'].mean():>+10.3f}"
                  f"{g['regime_pnl_atr'].median():>+10.3f}"
                  f"{dol:>+10.2f}{tag:>6}")

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
