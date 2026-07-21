"""Comprehensive performance report: V_A baseline vs filtered
(total_excursion_slow = mid) on the clean NQ.v.0 dataset.

Net PnL is primary. Gross is secondary. Goal: determine if the filter
actually smooths V_A or if it's carried by a few months.

Outputs five sections:
  1. Yearly overall stats
  2. Month-by-month tables (baseline + filtered, side-by-side)
  3. Baseline-vs-filtered monthly deltas
  4. Worst-month analysis (filtered)
  5. Stability summary (filtered)
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/v_a_excursion_regime/results_v0")
RPT = OUT / "filtered_va_report"
RPT.mkdir(parents=True, exist_ok=True)


# Tertile cuts on 2024+2025 (matches analyze_buckets_v0.py)
def compute_tertile_cuts(dfs):
    is_combined = pd.concat(
        [dfs[yr] for yr in (2024, 2025) if yr in dfs], ignore_index=True)
    return is_combined["total_excursion_slow"].quantile([1/3, 2/3]).values


def tertile_label(v, lo, hi):
    if pd.isna(v): return np.nan
    if v < lo: return "low"
    if v < hi: return "mid"
    return "high"


def add_drawdown(df):
    """Add cumulative net_pnl and drawdown columns. Trades sorted by entry_ts."""
    df = df.sort_values("entry_ts").copy()
    df["cum_net"] = df["net_pnl"].cumsum()
    df["cum_max"] = df["cum_net"].cummax()
    df["drawdown"] = df["cum_net"] - df["cum_max"]
    return df


def overall_stats(df, label):
    """Yearly overall stats — single year or 'ALL'."""
    if not len(df):
        return {"label": label, "n": 0}
    n = len(df)
    wins = df[df["net_pnl"] > 0]
    losses = df[df["net_pnl"] < 0]
    gross = df["gross_pnl"].sum()
    net = df["net_pnl"].sum()
    df_dd = add_drawdown(df)
    max_dd = df_dd["drawdown"].min()
    pf = (wins["net_pnl"].sum() / abs(losses["net_pnl"].sum())
            if len(losses) and losses["net_pnl"].sum() != 0 else float("inf"))
    return {
        "label": label,
        "n": n,
        "win_pct": len(wins) / n * 100,
        "gross_pnl": gross,
        "net_pnl": net,
        "per_trade": net / n,
        "profit_factor": pf,
        "avg_win": wins["net_pnl"].mean() if len(wins) else 0,
        "avg_loss": losses["net_pnl"].mean() if len(losses) else 0,
        "median_hold_s": df["hold_s"].median(),
        "p90_hold_s": df["hold_s"].quantile(0.9),
        "max_drawdown": max_dd,
    }


def monthly_breakdown(df, year):
    """Returns DataFrame indexed by month with monthly stats."""
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.to_period("M")
    df = df[df["entry_dt"].dt.year == year]
    if not len(df):
        return pd.DataFrame()

    rows = []
    for month, g in df.groupby("month"):
        if not len(g):
            continue
        wins = g[g["net_pnl"] > 0]
        losses = g[g["net_pnl"] < 0]
        g_dd = add_drawdown(g)
        n = len(g)
        net = g["net_pnl"].sum()
        pf = (wins["net_pnl"].sum() / abs(losses["net_pnl"].sum())
                if len(losses) and losses["net_pnl"].sum() != 0
                else float("inf"))
        rows.append({
            "month": str(month),
            "n": n,
            "win_pct": len(wins) / n * 100,
            "net_pnl": net,
            "per_trade": net / n,
            "profit_factor": pf,
            "max_drawdown": g_dd["drawdown"].min(),
            "avg_hold_s": g["hold_s"].mean(),
        })
    return pd.DataFrame(rows)


def streak_analysis(df):
    """Largest losing streak (consecutive losing trades)."""
    df = df.sort_values("entry_ts").copy()
    df["loss"] = df["net_pnl"] < 0
    streak = 0; max_streak = 0
    for is_loss in df["loss"]:
        if is_loss:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def main():
    print("=" * 78)
    print("V_A BASELINE vs FILTERED (total_excursion_slow=mid) | clean NQ.v.0")
    print("=" * 78)

    # Load data
    dfs = {}
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_v0_{yr}_with_excursion.parquet"
        d = pd.read_parquet(p)
        dfs[yr] = d
        print(f"  {yr}: {len(d):,} trades")

    # Compute tertile cuts on 2024+2025
    lo, hi = compute_tertile_cuts(dfs)
    print(f"\nTertile cuts on total_excursion_slow (2024+2025 IS):")
    print(f"  low/mid boundary: {lo:.2f}")
    print(f"  mid/high boundary: {hi:.2f}")

    # Build filtered + baseline subsets
    baseline = {}; filtered = {}
    for yr, d in dfs.items():
        d = d.copy()
        d["total_excursion_slow_bkt"] = d["total_excursion_slow"].apply(
            lambda v: tertile_label(v, lo, hi))
        baseline[yr] = d
        filtered[yr] = d[d["total_excursion_slow_bkt"] == "mid"].copy()
        print(f"  {yr}: baseline n={len(baseline[yr]):,}  "
              f"filtered n={len(filtered[yr]):,}  "
              f"({100*len(filtered[yr])/len(baseline[yr]):.1f}%)")

    # ============================================================
    # 1. YEARLY OVERALL
    # ============================================================
    print(f"\n{'='*78}")
    print("1. YEARLY OVERALL — net PnL primary")
    print(f"{'='*78}")
    rows = []
    for label, group in (("baseline", baseline), ("filtered", filtered)):
        for yr in (2024, 2025, 2026):
            s = overall_stats(group[yr], f"{label}_{yr}")
            rows.append(s)
        # All years combined
        s = overall_stats(pd.concat(group.values(), ignore_index=True),
                              f"{label}_ALL")
        rows.append(s)
    yearly = pd.DataFrame(rows)
    print()
    print(f"{'label':<16} {'n':>5} {'WR%':>5} {'gross':>10} {'net':>10} "
          f"{'$/tr':>7} {'PF':>5} {'avg_w':>7} {'avg_l':>7} "
          f"{'mhold':>5} {'p90h':>5} {'maxDD':>9}")
    for r in rows:
        if r["n"] == 0:
            print(f"{r['label']:<16}  no trades")
            continue
        print(f"{r['label']:<16} {int(r['n']):>5,} {r['win_pct']:>4.1f}% "
              f"{r['gross_pnl']:>+9,.0f} {r['net_pnl']:>+9,.0f} "
              f"{r['per_trade']:>+6.1f} {r['profit_factor']:>5.2f} "
              f"{r['avg_win']:>+6.0f} {r['avg_loss']:>+6.0f} "
              f"{r['median_hold_s']:>5.0f} {r['p90_hold_s']:>5.0f} "
              f"{r['max_drawdown']:>+8,.0f}")
    yearly.to_csv(RPT / "yearly_overall.csv", index=False)

    # ============================================================
    # 2. MONTH-BY-MONTH (baseline + filtered)
    # ============================================================
    print(f"\n{'='*78}")
    print("2. MONTH-BY-MONTH (filtered)")
    print(f"{'='*78}")
    all_filtered_monthly = []
    for yr in (2024, 2025, 2026):
        m = monthly_breakdown(filtered[yr], yr)
        if not len(m): continue
        m["year"] = yr; m["variant"] = "filtered"
        all_filtered_monthly.append(m)
        print(f"\n  --- {yr} (filtered) ---")
        print(f"  {'month':<10} {'n':>4} {'WR%':>5} {'net':>9} "
              f"{'$/tr':>6} {'PF':>5} {'maxDD':>9} {'avgH':>5}")
        for _, r in m.iterrows():
            print(f"  {r['month']:<10} {int(r['n']):>4,} "
                  f"{r['win_pct']:>4.1f}% {r['net_pnl']:>+8,.0f} "
                  f"{r['per_trade']:>+5.1f} {r['profit_factor']:>5.2f} "
                  f"{r['max_drawdown']:>+8,.0f} {r['avg_hold_s']:>5.0f}")
    fm = pd.concat(all_filtered_monthly, ignore_index=True) if all_filtered_monthly else pd.DataFrame()
    fm.to_csv(RPT / "monthly_filtered.csv", index=False)

    all_baseline_monthly = []
    for yr in (2024, 2025, 2026):
        m = monthly_breakdown(baseline[yr], yr)
        if not len(m): continue
        m["year"] = yr; m["variant"] = "baseline"
        all_baseline_monthly.append(m)
    bm = pd.concat(all_baseline_monthly, ignore_index=True) if all_baseline_monthly else pd.DataFrame()
    bm.to_csv(RPT / "monthly_baseline.csv", index=False)

    # ============================================================
    # 3. BASELINE vs FILTERED DELTAS
    # ============================================================
    print(f"\n{'='*78}")
    print("3. BASELINE vs FILTERED DELTAS — month-by-month")
    print(f"{'='*78}")
    if len(bm) and len(fm):
        merged = bm[["month", "year", "n", "net_pnl", "per_trade",
                     "max_drawdown"]].merge(
            fm[["month", "year", "n", "net_pnl", "per_trade", "max_drawdown"]],
            on=["month", "year"], suffixes=("_b", "_f"))
        merged["retain_pct"] = merged["n_f"] / merged["n_b"] * 100
        merged["pnl_delta"] = merged["net_pnl_f"] - merged["net_pnl_b"]
        merged["pertr_delta"] = merged["per_trade_f"] - merged["per_trade_b"]
        merged["dd_delta"] = merged["max_drawdown_f"] - merged["max_drawdown_b"]
        merged.to_csv(RPT / "monthly_deltas.csv", index=False)
        for yr in (2024, 2025, 2026):
            sub = merged[merged["year"] == yr]
            if not len(sub): continue
            print(f"\n  --- {yr} (delta = filtered - baseline) ---")
            print(f"  {'month':<10} {'n_b':>4} {'n_f':>4} {'ret%':>5} "
                  f"{'net_b':>9} {'net_f':>9} {'pnl_Δ':>9} "
                  f"{'$/tr_b':>6} {'$/tr_f':>6} {'tr_Δ':>6}")
            for _, r in sub.iterrows():
                print(f"  {r['month']:<10} {int(r['n_b']):>4,} "
                      f"{int(r['n_f']):>4,} {r['retain_pct']:>4.0f}% "
                      f"{r['net_pnl_b']:>+8,.0f} {r['net_pnl_f']:>+8,.0f} "
                      f"{r['pnl_delta']:>+8,.0f} "
                      f"{r['per_trade_b']:>+5.1f} {r['per_trade_f']:>+5.1f} "
                      f"{r['pertr_delta']:>+5.1f}")

    # ============================================================
    # 4. WORST-MONTH ANALYSIS (filtered)
    # ============================================================
    print(f"\n{'='*78}")
    print("4. WORST-MONTH ANALYSIS (filtered)")
    print(f"{'='*78}")
    if len(fm):
        worst_pnl = fm.loc[fm["net_pnl"].idxmin()]
        worst_pertr = fm.loc[fm["per_trade"].idxmin()]
        worst_dd = fm.loc[fm["max_drawdown"].idxmin()]
        print(f"  Worst month by net PnL:    {worst_pnl['month']}  "
              f"net ${worst_pnl['net_pnl']:+,.0f}  $/tr {worst_pnl['per_trade']:+.1f}")
        print(f"  Worst month by $/tr:       {worst_pertr['month']}  "
              f"net ${worst_pertr['net_pnl']:+,.0f}  $/tr {worst_pertr['per_trade']:+.1f}")
        print(f"  Worst monthly DD:          {worst_dd['month']}  "
              f"DD ${worst_dd['max_drawdown']:+,.0f}")

        all_filt = pd.concat(filtered.values(), ignore_index=True)
        max_streak = streak_analysis(all_filt)
        print(f"  Largest losing streak:     {max_streak} consecutive trades")

        # All-time (3-year) max DD
        df_all_dd = add_drawdown(all_filt)
        print(f"  3-year max drawdown:       "
              f"${df_all_dd['drawdown'].min():+,.0f}")

    # ============================================================
    # 5. STABILITY SUMMARY (filtered)
    # ============================================================
    print(f"\n{'='*78}")
    print("5. STABILITY SUMMARY (filtered)")
    print(f"{'='*78}")
    if len(fm):
        n_months = len(fm)
        pos = (fm["net_pnl"] > 0).sum()
        avg = fm["net_pnl"].mean()
        med = fm["net_pnl"].median()
        std = fm["net_pnl"].std()
        worst3 = fm.nsmallest(3, "net_pnl")[["month", "n", "net_pnl",
                                                  "per_trade"]]
        best3 = fm.nlargest(3, "net_pnl")[["month", "n", "net_pnl",
                                               "per_trade"]]
        print(f"  Total months: {n_months}")
        print(f"  Positive months: {pos} / {n_months} "
              f"({100*pos/n_months:.0f}%)")
        print(f"  Average monthly net PnL: ${avg:+,.0f}")
        print(f"  Median monthly net PnL:  ${med:+,.0f}")
        print(f"  StDev monthly net PnL:   ${std:,.0f}")
        print(f"\n  Worst 3 months:")
        for _, r in worst3.iterrows():
            print(f"    {r['month']}: n={int(r['n']):,}  "
                  f"net ${r['net_pnl']:+,.0f}  $/tr {r['per_trade']:+.1f}")
        print(f"\n  Best 3 months:")
        for _, r in best3.iterrows():
            print(f"    {r['month']}: n={int(r['n']):,}  "
                  f"net ${r['net_pnl']:+,.0f}  $/tr {r['per_trade']:+.1f}")

    print(f"\nReport written to {RPT}")


if __name__ == "__main__":
    main()
