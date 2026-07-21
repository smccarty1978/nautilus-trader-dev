"""Re-run V_A excursion bucket analysis with NEAR-ROLL trades excluded.

Per audit MEDIUM-severity finding: V_A trades came from the NQ.c.0
calendar-continuous catalog, but excursion features were computed on
NQ.v.0 (volume continuous). On quarterly roll windows (3rd Thu of
Mar/Jun/Sep/Dec ±3 days), the two contracts diverge by 100-250 pts.
Trades whose decision_ts falls in those windows have anchor_open and
high/low computed against a DIFFERENT contract than the V_A trade
itself — distorting excursion ratios for ~5-10% of trades.

This script:
  1. Adds a `near_roll` boolean to each trade
  2. Re-runs the stable-edges analysis on rolls-excluded subset
  3. Reports the impact of roll trades on bucket assignments

Roll dates (3rd Thu, NQ quarterly):
  2024: Mar 21, Jun 20, Sep 19, Dec 19
  2025: Mar 20, Jun 19, Sep 18, Dec 18
  2026: Mar 19 (only Q1 in our data)

Window: ±3 calendar days around each roll = 7-day exclusion zone.
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

OUT = Path("studies/v_a_excursion_regime/results")

ROLL_DATES = [
    pd.Timestamp("2024-03-21", tz="UTC"),
    pd.Timestamp("2024-06-20", tz="UTC"),
    pd.Timestamp("2024-09-19", tz="UTC"),
    pd.Timestamp("2024-12-19", tz="UTC"),
    pd.Timestamp("2025-03-20", tz="UTC"),
    pd.Timestamp("2025-06-19", tz="UTC"),
    pd.Timestamp("2025-09-18", tz="UTC"),
    pd.Timestamp("2025-12-18", tz="UTC"),
    pd.Timestamp("2026-03-19", tz="UTC"),
]


def is_near_roll(ts_ns, days=3):
    """ts_ns: int nanoseconds. days: half-window in calendar days."""
    if pd.isna(ts_ns): return False
    t = pd.Timestamp(ts_ns, unit="ns", tz="UTC")
    delta_days = pd.Timedelta(days=days)
    for r in ROLL_DATES:
        if abs(t - r) <= delta_days:
            return True
    return False


RATIO_BUCKETS = [
    ("<0.8",   -np.inf, 0.8),
    ("0.8-1.2", 0.8,    1.2),
    ("1.2-1.8", 1.2,    1.8),
    (">1.8",    1.8,    np.inf),
]


def bucket_ratio(v):
    if pd.isna(v): return np.nan
    for label, lo, hi in RATIO_BUCKETS:
        if lo <= v < hi:
            return label
    return np.nan


def per_bucket_stats(df, group_col):
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
            "median_hold_s": g["hold_s"].median(),
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 78)
    print("V_A Excursion Regime — bucket analysis (NEAR-ROLL EXCLUDED)")
    print("=" * 78)

    dfs_full = {}
    dfs_clean = {}
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_{yr}_with_excursion.parquet"
        if not p.exists(): continue
        d = pd.read_parquet(p)
        d["near_roll"] = d["decision_ts"].apply(is_near_roll)
        dfs_full[yr] = d
        n_roll = d["near_roll"].sum()
        clean = d[~d["near_roll"]].copy()
        dfs_clean[yr] = clean
        print(f"  {yr}: {len(d):,} total, {n_roll:,} near-roll "
              f"({100*n_roll/len(d):.1f}%), {len(clean):,} kept")

    # --- IMPACT of near-roll trades on overall PnL ---
    print(f"\n--- Roll vs non-roll PnL by year ---")
    for yr, d in dfs_full.items():
        roll = d[d["near_roll"]]
        nonroll = d[~d["near_roll"]]
        rp = roll["gross_pnl"].sum() if len(roll) else 0
        np_ = nonroll["gross_pnl"].sum() if len(nonroll) else 0
        print(f"  {yr}: roll n={len(roll):>4} ${rp:>+9,.0f}  "
              f"nonroll n={len(nonroll):>4} ${np_:>+9,.0f}")

    # Bucket the cleaned data
    for yr, d in dfs_clean.items():
        for win in ("fast", "medium", "slow"):
            d[f"ratio_{win}_bkt"] = d[f"ratio_{win}"].apply(bucket_ratio)

    # Compute IS-only tertile cuts (2024+2025 cleaned)
    is_combined = pd.concat(
        [dfs_clean[yr] for yr in (2024, 2025) if yr in dfs_clean],
        ignore_index=True)
    cuts = {}
    for win in ("fast", "medium", "slow"):
        cuts[f"efficiency_{win}"] = is_combined[
            f"efficiency_{win}"].quantile([1/3, 2/3]).values
        cuts[f"total_excursion_{win}"] = is_combined[
            f"total_excursion_{win}"].quantile([1/3, 2/3]).values

    def tertile_label(v, lo, hi):
        if pd.isna(v): return np.nan
        if v < lo: return "low"
        if v < hi: return "mid"
        return "high"

    for yr, d in dfs_clean.items():
        for win in ("fast", "medium", "slow"):
            lo, hi = cuts[f"efficiency_{win}"]
            d[f"efficiency_{win}_bkt"] = d[f"efficiency_{win}"].apply(
                lambda v: tertile_label(v, lo, hi))
            lo, hi = cuts[f"total_excursion_{win}"]
            d[f"total_excursion_{win}_bkt"] = d[
                f"total_excursion_{win}"].apply(
                lambda v: tertile_label(v, lo, hi))

    rows_1d = []
    for yr, d in dfs_clean.items():
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
    summary_1d.to_csv(OUT / "bucket_summary_1d_NO_ROLLS.csv", index=False)

    # Stable edges
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
            n24 = row[("n", 2024)]; n25 = row[("n", 2025)]
            tot24 = row[("gross_pnl_total", 2024)]
            tot25 = row[("gross_pnl_total", 2025)]
            tot26 = row[("gross_pnl_total", 2026)] if 2026 in \
                row[("gross_pnl_total",)].index else np.nan
        except Exception: continue
        if pd.isna(pt24) or pd.isna(pt25): continue
        if pt24 > 0 and pt25 > 0:
            rows.append({
                "feature": idx[0], "bucket": idx[1],
                "is2024_pertr": pt24, "is2025_pertr": pt25,
                "is2024_n": int(n24), "is2025_n": int(n25),
                "oos2026_pertr": pt26,
                "is2024_total": tot24, "is2025_total": tot25,
                "oos2026_total": tot26,
            })
    stable = pd.DataFrame(rows).sort_values("is2024_pertr",
                                                ascending=False) \
        if rows else pd.DataFrame()
    print(f"\n{'=' * 78}")
    print("STABLE EDGES (2024 AND 2025 BOTH POSITIVE) — NO-ROLL DATA")
    print(f"{'=' * 78}")
    if len(stable):
        stable.to_csv(OUT / "stable_positive_buckets_NO_ROLLS.csv",
                       index=False)
        print(stable.to_string(index=False, float_format="%.2f"))
    else:
        print("  No stable positive buckets after roll exclusion.")

    print(f"\n--- Compare: with vs without rolls (top filters) ---")
    print(f"Filter `ratio_slow_bkt = >1.8` was best-OOS in original analysis.")
    print(f"With rolls excluded, OOS PnL is computed on the cleaner set.")


if __name__ == "__main__":
    main()
