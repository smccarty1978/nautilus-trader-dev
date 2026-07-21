"""For armed trades, what % had max MAE BEFORE the arming moment?

Walk 1s bars per trade from entry to exit. For armed trades
(armed_before_exit), find:
  - max_mae_at: index (from entry) of deepest adverse excursion
  - be_armed_at_local: arming moment relative to entry

Report:
  - % of armed trades where max_mae_at < be_armed_at_local
    (i.e., trade dipped before recovering to +2.5)
  - distribution of max MAE for armed trades
  - cross-tab: max_mae_before_arm × outcome
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, filter_roll_window_1s,
)

OUT = Path("studies/level_momentum_continuation/results_1s_precision")


def main():
    for year in (2024, 2025):
        print(f"\n{'='*60}\n[{year}] loading 1s bars...")
        bars_1s = load_v0_1s(
            Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
        bars_1s = annotate_sessions_1s(bars_1s)
        bars_1s = filter_roll_window_1s(bars_1s, 3)
        bars_1s_reset = bars_1s.reset_index(drop=False)
        highs = bars_1s_reset["high"].values
        lows = bars_1s_reset["low"].values

        df = pd.read_csv(OUT / f"trades_1s_{year}.csv")
        df["armed_before_exit"] = (
            (df["be_armed_at_global"] >= 0)
            & (df["be_armed_at_global"]
               <= df["exit_idx_global"]))

        n_total = len(df)
        n_armed = int(df["armed_before_exit"].sum())
        print(f"  total trades: {n_total:,}, "
              f"armed: {n_armed:,} "
              f"({100*n_armed/n_total:.1f}%)")

        # Walk armed trades; compute max MAE timing
        max_mae_pts = np.zeros(n_total)
        max_mae_at_local = np.full(n_total, -1, dtype=int)
        mae_before_arm = np.zeros(n_total, dtype=bool)

        eidx = df["entry_1s_idx"].astype(int).values
        xidx = df["exit_idx_global"].astype(int).values
        baidx = df["be_armed_at_global"].astype(int).values
        di_arr = df["direction"].astype(int).values
        ep_arr = df["entry_px"].astype(float).values
        armed_arr = df["armed_before_exit"].values

        for i in range(n_total):
            ei = eidx[i]
            xi = min(xidx[i], len(highs) - 1)
            if xi < ei:
                continue
            sli_h = highs[ei : xi + 1]
            sli_l = lows[ei : xi + 1]
            ep = ep_arr[i]
            di = di_arr[i]
            if di == 1:
                # Long: MAE = entry - low
                mae_series = ep - sli_l
            else:
                # Short: MAE = high - entry
                mae_series = sli_h - ep
            if len(mae_series) == 0:
                continue
            mx_idx = int(np.argmax(mae_series))
            max_mae_pts[i] = float(mae_series[mx_idx])
            max_mae_at_local[i] = mx_idx

            if armed_arr[i]:
                ba_local = baidx[i] - ei  # arm idx in trade frame
                # MAX MAE BEFORE arm: mx_idx happens strictly
                # before the arming moment
                mae_before_arm[i] = mx_idx < ba_local

        df["max_mae_pts"] = max_mae_pts
        df["max_mae_at_local"] = max_mae_at_local
        df["mae_before_arm"] = mae_before_arm

        armed = df[df["armed_before_exit"]]
        n_a = len(armed)
        n_mb = int(armed["mae_before_arm"].sum())
        print(f"\n[{year}] ARMED TRADES: n={n_a:,}")
        print(f"  Max MAE BEFORE arm: {n_mb:,} "
              f"({100*n_mb/n_a:.1f}%)")
        print(f"  Max MAE AT/AFTER arm: {n_a - n_mb:,} "
              f"({100*(n_a-n_mb)/n_a:.1f}%)")

        # By outcome
        print(f"\n[{year}] mae_before_arm × outcome (armed only):")
        ct = pd.crosstab(armed["mae_before_arm"],
                                armed["outcome"])
        ct_pct = 100 * ct.div(ct.sum(axis=1), axis=0)
        print("--- counts ---")
        print(ct.to_string())
        print("--- row pct (within mae_before_arm group) ---")
        print(ct_pct.round(1).to_string())

        # Win rate split
        print(f"\n[{year}] Win rate by mae_before_arm "
              f"(armed only):")
        for grp, g in armed.groupby("mae_before_arm"):
            n_g = len(g)
            n_w = int((g["outcome"] == "win").sum())
            mean_p = float(g["pnl_net"].mean())
            label = ("MAE before arm (V-shape)"
                     if grp else "MAE at/after arm (run-then-break)")
            print(f"  {label}: n={n_g:,}, "
                  f"WR={100*n_w/n_g:.1f}%, "
                  f"mean PnL net = {mean_p:+.3f} pts")

        # MAE depth distribution
        print(f"\n[{year}] Max MAE depth (pts) distribution "
              f"for armed trades:")
        for grp, g in armed.groupby("mae_before_arm"):
            label = ("MAE before arm" if grp
                     else "MAE at/after arm")
            vals = g["max_mae_pts"]
            p25 = float(np.percentile(vals, 25))
            p50 = float(np.percentile(vals, 50))
            p75 = float(np.percentile(vals, 75))
            p95 = float(np.percentile(vals, 95))
            print(f"  {label}: p25={p25:.2f} p50={p50:.2f} "
                  f"p75={p75:.2f} p95={p95:.2f}")

        df.to_csv(OUT / f"trades_1s_with_mae_{year}.csv",
                       index=False)


if __name__ == "__main__":
    main()
