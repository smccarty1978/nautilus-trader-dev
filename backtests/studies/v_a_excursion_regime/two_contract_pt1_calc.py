"""2-contract PT1 calculation: enter 2 contracts, take 1 off at +1 ATR
MFE, let the runner go to regime exit.

Mechanics:
  Both contracts enter at fill_price (same time).
  C1: limit order at fill_price ± 1.0 * atr_at_signal (direction-aware)
      → fills when running_mfe >= 1.0 ATR (61.3% of trades)
      → PnL = 1.0 * atr * 20 - $10 (round trip commission)
  C2: held to regime exit
      → PnL = original net_pnl (which already accounts for $10 RT commission)

If C1 doesn't fill (mfe_atr < 1.0), both contracts exit at regime:
  → total = 2 * net_pnl

Compare to:
  - 1-contract V_A baseline (net_pnl sum)
  - 1-contract V_A * 2 (naive doubling — what 2c would look like
    WITHOUT the PT1 logic)
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

NQ_MULT = 20.0
COMMISSION = 5.0   # one-way; $10 RT per contract

OUT = Path("studies/v_a_excursion_regime/results_v0")


def load_year(yr):
    base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
    df = pd.read_parquet(base / "trades.parquet")
    df["year"] = yr
    df["mfe_atr"] = df["running_mfe"] / df["atr_at_signal"].clip(lower=0.01)
    df["mae_atr"] = df["running_mae"] / df["atr_at_signal"].clip(lower=0.01)
    df["is_winner"] = df["net_pnl"] > 0
    return df


def compute_2c(df, pt1_atr=1.0):
    """Compute 2-contract PT1 strategy per trade."""
    df = df.copy()
    df["c1_hits_pt"] = df["mfe_atr"] >= pt1_atr
    # C1 PnL when it hits PT
    c1_pt_pnl = pt1_atr * df["atr_at_signal"] * NQ_MULT - 2 * COMMISSION
    # When C1 hits PT, it locks in pt1 profit; else C1 exits at regime
    df["c1_pnl"] = np.where(df["c1_hits_pt"], c1_pt_pnl, df["net_pnl"])
    df["c2_pnl"] = df["net_pnl"]   # always regime exit
    df["total_2c_pt1"] = df["c1_pnl"] + df["c2_pnl"]
    df["total_2c_naive"] = 2 * df["net_pnl"]
    return df


def report(df, label):
    n = len(df)
    one_c = df["net_pnl"].sum()
    two_c_naive = df["total_2c_naive"].sum()
    two_c_pt1 = df["total_2c_pt1"].sum()
    pt1_hits = df["c1_hits_pt"].sum()
    print(f"\n{label}  (n={n:,})")
    print(f"  1c V_A baseline:      ${one_c:>+10,.0f}  "
          f"(${one_c/n:>+6.2f}/tr)")
    print(f"  2c naive (× 2):       ${two_c_naive:>+10,.0f}  "
          f"(${two_c_naive/n:>+6.2f}/tr)")
    print(f"  2c PT1 @ 1ATR:        ${two_c_pt1:>+10,.0f}  "
          f"(${two_c_pt1/n:>+6.2f}/tr)")
    print(f"  Δ (PT1 vs naive):     ${two_c_pt1 - two_c_naive:>+10,.0f}")
    print(f"  PT1 hits: {pt1_hits:,}/{n:,} "
          f"({100*pt1_hits/n:.1f}%)")


def main():
    print("=" * 78)
    print("2-CONTRACT PT1 STRATEGY  (1 off at +1 ATR, runner to regime)")
    print("=" * 78)

    df = pd.concat([load_year(yr) for yr in (2024, 2025, 2026)],
                     ignore_index=True)
    df = compute_2c(df, pt1_atr=1.0)

    # Per-year
    print(f"\n{'='*78}")
    print("PER-YEAR")
    print(f"{'='*78}")
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        report(sub, f"--- {yr} ---")
    report(df, "--- ALL YEARS ---")

    # ----- Decomposition: how much does PT1 add over naive doubling? -----
    print(f"\n{'='*78}")
    print("WHERE THE PT1 LIFT COMES FROM")
    print(f"{'='*78}")
    df["pt1_vs_runner_lift"] = df["total_2c_pt1"] - df["total_2c_naive"]
    # Lift is non-zero only when PT1 hits
    pt1_only = df[df["c1_hits_pt"]]
    print(f"\n  Trades with PT1 hit: {len(pt1_only):,}")
    print(f"  Total PT1-vs-naive lift: "
          f"${pt1_only['pt1_vs_runner_lift'].sum():+,.0f}")
    print(f"  Mean lift on PT1 trades: "
          f"${pt1_only['pt1_vs_runner_lift'].mean():+.2f}")

    # Split PT1 trades by what would have happened at regime
    print(f"\n  PT1-hit trades by REGIME outcome:")
    for label, mask in [
        ("regime winner (all good)", pt1_only["is_winner"]),
        ("regime loser (giveback rescued)", ~pt1_only["is_winner"]),
    ]:
        sub = pt1_only[mask]
        if not len(sub): continue
        # Naive: 2 * net_pnl
        # PT1:   c1_pt + net_pnl
        # Lift:  c1_pt - net_pnl
        # When net_pnl > c1_pt (big winner): lift NEGATIVE (gave up upside)
        # When net_pnl < c1_pt (small win or loss): lift POSITIVE
        print(f"    {label}: n={len(sub):,}")
        print(f"      sum lift: ${sub['pt1_vs_runner_lift'].sum():+,.0f}")
        print(f"      mean lift: ${sub['pt1_vs_runner_lift'].mean():+.2f}")
        print(f"      mean original net_pnl: ${sub['net_pnl'].mean():+.2f}")

    # ----- Sweep PT1 levels -----
    print(f"\n{'='*78}")
    print("PT1 LEVEL SWEEP (compare locked-in profit at different ATR)")
    print(f"{'='*78}")
    print(f"  {'PT1':<6}  {'%hits':>6}  {'1c':>10}  {'2c naive':>10}  "
          f"{'2c PT1':>10}  {'Δ vs naive':>11}  {'Δ vs 1c':>10}")
    for pt in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]:
        d = compute_2c(df, pt1_atr=pt)
        n = len(d)
        one_c = d["net_pnl"].sum()
        two_c_naive = d["total_2c_naive"].sum()
        two_c_pt1 = d["total_2c_pt1"].sum()
        pt1_hits = d["c1_hits_pt"].sum()
        print(f"  {pt:<6.2f}  {100*pt1_hits/n:>5.1f}%  "
              f"{one_c:>+9,.0f}  {two_c_naive:>+9,.0f}  "
              f"{two_c_pt1:>+9,.0f}  "
              f"{two_c_pt1 - two_c_naive:>+10,.0f}  "
              f"{two_c_pt1 - one_c:>+9,.0f}")

    # Per-year by PT1 level
    print(f"\n{'='*78}")
    print("PT1=1.0 ATR — PER YEAR DETAIL")
    print(f"{'='*78}")
    d = compute_2c(df, pt1_atr=1.0)
    print(f"  {'year':<5}  {'n':>5}  {'1c$':>9}  {'2c_naive$':>10}  "
          f"{'2c_PT1$':>10}  {'$/tr_PT1':>9}  {'Δ_naive':>9}")
    for yr in (2024, 2025, 2026):
        sub = d[d["year"] == yr]
        n = len(sub)
        oc = sub["net_pnl"].sum()
        nv = sub["total_2c_naive"].sum()
        pt = sub["total_2c_pt1"].sum()
        print(f"  {yr:<5}  {n:>5,}  {oc:>+8,.0f}  {nv:>+9,.0f}  "
              f"{pt:>+9,.0f}  {pt/n:>+8.2f}  {pt - nv:>+8,.0f}")


if __name__ == "__main__":
    main()
