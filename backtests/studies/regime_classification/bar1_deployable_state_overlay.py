"""Deployable bar1_confirm + state overlay (corrected anchor).

Universe : NT-detected 1m flips (full deployable universe).
Filter   : bar1_confirm  (HH+pos-close long / LL+neg-close short),
            observable only at bar1 close = T + 60s.
Entry    : open of the 1s bar at T + 60s (i.e. bar1 close moment ≈
            open of bar2). FULLY CAUSAL.
Exits    :
  A. +1.0 / -1.0 ATR first-touch on 1s bars (from bar1-close-entry).
  B. Regime-exit (already in nt_regime_exit_nq.parquet,
     bar1-close anchor).
States   : Two lookups, both causal:
  - state_at_flip = state of 1m bar that closes at T  (open_ts = T - 60s)
  - state_at_bar1 = state of 1m bar that closes at T+60s (open_ts = T)

For each (model_k) × {state_at_flip, state_at_bar1} × {bracket, regime}:
  pooled OOS n, win rate, lift vs cohort baseline,
  per-OOS-year n/win/lift, long/short split.

Filters (same as Phase 4):
  pooled OOS n >= 200,
  |lift| >= 3pp,
  per-OOS-year n >= 30 in 3+ years,
  same lift sign in 3+ years.

Key question: does the +5pp HMM-state lift on bar1_confirm survive
the corrected entry anchor? If it dies, it was anchor mismatch (the
prior 77% / 82% numbers were measuring move-during-bar1, not a
state-conditional continuation effect).
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
            "states": "studies/regime_classification/results/states_nq_1m.parquet",
            "mult": 20.0},
    "ES": {"raw": {**{y: f"data/raw/ES_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/ES_v0_1s_2026_ytd.parquet"},
            "regime_exit": "studies/v_a_excursion_regime/results_v0/nt_regime_exit_es.parquet",
            "states": "studies/regime_classification/results/states_es_1m.parquet",
            "mult": 50.0},
}
PD = PRODUCT_DATA[PRODUCT]
OUT = Path("studies/regime_classification/results")
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)

MIN_POOLED_OOS_N = 200
MIN_PER_YEAR_N = 30
MIN_YEARS_PASSING_N = 3
MIN_LIFT_PP = 3.0
MIN_YEARS_SAME_SIGN = 3
ENTRY_SNAP_NS = 5 * NS  # max gap from bar1 close to first 1s bar

STATE_COLS = [f"{m}_{k}" for k in (3, 4, 5, 6)
              for m in ("hmm", "gmm", "kmeans")]


@njit
def race_unbounded(start_ts, anchor_px, d, atr, ts_1s, h_1s, l_1s):
    if not (anchor_px == anchor_px) or atr <= 0:
        return -1
    j = np.searchsorted(ts_1s, start_ts, side="left")
    if d == 1:
        tgt, stp = anchor_px + atr, anchor_px - atr
    else:
        tgt, stp = anchor_px - atr, anchor_px + atr
    while j < len(ts_1s):
        h, l = h_1s[j], l_1s[j]
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


def compute_bracket_outcome(cohort, year):
    parts = []
    for y in (year - 1, year, year + 1):
        p = PD["raw"].get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["open", "high", "low"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    ts_1s = bars.index.values.astype(np.int64)
    o_1s = bars["open"].to_numpy(np.float64)
    h_1s = bars["high"].to_numpy(np.float64)
    l_1s = bars["low"].to_numpy(np.float64)

    sub = cohort[cohort["year"] == year]
    ets = sub["entry_ts"].to_numpy(np.int64)
    drs = sub["signal_direction"].to_numpy(np.int64)
    ats = sub["entry_atr"].to_numpy(np.float64)
    n = len(sub)
    hit = np.full(n, -1, dtype=np.int64)
    entry_b1 = np.full(n, np.nan)
    for k in range(n):
        T = int(ets[k])
        b1_close = T + 60 * NS
        i = np.searchsorted(ts_1s, b1_close, side="left")
        if i >= len(ts_1s) or ts_1s[i] - b1_close > ENTRY_SNAP_NS:
            continue
        entry_b1[k] = o_1s[i]
        hit[k] = race_unbounded(b1_close, o_1s[i], int(drs[k]),
                                  float(ats[k]), ts_1s, h_1s, l_1s)
    out = pd.DataFrame(index=sub.index)
    out["entry_px_bar1_open"] = entry_b1
    out["bracket_hit_bar1"] = hit
    return out


def lookup_state(target_ts_arr, state_ts_arr, state_arr):
    """Exact-match state lookup (target = 1m bar open ts; expect exact hit)."""
    state_arr = np.asarray(state_arr).flatten().astype(np.int64)
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    i = np.searchsorted(state_ts_arr, target_ts_arr, side="left")
    valid = (i < len(state_ts_arr)) & \
             (state_ts_arr[np.clip(i, 0, len(state_ts_arr) - 1)]
              == target_ts_arr)
    out[valid] = state_arr[i[valid]]
    return out


def assess(cohort, state_col_values, state_ts_arr, state_anchor_col,
            outcome_col, label):
    """Per-state pooled OOS lift, with per-OOS-year breakdown."""
    target_ts = cohort[state_anchor_col].to_numpy(np.int64)
    cohort = cohort.copy()
    cohort["state"] = lookup_state(target_ts, state_ts_arr, state_col_values)
    res = cohort[(cohort["state"] >= 0) & cohort[outcome_col].between(0, 1)]
    oos = res[res["year"].isin(OOS_YEARS)]
    if len(oos) == 0:
        return [], float("nan")
    base = oos[outcome_col].mean()
    rows = []
    for st in sorted(oos["state"].unique()):
        sub = oos[oos["state"] == st]
        if len(sub) == 0:
            continue
        per_year = []
        for y in OOS_YEARS:
            g = sub[sub["year"] == y]
            base_y = oos[oos["year"] == y][outcome_col].mean()
            if len(g) >= 1:
                per_year.append((y, len(g), g[outcome_col].mean(),
                                  (g[outcome_col].mean() - base_y) * 100))
        rows.append({
            "label": label,
            "state": st,
            "n_pool_oos": len(sub),
            "win_pool_oos": sub[outcome_col].mean(),
            "base_pool_oos": base,
            "lift_pool_pp": (sub[outcome_col].mean() - base) * 100,
            "per_year": per_year,
        })
    return rows, base


def filter_survivors(rows):
    survivors = []
    for r in rows:
        if r["n_pool_oos"] < MIN_POOLED_OOS_N:
            continue
        if abs(r["lift_pool_pp"]) < MIN_LIFT_PP:
            continue
        years_with_n = sum(1 for y, n, w, lp in r["per_year"]
                            if n >= MIN_PER_YEAR_N)
        if years_with_n < MIN_YEARS_PASSING_N:
            continue
        signs = [np.sign(lp) for y, n, w, lp in r["per_year"]
                  if n >= MIN_PER_YEAR_N]
        pos = sum(1 for s in signs if s > 0)
        neg = sum(1 for s in signs if s < 0)
        if max(pos, neg) < MIN_YEARS_SAME_SIGN:
            continue
        survivors.append(r)
    return survivors


def main():
    t0 = time.time()
    print(f"PRODUCT={PRODUCT}")
    re = pd.read_parquet(PD["regime_exit"])
    re["entry_ts"] = re["entry_ts"].astype(np.int64)
    re["signal_direction"] = re["signal_direction"].astype(np.int64)
    cohort = re[re["bar1_confirm"]].copy()
    print(f"  bar1-confirmed flips: {len(cohort):,}")
    print(f"  has regime-exit outcome (already bar1-close anchored): "
          f"regime_win_bar1, regime_pnl_atr_bar1 columns present "
          f"= {'regime_win_bar1' in cohort.columns}")

    # Compute +1/-1 ATR bracket outcome from bar1-close entry (NEW)
    print("Computing +1/-1 ATR first-touch from bar1-close-entry per year ...")
    parts = []
    for y in sorted(cohort["year"].unique()):
        t1 = time.time()
        addl = compute_bracket_outcome(cohort, int(y))
        parts.append(addl)
        print(f"  {y}: {len(addl):,}  ({time.time()-t1:.0f}s)")
    feats = pd.concat(parts)
    cohort = pd.concat([cohort, feats], axis=1)
    cohort["bracket_win_bar1"] = (cohort["bracket_hit_bar1"] == 1).astype(int)
    cohort["bracket_resolved"] = cohort["bracket_hit_bar1"] >= 0
    cohort["regime_win_bar1_int"] = cohort["regime_win_bar1"].astype(int)

    # Baseline reports
    res_b = cohort[cohort["bracket_resolved"]]
    res_r = cohort[cohort["resolved"]]  # regime exit resolved
    oos_b = res_b[res_b["year"].isin(OOS_YEARS)]
    oos_r = res_r[res_r["year"].isin(OOS_YEARS)]
    print(f"\n{'='*88}\nBASELINE bar1_confirm at bar1-close entry "
          f"(deployable causal anchor)\n{'='*88}")
    print(f"  ── BRACKET (+1/-1 ATR first-touch) ──")
    print(f"  pooled OOS  n={len(oos_b):,}  win={oos_b['bracket_win_bar1'].mean():.1%}")
    print(f"  per year:")
    print(f"  {'year':<6}{'n':>7}{'win%':>9}{'long n':>9}{'long win%':>12}"
          f"{'short n':>10}{'short win%':>13}")
    for y in OOS_YEARS:
        g = oos_b[oos_b["year"] == y]
        gl = g[g["signal_direction"] == 1]
        gs = g[g["signal_direction"] == -1]
        if len(g):
            print(f"  {y:<6}{len(g):>7,}{g['bracket_win_bar1'].mean():>8.1%}"
                  f"{len(gl):>9,}{gl['bracket_win_bar1'].mean():>11.1%}"
                  f"{len(gs):>10,}{gs['bracket_win_bar1'].mean():>12.1%}")

    print(f"\n  ── REGIME-EXIT (already bar1-close anchored) ──")
    print(f"  pooled OOS  n={len(oos_r):,}  win={oos_r['regime_win_bar1_int'].mean():.1%}")
    print(f"  per year:")
    print(f"  {'year':<6}{'n':>7}{'win%':>9}{'long n':>9}{'long win%':>12}"
          f"{'short n':>10}{'short win%':>13}")
    for y in OOS_YEARS:
        g = oos_r[oos_r["year"] == y]
        gl = g[g["signal_direction"] == 1]
        gs = g[g["signal_direction"] == -1]
        if len(g):
            print(f"  {y:<6}{len(g):>7,}{g['regime_win_bar1_int'].mean():>8.1%}"
                  f"{len(gl):>9,}{gl['regime_win_bar1_int'].mean():>11.1%}"
                  f"{len(gs):>10,}{gs['regime_win_bar1_int'].mean():>12.1%}")

    # Load states
    states = pd.read_parquet(PD["states"])
    state_ts = states.index.values.astype(np.int64)

    # Set up two state-anchor columns on cohort
    cohort["state_anchor_flip"] = cohort["entry_ts"] - 60 * NS
    cohort["state_anchor_bar1"] = cohort["entry_ts"]

    # ── HEADLINE: hmm_4 + kmeans_4 detail ──
    for headline in ("hmm_4", "kmeans_4"):
        print(f"\n{'='*88}\nHEADLINE {headline.upper()} — both state anchors x both exits\n{'='*88}")
        state_arr = states[headline].to_numpy(np.int64)
        for state_moment in ("state_anchor_flip", "state_anchor_bar1"):
            for outcome_col, outcome_name in (
                    ("bracket_win_bar1", "BRACKET"),
                    ("regime_win_bar1_int", "REGIME"),):
                sub = cohort[cohort["bracket_resolved"]
                              if outcome_name == "BRACKET"
                              else cohort["resolved"]]
                rows, base = assess(sub, state_arr, state_ts,
                                      state_moment, outcome_col,
                                      f"{headline}/{state_moment}/{outcome_name}")
                if not rows:
                    continue
                print(f"\n  {state_moment} × {outcome_name}  "
                      f"(OOS base = {base:.1%})")
                print(f"    {'state':<6}{'n_pool':>8}{'win%':>8}{'lift':>9}  "
                      f"per-OOS-year")
                for r in sorted(rows, key=lambda x: -x["n_pool_oos"]):
                    yr_str = " ".join(
                        f"{y}:{n}/{w:.0%}/{lp:+.1f}"
                        for y, n, w, lp in r["per_year"])
                    print(f"    {r['state']:<6}{r['n_pool_oos']:>8,}"
                          f"{r['win_pool_oos']:>7.1%}"
                          f"{r['lift_pool_pp']:>+8.1f}pp  {yr_str}")

    # ── FULL SWEEP: all 12 models × 2 state moments × 2 exits ──
    print(f"\n{'='*88}\nFULL SWEEP — survivors (pooled OOS n >= {MIN_POOLED_OOS_N}, "
          f"|lift| >= {MIN_LIFT_PP}pp, per-year n >= {MIN_PER_YEAR_N} in {MIN_YEARS_PASSING_N}+ yrs, "
          f"same sign in {MIN_YEARS_SAME_SIGN}+ yrs)\n{'='*88}")
    all_surv = []
    for sc in STATE_COLS:
        state_arr = states[sc].to_numpy(np.int64)
        for state_moment in ("state_anchor_flip", "state_anchor_bar1"):
            for outcome_col, outcome_name in (
                    ("bracket_win_bar1", "BRACKET"),
                    ("regime_win_bar1_int", "REGIME")):
                sub = cohort[cohort["bracket_resolved"]
                              if outcome_name == "BRACKET"
                              else cohort["resolved"]]
                rows, base = assess(sub, state_arr, state_ts,
                                      state_moment, outcome_col, "")
                if np.isnan(base):
                    continue
                surv = filter_survivors(rows)
                for s in surv:
                    s["model_k"] = sc
                    s["state_moment"] = state_moment.replace("state_anchor_", "")
                    s["outcome"] = outcome_name
                    s["base_oos"] = base
                    all_surv.append(s)
    if not all_surv:
        print(f"\n  NO CELLS PASSED ALL FILTERS.")
    else:
        all_surv.sort(key=lambda x: -abs(x["lift_pool_pp"]))
        print(f"\n  {len(all_surv)} survivor cells:\n")
        print(f"  {'model_k':<14}{'anchor':<6}{'exit':<9}{'state':<7}"
              f"{'n_pool':>8}{'win%':>8}{'base%':>8}{'lift':>9}  "
              f"per-OOS-year")
        for s in all_surv:
            yr_str = " ".join(
                f"{y}:{n}/{w:.0%}/{lp:+.1f}"
                for y, n, w, lp in s["per_year"])
            print(f"  {s['model_k']:<14}{s['state_moment']:<6}"
                  f"{s['outcome']:<9}{s['state']:<7}"
                  f"{s['n_pool_oos']:>8,}{s['win_pool_oos']:>7.1%}"
                  f"{s['base_oos']:>7.1%}{s['lift_pool_pp']:>+8.1f}pp  "
                  f"{yr_str}")

    cohort.to_parquet(OUT / f"bar1_deployable_state_{PRODUCT.lower()}.parquet")
    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
