"""Analysis A — Collector integrity audit.

Per-checkpoint integrity checks. If any 'hard fail' column is non-zero,
collector has a bug and further analysis should pause.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

CHECKPOINT_TS = list(range(0, 601, 30))


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
    n = len(df)
    print(f"Loaded {n:,} trades x {len(df.columns)} cols\n")

    rows = []
    hard_fails = []

    for T in CHECKPOINT_TS:
        tag = f"{T:03d}"
        alive_col = f"alive_at_T_{tag}"
        fillable_col = f"fillable_at_T_{tag}"
        dead_col = f"dead_before_T_{tag}"
        fill_price_col = f"checkpoint_entry_fill_price_T_{tag}"
        fwd_pnl_col = f"forward_regime_pnl_dollars_T_{tag}"

        alive = df[alive_col]
        fillable = df[fillable_col]
        dead = df[dead_col]
        fill_price = df[fill_price_col]
        fwd_pnl = df[fwd_pnl_col]

        # Core counts
        alive_pop = (alive == 1).sum()
        fillable_pop = (fillable == 1).sum()
        alive_not_fillable = ((alive == 1) & (fillable == 0)).sum()
        fill_nonnull = fill_price.notna().sum()
        fwd_nonnull = fwd_pnl.notna().sum()

        # HARD FAIL checks
        fill_null_when_fillable = (
            (fillable == 1) & fill_price.isna()).sum()
        fill_present_when_not_fillable = (
            (fillable.fillna(0) == 0) & fill_price.notna()).sum()
        fwd_present_when_not_fillable = (
            (fillable.fillna(0) == 0) & fwd_pnl.notna()).sum()
        dead_before_missing = (
            (alive == 0) & dead.isna()).sum()

        # Values only 0/1 (excluding NaN)
        alive_vals = set(alive.dropna().unique())
        alive_bad = alive_vals - {0.0, 1.0}
        fillable_vals = set(fillable.dropna().unique())
        fillable_bad = fillable_vals - {0.0, 1.0}
        # fillable=1 with alive=0 (impossible)
        fillable1_alive0 = ((fillable == 1) & (alive == 0)).sum()

        row = {
            "T": T,
            "n_rows": n,
            "alive%": alive_pop / n * 100,
            "fillable%": fillable_pop / n * 100,
            "alive_not_fillable%": alive_not_fillable / n * 100,
            "fill_nonnull%": fill_nonnull / n * 100,
            "fill_null_when_fillable": fill_null_when_fillable,
            "fill_present_when_not_fillable": fill_present_when_not_fillable,
            "fwd_nonnull%": fwd_nonnull / n * 100,
            "fwd_present_when_not_fillable": fwd_present_when_not_fillable,
            "dead_before_missing": dead_before_missing,
            "alive_bad_vals": len(alive_bad),
            "fillable_bad_vals": len(fillable_bad),
            "fillable1_alive0": fillable1_alive0,
        }
        rows.append(row)

        # Collect hard fails
        if fill_present_when_not_fillable > 0:
            hard_fails.append(
                f"T={T}: fill_present_when_not_fillable={fill_present_when_not_fillable}")
        if fwd_present_when_not_fillable > 0:
            hard_fails.append(
                f"T={T}: fwd_present_when_not_fillable={fwd_present_when_not_fillable}")
        if dead_before_missing > 0:
            hard_fails.append(
                f"T={T}: dead_before_missing={dead_before_missing}")
        if fillable1_alive0 > 0:
            hard_fails.append(
                f"T={T}: fillable=1 but alive=0: {fillable1_alive0}")
        if fill_null_when_fillable > 0:
            hard_fails.append(
                f"T={T}: fill_null_when_fillable={fill_null_when_fillable}")
        if alive_bad or fillable_bad:
            hard_fails.append(
                f"T={T}: alive_bad={alive_bad} fillable_bad={fillable_bad}")

    # Print table
    print("=" * 132)
    print("TABLE A — CHECKPOINT INTEGRITY AUDIT")
    print("=" * 132)
    print(f"\n  {'T':>4}  {'alive%':>7} {'fillable%':>9} {'a_not_f%':>8} "
          f"{'fill%':>6} {'fwd%':>6} |  "
          f"{'fpNullFillable':>14} {'fpPresNotFill':>13} "
          f"{'fwdPresNotFill':>14} {'deadMiss':>8} "
          f"{'fill1_alive0':>12}")
    print("  " + "-" * 130)
    for r in rows:
        print(
            f"  {r['T']:>3}s  {r['alive%']:>6.1f}% {r['fillable%']:>8.1f}% "
            f"{r['alive_not_fillable%']:>7.2f}% {r['fill_nonnull%']:>5.1f}% "
            f"{r['fwd_nonnull%']:>5.1f}% |  "
            f"{r['fill_null_when_fillable']:>14,} "
            f"{r['fill_present_when_not_fillable']:>13,} "
            f"{r['fwd_present_when_not_fillable']:>14,} "
            f"{r['dead_before_missing']:>8,} "
            f"{r['fillable1_alive0']:>12,}"
        )

    # Summary
    print(f"\n{'='*132}")
    print("HARD-FAIL SUMMARY")
    print(f"{'='*132}")
    if not hard_fails:
        print("  ✓ ALL INTEGRITY CHECKS PASSED — collector is clean")
    else:
        print(f"  ⚠️ {len(hard_fails)} ISSUES:")
        for msg in hard_fails[:30]:
            print(f"    {msg}")

    # Save table
    tdf = pd.DataFrame(rows)
    out = Path("studies/1m_delayed_checkpoint_context/results/"
                "checkpoint_integrity_audit.parquet")
    tdf.to_parquet(out, index=False)
    print(f"\n  Saved: {out}")


if __name__ == "__main__":
    main()
