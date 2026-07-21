"""Compression + bar1-confirmed NT flips → regime-exit outcome.

Reframes the question from the failed ±1 ATR bracket to:
  "Of the cohort we trust most (compressed AND bar1-confirmed), what
   fraction exits favorably when the regime NEXT flips?"

Universe : NT-detected 1m regime flips, both directions, 2020-2026
            (deployable universe; not v2's filtered set).
Filter   : tot_slow_30m < IS-tuned tertile cut (compression) AND
            bar1_confirm (long: bar1.high > flip.high AND
            bar1.close > bar1.open; short mirrors).
Exit     : at the close of the FIRST 1m bar where regime flips OUT
            of the entry direction. (If regime persists to end of
            data: skip — unresolved.)
Outcome  : positive = exit_px > entry_px for long (mirror short).
            Also reports magnitude in ATR units and holding time.

This is NOT a deployable test directly — bar1_confirm is observable
only AFTER bar1 closes (60s after flip). It IS a diagnostic of
WHETHER the compression + bar1-confirm cohort has structural
continuation when the regime holds.
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
ATR_PERIOD = 14
ALPHA_EMA3 = 0.5
ALPHA_EMA9 = 0.2

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
PRODUCT_DATA = {
    "NQ": {"raw": {**{y: f"data/raw/NQ_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet"},
            "trades": "backtests/baseline_flip_parity/results/nq_live_{}/trades.parquet",
            "archetype": "studies/v_a_excursion_regime/results_v0/nt_flip_archetypes_nq.parquet",
            "mult": 20.0},
    "ES": {"raw": {**{y: f"data/raw/ES_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/ES_v0_1s_2026_ytd.parquet"},
            "trades": "backtests/baseline_flip_parity/results/es_live_{}/trades.parquet",
            "archetype": "studies/v_a_excursion_regime/results_v0/nt_flip_archetypes_es.parquet",
            "mult": 50.0},
}
PD = PRODUCT_DATA[PRODUCT]
OUT = Path("studies/v_a_excursion_regime/results_v0")
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)


@njit
def compute_regime(om_h, om_l, om_c):
    n = len(om_c)
    reg = np.zeros(n, dtype=np.int64)
    e3h = e9h = e3l = e9l = 0.0
    cur = 0
    for i in range(n):
        if i == 0:
            e3h = om_h[i]; e9h = om_h[i]; e3l = om_l[i]; e9l = om_l[i]
        else:
            e3h = ALPHA_EMA3 * om_h[i] + (1.0 - ALPHA_EMA3) * e3h
            e9h = ALPHA_EMA9 * om_h[i] + (1.0 - ALPHA_EMA9) * e9h
            e3l = ALPHA_EMA3 * om_l[i] + (1.0 - ALPHA_EMA3) * e3l
            e9l = ALPHA_EMA9 * om_l[i] + (1.0 - ALPHA_EMA9) * e9l
        new_reg = cur
        if om_c[i] > e3h and om_c[i] > e9h:
            new_reg = 1
        elif om_c[i] < e3l and om_c[i] < e9l:
            new_reg = -1
        reg[i] = new_reg
        cur = new_reg
    return reg


def process_year(year, nt_year):
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
    ts = bars.index.values.astype(np.int64)
    bucket = (ts // (60 * NS)) * (60 * NS)
    g = pd.DataFrame({"b": bucket,
                       "o": bars["open"].values,
                       "h": bars["high"].values,
                       "l": bars["low"].values,
                       "c": bars["close"].values})
    one_m = g.groupby("b").agg(o=("o", "first"), h=("h", "max"),
                                l=("l", "min"), c=("c", "last"))
    m_ts = one_m.index.values.astype(np.int64)
    m_h, m_l, m_o, m_c = (one_m["h"].to_numpy(np.float64),
                          one_m["l"].to_numpy(np.float64),
                          one_m["o"].to_numpy(np.float64),
                          one_m["c"].to_numpy(np.float64))
    reg = compute_regime(m_h, m_l, m_c)
    idx = {int(t): i for i, t in enumerate(m_ts)}

    ets = nt_year["entry_ts"].to_numpy(np.int64)
    dr  = nt_year["signal_direction"].to_numpy(np.int64)
    n = len(nt_year)
    bar1_conf = np.zeros(n, dtype=bool)
    exit_ts   = np.full(n, -1, dtype=np.int64)
    exit_px   = np.full(n, np.nan)
    entry_px_flip = np.full(n, np.nan)   # flip-bar close (non-causal w/ bar1 filter)
    entry_px_bar1 = np.full(n, np.nan)   # bar1 close (CAUSAL deployable anchor)
    hold_min_flip = np.full(n, np.nan)
    hold_min_bar1 = np.full(n, np.nan)

    for k in range(n):
        T = int(ets[k]); d = int(dr[k])
        # Flip bar: 1m bar with open ts = T - 60s (close at T)
        fb_open = T - 60 * NS
        fb_i = idx.get(fb_open, -1)
        if fb_i < 0:
            continue
        entry_px_flip[k] = m_c[fb_i]
        # Bar1: open ts = T (close at T+60s)
        b1_i = idx.get(T, -1)
        if b1_i >= 0:
            entry_px_bar1[k] = m_c[b1_i]
            if d == 1:
                bar1_conf[k] = (m_h[b1_i] > m_h[fb_i]) and (m_c[b1_i] > m_o[b1_i])
            else:
                bar1_conf[k] = (m_l[b1_i] < m_l[fb_i]) and (m_c[b1_i] < m_o[b1_i])
        # Find next regime exit: scan forward from fb_i + 1
        for j in range(fb_i + 1, len(reg)):
            if reg[j] != d and reg[j] != 0:
                exit_ts[k] = m_ts[j] + 60 * NS  # close of bar j
                exit_px[k] = m_c[j]
                hold_min_flip[k] = (m_ts[j] + 60 * NS - T) / (60 * NS)
                hold_min_bar1[k] = (m_ts[j] + 60 * NS - (T + 60 * NS)) / (60 * NS)
                break

    out = pd.DataFrame(index=nt_year.index)
    out["bar1_confirm"]     = bar1_conf
    out["entry_px_flip"]    = entry_px_flip
    out["entry_px_bar1"]    = entry_px_bar1
    out["exit_ts"]          = exit_ts
    out["exit_px"]          = exit_px
    out["hold_min_flip"]    = hold_min_flip
    out["hold_min_bar1"]    = hold_min_bar1
    return out


def main():
    t0 = time.time()
    print(f"PRODUCT={PRODUCT}")
    # Load NT trades + archetype parquet (already has tot_slow_30m)
    arc = pd.read_parquet(PD["archetype"])
    arc["entry_ts"] = arc["entry_ts"].astype(np.int64)
    arc["signal_direction"] = arc["signal_direction"].astype(np.int64)
    print(f"  archetype parquet rows: {len(arc):,}")

    parts = []
    for y in sorted(arc["year"].unique()):
        sub = arc[arc["year"] == y]
        t1 = time.time()
        addl = process_year(int(y), sub)
        parts.append(addl)
        print(f"  {y}: {len(sub):,}  ({time.time()-t1:.0f}s)")
    feats = pd.concat(parts)
    df = pd.concat([arc, feats], axis=1)

    # IS-tuned tot_slow_30m tertile cut for "compression"
    is_ts = df[df["year"].isin(IS_YEARS)]["tot_slow_30m"].dropna()
    exc_lo = float(is_ts.quantile(1 / 3)) if len(is_ts) else np.nan
    df["compressed"] = df["tot_slow_30m"] < exc_lo

    # PnL points and ATR-multiple — TWO ANCHORS:
    #   flip-close: entry at flip-bar close (NON-CAUSAL if bar1_confirm filter applied)
    #   bar1-close: entry at bar1 close       (CAUSAL deployable anchor)
    df["regime_pnl_pts_flip"] = (df["exit_px"] - df["entry_px_flip"]) * df["signal_direction"]
    df["regime_pnl_atr_flip"] = df["regime_pnl_pts_flip"] / df["entry_atr"]
    df["regime_win_flip"]     = (df["regime_pnl_pts_flip"] > 0).astype(int)
    df["regime_pnl_pts_bar1"] = (df["exit_px"] - df["entry_px_bar1"]) * df["signal_direction"]
    df["regime_pnl_atr_bar1"] = df["regime_pnl_pts_bar1"] / df["entry_atr"]
    df["regime_win_bar1"]     = (df["regime_pnl_pts_bar1"] > 0).astype(int)
    df["resolved"]      = df["exit_ts"] > 0

    out_p = OUT / f"nt_regime_exit_{PD['archetype'].split('_')[-1]}"
    df.to_parquet(out_p, index=False)
    print(f"\n  saved {out_p}")

    # ── Report ──
    resolved = df[df["resolved"]].copy()
    print(f"\n{'='*78}\nCOHORT — compressed ({PRODUCT} tot_slow_30m < "
          f"{exc_lo:.1f}) AND bar1-confirmed\n{'='*78}")
    print(f"  Total NT flips:               {len(df):,}")
    print(f"  Resolved (regime exit found): {len(resolved):,} "
          f"({resolved['resolved'].sum()/len(df):.1%})")
    print(f"  Compressed:                   {(df['compressed']).sum():,}")
    print(f"  Bar1-confirmed:               {(df['bar1_confirm']).sum():,} "
          f"({df['bar1_confirm'].mean():.1%})")

    def report_cell(sub, label):
        print(f"\n  ── {label}  n={len(sub):,} ──")
        for anchor in ("flip", "bar1"):
            wcol = f"regime_win_{anchor}"
            acol = f"regime_pnl_atr_{anchor}"
            mean_atr_pts = sub["entry_atr"].mean()
            print(f"    [{anchor}-close entry]  "
                  f"win={sub[wcol].mean():.1%}  "
                  f"meanATR={sub[acol].mean():+.3f}  "
                  f"medATR={sub[acol].median():+.3f}  "
                  f"$/tr={sub[acol].mean() * mean_atr_pts * PD['mult'] - 5:+.2f}")

    # All cohorts
    report_cell(resolved, "all NT flips (no filter)")
    report_cell(resolved[resolved["compressed"]],
                f"compressed only (tot_slow_30m < {exc_lo:.1f})")
    report_cell(resolved[resolved["bar1_confirm"]],
                "bar1-confirm only")
    coh = resolved[resolved["compressed"] & resolved["bar1_confirm"]]
    report_cell(coh, "compressed AND bar1-confirm (cohort)")

    # By year for CAUSAL deployable bar1-confirm only (the live filter)
    sub = resolved[resolved["bar1_confirm"]]
    print(f"\n{'='*78}\nDEPLOYABLE — bar1-confirm filter + bar1-close entry "
          f"(causal, 60s post-flip)\n{'='*78}")
    print(f"  {'year':<6}{'n':>6}{'win%':>8}{'meanATR':>10}{'medATR':>10}"
          f"{'medHold':>10}{'$/tr':>10}{'tag':>6}")
    for y in range(2020, 2027):
        g = sub[sub["year"] == y]
        if len(g) < 5:
            continue
        tag = "IS" if y in IS_YEARS else "OOS"
        mean_atr_pts = g["entry_atr"].mean()
        dollars = g["regime_pnl_atr_bar1"].mean() * mean_atr_pts * PD['mult'] - 5
        print(f"  {y:<6}{len(g):>6}"
              f"{g['regime_win_bar1'].mean():>7.1%}"
              f"{g['regime_pnl_atr_bar1'].mean():>+10.3f}"
              f"{g['regime_pnl_atr_bar1'].median():>+10.3f}"
              f"{g['hold_min_bar1'].median():>9.1f}m"
              f"{dollars:>+10.2f}{tag:>6}")

    # PnL distribution (causal bar1-close entry, full bar1-confirm set)
    print(f"\n  bar1-confirm deployable PnL dist (ATR, bar1-close anchor):")
    for q in (0.1, 0.25, 0.5, 0.75, 0.9):
        print(f"    {q*100:>4.0f}%ile: {sub['regime_pnl_atr_bar1'].quantile(q):+.3f}")

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
