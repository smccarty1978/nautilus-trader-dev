"""Build cohort with NEW full-population PT-first label.

Reuses existing cohort_long.parquet from bracket_entry_v2 (already
filtered to RTH + fillable + T ∈ {0..600}). Just adds a new label
and keeps unresolved rows in the population.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

OUT = Path("studies/bracket_entry_v3_fullpop/results/cohort_v3.parquet")


def load_year_from_collector(year: int) -> pd.DataFrame:
    """Load a single year's feature+label parquets, apply same
    filters as bracket_entry_v2/collect.py (RTH, fillable,
    T ∈ {0..600}). Returns merged dataframe."""
    feat_path = Path(
        f"studies/1m_regime_collector_v2/results/"
        f"v2_feature_snapshots_{year}.parquet")
    lbl_path = Path(
        f"studies/1m_regime_collector_v2/results/"
        f"v2_outcome_labels_{year}.parquet")
    if not feat_path.exists():
        raise FileNotFoundError(feat_path)

    CHECKPOINTS = list(range(0, 601, 30))
    feats = pd.read_parquet(feat_path)
    labels = pd.read_parquet(lbl_path)
    feats = feats[feats["checkpoint_s"].isin(CHECKPOINTS)]
    labels = labels[labels["checkpoint_s"].isin(CHECKPOINTS)]

    # Keep the same columns we had in v2 cohort
    feat_cols = ["event_id", "checkpoint_s"]
    for c in feats.columns:
        if c not in ("event_id", "checkpoint_s"):
            feat_cols.append(c)
    feats = feats[feat_cols]
    lbl_cols = ["event_id", "checkpoint_s"]
    for c in labels.columns:
        if c in ("pt100_before_sl100", "mfe_mae_ratio_300s",
                  "bracket_resolution_time_s_pt100_before_sl100",
                  "mfe_300s_atr", "mae_300s_atr",
                  "mfe_300s_censored",
                  "regime_exit_pnl_dollars",
                  "regime_exit_pnl_atr"):
            lbl_cols.append(c)
    labels = labels[lbl_cols]

    merged = feats.merge(labels,
                           on=["event_id", "checkpoint_s"],
                           how="inner")
    merged["year"] = year
    # Filter to fillable + RTH
    merged = merged[merged["fillable_at_T"] == True].copy()
    if "is_rth_checkpoint" in merged.columns:
        merged = merged[merged["is_rth_checkpoint"] == 1].copy()
    # Compute resolved flag
    merged["resolved"] = (
        ~merged["pt100_before_sl100"].isna()).astype("int8")
    return merged


def main():
    # Load existing v2 cohort (covers 2020-2025)
    src = pd.read_parquet(
        "studies/bracket_entry_v2/results/cohort_long.parquet")
    print(f"Source v2 cohort (2020-2025): {len(src):,}")

    # Load 2026 from collector output
    if 2026 not in src["year"].unique():
        print("Loading 2026 from v2 collector output...")
        y26 = load_year_from_collector(2026)
        print(f"  2026: {len(y26):,} rows (RTH, fillable, T<=600)")
        # Align columns — drop any v2-cohort-specific cols that
        # aren't in y26, and add missing ones as NaN
        common = [c for c in src.columns
                   if c in y26.columns or c in ("good_bracket_entry",
                                                  "resolved")]
        for c in y26.columns:
            if c not in src.columns:
                src[c] = np.nan
        for c in src.columns:
            if c not in y26.columns:
                y26[c] = np.nan
        # Reorder y26 columns to match src
        y26 = y26[src.columns.tolist()]
        src = pd.concat([src, y26], ignore_index=True)
    print(f"Combined (2020-2026): {len(src):,}")
    print(f"  Resolved: {(src['resolved'] == 1).sum():,}")
    print(f"  Unresolved: {(src['resolved'] == 0).sum():,}")

    # NEW LABEL: PT first vs everything else
    # pt100_before_sl100 == 1 → positive
    # pt100_before_sl100 == 0 (SL) → negative
    # pt100_before_sl100 == NaN (unresolved/regime-exit) → negative
    df = src.copy()
    df["is_pt_first"] = (df["pt100_before_sl100"] == 1).astype("int8")

    # Drop the old labels to avoid confusion
    df = df.drop(columns=["good_bracket_entry"], errors="ignore")

    print()
    print(f"NEW label `is_pt_first`:")
    print(f"  Positive (PT first): "
           f"{(df['is_pt_first'] == 1).sum():,} "
           f"({100*(df['is_pt_first']==1).mean():.1f}%)")
    print(f"  Negative (SL/regime/unresolved): "
           f"{(df['is_pt_first'] == 0).sum():,} "
           f"({100*(df['is_pt_first']==0).mean():.1f}%)")

    # Outcome mix
    print()
    print("Outcome mix on full population:")
    pt = (df["pt100_before_sl100"] == 1).sum()
    sl = (df["pt100_before_sl100"] == 0).sum()
    unres = df["pt100_before_sl100"].isna().sum()
    print(f"  PT (pt100=1):  {pt:,} ({100*pt/len(df):.1f}%)")
    print(f"  SL (pt100=0):  {sl:,} ({100*sl/len(df):.1f}%)")
    print(f"  Unresolved:    {unres:,} ({100*unres/len(df):.1f}%)")

    # Year breakdown
    print()
    print("Per-year base rate of is_pt_first:")
    for y in sorted(df["year"].unique()):
        sub = df[df["year"] == y]
        rate = sub["is_pt_first"].mean()
        print(f"  {y}: n={len(sub):,}  base_rate={rate:.4f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"\nSaved: {OUT}  ({len(df):,} rows × {len(df.columns)} cols)")


if __name__ == "__main__":
    main()
