"""Path shape diagnostic — are bad years bad entries or bad exits?

For the hmm_4 flip state 3 cohort (NT-validated), examine PATH shape
of each trade between bar1-close entry and regime-exit:

  - MFE distribution per year group
  - % never reach +0.25 / hit +0.5 / +1.0 / +1.5 ATR
  - +1 ATR before -1 ATR first-touch race
  - Positive-then-lost frequency (MFE > 0 but final PnL < 0)
  - Time to max MFE
  - Median MFE / MAE
  - Regime-exit EV

Answers one of:
  A. Bad years rarely reach +0.5 → state/entry is weak → dead.
  B. Bad years often hit +0.5/+1 but give it back at regime flip
     → regime-flip exit is wrong → test profit-lock / partial / BE.
  C. Bad years hit +1 ATR similarly to 2025 but fail runners
     → use partial/trailing, not regime-exit.
  D. 2025 uniquely reaches +1.5/+2 ATR (amplitude unique to that year)
     → edge depends on volatility-amplitude regime.
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
OUT = Path("studies/regime_classification/results")
ONE_S = {y: f"data/raw/{PRODUCT}_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = f"data/raw/{PRODUCT}_v0_1s_2026_ytd.parquet"


@njit
def compute_path_features(entry_ts, exit_ts, entry_px, dir_arr, atr_arr,
                            ts_1s, h_1s, l_1s):
    """For each trade: find first +1 ATR touch, first -1 ATR touch,
    and time/value of max MFE."""
    n = len(entry_ts)
    first_plus1_ts  = np.full(n, -1, dtype=np.int64)
    first_minus1_ts = np.full(n, -1, dtype=np.int64)
    max_mfe_ts      = np.full(n, -1, dtype=np.int64)
    max_mfe_val_atr = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; T1 = exit_ts[k]
        ep = entry_px[k]; d = dir_arr[k]; atr = atr_arr[k]
        if T0 < 0 or T1 <= T0 or not np.isfinite(ep) or atr <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, T1, side="left")
        if i_hi <= i_lo:
            continue
        target_plus  = ep + d * atr
        target_minus = ep - d * atr
        running_max_mfe = 0.0
        running_max_mfe_idx = -1
        for j in range(i_lo, i_hi):
            h = h_1s[j]; l = l_1s[j]
            if d == 1:
                bar_mfe = h - ep
                hit_plus  = h >= target_plus
                hit_minus = l <= target_minus
            else:
                bar_mfe = ep - l
                hit_plus  = l <= target_plus
                hit_minus = h >= target_minus
            if bar_mfe > running_max_mfe:
                running_max_mfe = bar_mfe
                running_max_mfe_idx = j
            if first_plus1_ts[k] == -1 and hit_plus:
                first_plus1_ts[k] = ts_1s[j]
            if first_minus1_ts[k] == -1 and hit_minus:
                first_minus1_ts[k] = ts_1s[j]
        if running_max_mfe_idx >= 0:
            max_mfe_ts[k] = ts_1s[running_max_mfe_idx]
            max_mfe_val_atr[k] = running_max_mfe / atr
    return first_plus1_ts, first_minus1_ts, max_mfe_ts, max_mfe_val_atr


def annotate_path(df):
    parts = []
    for y in sorted(df["year"].unique()):
        sub_idx = df.index[df["year"] == y]
        bars_parts = []
        for yy in (y - 1, y, y + 1):
            p = ONE_S.get(yy)
            if p and Path(p).exists():
                bars_parts.append(pd.read_parquet(p, columns=["high", "low"]))
        bars = pd.concat(bars_parts).sort_index()
        bars = bars[~bars.index.duplicated(keep="first")]
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        ts_1s = bars.index.values.astype(np.int64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        sub = df.loc[sub_idx]
        fp, fm, mt, mv = compute_path_features(
            sub["entry_ts"].to_numpy(np.int64),
            sub["exit_ts"].to_numpy(np.int64),
            sub["entry_px"].to_numpy(np.float64),
            sub["signal_direction"].to_numpy(np.int64),
            sub["entry_atr"].to_numpy(np.float64),
            ts_1s, h_1s, l_1s)
        addl = pd.DataFrame({
            "first_plus1_ts": fp,
            "first_minus1_ts": fm,
            "max_mfe_ts": mt,
            "max_mfe_val_atr": mv,
        }, index=sub_idx)
        parts.append(addl)
        print(f"  path {y}: {len(sub):,}")
    return pd.concat(parts)


def report(df, label, years):
    sub = df[df["year"].isin(years)]
    n = len(sub)
    if n == 0:
        return
    # Threshold flags using mfe_atr (max favorable during trade)
    pct_never_025 = (sub["mfe_atr"] < 0.25).mean()
    pct_hit_05    = (sub["mfe_atr"] >= 0.5).mean()
    pct_hit_10    = (sub["mfe_atr"] >= 1.0).mean()
    pct_hit_15    = (sub["mfe_atr"] >= 1.5).mean()
    pct_hit_20    = (sub["mfe_atr"] >= 2.0).mean()
    # +1 before -1 first-touch race
    # plus_first = first_plus1_ts > 0 AND (first_minus1_ts == -1 OR first_plus1_ts < first_minus1_ts)
    has_plus  = sub["first_plus1_ts"] > 0
    has_minus = sub["first_minus1_ts"] > 0
    plus_first = has_plus & ((~has_minus) |
                              (sub["first_plus1_ts"] < sub["first_minus1_ts"]))
    pct_plus_before_minus = plus_first.mean()
    # Of trades that did hit +1, what fraction won?
    of_plus_hit = sub[has_plus]
    pct_plus_then_win = (of_plus_hit["win"] == 1).mean() if len(of_plus_hit) else float("nan")
    # Positive-then-lost
    pos_then_lost = ((sub["mfe_atr"] > 0.5) & (sub["pnl_atr"] < 0)).mean()
    # Medians
    med_mfe = sub["mfe_atr"].median()
    med_mae = sub["mae_atr"].median()
    # Regime-exit EV
    ev = sub["pnl_atr"].mean()
    # Time to peak (median, in min)
    time_to_peak_sec = (sub["max_mfe_ts"] - sub["entry_ts"]) / NS
    med_t_peak_min = time_to_peak_sec[time_to_peak_sec >= 0].median() / 60

    print(f"\n  {label}  n={n:,}")
    print(f"    never reach +0.25 ATR:  {pct_never_025:>5.1%}")
    print(f"    hit +0.5 ATR:           {pct_hit_05:>5.1%}")
    print(f"    hit +1.0 ATR:           {pct_hit_10:>5.1%}")
    print(f"    hit +1.5 ATR:           {pct_hit_15:>5.1%}")
    print(f"    hit +2.0 ATR:           {pct_hit_20:>5.1%}")
    print(f"    +1 ATR before -1 ATR:   {pct_plus_before_minus:>5.1%}")
    print(f"    of trades hitting +1:")
    print(f"      % ending in win:      {pct_plus_then_win:>5.1%}  "
          f"(n_hit_plus={len(of_plus_hit)})")
    print(f"    positive (MFE>+0.5) → lost: {pos_then_lost:>5.1%}")
    print(f"    median MFE (ATR):       {med_mfe:>+6.3f}")
    print(f"    median MAE (ATR):       {med_mae:>+6.3f}")
    print(f"    median time-to-peak:    {med_t_peak_min:>5.1f} min")
    print(f"    regime-exit EV (ATR):   {ev:>+6.3f}")


def main():
    t0 = time.time()
    p = OUT / f"diagnose_2025_{PRODUCT.lower()}.parquet"
    df = pd.read_parquet(p)
    df = df.reset_index(drop=True)
    df["entry_ts"] = df["entry_ts"].astype(np.int64)
    df["exit_ts"]  = df["exit_ts"].astype(np.int64)
    df["signal_direction"] = df["signal_direction"].astype(np.int64)
    print(f"Loaded {len(df):,} OOS trades from {p.name}")

    print("Computing path features (first-touch race, time-to-peak) ...")
    addl = annotate_path(df)
    df = pd.concat([df, addl], axis=1)

    # ── Year-group reports ──
    print(f"\n{'='*88}\n PATH SHAPE BY YEAR GROUP\n{'='*88}")
    report(df, "BAD (2023+2024)", (2023, 2024))
    report(df, "GOOD (2025)",     (2025,))
    report(df, "PARTIAL (2026)",  (2026,))

    # ── Individual years ──
    print(f"\n{'='*88}\n PATH SHAPE PER OOS YEAR\n{'='*88}")
    for y in (2023, 2024, 2025, 2026):
        report(df, str(y), (y,))

    # ── MFE distribution table (percentiles per group) ──
    print(f"\n{'='*88}\n MFE DISTRIBUTION (ATR units, percentiles) by group\n{'='*88}")
    print(f"  {'group':<18}{'10%':>8}{'25%':>8}{'50%':>8}{'75%':>8}{'90%':>8}{'95%':>8}{'99%':>8}{'max':>8}")
    for label, years in (("BAD (23+24)", (2023, 2024)),
                          ("GOOD (25)", (2025,)),
                          ("PART (26)", (2026,))):
        sub = df[df["year"].isin(years)]
        if len(sub) == 0:
            continue
        m = sub["mfe_atr"].dropna()
        qs = m.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]).values
        mx = m.max()
        print(f"  {label:<18}"
              f"{qs[0]:>+8.3f}{qs[1]:>+8.3f}{qs[2]:>+8.3f}{qs[3]:>+8.3f}"
              f"{qs[4]:>+8.3f}{qs[5]:>+8.3f}{qs[6]:>+8.3f}{mx:>+8.3f}")

    # ── Save enriched parquet ──
    out_p = OUT / f"path_shape_{PRODUCT.lower()}.parquet"
    df.to_parquet(out_p, index=False)
    print(f"\nsaved {out_p}")
    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
