"""MFE-in-ATR-units analysis for filtered V_A trades.

Per-trade question: how much favorable excursion did each trade get
relative to its ATR_at_signal? Categorize:
  - "dead on arrival": MFE < 0.25 ATR — trade barely budged in trade direction
  - "tested but failed": 0.25-1.0 ATR — got some favorable move but reversed
  - "hit 1+ ATR": MFE >= 1.0 ATR — meaningful directional follow-through
  - "hit 2+ ATR": MFE >= 2.0 ATR — strong follow-through

Compare filtered (total_excursion_slow = mid) vs baseline.

Also report: what's the WR within each MFE bucket?
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

EFF_BUCKETS = [
    ("DOA (<0.25)",  -np.inf, 0.25),
    ("0.25-0.5",      0.25,    0.5),
    ("0.5-1.0",       0.5,     1.0),
    ("1.0-1.5",       1.0,     1.5),
    ("1.5-2.0",       1.5,     2.0),
    ("2.0-3.0",       2.0,     3.0),
    (">=3.0",         3.0,     np.inf),
]


def bucket_mfe(v):
    if pd.isna(v): return np.nan
    for label, lo, hi in EFF_BUCKETS:
        if lo <= v < hi:
            return label
    return np.nan


def compute_tertile_cuts(dfs):
    is_combined = pd.concat(
        [dfs[yr] for yr in (2024, 2025) if yr in dfs], ignore_index=True)
    return is_combined["total_excursion_slow"].quantile([1/3, 2/3]).values


def tertile_label(v, lo, hi):
    if pd.isna(v): return np.nan
    if v < lo: return "low"
    if v < hi: return "mid"
    return "high"


def analyze_subset(df, label):
    df = df.copy()
    df["mfe_atr"] = df["running_mfe"] / df["atr_at_signal"]
    df["mae_atr"] = df["running_mae"] / df["atr_at_signal"]
    df["bucket"] = df["mfe_atr"].apply(bucket_mfe)
    n = len(df)

    print(f"\n--- {label} (n={n:,}) ---")
    print(f"  median MFE_atr: {df['mfe_atr'].median():.2f}")
    print(f"  mean MFE_atr:   {df['mfe_atr'].mean():.2f}")
    print(f"  p10 / p25 / p50 / p75 / p90 MFE_atr: "
          f"{df['mfe_atr'].quantile(0.1):.2f} / "
          f"{df['mfe_atr'].quantile(0.25):.2f} / "
          f"{df['mfe_atr'].quantile(0.5):.2f} / "
          f"{df['mfe_atr'].quantile(0.75):.2f} / "
          f"{df['mfe_atr'].quantile(0.9):.2f}")

    # Top-line categories the user asked
    doa = (df["mfe_atr"] < 0.25).sum()
    hit_1atr = (df["mfe_atr"] >= 1.0).sum()
    hit_2atr = (df["mfe_atr"] >= 2.0).sum()
    print(f"\n  DOA (MFE < 0.25 ATR):   {doa:>5,}  ({100*doa/n:.1f}%)")
    print(f"  Hit 1+ ATR MFE:         {hit_1atr:>5,}  "
          f"({100*hit_1atr/n:.1f}%)")
    print(f"  Hit 2+ ATR MFE:         {hit_2atr:>5,}  "
          f"({100*hit_2atr/n:.1f}%)")

    # Per-bucket breakdown w/ outcomes
    print(f"\n  {'bucket':<12} {'n':>6} {'pct':>5} {'WR%':>5} "
          f"{'$/tr':>7} {'med_hold':>9}")
    rows = []
    for bk_label, _, _ in EFF_BUCKETS:
        g = df[df["bucket"] == bk_label]
        if len(g) == 0:
            print(f"  {bk_label:<12} {0:>6,}    -")
            continue
        wr = (g["net_pnl"] > 0).mean() * 100
        per_tr = g["net_pnl"].mean()
        med_hold = g["hold_s"].median()
        print(f"  {bk_label:<12} {len(g):>6,} "
              f"{100*len(g)/n:>4.1f}% {wr:>4.1f}% "
              f"{per_tr:>+6.0f} {med_hold:>9.0f}")
        rows.append({"label": label, "bucket": bk_label,
                     "n": len(g), "pct": 100*len(g)/n,
                     "wr": wr, "per_tr": per_tr,
                     "med_hold_s": med_hold})
    return pd.DataFrame(rows)


def main():
    print("=" * 78)
    print("MFE-in-ATR analysis | filtered (total_excursion_slow=mid) vs baseline")
    print("=" * 78)

    dfs = {}
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_v0_{yr}_with_excursion.parquet"
        d = pd.read_parquet(p)
        dfs[yr] = d

    lo, hi = compute_tertile_cuts(dfs)
    print(f"\nTertile cuts on total_excursion_slow (2024+2025): "
          f"low/mid={lo:.2f}, mid/high={hi:.2f}")

    all_rows = []
    for yr in (2024, 2025, 2026):
        d = dfs[yr].copy()
        d["bkt"] = d["total_excursion_slow"].apply(
            lambda v: tertile_label(v, lo, hi))
        baseline = d
        filtered = d[d["bkt"] == "mid"]

        print(f"\n{'='*78}")
        print(f"YEAR {yr}")
        print(f"{'='*78}")
        rb = analyze_subset(baseline, f"{yr} baseline")
        rf = analyze_subset(filtered, f"{yr} filtered (mid)")
        if len(rb): all_rows.append(rb)
        if len(rf): all_rows.append(rf)

    # All years combined
    print(f"\n{'='*78}")
    print(f"ALL YEARS COMBINED")
    print(f"{'='*78}")
    all_baseline = pd.concat(dfs.values(), ignore_index=True)
    all_filtered = pd.concat([
        dfs[yr][dfs[yr]["total_excursion_slow"].apply(
            lambda v: tertile_label(v, lo, hi)) == "mid"]
        for yr in (2024, 2025, 2026)], ignore_index=True)
    rb = analyze_subset(all_baseline, "ALL baseline")
    rf = analyze_subset(all_filtered, "ALL filtered")
    if len(rb): all_rows.append(rb)
    if len(rf): all_rows.append(rf)

    summary = pd.concat(all_rows, ignore_index=True)
    summary.to_csv(OUT / "mfe_atr_buckets.csv", index=False)
    print(f"\nWrote {OUT}/mfe_atr_buckets.csv")


if __name__ == "__main__":
    main()
