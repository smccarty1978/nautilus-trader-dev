"""Decompose all-flips C6 cohort by V_A confirmation status.

Question: of the 2,299 trades in all-flips C6 (delayed @+6m + unr ≥ IS-q80),
how many are also V_A-confirmed (HH/LL on bar+1 AND momentum_ok)?
And does the V_A subset account for all positive expectancy, or does
a non-V_A continuation family also profit?

Build is_VA_confirmed for each regime_flip via:
  bar1_check.bar_ts_event = regime_flip.bar_ts_event + 60s
  is_VA_confirmed = bar1_check.confirmed

Then apply the C6 filter (alive_6m AND f_unr_pnl_T_6m >= IS-q80)
and split.

Also reports E8 (delayed @+8m + dual momentum) decomposition.

For each subset, reports:
  n, total $, $/tr, WR, max DD, per-year, positive months,
  survival to +6m / +8m (within the C6 cohort, alive_6m=True by
  construction), forward MFE/MAE from checkpoint.
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
COMMISSION = 5.0
OUT = Path("studies/v_a_excursion_regime/results_v0")


def load_year_bars(year):
    parts = []
    files_for_year = {
        2024: ["data/raw/NQ_v0_1s_2023.parquet",
                "data/raw/NQ_v0_1s_2024.parquet"],
        2025: ["data/raw/NQ_v0_1s_2024.parquet",
                "data/raw/NQ_v0_1s_2025.parquet"],
        2026: ["data/raw/NQ_v0_1s_2025.parquet",
                "data/raw/NQ_v0_1s_2026_ytd.parquet"],
    }
    for f in files_for_year[year]:
        if Path(f).exists():
            df = pd.read_parquet(f, columns=["open","high","low","close"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            parts.append(df)
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    return bars


def build_va_confirmation_lookup():
    """For each regime_flip across years, look up bar1_check confirmed
    flag via bar_ts_event + 60s match. Returns DataFrame keyed by
    (year, decision_ts) with is_VA_confirmed."""
    rows = []
    for yr in (2024, 2025, 2026):
        snap = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/"
            f"snapshots.parquet")
        rf = snap[snap["kind"] == "regime_flip"][
            ["decision_ts", "bar_ts_event", "direction"]].copy()
        b1 = snap[snap["kind"] == "bar1_check"][
            ["bar_ts_event", "direction", "confirmed",
             "hhll_ok", "momentum_ok"]].copy()
        # Match by direction + bar_ts_event_offset
        rf["expected_b1_bts"] = rf["bar_ts_event"] + 60_000_000_000
        rf_lookup = rf.rename(
            columns={"expected_b1_bts": "b1_bar_ts_event",
                       "bar_ts_event": "flip_bar_ts_event"})
        b1 = b1.rename(columns={"bar_ts_event": "b1_bar_ts_event"})
        merged = rf_lookup.merge(
            b1, on=["b1_bar_ts_event", "direction"], how="left")
        merged["year"] = yr
        # Fill NaN confirmed as False (treat unmatched as not confirmed)
        merged["confirmed"] = merged["confirmed"].fillna(False)
        merged["hhll_ok"] = merged["hhll_ok"].fillna(False)
        merged["momentum_ok"] = merged["momentum_ok"].fillna(False)
        rows.append(merged[["year", "decision_ts", "confirmed",
                              "hhll_ok", "momentum_ok"]])
    out = pd.concat(rows, ignore_index=True)
    out = out.rename(columns={"confirmed": "is_VA_confirmed"})
    return out


def compute_forward_excursion(df, cp_col, exit_col, fill_col,
                                 direction_col, atr_col):
    """For each row, compute MFE/MAE from checkpoint to exit using
    bars[cp_ts, exit_ts). Returns arrays of (mfe_atr, mae_atr,
    mfe_pts, mae_pts)."""
    df = df.copy().reset_index(drop=True)
    mfe_atr_arr = np.full(len(df), np.nan)
    mae_atr_arr = np.full(len(df), np.nan)
    mfe_pts_arr = np.full(len(df), np.nan)
    mae_pts_arr = np.full(len(df), np.nan)
    # Process per-year (bar data per-year)
    for yr in df["year"].unique():
        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        mask = (df["year"] == yr).to_numpy()
        idxs = np.where(mask)[0]
        for i in idxs:
            cp_ts = int(df.iloc[i][cp_col])
            ex_ts = int(df.iloc[i][exit_col])
            fill = float(df.iloc[i][fill_col])
            dirn = int(df.iloc[i][direction_col])
            atr = float(df.iloc[i][atr_col])
            i_lo = np.searchsorted(ts_idx, cp_ts, side="left")
            i_hi = np.searchsorted(ts_idx, ex_ts, side="left")
            if i_hi <= i_lo or atr <= 0:
                continue
            seg_h = highs[i_lo:i_hi]
            seg_l = lows[i_lo:i_hi]
            if dirn == 1:
                mfe_pts = float(seg_h.max() - fill)
                mae_pts = float(fill - seg_l.min())
            else:
                mfe_pts = float(fill - seg_l.min())
                mae_pts = float(seg_h.max() - fill)
            mfe_pts_arr[i] = mfe_pts
            mae_pts_arr[i] = mae_pts
            mfe_atr_arr[i] = mfe_pts / atr
            mae_atr_arr[i] = mae_pts / atr
    return mfe_atr_arr, mae_atr_arr, mfe_pts_arr, mae_pts_arr


def metrics(df, pnl_col, ts_col="decision_ts"):
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
    print("DECOMPOSE ALL-FLIPS C6 / E8 BY V_A CONFIRMATION STATUS")
    print("=" * 78)

    # Load all_flips features
    df = pd.read_parquet(OUT / "all_flips_features.parquet")
    n_pre = len(df)
    df = df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset="decision_ts", keep="first").reset_index(drop=True)
    if n_pre != len(df):
        print(f"  deduped cross-year overlaps: {n_pre:,} -> {len(df):,}")

    # Build V_A confirmation lookup
    print("\nBuilding V_A confirmation lookup...")
    va_lookup = build_va_confirmation_lookup()
    print(f"  lookup rows: {len(va_lookup):,}")

    # Merge — match by (year, decision_ts) but be careful about the
    # cross-year dedupe: our df now uses earlier-year for boundary
    # trades. va_lookup has both years. Match by decision_ts only,
    # keep first.
    va_dedup = va_lookup.sort_values(
        ["decision_ts", "year"]).drop_duplicates(
        subset="decision_ts", keep="first")
    df = df.merge(va_dedup[["decision_ts", "is_VA_confirmed",
                                 "hhll_ok", "momentum_ok"]],
                    on="decision_ts", how="left")
    assert df["is_VA_confirmed"].notna().all(), \
        "missing V_A confirmation for some rows"
    df["is_VA_confirmed"] = df["is_VA_confirmed"].astype(bool)
    print(f"  is_VA_confirmed: True={df['is_VA_confirmed'].sum():,} "
          f"False={(~df['is_VA_confirmed']).sum():,}")

    # ===== Refit IS-only filter thresholds =====
    is_alive_6m = df[df["alive_6m"]
                       & df["year"].isin([2024, 2025])
                       & df["f_unr_pnl_T_6m"].notna()]
    assert is_alive_6m["year"].max() <= 2025
    thr_unr_6m = is_alive_6m["f_unr_pnl_T_6m"].quantile(0.80)
    print(f"\n  C6 filter threshold (IS q=0.80): "
          f"f_unr_pnl_T_6m >= ${thr_unr_6m:.0f}")

    is_alive_8m = df[df["alive_8m"]
                       & df["year"].isin([2024, 2025])
                       & df["f_net_move_150s_8m"].notna()
                       & df["f_net_move_300s_8m"].notna()]
    assert is_alive_8m["year"].max() <= 2025
    thr_150_8m = is_alive_8m["f_net_move_150s_8m"].quantile(0.10)
    thr_300_8m = is_alive_8m["f_net_move_300s_8m"].quantile(0.20)
    print(f"  E8 filter thresholds: "
          f"f_net_move_150s >= ${thr_150_8m:.2f}, "
          f"f_net_move_300s >= ${thr_300_8m:.2f}")

    alive_6m = df[df["alive_6m"]].copy()
    alive_8m = df[df["alive_8m"]].copy()
    c6_mask = alive_6m["f_unr_pnl_T_6m"] >= thr_unr_6m
    e8_mask = ((alive_8m["f_net_move_150s_8m"] >= thr_150_8m)
                & (alive_8m["f_net_move_300s_8m"] >= thr_300_8m))

    c6_pop = alive_6m[c6_mask].copy()
    e8_pop = alive_8m[e8_mask].copy()
    print(f"\n  C6 cohort size: {len(c6_pop):,}")
    print(f"  E8 cohort size: {len(e8_pop):,}")

    # ===== Compute forward MFE/MAE from checkpoint =====
    # Window [cp_ts, exit_ts) covers the delayed-trade holding period.
    print("\nComputing forward MFE/MAE from +6m checkpoint (C6)...",
            flush=True)
    c6_pop["cp_ts"] = c6_pop["decision_ts"] + 360_000_000_000
    mfe_a, mae_a, mfe_p, mae_p = compute_forward_excursion(
        c6_pop, "cp_ts", "exit_ts", "price_at_cp_6m",
        "direction", "atr")
    c6_pop["fwd_mfe_atr_c6"] = mfe_a
    c6_pop["fwd_mae_atr_c6"] = mae_a

    print("Computing forward MFE/MAE from +8m checkpoint (E8)...",
            flush=True)
    e8_pop["cp_ts"] = e8_pop["decision_ts"] + 480_000_000_000
    mfe_a, mae_a, mfe_p, mae_p = compute_forward_excursion(
        e8_pop, "cp_ts", "exit_ts", "price_at_cp_8m",
        "direction", "atr")
    e8_pop["fwd_mfe_atr_e8"] = mfe_a
    e8_pop["fwd_mae_atr_e8"] = mae_a

    # ===== Decomposition reports =====
    def print_split_report(pop, pnl_col, fwd_mfe_col, fwd_mae_col,
                              label, cp_lab):
        print(f"\n{'='*120}")
        print(f"DECOMPOSITION — {label}")
        print(f"  Cohort: {len(pop):,} trades")
        print(f"{'='*120}")
        is_va = pop[pop["is_VA_confirmed"]]
        no_va = pop[~pop["is_VA_confirmed"]]
        print(f"  V_A confirmed:  {len(is_va):,} "
              f"({100*len(is_va)/len(pop):.1f}%)")
        print(f"  NOT confirmed:  {len(no_va):,} "
              f"({100*len(no_va)/len(pop):.1f}%)")
        print()
        print(f"  {'subset':<25}  {'n':>5}  {'total$':>10}  "
              f"{'$/tr':>7}  {'WR%':>5}  {'max DD':>10}  "
              f"{'2024':>10}  {'2025':>10}  {'2026':>10}  {'+mo':>6}")
        print("  " + "-" * 118)
        for sub_label, sub in [
            ("ALL " + label, pop),
            ("V_A confirmed", is_va),
            ("NOT confirmed", no_va),
        ]:
            m = metrics(sub, pnl_col)
            pos = f"{m['pos_months']}/{m['total_months']}"
            print(f"  {sub_label:<25}  {m['n']:>5,}  "
                  f"${m['total']:>+8,.0f}  {m['per_tr']:>+6.2f}  "
                  f"{m['wr_pct']:>4.1f}  ${m['max_dd']:>+8,.0f}  "
                  f"${m['y2024']:>+8,.0f}  ${m['y2025']:>+8,.0f}  "
                  f"${m['y2026']:>+8,.0f}  {pos:>6}")

        # Forward MFE/MAE percentiles
        print(f"\n  Forward MFE/MAE from {cp_lab} checkpoint to regime exit:")
        print(f"  {'subset':<25}  {'med_mfe':>8}  {'p25_mfe':>8}  "
              f"{'p75_mfe':>8}  {'p90_mfe':>8}  | "
              f"{'med_mae':>8}  {'p75_mae':>8}  {'p90_mae':>8}")
        for sub_label, sub in [
            ("ALL " + label, pop),
            ("V_A confirmed", is_va),
            ("NOT confirmed", no_va),
        ]:
            mfe = sub[fwd_mfe_col].dropna()
            mae = sub[fwd_mae_col].dropna()
            print(f"  {sub_label:<25}  "
                  f"{mfe.median():>7.2f}  {mfe.quantile(0.25):>7.2f}  "
                  f"{mfe.quantile(0.75):>7.2f}  {mfe.quantile(0.90):>7.2f}  | "
                  f"{mae.median():>7.2f}  {mae.quantile(0.75):>7.2f}  "
                  f"{mae.quantile(0.90):>7.2f}")

        # Survival rates within cohort
        print(f"\n  Survival within {label} cohort:")
        print(f"  {'subset':<25}  {'n':>5}  {'alive_6m':>10}  "
              f"{'alive_8m':>10}")
        for sub_label, sub in [
            ("ALL " + label, pop),
            ("V_A confirmed", is_va),
            ("NOT confirmed", no_va),
        ]:
            a6 = sub["alive_6m"].sum()
            a8 = sub["alive_8m"].sum()
            n = len(sub)
            print(f"  {sub_label:<25}  {n:>5,}  "
                  f"{a6:>5,} ({100*a6/n:>4.0f}%)  "
                  f"{a8:>5,} ({100*a8/n:>4.0f}%)")

    print_split_report(c6_pop, "d_pnl_6m", "fwd_mfe_atr_c6",
                          "fwd_mae_atr_c6", "C6", "+6m")
    print_split_report(e8_pop, "d_pnl_8m", "fwd_mfe_atr_e8",
                          "fwd_mae_atr_e8", "E8", "+8m")

    # ===== Cross-check: V_A subset of all-flips C6 vs V_A C =====
    print(f"\n{'='*120}")
    print("CROSS-CHECK — V_A subset of all-flips C6 vs V_A's own C")
    print(f"{'='*120}")
    va_subset_c6 = c6_pop[c6_pop["is_VA_confirmed"]]
    print(f"  V_A subset of all-flips C6: {len(va_subset_c6):,} trades")
    print(f"    total d_pnl_6m: "
          f"${va_subset_c6['d_pnl_6m'].sum():+,.0f}")
    print(f"    $/tr:           "
          f"{va_subset_c6['d_pnl_6m'].mean():+.2f}")
    print(f"\n  Expected: V_A C result was n=1,269 / +$61,370 / +$48.36/tr")
    print(f"  Note: these will differ because:")
    print(f"    - C6 uses +6m from decision_ts (= flip_bar_close)")
    print(f"    - V_A C uses +5m from V_A entry (= flip_bar_close + 60s")
    print(f"      + 30s legacy delay)")
    print(f"    - The 30s offset shifts the unr_pnl threshold IS-fit")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
