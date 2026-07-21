"""Compression metrics AT pullback-resume entry — winners vs losers.

For each entry in the 5s pullback-resume cohort (bar1-confirmed flips
with a 5s 3/9 regime resume after a ≥2-bar, ≥0.25 ATR pullback),
compute compression metrics at the ENTRY MOMENT (not the original
1m flip moment) at multiple timeframes:

  - 30m, 15m, 5m, 2m, 1m, 30s total-excursion (max_high - min_low)
    over 1s bars, normalized by entry_atr

Also compute the DELTA from "compression at original flip" to
"compression at pullback entry" (does the 30m compression hold
through the pullback, or has it broken down by PB time?).

Then split by outcome (regime-exit winner/loser, bracket winner/loser)
and compute:
  - Mean and median per feature per cohort
  - Univariate AUC
  - Look for features where winners and losers DRASTICALLY differ
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
from sklearn.metrics import roc_auc_score

NS = 1_000_000_000
PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
PRODUCT_DATA = {
    "NQ": {"raw": {**{y: f"data/raw/NQ_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet"},
            "pb": "studies/v_a_excursion_regime/results_v0/nt_5s_pullback_resume_nq.parquet",
            "arc": "studies/v_a_excursion_regime/results_v0/nt_flip_archetypes_nq.parquet"},
    "ES": {"raw": {**{y: f"data/raw/ES_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/ES_v0_1s_2026_ytd.parquet"},
            "pb": "studies/v_a_excursion_regime/results_v0/nt_5s_pullback_resume_es.parquet",
            "arc": "studies/v_a_excursion_regime/results_v0/nt_flip_archetypes_es.parquet"},
}
PD = PRODUCT_DATA[PRODUCT]
OUT = Path("studies/v_a_excursion_regime/results_v0")
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)

WINDOWS_SEC = [30, 60, 120, 300, 900, 1800]   # 30s 1m 2m 5m 15m 30m
WIN_NAMES = ["30s", "1m", "2m", "5m", "15m", "30m"]


@njit
def compute_compression_at(entry_ts_arr, atr_arr,
                            ts_1s, h_1s, l_1s,
                            windows_ns):
    """For each entry, compute total-excursion (max_h - min_l) over
    each window ending at entry_ts (exclusive), normalized by atr.

    Returns 2D array [n, n_windows] of ATR-unit compression values.
    """
    n = len(entry_ts_arr)
    n_win = len(windows_ns)
    out = np.full((n, n_win), np.nan)
    for k in range(n):
        T = entry_ts_arr[k]
        atr = atr_arr[k]
        if T < 0 or atr <= 0:
            continue
        i_hi = np.searchsorted(ts_1s, T, side="left")
        if i_hi < 2:
            continue
        for w in range(n_win):
            i_lo = np.searchsorted(ts_1s, T - windows_ns[w], side="left")
            if i_hi - i_lo < 5:
                continue
            seg_h = h_1s[i_lo:i_hi]
            seg_l = l_1s[i_lo:i_hi]
            rng = seg_h.max() - seg_l.min()
            out[k, w] = rng / atr
    return out


def process_year(year, sub):
    """sub = pullback-resume entries for this year (with pb_entry_ts)."""
    parts = []
    for y in (year - 1, year, year + 1):
        p = PD["raw"].get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["high", "low"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    ts_1s = bars.index.values.astype(np.int64)
    h_1s = bars["high"].to_numpy(np.float64)
    l_1s = bars["low"].to_numpy(np.float64)
    windows_ns = np.array([w * NS for w in WINDOWS_SEC], dtype=np.int64)

    # Compute compression AT pullback-resume entry moment
    pb_ts  = sub["pb_entry_ts"].to_numpy(np.int64)
    atrs   = sub["entry_atr"].to_numpy(np.float64)
    pb_compress = compute_compression_at(pb_ts, atrs, ts_1s, h_1s, l_1s,
                                          windows_ns)

    # Compute compression AT original flip moment for comparison
    fl_ts  = sub["entry_ts"].to_numpy(np.int64)
    fl_compress = compute_compression_at(fl_ts, atrs, ts_1s, h_1s, l_1s,
                                          windows_ns)

    out = pd.DataFrame(index=sub.index)
    for i, nm in enumerate(WIN_NAMES):
        out[f"compress_{nm}_atPB"]   = pb_compress[:, i]
        out[f"compress_{nm}_atFLIP"] = fl_compress[:, i]
        out[f"compress_{nm}_delta"]  = pb_compress[:, i] - fl_compress[:, i]
    return out


def main():
    t0 = time.time()
    print(f"PRODUCT={PRODUCT}")
    pb = pd.read_parquet(PD["pb"])
    pb["entry_ts"] = pb["entry_ts"].astype(np.int64)
    pb["pb_entry_ts"] = pb["pb_entry_ts"].astype(np.int64)
    pb["signal_direction"] = pb["signal_direction"].astype(np.int64)
    found = pb[pb["pb_found"]].copy()
    print(f"  pullback-resume entries: {len(found):,}")

    # Compute features
    parts = []
    for y in sorted(found["year"].unique()):
        sub = found[found["year"] == y]
        t1 = time.time()
        addl = process_year(int(y), sub)
        parts.append(addl)
        print(f"  {y}: {len(sub):,}  ({time.time()-t1:.0f}s)")
    feats = pd.concat(parts)
    df = pd.concat([found.reset_index(drop=True),
                     feats.reset_index(drop=True)], axis=1)
    df["regime_pnl_atr"] = df["regime_pnl_pts"] / df["entry_atr"]
    df["regime_win"] = (df["regime_pnl_pts"] > 0).astype(int)
    df["bracket_resolved"] = df["bracket_hit"] >= 0
    df["bracket_win"] = (df["bracket_hit"] == 1).astype(int)

    out_p = OUT / f"nt_pullback_compression_{PRODUCT.lower()}.parquet"
    df.to_parquet(out_p, index=False)
    print(f"  saved {out_p}")

    # ── Report ──
    feat_cols = [f"compress_{nm}_atPB" for nm in WIN_NAMES] + \
                [f"compress_{nm}_atFLIP" for nm in WIN_NAMES] + \
                [f"compress_{nm}_delta" for nm in WIN_NAMES]

    # Univariate AUC per feature, both targets, IS and OOS
    is_set  = df[df["year"].isin(IS_YEARS)]
    oos_set = df[df["year"].isin(OOS_YEARS)]
    print(f"\n{'='*100}")
    print(f"UNIVARIATE AUC — compression features at PB entry "
          f"(target = win/loss)")
    print(f"{'='*100}")
    print(f"  {'feature':<26}{'IS n':>7}{'reg AUC IS':>13}"
          f"{'reg AUC OOS':>14}{'br AUC IS':>12}{'br AUC OOS':>13}")
    rows = []
    for c in feat_cols:
        is_s = is_set.dropna(subset=[c])
        oos_s = oos_set.dropna(subset=[c])
        if len(is_s) < 200 or len(oos_s) < 200:
            continue
        # regime-exit
        is_r = roc_auc_score(is_s["regime_win"], is_s[c])
        oos_r = roc_auc_score(oos_s["regime_win"], oos_s[c])
        # bracket (only resolved)
        is_br = is_s[is_s["bracket_resolved"]]
        oos_br = oos_s[oos_s["bracket_resolved"]]
        is_b = (roc_auc_score(is_br["bracket_win"], is_br[c])
                if len(is_br) > 100 and is_br["bracket_win"].nunique() > 1
                else float("nan"))
        oos_b = (roc_auc_score(oos_br["bracket_win"], oos_br[c])
                 if len(oos_br) > 100 and oos_br["bracket_win"].nunique() > 1
                 else float("nan"))
        rows.append((c, len(is_s), is_r, oos_r, is_b, oos_b))
    # Sort by |OOS regime AUC - 0.5| desc to surface strongest features
    rows.sort(key=lambda r: -abs(r[3] - 0.5))
    for r in rows:
        print(f"  {r[0]:<26}{r[1]:>7,}{r[2]:>12.4f}"
              f"{r[3]:>14.4f}{r[4]:>12.4f}{r[5]:>13.4f}")

    # Cohort-mean comparison: regime winners vs losers, OOS only
    res_oos = oos_set
    print(f"\n{'='*100}")
    print(f"COHORT MEANS — OOS regime winners vs losers (mean compression "
          f"in ATR units)")
    print(f"{'='*100}")
    print(f"  {'feature':<26}{'win mean':>11}{'loss mean':>11}"
          f"{'delta':>9}{'win med':>10}{'loss med':>10}{'n':>8}")
    win_set = res_oos[res_oos["regime_win"] == 1]
    los_set = res_oos[res_oos["regime_win"] == 0]
    for c in feat_cols:
        ws = win_set[c].dropna()
        ls = los_set[c].dropna()
        if len(ws) < 50 or len(ls) < 50:
            continue
        wm = ws.mean(); lm = ls.mean()
        wmed = ws.median(); lmed = ls.median()
        print(f"  {c:<26}{wm:>11.3f}{lm:>11.3f}{wm-lm:>+9.3f}"
              f"{wmed:>10.3f}{lmed:>10.3f}{min(len(ws),len(ls)):>8,}")

    # Is 1m compression STABLE between flip and PB entry?
    print(f"\n{'='*100}")
    print(f"DRIFT: compression at FLIP vs at PB entry (mean delta in ATR)")
    print(f"{'='*100}")
    print(f"  {'window':<10}{'mean atFLIP':>14}{'mean atPB':>14}"
          f"{'mean delta':>14}{'median delta':>14}")
    for nm in WIN_NAMES:
        fl = df[f"compress_{nm}_atFLIP"].dropna()
        pb = df[f"compress_{nm}_atPB"].dropna()
        delta = df[f"compress_{nm}_delta"].dropna()
        print(f"  {nm:<10}{fl.mean():>14.3f}{pb.mean():>14.3f}"
              f"{delta.mean():>+14.3f}{delta.median():>+14.3f}")

    # Best feature decile-stratified outcome (OOS only)
    if rows:
        best_feat = rows[0][0]
        best_oos_auc = rows[0][3]
        print(f"\n{'='*100}")
        print(f"DECILE STRATIFICATION on '{best_feat}'  (best OOS regime AUC "
              f"= {best_oos_auc:.4f}, OOS data)")
        print(f"{'='*100}")
        oos_s = oos_set.dropna(subset=[best_feat]).copy()
        oos_s["decile"] = pd.qcut(oos_s[best_feat], 10,
                                    labels=False, duplicates="drop")
        print(f"  {'decile':<8}{'n':>7}{'reg win%':>11}"
              f"{'mean reg ATR':>15}{'$/tr':>10}")
        mult = 20.0 if PRODUCT == "NQ" else 50.0
        for d_ in range(10):
            g = oos_s[oos_s["decile"] == d_]
            if len(g) < 30:
                continue
            wm = g["regime_win"].mean()
            am = g["regime_pnl_atr"].mean()
            ma = g["entry_atr"].mean()
            dol = am * ma * mult - 5
            print(f"  {d_:<8}{len(g):>7,}{wm:>10.1%}{am:>+15.3f}{dol:>+10.2f}")

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
