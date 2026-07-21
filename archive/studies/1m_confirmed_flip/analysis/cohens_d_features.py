"""Cohen's d separation: which features predict PT-first vs SL-first?

For each candidate feature, compute Cohen's d between PT-first and
SL-first populations at two brackets (0.75/0.75 and 1.0/0.5).
Quintile analysis on |d| > 0.10. Year stability on > 0.15.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time as _time
import pandas as pd
import numpy as np
from numba import njit

from nautilus_trader.persistence.catalog import ParquetDataCatalog


@njit(cache=True)
def race_bracket(entry_px, direction, atr,
                 h_arr, l_arr,
                 pt_atr, sl_atr):
    n = len(h_arr)
    if n == 0 or atr <= 0:
        return 3  # neither
    pt_px = entry_px + direction * pt_atr * atr
    sl_px = entry_px - direction * sl_atr * atr
    for i in range(n):
        h = h_arr[i]
        l = l_arr[i]
        if direction == 1:
            pt_hit = h >= pt_px
            sl_hit = l <= sl_px
        else:
            pt_hit = l <= pt_px
            sl_hit = h >= sl_px
        if pt_hit and sl_hit:
            return 0  # both same bar — call it PT (optimistic)
        if pt_hit:
            return 0
        if sl_hit:
            return 1
    return 3


def cohens_d(g1, g2):
    g1 = np.asarray(g1, dtype=np.float64)
    g2 = np.asarray(g2, dtype=np.float64)
    g1 = g1[~np.isnan(g1)]
    g2 = g2[~np.isnan(g2)]
    if len(g1) < 2 or len(g2) < 2:
        return np.nan
    n1, n2 = len(g1), len(g2)
    m1, m2 = g1.mean(), g2.mean()
    v1, v2 = g1.var(ddof=1), g2.var(ddof=1)
    pooled = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    if pooled == 0:
        return 0.0
    return (m1 - m2) / pooled


def print_d_table(features, d_table, header):
    print(f"\n{header}")
    print("-" * 92)
    print(f"  {'Feature':<32} {'d':>7}  {'PT-1st avg':>11}  "
          f"{'SL-1st avg':>11}  {'PT N':>7}  {'SL N':>7}")
    print("-" * 92)
    sorted_d = sorted(d_table, key=lambda r: -abs(r["d"]))
    for r in sorted_d:
        flag = " ★" if abs(r["d"]) >= 0.20 else (
               " ·" if abs(r["d"]) >= 0.10 else "")
        print(f"  {r['name']:<32} {r['d']:>+7.3f}  "
              f"{r['pt_avg']:>+11.4f}  {r['sl_avg']:>+11.4f}  "
              f"{r['pt_n']:>7,}  {r['sl_n']:>7,}{flag}")


def quintile_analysis(name, vals, race_outcomes, regime_pnl, atr,
                       pt_atr, sl_atr):
    """Bucket trades by feature value, show PT-1st%, SL-1st%, avg PnL.

    PnL = if PT first: +pt_atr * atr * 20 - 5
          if SL first: -sl_atr * atr * 20 - 5
          if neither: regime_pnl_dollars
    """
    df = pd.DataFrame({
        "v": vals, "outcome": race_outcomes, "atr": atr,
        "regime_pnl": regime_pnl,
    })
    df = df.dropna(subset=["v"])
    nq_mult = 20.0
    comm = 5.0
    pnl = np.where(df["outcome"] == 0,
                    pt_atr * df["atr"] * nq_mult - comm,
                    np.where(df["outcome"] == 1,
                              -sl_atr * df["atr"] * nq_mult - comm,
                              df["regime_pnl"]))
    df["pnl"] = pnl

    # Quintiles
    df["q"] = pd.qcut(df["v"], q=5, duplicates="drop", labels=False)
    if df["q"].max() < 4:
        return None

    print(f"\n  Quintiles for {name}:")
    print(f"    {'Q':>2} {'Range':>20} {'N':>7} {'PT%':>7} {'SL%':>7} "
          f"{'Neither%':>9} {'Avg$':>8} {'WR':>6}")
    for q in sorted(df["q"].unique()):
        sub = df[df["q"] == q]
        v_lo = sub["v"].min()
        v_hi = sub["v"].max()
        pt_pct = (sub["outcome"] == 0).mean() * 100
        sl_pct = (sub["outcome"] == 1).mean() * 100
        nei_pct = (sub["outcome"] == 3).mean() * 100
        avg_pnl = sub["pnl"].mean()
        wr = (sub["pnl"] > 0).mean() * 100
        print(f"    Q{int(q)+1} [{v_lo:>+8.3f}, {v_hi:>+8.3f}] "
              f"{len(sub):>6,} {pt_pct:>6.1f}% {sl_pct:>6.1f}% "
              f"{nei_pct:>8.1f}% ${avg_pnl:>+7.1f} {wr:>5.1f}%")


def main():
    print("=" * 92)
    print("COHEN'S d FEATURE SEPARATION — confirmed flip entries (6 years)")
    print("=" * 92)

    print("\nLoading trades...")
    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    print(f"  {len(trades):,} trades")

    print("\nLoading 1s bars (6 years)...")
    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")

    print("Extracting...")
    t0 = _time.time()
    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    high_arr = np.empty(n)
    low_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        high_arr[i] = float(b.high)
        low_arr[i] = float(b.low)
    del bars_1s
    print(f"  Done ({_time.time()-t0:.0f}s)")

    entry_walk = trades["entry_ts"].astype("int64").values + 60_000_000_000
    exit_walk = (pd.to_datetime(trades["exit_time"]).astype("int64").values
                 + 60_000_000_000)
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr_arr = trades["atr_at_flip"].values

    # Pre-slice
    h_list = [None] * len(trades)
    l_list = [None] * len(trades)
    for k in range(len(trades)):
        i_start = np.searchsorted(ts_arr, entry_walk[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_walk[k], side="right")
        h_list[k] = high_arr[i_start:i_end]
        l_list[k] = low_arr[i_start:i_end]

    # JIT warmup
    race_bracket(100.0, 1, 1.0,
                  np.array([100.0]), np.array([100.0]), 1.0, 1.0)

    # Race both brackets
    print("\nRacing brackets...")
    t0 = _time.time()
    out_75 = np.empty(len(trades), dtype=np.int32)
    out_10_05 = np.empty(len(trades), dtype=np.int32)
    for k in range(len(trades)):
        if atr_arr[k] <= 0 or len(h_list[k]) == 0:
            out_75[k] = 3
            out_10_05[k] = 3
            continue
        out_75[k] = race_bracket(
            entry_px[k], direction[k], atr_arr[k],
            h_list[k], l_list[k], 0.75, 0.75)
        out_10_05[k] = race_bracket(
            entry_px[k], direction[k], atr_arr[k],
            h_list[k], l_list[k], 1.00, 0.50)
    print(f"  Done ({_time.time()-t0:.0f}s)")
    print(f"  0.75/0.75: PT={(out_75==0).sum():,} SL={(out_75==1).sum():,} "
          f"Neither={(out_75==3).sum():,}")
    print(f"  1.00/0.50: PT={(out_10_05==0).sum():,} "
          f"SL={(out_10_05==1).sum():,} Neither={(out_10_05==3).sum():,}")

    trades["race_75"] = out_75
    trades["race_10_05"] = out_10_05

    # Compute derived features
    trades["flip_close_dir"] = (
        np.sign(trades["flip_bar_close"] - trades["flip_bar_open"])
        * trades["direction"])  # +1 = close in flip direction
    trades["flip_upper_wick_pct"] = (
        (trades["flip_bar_high"] - np.maximum(
            trades["flip_bar_open"], trades["flip_bar_close"]))
        / trades["flip_bar_range"].replace(0, np.nan))
    trades["flip_lower_wick_pct"] = (
        (np.minimum(trades["flip_bar_open"], trades["flip_bar_close"])
         - trades["flip_bar_low"])
        / trades["flip_bar_range"].replace(0, np.nan))
    trades["range_x_body"] = (trades["flip_bar_range_atr"]
                               * trades["flip_bar_body_pct"])
    trades["vol_x_body"] = (trades["flip_bar_vol_vs_20avg"]
                             * trades["flip_bar_body_pct"])
    trades["dir_x_slope"] = trades["direction"] * trades["ema3_slope"]
    trades["abs_ema_spread"] = trades["ema3_ema9_spread"].abs()
    trades["minutes_since_rth_open"] = np.where(
        trades["is_rth"] == 1,
        (trades["hour_ct"] - 8) * 60 - 30,  # approx
        np.nan)

    # Feature list
    features = [
        # Flip bar
        ("flip_bar_range_atr", trades["flip_bar_range_atr"].values),
        ("flip_bar_body_pct", trades["flip_bar_body_pct"].values),
        ("flip_close_dir", trades["flip_close_dir"].values),
        ("flip_bar_close_location", trades["flip_bar_close_location"].values),
        ("flip_upper_wick_pct", trades["flip_upper_wick_pct"].values),
        ("flip_lower_wick_pct", trades["flip_lower_wick_pct"].values),
        ("flip_bar_volume", trades["flip_bar_volume"].values),
        ("flip_bar_vol_vs_20avg", trades["flip_bar_vol_vs_20avg"].values),
        # Regime context
        ("direction", trades["direction"].values.astype(float)),
        ("prior_regime_duration_bars",
         trades["prior_regime_duration_bars"].values.astype(float)),
        ("ema3_slope", trades["ema3_slope"].values),
        ("ema_spread", trades["ema_spread"].values),
        ("ema3_ema9_spread", trades["ema3_ema9_spread"].values),
        ("atr_at_flip", trades["atr_at_flip"].values),
        ("atr_relative", trades["atr_relative"].values),
        # Time/session
        ("hour_ct", trades["hour_ct"].values.astype(float)),
        ("is_rth", trades["is_rth"].values.astype(float)),
        # Bar+1 features
        ("bar1_range_atr", trades["bar1_range_atr"].values),
        ("bar1_body_pct", trades["bar1_body_pct"].values),
        ("bar1_hh_amount_atr", trades["bar1_hh_amount_atr"].values),
        # Derived
        ("range_x_body", trades["range_x_body"].values),
        ("vol_x_body", trades["vol_x_body"].values),
        ("dir_x_slope", trades["dir_x_slope"].values),
        ("abs_ema_spread", trades["abs_ema_spread"].values),
    ]

    # ----- Compute d for each bracket -----
    for bracket_name, race_col in [("0.75 / 0.75", "race_75"),
                                    ("1.00 / 0.50", "race_10_05")]:
        out = trades[race_col].values
        pt_mask = out == 0
        sl_mask = out == 1
        d_table = []
        for fname, vals in features:
            d = cohens_d(vals[pt_mask], vals[sl_mask])
            pt_avg = np.nanmean(vals[pt_mask]) if pt_mask.any() else np.nan
            sl_avg = np.nanmean(vals[sl_mask]) if sl_mask.any() else np.nan
            d_table.append({
                "name": fname, "d": d,
                "pt_avg": pt_avg, "sl_avg": sl_avg,
                "pt_n": pt_mask.sum(), "sl_n": sl_mask.sum(),
            })

        print_d_table(features, d_table,
                       f"BRACKET {bracket_name} — Cohen's d "
                       f"(PT-first vs SL-first)")

        # Quintile analysis on |d| > 0.10
        pt_atr_v, sl_atr_v = (0.75, 0.75) if "0.75" in bracket_name \
            else (1.00, 0.50)
        regime_pnl = trades["regime_pnl_dollars"].values
        promising = [r for r in d_table if abs(r["d"]) >= 0.10]
        if promising:
            print(f"\nQUINTILE ANALYSIS — features with |d| >= 0.10 "
                  f"(bracket {bracket_name}):")
            for r in sorted(promising, key=lambda x: -abs(x["d"])):
                vals = dict(features)[r["name"]]
                quintile_analysis(r["name"], vals, out, regime_pnl,
                                   atr_arr, pt_atr_v, sl_atr_v)
        else:
            print(f"\n  No features with |d| >= 0.10 for {bracket_name}.")

    # ---- Year stability for top features (bracket 0.75/0.75) ----
    print(f"\n{'='*92}")
    print(f"YEAR-BY-YEAR STABILITY — top features (bracket 0.75/0.75)")
    print(f"{'='*92}")
    out_75 = trades["race_75"].values
    pt_mask = out_75 == 0
    sl_mask = out_75 == 1
    d_table = []
    for fname, vals in features:
        d = cohens_d(vals[pt_mask], vals[sl_mask])
        d_table.append({"name": fname, "d": d})
    top5 = sorted(d_table, key=lambda r: -abs(r["d"]))[:5]

    for r in top5:
        if abs(r["d"]) < 0.05:
            continue
        vals = dict(features)[r["name"]]
        print(f"\n  Feature: {r['name']} (overall d={r['d']:+.3f})")
        print(f"  {'Year':>6} {'N':>7} {'PT-1st%':>9} {'SL-1st%':>9} "
              f"{'d':>7}")
        for year in sorted(trades["year"].unique()):
            ymask = trades["year"].values == year
            ypt = pt_mask & ymask
            ysl = sl_mask & ymask
            if ypt.sum() < 50 or ysl.sum() < 50:
                continue
            yd = cohens_d(vals[ypt], vals[ysl])
            n_total = ymask.sum()
            print(f"  {year:>6} {n_total:>7,} "
                  f"{ypt.sum()/n_total*100:>8.1f}% "
                  f"{ysl.sum()/n_total*100:>8.1f}% {yd:>+7.3f}")

    # Save
    trades.to_parquet(
        "studies/1m_confirmed_flip/results/cohens_d_classified.parquet",
        index=False)
    print(f"\n  Saved: studies/1m_confirmed_flip/results/"
          f"cohens_d_classified.parquet")
    print(f"\n{'='*92}")


if __name__ == "__main__":
    main()
