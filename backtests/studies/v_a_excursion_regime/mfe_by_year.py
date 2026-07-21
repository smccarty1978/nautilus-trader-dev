"""MFE distribution for no-flip cohort, bucketed by year.

Builds the no-flip cohort per year (with roll-day exclusion) and computes
MFE at multiple horizons. Reports per-year distribution + % at key
thresholds.

Also computes time-to-flip-in-direction per year, so we can see if the
'eventually flip' pattern is regime-stable.
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from bracket_2025_2026 import (
    build_schedule, PRE_FLIP_OOS, COLLECTOR_DIR,
    TOP_QUANTILE, ROLL_EXCL_DAYS,
)
from bracket_grid_2024_2025 import (
    load_year_bars_and_flips, apply_roll_filter_year,
)


OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/mfe_by_year")
HORIZONS_S = [15, 30, 60, 120, 300, 600, 1200, 1800]
MFE_THRESHOLDS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]


def compute_mfe_for_year(year, oos_df, threshold):
    print(f"\n{'='*78}")
    print(f"YEAR {year}")
    print(f"{'='*78}")
    t0 = time.time()
    sched = build_schedule(
        oos_df, year, threshold,
        f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
        f"{COLLECTOR_DIR}/v_a_v0_{year}/"
        f"snapshots_with_vol_vwap.parquet")
    n_pre = len(sched)
    sched, n_drop = apply_roll_filter_year(sched, year)
    print(f"  Schedule: {n_pre:,} → {len(sched):,} after roll-day "
          f"exclusion (-{n_drop})")

    bar_ts, bar_open, bar_high, bar_low, bar_close, fu, fd = \
        load_year_bars_and_flips(year)

    # No-flip cohort only
    nf = sched[~sched["is_va_confirm"]].copy().reset_index(drop=True)
    print(f"  No-flip cohort: {len(nf):,}")

    rows = []
    for _, tr in nf.iterrows():
        ets = int(tr["entry_ts_ns"])
        d = int(tr["direction"])
        atr = float(tr["atr_at_signal"])
        eidx = int(np.searchsorted(bar_ts, ets, side="right"))
        if eidx >= len(bar_ts):
            continue
        entry_px = float(bar_open[eidx])

        # Time to next regime flip in direction
        flips_dir = fu if d == 1 else fd
        f_after = flips_dir[flips_dir > ets]
        tof_s = ((int(f_after[0]) - ets) / 1e9) if len(f_after) else np.nan

        row = {
            "entry_ts_ns": ets,
            "direction": d,
            "atr_at_signal": atr,
            "time_to_flip_s": tof_s,
        }
        for h in HORIZONS_S:
            end_ts = ets + h * 1_000_000_000
            idx1 = int(np.searchsorted(bar_ts, end_ts, side="right"))
            idx1 = min(idx1, len(bar_ts))
            if idx1 <= eidx:
                row[f"mfe_atr_{h}s"] = np.nan
                continue
            if d == 1:
                mfe_pts = max(bar_high[eidx:idx1].max() - entry_px, 0)
            else:
                mfe_pts = max(entry_px - bar_low[eidx:idx1].min(), 0)
            row[f"mfe_atr_{h}s"] = mfe_pts / atr if atr > 0 else np.nan
        rows.append(row)
    res = pd.DataFrame(rows)
    res["year"] = year
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res.to_parquet(OUT_DIR / f"mfe_{year}.parquet", index=False)
    print(f"  Computed in {time.time()-t0:.0f}s")

    del bar_ts, bar_open, bar_high, bar_low, bar_close
    gc.collect()
    return res


def print_per_year_table(results_by_year):
    """Per-year MFE distribution table."""
    for year, df in results_by_year.items():
        print(f"\n{'='*92}")
        print(f"YEAR {year} — No-flip cohort MFE distribution "
              f"(n={len(df):,})")
        print(f"{'='*92}")
        print(f"  {'horizon':<10} {'mean':>7} {'median':>8} "
              f"{'p75':>7} {'p90':>7} "
              f"{'≥0.5atr':>9} {'≥1.0atr':>9} {'≥1.5atr':>9} "
              f"{'≥2.0atr':>9} {'≥2.5atr':>9}")
        for h in HORIZONS_S:
            col = f"mfe_atr_{h}s"
            v = df[col].dropna()
            if len(v) == 0:
                continue
            p50, p75, p90 = v.quantile([0.5, 0.75, 0.9]).tolist()
            print(f"  {h:>5}s     {v.mean():>7.3f} {p50:>8.3f} "
                  f"{p75:>7.3f} {p90:>7.3f} "
                  f"{(v>=0.5).mean():>8.1%} "
                  f"{(v>=1.0).mean():>8.1%} "
                  f"{(v>=1.5).mean():>8.1%} "
                  f"{(v>=2.0).mean():>8.1%} "
                  f"{(v>=2.5).mean():>8.1%}")


def print_time_to_flip_table(results_by_year):
    """Per-year eventual regime-flip distribution."""
    print(f"\n{'='*92}")
    print(f"EVENTUAL REGIME FLIP IN DIRECTION — per-year cumulative %")
    print(f"{'='*92}")
    buckets = [60, 120, 300, 600, 1200, 1800, 3600]
    print(f"  {'year':<6} {'n':>5}  "
          + "  ".join(f"≤{b:>5}s" for b in buckets) + "   never")
    for year, df in results_by_year.items():
        tof = df["time_to_flip_s"]
        cells = []
        for b in buckets:
            pct = (tof <= b).mean()
            cells.append(f"{pct:>6.1%}")
        never_pct = tof.isna().mean()
        print(f"  {year:<6} {len(df):>5,}  " + "  ".join(cells)
              + f"  {never_pct:>5.1%}")


def print_year_over_year_comparison(results_by_year):
    """Cross-year comparison at key horizons."""
    print(f"\n{'='*92}")
    print(f"CROSS-YEAR COMPARISON — % of no-flip trades reaching MFE threshold")
    print(f"{'='*92}")
    for h in [60, 120, 300, 600, 1200]:
        print(f"\n  Horizon {h}s:")
        col = f"mfe_atr_{h}s"
        print(f"    {'thresh':<10}  " + "  ".join(
            f"{year}" for year in results_by_year.keys()))
        for tp in MFE_THRESHOLDS:
            row_vals = []
            for year, df in results_by_year.items():
                v = df[col].dropna()
                if len(v) == 0:
                    row_vals.append("    -")
                else:
                    pct = (v >= tp).mean()
                    row_vals.append(f"{pct:>5.1%}")
            print(f"    ≥{tp:.1f} ATR  " + "  ".join(row_vals))


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    oos = pd.read_parquet(PRE_FLIP_OOS)
    threshold = oos["p_score"].quantile(1 - TOP_QUANTILE)
    print(f"Threshold: p >= {threshold:.4f}")

    results = {}
    for year in [2024, 2025, 2026]:
        results[year] = compute_mfe_for_year(year, oos, threshold)

    print_per_year_table(results)
    print_time_to_flip_table(results)
    print_year_over_year_comparison(results)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
