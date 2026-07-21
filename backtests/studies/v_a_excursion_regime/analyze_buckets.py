"""Bucket V_A trades by pre-decision excursion features and report
per-bucket outcomes.

Reads results from compute_excursion_features.py and produces:
  - 1D buckets per feature (fast/medium/slow ratio quartiles, total_exc
    percentiles, efficiency tertiles)
  - 2D combination buckets (fast_ratio × medium_ratio, etc.)
  - Year-stability check (require sign agreement across 2024 + 2025)
  - 2026 hold-out validation

Outputs:
  - bucket_summary_1d.csv
  - bucket_summary_2d.csv
  - top_regimes.csv (best $/trade buckets stable across years)
  - worst_regimes.csv (filter-out candidates)

This is a FILTER study, not a signal redesign — the question is whether
pre-decision 5/15/30-min market excursion structure separates V_A
winners from losers.
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

OUT = Path("studies/v_a_excursion_regime/results")
OUT.mkdir(parents=True, exist_ok=True)


# Coarse buckets per spec — kept WIDE to avoid overfitting
RATIO_BUCKETS = [
    ("<0.8",   -np.inf, 0.8),
    ("0.8-1.2", 0.8,    1.2),
    ("1.2-1.8", 1.2,    1.8),
    (">1.8",    1.8,    np.inf),
]
# Tertiles based on full-population (cross-year) percentiles
EFF_TERTILES = (1/3, 2/3)
EXC_TERTILES = (1/3, 2/3)


def bucket_ratio(v):
    if pd.isna(v): return np.nan
    for label, lo, hi in RATIO_BUCKETS:
        if lo <= v < hi:
            return label
    return np.nan


def per_bucket_stats(df, group_col):
    """Stats per bucket of group_col."""
    rows = []
    for grp, g in df.groupby(group_col, dropna=False):
        if len(g) == 0: continue
        rows.append({
            group_col: grp,
            "n": len(g),
            "winner_pct": (g["gross_pnl"] > 0).mean() * 100,
            "loser_pct": (g["gross_pnl"] < 0).mean() * 100,
            "gross_pnl_total": g["gross_pnl"].sum(),
            "per_trade": g["gross_pnl"].mean(),
            "median_pnl": g["gross_pnl"].median(),
            "median_hold_s": g["hold_s"].median(),
            "trade_mfe_mean": g["trade_mfe"].mean()
                if "trade_mfe" in g.columns else np.nan,
            "trade_mae_mean": g["trade_mae"].mean()
                if "trade_mae" in g.columns else np.nan,
            "trade_mfe_to_mae_median": g["trade_mfe_to_mae"].median()
                if "trade_mfe_to_mae" in g.columns else np.nan,
        })
    return pd.DataFrame(rows)


def per_bucket_2d(df, col1, col2):
    rows = []
    for (g1, g2), g in df.groupby([col1, col2], dropna=False):
        if len(g) < 30: continue   # min sample size
        rows.append({
            col1: g1, col2: g2,
            "n": len(g),
            "winner_pct": (g["gross_pnl"] > 0).mean() * 100,
            "gross_pnl_total": g["gross_pnl"].sum(),
            "per_trade": g["gross_pnl"].mean(),
            "median_hold_s": g["hold_s"].median(),
            "trade_mfe_mean": g["trade_mfe"].mean()
                if "trade_mfe" in g.columns else np.nan,
            "trade_mae_mean": g["trade_mae"].mean()
                if "trade_mae" in g.columns else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 78)
    print("V_A Excursion Regime — bucket analysis")
    print("=" * 78)

    # Load with-excursion data per year
    dfs = {}
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_{yr}_with_excursion.parquet"
        if not p.exists():
            print(f"  MISSING: {p}")
            continue
        d = pd.read_parquet(p)
        print(f"  {yr}: {len(d):,} trades, "
              f"complete features: {d['ratio_fast'].notna().sum():,}")
        dfs[yr] = d

    if not dfs:
        print("ERROR: no data files found. Run compute_excursion_features.py first.")
        return

    # --- Bucket each feature ---
    for yr, d in dfs.items():
        for win in ("fast", "medium", "slow"):
            d[f"ratio_{win}_bkt"] = d[f"ratio_{win}"].apply(bucket_ratio)

    # Compute global tertile cuts on combined 2024+2025 (NOT 2026)
    is_combined = pd.concat(
        [dfs[yr] for yr in (2024, 2025) if yr in dfs],
        ignore_index=True)
    cuts = {}
    for win in ("fast", "medium", "slow"):
        cuts[f"efficiency_{win}"] = is_combined[
            f"efficiency_{win}"].quantile(EFF_TERTILES).values
        cuts[f"total_excursion_{win}"] = is_combined[
            f"total_excursion_{win}"].quantile(EXC_TERTILES).values

    def tertile_label(v, lo, hi):
        if pd.isna(v): return np.nan
        if v < lo: return "low"
        if v < hi: return "mid"
        return "high"

    for yr, d in dfs.items():
        for win in ("fast", "medium", "slow"):
            lo, hi = cuts[f"efficiency_{win}"]
            d[f"efficiency_{win}_bkt"] = d[f"efficiency_{win}"].apply(
                lambda v: tertile_label(v, lo, hi))
            lo, hi = cuts[f"total_excursion_{win}"]
            d[f"total_excursion_{win}_bkt"] = d[
                f"total_excursion_{win}"].apply(
                lambda v: tertile_label(v, lo, hi))

    # --- 1D bucket reports ---
    print("\n" + "=" * 78)
    print("1D BUCKET REPORTS")
    print("=" * 78)

    rows_1d = []
    for yr, d in dfs.items():
        for feat in ("ratio_fast_bkt", "ratio_medium_bkt", "ratio_slow_bkt",
                     "efficiency_fast_bkt", "efficiency_medium_bkt",
                     "efficiency_slow_bkt",
                     "total_excursion_fast_bkt",
                     "total_excursion_medium_bkt",
                     "total_excursion_slow_bkt"):
            stats = per_bucket_stats(d, feat)
            stats["year"] = yr
            stats["feature"] = feat
            stats = stats.rename(columns={feat: "bucket"})
            rows_1d.append(stats)
    summary_1d = pd.concat(rows_1d, ignore_index=True)
    cols = ["feature", "year", "bucket", "n", "winner_pct", "loser_pct",
            "gross_pnl_total", "per_trade", "median_pnl", "median_hold_s",
            "trade_mfe_mean", "trade_mae_mean", "trade_mfe_to_mae_median"]
    summary_1d = summary_1d[cols]
    summary_1d.to_csv(OUT / "bucket_summary_1d.csv", index=False)
    print(f"  saved bucket_summary_1d.csv  ({len(summary_1d)} rows)")

    # --- Print 1D summary nicely ---
    for feat in summary_1d["feature"].unique():
        sub = summary_1d[summary_1d["feature"] == feat]
        print(f"\n  --- {feat} ---")
        print(f"  {'year':<6} {'bucket':<10} {'n':>5} {'WR%':>5} "
              f"{'$/tr':>8} {'tot$':>10} {'hold_s':>6}")
        for _, r in sub.iterrows():
            print(f"  {int(r['year']):<6} {str(r['bucket']):<10} "
                  f"{int(r['n']):>5,} {r['winner_pct']:>4.1f}  "
                  f"{r['per_trade']:>+7.1f} {r['gross_pnl_total']:>+9,.0f} "
                  f"{r['median_hold_s']:>6.0f}")

    # --- 2D combinations (fast_ratio × medium_ratio, etc) ---
    print("\n" + "=" * 78)
    print("2D BUCKET REPORTS — fast_ratio × medium_ratio (2024+2025 IS)")
    print("=" * 78)
    rows_2d = []
    for yr, d in dfs.items():
        for c1, c2 in (("ratio_fast_bkt", "ratio_medium_bkt"),
                        ("ratio_fast_bkt", "ratio_slow_bkt"),
                        ("ratio_medium_bkt", "ratio_slow_bkt"),
                        ("efficiency_fast_bkt", "ratio_medium_bkt"),
                        ("total_excursion_medium_bkt",
                         "efficiency_medium_bkt")):
            tab = per_bucket_2d(d, c1, c2)
            if len(tab):
                tab["year"] = yr
                tab["pair"] = f"{c1} × {c2}"
                tab = tab.rename(columns={c1: "bkt1", c2: "bkt2"})
                rows_2d.append(tab)
    summary_2d = pd.concat(rows_2d, ignore_index=True) if rows_2d else \
        pd.DataFrame()
    if len(summary_2d):
        summary_2d.to_csv(OUT / "bucket_summary_2d.csv", index=False)
        print(f"  saved bucket_summary_2d.csv  ({len(summary_2d)} rows)")

    # --- Year-stability check (find buckets where 2024 AND 2025 agree
    # in sign AND both > 0) ---
    print("\n" + "=" * 78)
    print("STABLE EDGES (2024 AND 2025 BOTH POSITIVE in 1D buckets)")
    print("=" * 78)
    pivot = summary_1d.pivot_table(
        index=["feature", "bucket"], columns="year",
        values=["per_trade", "n", "gross_pnl_total"], aggfunc="first")
    rows = []
    for idx, row in pivot.iterrows():
        try:
            pt24 = row[("per_trade", 2024)]
            pt25 = row[("per_trade", 2025)]
            pt26 = row[("per_trade", 2026)] if 2026 in row[("per_trade",)
                ].index else np.nan
            n24 = row[("n", 2024)]
            n25 = row[("n", 2025)]
            tot24 = row[("gross_pnl_total", 2024)]
            tot25 = row[("gross_pnl_total", 2025)]
            tot26 = row[("gross_pnl_total", 2026)] if 2026 in \
                row[("gross_pnl_total",)].index else np.nan
        except Exception:
            continue
        if pd.isna(pt24) or pd.isna(pt25): continue
        if (pt24 > 0 and pt25 > 0):
            rows.append({
                "feature": idx[0], "bucket": idx[1],
                "is2024_pertr": pt24, "is2025_pertr": pt25,
                "is2024_n": n24, "is2025_n": n25,
                "oos2026_pertr": pt26,
                "is2024_total": tot24, "is2025_total": tot25,
                "oos2026_total": tot26,
            })
    stable = pd.DataFrame(rows).sort_values("is2024_pertr", ascending=False) \
        if rows else pd.DataFrame()
    if len(stable):
        stable.to_csv(OUT / "stable_positive_buckets.csv", index=False)
        print(stable.to_string(index=False))
    else:
        print("  No buckets with both 2024 and 2025 positive.")

    # --- Worst-of-the-worst (avoid these) ---
    print("\n" + "=" * 78)
    print("STABLE LOSS BUCKETS (2024 AND 2025 BOTH NEGATIVE — filter out)")
    print("=" * 78)
    rows = []
    for idx, row in pivot.iterrows():
        try:
            pt24 = row[("per_trade", 2024)]
            pt25 = row[("per_trade", 2025)]
            pt26 = row[("per_trade", 2026)] if 2026 in row[("per_trade",)
                ].index else np.nan
            n24 = row[("n", 2024)]
            n25 = row[("n", 2025)]
            tot24 = row[("gross_pnl_total", 2024)]
            tot25 = row[("gross_pnl_total", 2025)]
            tot26 = row[("gross_pnl_total", 2026)] if 2026 in \
                row[("gross_pnl_total",)].index else np.nan
        except Exception:
            continue
        if pd.isna(pt24) or pd.isna(pt25): continue
        if (pt24 < 0 and pt25 < 0):
            rows.append({
                "feature": idx[0], "bucket": idx[1],
                "is2024_pertr": pt24, "is2025_pertr": pt25,
                "is2024_n": n24, "is2025_n": n25,
                "oos2026_pertr": pt26,
                "is2024_total": tot24, "is2025_total": tot25,
                "oos2026_total": tot26,
            })
    worst = pd.DataFrame(rows).sort_values("is2024_pertr") if rows \
        else pd.DataFrame()
    if len(worst):
        worst.to_csv(OUT / "stable_negative_buckets.csv", index=False)
        print(worst.to_string(index=False))
    else:
        print("  No buckets with both 2024 and 2025 negative.")


if __name__ == "__main__":
    main()
