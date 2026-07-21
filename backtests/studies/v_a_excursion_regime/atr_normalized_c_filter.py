"""ATR-normalized version of V_A C filter.

Replace the fixed $325 unr_pnl threshold with an ATR-normalized filter:

  f_unr_atr_T_5m = f_unr_pnl_T_5m / (atr × NQ_MULT)
                 = (close@5m - fill_px) × direction / atr

This is "unrealized excursion in ATR units at +5m". Should be more
robust across vol regimes than a fixed $ threshold.

Plan:
  1. Compute f_unr_atr for each V_A alive @ +5m trade.
  2. Show distribution + relationship to existing $-filter.
  3. Compute IS q80 of f_unr_atr (apples-to-apples with $325 = IS-q80
     of f_unr_pnl_T_5m).
  4. Sweep ATR thresholds {0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0}
     fitted IS-only, applied to all years.
  5. For each: per-year PnL, $/tr, max DD, +months.
  6. Compare to fixed-$ filter on robustness profile.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
OUT = Path("studies/v_a_excursion_regime/results_v0")


def metrics(df, pnl_col, ts_col="entry_ts"):
    if not len(df):
        return {"n": 0, "total": 0.0, "per_tr": 0.0, "wr_pct": 0.0,
                "max_dd": 0.0, "y2024": 0.0, "y2025": 0.0,
                "y2026": 0.0, "pos_months": 0, "total_months": 0}
    df = df.sort_values(ts_col).copy()
    total = df[pnl_col].sum()
    n = len(df)
    wr_pct = (df[pnl_col] > 0).mean() * 100
    df["cum"] = df[pnl_col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    max_dd = float((df["cum"] - df["cum_max"]).min())
    y = df.groupby("year")[pnl_col].sum()
    df["entry_dt"] = pd.to_datetime(df[ts_col], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.to_period("M")
    monthly = df.groupby("month")[pnl_col].sum()
    return {
        "n": n, "total": float(total), "per_tr": float(total / n),
        "wr_pct": float(wr_pct), "max_dd": max_dd,
        "y2024": float(y.get(2024, 0.0)),
        "y2025": float(y.get(2025, 0.0)),
        "y2026": float(y.get(2026, 0.0)),
        "pos_months": int((monthly > 0).sum()),
        "total_months": int(len(monthly)),
    }


def main():
    t0 = time.time()
    print("=" * 78)
    print("ATR-NORMALIZED C FILTER  (vs fixed $325 baseline)")
    print("=" * 78)

    feats = pd.read_parquet(OUT / "checkpoint_features.parquet")
    n_pre = len(feats)
    feats = feats.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    if n_pre != len(feats):
        print(f"  deduped: {n_pre:,} -> {len(feats):,}")

    alive = feats[feats["alive_5m"]].copy()
    alive["f_unr_atr_T_5m"] = (
        alive["f_unr_pnl_T_5m"] / (alive["atr"] * NQ_MULT))
    print(f"\n  V_A alive @ +5m cohort: {len(alive):,}")
    print(f"  ATR distribution: median={alive['atr'].median():.2f}  "
          f"p25={alive['atr'].quantile(0.25):.2f}  "
          f"p75={alive['atr'].quantile(0.75):.2f}  "
          f"p90={alive['atr'].quantile(0.90):.2f}")

    # ===== Existing fixed-$ filter implicit ATR multiple =====
    print(f"\n{'='*78}")
    print("CURRENT FIXED-$ FILTER  ($325)  EXPRESSED IN ATR")
    print(f"{'='*78}")
    is_alive = alive[alive["year"].isin([2024, 2025])]
    thr_dollar = is_alive["f_unr_pnl_T_5m"].quantile(0.80)
    print(f"  IS-q80 fixed threshold: ${thr_dollar:.0f}")
    # For each trade in C cohort, what was the ATR-equivalent threshold?
    c_pop = alive[alive["f_unr_pnl_T_5m"] >= thr_dollar].copy()
    c_pop["atr_mult_at_threshold"] = thr_dollar / (
        c_pop["atr"] * NQ_MULT)
    print(f"\n  ATR-multiple of $325 by trade ATR (in C cohort, n={len(c_pop):,}):")
    print(f"    median: {c_pop['atr_mult_at_threshold'].median():.3f} ATR")
    print(f"    p25:    {c_pop['atr_mult_at_threshold'].quantile(0.25):.3f} ATR")
    print(f"    p75:    {c_pop['atr_mult_at_threshold'].quantile(0.75):.3f} ATR")
    print(f"    range:  [{c_pop['atr_mult_at_threshold'].min():.3f}, "
          f"{c_pop['atr_mult_at_threshold'].max():.3f}] ATR")
    print(f"\n  In other words: $325 means a 0.4-3+ ATR move depending")
    print(f"  on the trade's ATR. For low-ATR trades (atr~3), $325 = ~5 ATR")
    print(f"  excursion; for high-ATR trades (atr~15), $325 = ~1 ATR.")
    print(f"  This is structural noise in the filter.")

    # ===== Distribution of f_unr_atr_T_5m =====
    print(f"\n{'='*78}")
    print("DISTRIBUTION OF f_unr_atr_T_5m  (alive @ +5m, all years)")
    print(f"{'='*78}")
    f = alive["f_unr_atr_T_5m"]
    print(f"  min: {f.min():.3f}  max: {f.max():.3f}")
    for q in [0.05, 0.10, 0.25, 0.50, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
        v = f.quantile(q)
        print(f"  q={q:.2f}: {v:+.3f} ATR")

    # ===== ATR threshold sweep =====
    print(f"\n{'='*78}")
    print("ATR THRESHOLD SWEEP — KEEP IF f_unr_atr_T_5m >= X")
    print(f"  Each row: IS-fit nothing (fixed thresholds), evaluate all yrs")
    print(f"{'='*78}")
    print(f"  {'thr':<6}  {'n':>5}  {'total$':>10}  {'$/tr':>7}  "
          f"{'WR%':>5}  {'max DD':>10}  "
          f"{'2024':>9}  {'2025':>9}  {'2026':>9}  {'+mo':>6}")
    print("  " + "-" * 100)
    for thr in [0.0, 0.10, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60,
                  0.75, 1.00, 1.25, 1.50, 2.00]:
        sub = alive[alive["f_unr_atr_T_5m"] >= thr].copy()
        if len(sub) == 0: continue
        m = metrics(sub, "d_pnl_5m")
        pos = f"{m['pos_months']}/{m['total_months']}"
        print(f"  {thr:<6.2f}  {m['n']:>5,}  ${m['total']:>+8,.0f}  "
              f"{m['per_tr']:>+6.2f}  {m['wr_pct']:>4.1f}  "
              f"${m['max_dd']:>+8,.0f}  "
              f"${m['y2024']:>+7,.0f}  ${m['y2025']:>+7,.0f}  "
              f"${m['y2026']:>+7,.0f}  {pos:>6}")

    # ===== IS-fit ATR threshold (q80 to match $-filter methodology) =====
    print(f"\n{'='*78}")
    print("IS-FIT ATR THRESHOLDS (parallel to fixed-$ q80 method)")
    print(f"{'='*78}")
    for q in [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90]:
        thr = is_alive["f_unr_atr_T_5m"].quantile(q)
        sub = alive[alive["f_unr_atr_T_5m"] >= thr]
        if len(sub) == 0: continue
        m = metrics(sub, "d_pnl_5m")
        pos = f"{m['pos_months']}/{m['total_months']}"
        print(f"  IS-q={q:.2f}  thr={thr:+.3f} ATR  n={m['n']:>5,}  "
              f"${m['total']:>+9,.0f}  {m['per_tr']:>+6.2f}/tr  "
              f"DD ${m['max_dd']:>+8,.0f}  "
              f"24=${m['y2024']:>+7,.0f}  "
              f"25=${m['y2025']:>+7,.0f}  "
              f"26=${m['y2026']:>+7,.0f}  +mo={pos}")

    # ===== Direct comparison: $325 vs ATR-equivalents =====
    print(f"\n{'='*78}")
    print("HEAD-TO-HEAD: fixed-$ vs ATR-normalized filters")
    print(f"{'='*78}")
    # Fixed $325 baseline (current C strategy)
    sub_dollar = alive[alive["f_unr_pnl_T_5m"] >= thr_dollar]
    m_dollar = metrics(sub_dollar, "d_pnl_5m")

    # ATR-normalized at IS-q80 (matches methodology)
    thr_atr_q80 = is_alive["f_unr_atr_T_5m"].quantile(0.80)
    sub_atr_q80 = alive[alive["f_unr_atr_T_5m"] >= thr_atr_q80]
    m_atr_q80 = metrics(sub_atr_q80, "d_pnl_5m")

    # ATR-normalized at simple round threshold (e.g., 1.0 ATR)
    candidates = [0.50, 0.75, 1.00, 1.25, 1.50]
    rows = []
    rows.append(("Current C ($325 IS-q80)", m_dollar))
    rows.append((f"ATR IS-q80 ({thr_atr_q80:+.3f})", m_atr_q80))
    for thr in candidates:
        sub = alive[alive["f_unr_atr_T_5m"] >= thr]
        rows.append((f"ATR fixed >= {thr:.2f}", metrics(sub, "d_pnl_5m")))

    print(f"  {'filter':<32}  {'n':>5}  {'total$':>10}  {'$/tr':>7}  "
          f"{'WR%':>5}  {'DD':>9}  "
          f"{'2024':>9}  {'2025':>9}  {'2026':>9}  {'+mo':>6}")
    for label, m in rows:
        pos = f"{m['pos_months']}/{m['total_months']}"
        print(f"  {label:<32}  {m['n']:>5,}  ${m['total']:>+8,.0f}  "
              f"{m['per_tr']:>+6.2f}  {m['wr_pct']:>4.1f}  "
              f"${m['max_dd']:>+7,.0f}  "
              f"${m['y2024']:>+7,.0f}  ${m['y2025']:>+7,.0f}  "
              f"${m['y2026']:>+7,.0f}  {pos:>6}")

    # ===== ATR regime analysis =====
    print(f"\n{'='*78}")
    print("PER-YEAR ATR REGIME (alive @ +5m)")
    print(f"{'='*78}")
    print(f"  {'year':<6}  {'n':>5}  {'med ATR':>8}  {'p25 ATR':>8}  "
          f"{'p75 ATR':>8}  {'p90 ATR':>8}")
    for yr in (2024, 2025, 2026):
        sub = alive[alive["year"] == yr]
        a = sub["atr"]
        print(f"  {yr:<6}  {len(sub):>5,}  "
              f"{a.median():>7.2f}  {a.quantile(0.25):>7.2f}  "
              f"{a.quantile(0.75):>7.2f}  {a.quantile(0.90):>7.2f}")

    # Are 2024/2025/2026 trades getting different relative selection
    # under fixed $ vs ATR?
    print(f"\n{'='*78}")
    print("FILTER SELECTIVITY BY YEAR (% of alive cohort that PASSES)")
    print(f"{'='*78}")
    print(f"  {'year':<6}  {'fixed$':>8}  {'ATR>=0.5':>10}  "
          f"{'ATR>=0.75':>10}  {'ATR>=1.0':>10}")
    for yr in (2024, 2025, 2026):
        sub = alive[alive["year"] == yr]
        n = len(sub)
        for_dollar = (sub["f_unr_pnl_T_5m"] >= thr_dollar).sum()
        for_05 = (sub["f_unr_atr_T_5m"] >= 0.5).sum()
        for_075 = (sub["f_unr_atr_T_5m"] >= 0.75).sum()
        for_10 = (sub["f_unr_atr_T_5m"] >= 1.0).sum()
        print(f"  {yr:<6}  {100*for_dollar/n:>6.1f}%  "
              f"{100*for_05/n:>9.1f}%  "
              f"{100*for_075/n:>9.1f}%  "
              f"{100*for_10/n:>9.1f}%")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
