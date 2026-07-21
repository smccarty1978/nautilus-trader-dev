"""Smoke validation — 8 checks per Revision 11."""

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
FWD_SNAPSHOT_TS = [30, 60, 90, 120, 180, 300]
BRACKETS = ["pt100_before_sl100", "pt150_before_sl100",
            "pt200_before_sl100", "pt300_before_sl150"]


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_smoke.parquet")
    print(f"Loaded {len(df):,} trades × {len(df.columns)} cols\n")

    issues = []

    # CHECK 1: Column naming convention {field}_{T:03d}
    print("=" * 80)
    print("CHECK 1: Column naming convention {field}_{T:03d}")
    print("=" * 80)
    expected_suffixes = [f"_{T:03d}" for T in CHECKPOINT_TS]
    cp_cols = [c for c in df.columns
                if any(c.endswith(s) for s in expected_suffixes)]
    print(f"  Columns matching _{{000..600}} pattern: {len(cp_cols):,}")
    # Quick check that 21 unique field bases exist
    field_bases = set()
    for c in cp_cols:
        for s in expected_suffixes:
            if c.endswith(s):
                field_bases.add(c[:-len(s)])
                break
    print(f"  Unique field bases: {len(field_bases)}")
    print(f"  Sample fields: {sorted(field_bases)[:5]}")
    # Each base should appear with all 21 suffixes
    incomplete = []
    for base in field_bases:
        present = sum(1 for s in expected_suffixes
                       if f"{base}{s}" in df.columns)
        if present != 21:
            incomplete.append((base, present))
    if incomplete:
        print(f"  ⚠️ Incomplete checkpoint coverage: {incomplete[:5]}")
        issues.append(f"Incomplete checkpoint coverage on {len(incomplete)} fields")
    else:
        print(f"  ✓ All {len(field_bases)} field bases have 21 checkpoints")

    # CHECK 2: alive_at_T and fillable_at_T
    print("\n" + "=" * 80)
    print("CHECK 2: alive_at_T and fillable_at_T behavior")
    print("=" * 80)
    for T in [0, 60, 300, 600]:
        tag = f"{T:03d}"
        alive = df[f"alive_at_T_{tag}"]
        dead = df[f"dead_before_T_{tag}"]
        fillable = df[f"fillable_at_T_{tag}"]
        n_alive = (alive == 1).sum()
        n_dead = (dead == 1).sum()
        n_fillable = (fillable == 1).sum()
        # alive + dead should = total (no NaN here)
        n_alive_or_dead = ((alive == 1) | (dead == 1)).sum()
        print(f"  T={T}s: alive={n_alive}, dead_before={n_dead}, "
              f"fillable={n_fillable}, alive_xor_dead_total={n_alive_or_dead}/{len(df)}")
        if n_fillable > n_alive:
            issues.append(f"T={T}: fillable > alive — IMPOSSIBLE")
        # alive must be >= fillable always
        if (alive < fillable).any():
            issues.append(f"T={T}: some rows have fillable=1 but alive=0")

    # CHECK 3: regime_5m_flip_checkpoint semantics (0 / T / NaN)
    print("\n" + "=" * 80)
    print("CHECK 3: regime_5m_flip_checkpoint values")
    print("=" * 80)
    flip_cp = df["regime_5m_flip_checkpoint"]
    n_zero = (flip_cp == 0).sum()
    n_nan = flip_cp.isna().sum()
    n_T = ((flip_cp > 0) & (flip_cp <= 600)).sum()
    n_other = len(df) - n_zero - n_nan - n_T
    print(f"  =0 (already aligned): {n_zero}")
    print(f"  NaN (never aligned):  {n_nan}")
    print(f"  T value (flipped):    {n_T}")
    print(f"  Other (illegal):      {n_other}")
    if n_other > 0:
        issues.append("regime_5m_flip_checkpoint has illegal values")
    # Cross-check: =0 trades should have regime_5m_aligned_t0 = 1
    cross = ((flip_cp == 0) & (df["regime_5m_aligned_t0"] == 0)).sum()
    if cross > 0:
        issues.append(f"flip_cp=0 but regime_5m_aligned_t0=0 in {cross} trades")
    else:
        print(f"  ✓ flip_cp=0 always implies regime_5m_aligned_t0=1")
    # Spot check: 5 trades with non-zero flip_cp
    nonzero = df[(flip_cp > 0) & (flip_cp <= 600)].head(5)
    print(f"\n  Spot check (5 trades with flip_cp > 0):")
    for idx, row in nonzero.iterrows():
        T = int(row["regime_5m_flip_checkpoint"])
        tag = f"{T:03d}"
        # At checkpoint T, regime_5m_aligned should be 1
        aligned_at_T = row.get(f"regime_5m_aligned_T_{tag}", "MISSING")
        flipped_at_T = row.get(f"regime_5m_flipped_to_align_by_T_{tag}", "MISSING")
        print(f"    Trade {row['trade_id']}: flip_cp={T}, "
              f"regime_5m_aligned_T_{tag}={aligned_at_T}, "
              f"regime_5m_flipped_to_align_by_T_{tag}={flipped_at_T}")

    # CHECK 4 & 9: NaN rules — dead_before_T → other fields NaN
    print("\n" + "=" * 80)
    print("CHECK 4/9: NaN rules — dead_before_T propagates NaN")
    print("=" * 80)
    for T in [60, 120, 300, 600]:
        tag = f"{T:03d}"
        dead_mask = df[f"dead_before_T_{tag}"] == 1
        if dead_mask.sum() == 0:
            print(f"  T={T}s: 0 dead trades, skipping check")
            continue
        # Section C field should be NaN when dead
        regime_field = df.loc[dead_mask, f"regime_5m_T_{tag}"]
        n_non_nan = regime_field.notna().sum()
        # Forward path field should be NaN
        fwd_field = df.loc[dead_mask, f"forward_peak_mfe_atr_T_{tag}"]
        n_fwd_non_nan = fwd_field.notna().sum()
        # Bracket field should be NaN
        br_field = df.loc[dead_mask, f"forward_pt100_before_sl100_T_{tag}"]
        n_br_non_nan = br_field.notna().sum()
        print(f"  T={T}s ({dead_mask.sum()} dead): "
              f"regime_5m_T non-NaN={n_non_nan}, "
              f"forward_mfe non-NaN={n_fwd_non_nan}, "
              f"bracket non-NaN={n_br_non_nan}")
        if n_non_nan > 0 or n_fwd_non_nan > 0 or n_br_non_nan > 0:
            issues.append(f"T={T}: dead trades have non-NaN fields")

    # CHECK 5: Forward path only when fillable_at_T = 1
    print("\n" + "=" * 80)
    print("CHECK 5: Forward path populated only when fillable_at_T = 1")
    print("=" * 80)
    for T in [0, 60, 300, 600]:
        tag = f"{T:03d}"
        not_fillable_alive = (
            (df[f"alive_at_T_{tag}"] == 1)
            & (df[f"fillable_at_T_{tag}"] == 0))
        n = not_fillable_alive.sum()
        if n == 0:
            print(f"  T={T}s: 0 alive-but-not-fillable, skipping")
            continue
        # These should have forward fields = NaN
        fwd_non_nan = df.loc[
            not_fillable_alive, f"forward_peak_mfe_atr_T_{tag}"].notna().sum()
        # And fill_price should be NaN
        fp_non_nan = df.loc[
            not_fillable_alive,
            f"checkpoint_entry_fill_price_T_{tag}"].notna().sum()
        print(f"  T={T}s ({n} alive-not-fillable): "
              f"forward_mfe non-NaN={fwd_non_nan}, fill_price non-NaN={fp_non_nan}")
        if fwd_non_nan > 0:
            issues.append(f"T={T}: alive_not_fillable has forward path data")
        if fp_non_nan > 0:
            issues.append(f"T={T}: alive_not_fillable has fill price")

    # CHECK 6: Forward snapshots NaN when trade exits before horizon
    print("\n" + "=" * 80)
    print("CHECK 6: Forward snapshots NaN when trade ends before horizon")
    print("=" * 80)
    for T in [60, 120]:
        tag = f"{T:03d}"
        fillable_mask = df[f"fillable_at_T_{tag}"] == 1
        # For trades with fillable=1, check forward_mfe_at_300s
        # vs forward_regime_duration_s_T
        if not fillable_mask.any():
            continue
        sub = df[fillable_mask]
        for fwd_t in [60, 180, 300]:
            mfe_field = sub[f"forward_mfe_at_{fwd_t}s_T_{tag}"]
            dur_field = sub[f"forward_regime_duration_s_T_{tag}"]
            # If duration < fwd_t, mfe should be NaN
            short_dur = (dur_field < fwd_t)
            mfe_should_be_nan = mfe_field[short_dur]
            n_nan_correct = mfe_should_be_nan.isna().sum()
            n_total = short_dur.sum()
            if n_total > 0:
                print(f"  T={T}s, fwd_horizon={fwd_t}s: "
                      f"trades with dur<{fwd_t} = {n_total}, "
                      f"NaN'd correctly = {n_nan_correct}")

    # CHECK 7: Root anchors match T0 logic
    print("\n" + "=" * 80)
    print("CHECK 7: Root alignment anchors match T0 checkpoint")
    print("=" * 80)
    # regime_5m_aligned_t0 should match regime_5m_aligned_T_000 (when alive)
    alive_t0 = df["alive_at_T_000"] == 1
    if alive_t0.sum() > 0:
        anchor = df.loc[alive_t0, "regime_5m_aligned_t0"]
        cp_val = df.loc[alive_t0, "regime_5m_aligned_T_000"]
        mismatch = (anchor != cp_val).sum()
        print(f"  regime_5m_aligned_t0 vs regime_5m_aligned_T_000: "
              f"mismatch={mismatch}/{alive_t0.sum()}")
        if mismatch > 0:
            issues.append(f"regime_5m anchor mismatch: {mismatch}")
        anchor30s = df.loc[alive_t0, "regime_30s_aligned_t0"]
        cp30s = df.loc[alive_t0, "regime_30s_aligned_T_000"]
        mismatch30s = (anchor30s != cp30s).sum()
        print(f"  regime_30s_aligned_t0 vs regime_30s_aligned_T_000: "
              f"mismatch={mismatch30s}/{alive_t0.sum()}")

    # CHECK 8: fill_price NaN when fillable=0 (most likely mistake)
    print("\n" + "=" * 80)
    print("CHECK 8: checkpoint_entry_fill_price_T NaN when fillable=0")
    print("=" * 80)
    for T in [0, 30, 60, 300]:
        tag = f"{T:03d}"
        not_fillable = df[f"fillable_at_T_{tag}"].fillna(0) == 0
        fp = df.loc[not_fillable, f"checkpoint_entry_fill_price_T_{tag}"]
        n_non_nan = fp.notna().sum()
        print(f"  T={T}s: fillable=0 trades={not_fillable.sum()}, "
              f"fill_price non-NaN={n_non_nan}")
        if n_non_nan > 0:
            issues.append(f"T={T}: fillable=0 has non-NaN fill_price")

    # CHECK 9 (extra): trade count sanity
    print("\n" + "=" * 80)
    print("EXTRA: Trade count + alive% per T")
    print("=" * 80)
    print(f"  Total trades: {len(df):,}")
    print(f"  T  | alive% | fillable% | dead% ")
    for T in CHECKPOINT_TS:
        tag = f"{T:03d}"
        alive_pct = (df[f"alive_at_T_{tag}"] == 1).mean() * 100
        fillable_pct = (df[f"fillable_at_T_{tag}"] == 1).mean() * 100
        dead_pct = (df[f"dead_before_T_{tag}"] == 1).mean() * 100
        print(f"  {T:>3}s | {alive_pct:>5.1f}% | {fillable_pct:>5.1f}% | {dead_pct:>5.1f}%")

    # SUMMARY
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    if not issues:
        print("  ✓ ALL CHECKS PASSED")
    else:
        print(f"  ⚠️ {len(issues)} ISSUES:")
        for i, msg in enumerate(issues, 1):
            print(f"    {i}. {msg}")


if __name__ == "__main__":
    main()
