"""Matched-baseline comparison: T0 vs delayed-entry variants.

For +5m strategies, cohort = trades alive at +5m (5,994).
For +7m strategies, cohort = trades alive at +7m (5,166).

Strategies:
  A_5m  matched T0 baseline on alive-@-5m cohort
  B     delayed +5m only
  C     delayed +5m + (f_unr_pnl_T_5m >= IS-q80 ≈ $330)
  A_7m  matched T0 baseline on alive-@-7m cohort
  D     delayed +7m only
  E     delayed +7m + (f_net_move_150s_7m >= IS-q10 AND
                        f_net_move_300s_7m >= IS-q20)
  Also: C_T0 / E_T0 = matched T0 on the filtered subsets (apples-
  to-apples for filter contribution).

Thresholds for C and E are FIXED at the IS-only quantile values from
the prior sweep (no re-fit).

Metrics per strategy:
  n, total $, $/tr, max DD, per-year totals, positive months / total
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

OUT = Path("studies/v_a_excursion_regime/results_v0")


def metrics(df, pnl_col):
    """Compute headline metrics. df expects entry_ts, year, pnl_col."""
    if not len(df):
        return {"n": 0, "total": 0.0, "per_tr": 0.0, "max_dd": 0.0,
                "y2024": 0.0, "y2025": 0.0, "y2026": 0.0,
                "pos_months": 0, "total_months": 0}
    df = df.sort_values("entry_ts").copy()
    total = df[pnl_col].sum()
    n = len(df)
    # Drawdown
    df["cum"] = df[pnl_col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    max_dd = float((df["cum"] - df["cum_max"]).min())
    # Per-year
    y = df.groupby("year")[pnl_col].sum()
    # Monthly
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.to_period("M")
    monthly = df.groupby("month")[pnl_col].sum()
    return {
        "n": n, "total": float(total),
        "per_tr": float(total / n),
        "max_dd": max_dd,
        "y2024": float(y.get(2024, 0.0)),
        "y2025": float(y.get(2025, 0.0)),
        "y2026": float(y.get(2026, 0.0)),
        "pos_months": int((monthly > 0).sum()),
        "total_months": int(len(monthly)),
    }


def print_row(label, m, indent="  "):
    pos_str = f"{m['pos_months']}/{m['total_months']}"
    print(f"{indent}{label:<42}  {m['n']:>5,}  "
          f"${m['total']:>+10,.0f}  {m['per_tr']:>+7.2f}  "
          f"${m['max_dd']:>+9,.0f}  "
          f"${m['y2024']:>+9,.0f}  ${m['y2025']:>+9,.0f}  "
          f"${m['y2026']:>+9,.0f}  {pos_str:>6}")


def print_header():
    print(f"  {'strategy':<42}  {'n':>5}  {'total$':>11}  {'$/tr':>7}  "
          f"{'max DD':>10}  {'2024':>10}  {'2025':>10}  {'2026':>10}  "
          f"{'+mo':>6}")


def main():
    print("=" * 78)
    print("MATCHED-BASELINE COMPARISON  —  T0 vs delayed entries")
    print("=" * 78)

    # Load features parquet (has T0 baseline_pnl, alive flags, d_pnl)
    feats_path = OUT / "checkpoint_features.parquet"
    if not feats_path.exists():
        raise FileNotFoundError(
            "Run checkpoint_filter_search.py first to produce "
            f"{feats_path}")
    feats = pd.read_parquet(feats_path)
    print(f"\n  total V_A trades loaded: {len(feats):,}")

    # Dedupe: 49 trades span the 2024/2025 boundary and appear in both
    # year collector runs. Keep the earlier-year occurrence.
    n_pre = len(feats)
    feats = feats.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    if n_pre != len(feats):
        print(f"  deduped cross-year overlaps: "
              f"{n_pre:,} → {len(feats):,}  (-{n_pre - len(feats)})")

    # Need baseline_pnl (T0) — load from V_A collector trades
    base_rows = []
    for yr in (2024, 2025, 2026):
        df = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/trades.parquet"
        )[["entry_ts", "net_pnl"]]
        df["year"] = yr
        base_rows.append(df)
    base_df = pd.concat(base_rows, ignore_index=True)
    base_df = base_df.rename(columns={"net_pnl": "baseline_pnl"})
    # Dedupe same way (keep earlier year)
    base_df = base_df.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)

    # Guard against duplicate entry_ts (would silently inflate n/PnL)
    assert base_df["entry_ts"].is_unique, "base_df entry_ts duplicated"
    assert feats["entry_ts"].is_unique, "feats entry_ts duplicated"
    # Merge baseline_pnl onto features
    feats = feats.merge(base_df[["entry_ts", "baseline_pnl"]],
                          on="entry_ts", how="left")
    assert feats["baseline_pnl"].notna().all(), "missing baseline_pnl"
    assert len(feats) == feats["entry_ts"].nunique(), \
        "merge introduced row duplication"

    # ===== Fix thresholds from IS-only =====
    # +5m: unr_pnl_T_5m  IS-q80 (KEEP if >=)
    assert set(feats["year"].unique()).issubset({2024, 2025, 2026}), \
        f"unexpected year values: {feats['year'].unique()}"
    is_alive_5m = feats[feats["alive_5m"]
                          & feats["year"].isin([2024, 2025])]
    assert is_alive_5m["year"].max() <= 2025, "IS leak: 2026 in is_alive_5m"
    thr_unr_5m = is_alive_5m["f_unr_pnl_T_5m"].quantile(0.80)
    print(f"\n  +5m filter threshold (IS q=0.80): "
          f"f_unr_pnl_T >= ${thr_unr_5m:.0f}")

    is_alive_7m = feats[feats["alive_7m"]
                          & feats["year"].isin([2024, 2025])]
    assert is_alive_7m["year"].max() <= 2025, "IS leak: 2026 in is_alive_7m"
    thr_150_7m = is_alive_7m["f_net_move_150s_7m"].quantile(0.10)
    thr_300_7m = is_alive_7m["f_net_move_300s_7m"].quantile(0.20)
    print(f"  +7m filter thresholds (IS-fit): "
          f"f_net_move_150s >= ${thr_150_7m:.2f}, "
          f"f_net_move_300s >= ${thr_300_7m:.2f}")

    # ===== Build cohorts =====
    alive_5m = feats[feats["alive_5m"]].copy()
    alive_7m = feats[feats["alive_7m"]].copy()

    # Filter masks
    c_mask = alive_5m["f_unr_pnl_T_5m"] >= thr_unr_5m
    e_mask = ((alive_7m["f_net_move_150s_7m"] >= thr_150_7m)
                & (alive_7m["f_net_move_300s_7m"] >= thr_300_7m))

    # ===== Compute metrics =====
    A5m = metrics(alive_5m, "baseline_pnl")
    B   = metrics(alive_5m, "d_pnl_5m")
    C   = metrics(alive_5m[c_mask], "d_pnl_5m")
    C_T0 = metrics(alive_5m[c_mask], "baseline_pnl")

    A7m = metrics(alive_7m, "baseline_pnl")
    D   = metrics(alive_7m, "d_pnl_7m")
    E   = metrics(alive_7m[e_mask], "d_pnl_7m")
    E_T0 = metrics(alive_7m[e_mask], "baseline_pnl")

    # Also include the original "all V_A" baseline for context
    all_va = base_df.copy()
    all_va_metrics = metrics(all_va, "baseline_pnl")

    # ===== Report =====
    print(f"\n{'='*120}")
    print("STRATEGIES")
    print(f"{'='*120}")
    print_header()
    print("  " + "-" * 118)
    print_row("(context) full V_A baseline 1c T0", all_va_metrics)
    print()
    print("  +5m cohort (5,994 trades alive at +5m)")
    print_row("A_5m  matched T0 (alive@5m cohort)", A5m)
    print_row("B     delayed-only @+5m", B)
    print_row("C     delayed @+5m + unr filter", C)
    print_row("  C_T0  same filtered cohort, T0 entry", C_T0, indent="    ")
    print()
    print("  +7m cohort (5,166 trades alive at +7m)")
    print_row("A_7m  matched T0 (alive@7m cohort)", A7m)
    print_row("D     delayed-only @+7m", D)
    print_row("E     delayed @+7m + dual momentum", E)
    print_row("  E_T0  same filtered cohort, T0 entry", E_T0, indent="    ")

    # ===== Pairwise deltas (signed lift over matched baselines) =====
    print(f"\n{'='*120}")
    print("PAIRWISE LIFT (delayed/filtered  vs  matched T0)")
    print(f"{'='*120}")
    print(f"  {'comparison':<60}  {'Δtotal':>10}  {'Δ$/tr':>7}  "
          f"{'Δ2024':>10}  {'Δ2025':>10}  {'Δ2026':>10}")

    def diff(a, b, label):
        return (f"{label:<60}  ${a['total']-b['total']:>+8,.0f}  "
                f"{a['per_tr']-b['per_tr']:>+7.2f}  "
                f"${a['y2024']-b['y2024']:>+8,.0f}  "
                f"${a['y2025']-b['y2025']:>+8,.0f}  "
                f"${a['y2026']-b['y2026']:>+8,.0f}")

    print("  " + diff(B, A5m, "B (delay+5m)  vs  A_5m (T0 on alive@5m)"))
    print("  " + diff(C, A5m, "C (+5m+filter)  vs  A_5m"))
    print("  " + diff(C, C_T0,
            "C (+5m+filter)  vs  C_T0 (same trades, T0)"))
    print("  " + diff(D, A7m, "D (delay+7m)  vs  A_7m (T0 on alive@7m)"))
    print("  " + diff(E, A7m, "E (+7m+dual)  vs  A_7m"))
    print("  " + diff(E, E_T0,
            "E (+7m+dual)  vs  E_T0 (same trades, T0)"))

    # ===== Per-month detail for C and E (most promising candidates) =====
    print(f"\n{'='*120}")
    print("MONTHLY PnL — C (+5m + unr filter)")
    print(f"{'='*120}")
    sub = alive_5m[c_mask].sort_values("entry_ts").copy()
    sub["month"] = pd.to_datetime(sub["entry_ts"], unit="ns",
                                      utc=True).dt.to_period("M")
    monthly = sub.groupby("month").agg(
        n=("d_pnl_5m", "size"), pnl=("d_pnl_5m", "sum"),
    )
    monthly["cum"] = monthly["pnl"].cumsum()
    for m, row in monthly.iterrows():
        marker = "+" if row["pnl"] > 0 else "-"
        print(f"  {m}  n={int(row['n']):>3,}  "
              f"${row['pnl']:>+8,.0f} {marker}  "
              f"cum=${row['cum']:>+9,.0f}")

    print(f"\n{'='*120}")
    print("MONTHLY PnL — E (+7m + dual momentum)")
    print(f"{'='*120}")
    sub = alive_7m[e_mask].sort_values("entry_ts").copy()
    sub["month"] = pd.to_datetime(sub["entry_ts"], unit="ns",
                                      utc=True).dt.to_period("M")
    monthly = sub.groupby("month").agg(
        n=("d_pnl_7m", "size"), pnl=("d_pnl_7m", "sum"),
    )
    monthly["cum"] = monthly["pnl"].cumsum()
    for m, row in monthly.iterrows():
        marker = "+" if row["pnl"] > 0 else "-"
        print(f"  {m}  n={int(row['n']):>3,}  "
              f"${row['pnl']:>+8,.0f} {marker}  "
              f"cum=${row['cum']:>+9,.0f}")

    print(f"\n[done]")


if __name__ == "__main__":
    main()
