"""Constant-anchor C strategy on no-delay V_A data.

Original C: unr_pnl_T_5m = (close@+5m − V_A_fill_price) × dir × 20
            Anchor (V_A fill) shifts when V_A entry timing shifts.

Constant-anchor C: unr_pnl_anchored = (close@+5m − bar1_close_price) × dir × 20
            Anchor (bar1_close) is invariant to V_A entry timing.

This isolates "did the price move >X from the confirmation bar?"
without picking up V-shape recovery artifacts that are sensitive to
the exact V_A fill timing.

Question: does the constant-anchor C produce similar PnL to V_A entry-
anchored C? If yes, the C edge is a "did price move favorably from
bar1 close?" signal. If no, the original C was relying on the V-shape
selection effect.

Reports:
  Both anchor variants on no-delay V_A data, same threshold method
  (IS-q80), per-year + monthly metrics.
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
EPS = 1e-6

OUT = Path("studies/v_a_excursion_regime/results_v0")


def metrics(df, pnl_col, ts_col="entry_ts"):
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


def build_bar1_close_lookup():
    """For each V_A no-delay trade, get bar1_close_price from
    bar1_check snapshot. Match by direction + bar_ts_event."""
    rows = []
    for yr in (2024, 2025, 2026):
        snap = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_nodelay_{yr}/"
            f"snapshots.parquet")
        b1 = snap[snap["kind"] == "bar1_check"][
            ["decision_ts", "direction", "bar1_c", "confirmed"]].copy()
        b1 = b1[b1["confirmed"]]
        b1["year"] = yr
        rows.append(b1)
    out = pd.concat(rows, ignore_index=True)
    out = out.rename(columns={"bar1_c": "bar1_close_px"})
    return out[["decision_ts", "direction", "bar1_close_px", "year"]]


def main():
    t0 = time.time()
    print("=" * 78)
    print("CONSTANT-ANCHOR C  vs  V_A-FILL-ANCHOR C  (no-delay data)")
    print("=" * 78)

    df = pd.read_parquet(OUT / "checkpoint_features_nodelay.parquet")
    n_pre = len(df)
    df = df.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    if n_pre != len(df):
        print(f"  deduped: {n_pre:,} -> {len(df):,}")
    print(f"\n  no-delay V_A trades: {len(df):,}")

    # Need bar1_close_px from no-delay snapshots
    print("\n  loading bar1_close lookup...")
    b1_lookup = build_bar1_close_lookup()
    # V_A trade decision_ts == bar1_check decision_ts
    df = df.merge(b1_lookup[["decision_ts", "bar1_close_px"]]
                    .drop_duplicates(subset="decision_ts"),
                    left_on="entry_ts", right_on="decision_ts", how="left")
    # Wait — V_A trade's decision_ts is bar1_check decision_ts, NOT entry_ts.
    # The trades.parquet should have decision_ts column.
    print(f"  merged on entry_ts → bar1_check.decision_ts...")
    print(f"  bar1_close_px non-null: "
          f"{df['bar1_close_px'].notna().sum():,} / {len(df):,}")
    if df['bar1_close_px'].isna().any():
        print(f"  WARN: trying decision_ts merge instead")

    # Try matching on the V_A trade's decision_ts column from trades.parquet
    if df['bar1_close_px'].isna().sum() > 100:
        df = df.drop(columns=['bar1_close_px', 'decision_ts'])
        # Reload trades to get decision_ts
        tr_rows = []
        for yr in (2024, 2025, 2026):
            tr = pd.read_parquet(
                f"collectors/collector_v2/results/v_a_v0_nodelay_{yr}/"
                f"trades.parquet")[["entry_ts", "decision_ts"]]
            tr_rows.append(tr)
        tr_full = pd.concat(tr_rows, ignore_index=True)
        tr_full = tr_full.drop_duplicates(subset="entry_ts", keep="first")
        df = df.merge(tr_full, on="entry_ts", how="left")
        df = df.merge(b1_lookup[["decision_ts", "bar1_close_px"]]
                        .drop_duplicates(subset="decision_ts"),
                        on="decision_ts", how="left")
        print(f"  retried via trades.decision_ts merge: "
              f"bar1_close_px non-null = "
              f"{df['bar1_close_px'].notna().sum():,} / {len(df):,}")

    assert df["bar1_close_px"].notna().all(), "missing bar1_close_px"

    # Compute constant-anchor unr_pnl at +5m
    df["close_at_5m"] = (df["fill_px"]   # placeholder — need actual close@5m
                          + df["f_unr_pnl_T_5m"] / NQ_MULT
                            * df["direction"])
    # Wait: f_unr_pnl_T_5m = (close@5m - fill_px) * dir * 20
    # → close@5m = fill_px + (f_unr_pnl / 20) * direction
    # Reverse: f_unr_pnl_T_5m / NQ_MULT = (close@5m - fill_px) * direction
    # → close@5m - fill_px = (f_unr_pnl_T_5m / NQ_MULT) * direction
    # → close@5m = fill_px + (f_unr_pnl_T_5m / NQ_MULT) * direction

    # New unr_pnl with bar1_close_px as anchor
    df["f_unr_pnl_anc_T_5m"] = (
        (df["close_at_5m"] - df["bar1_close_px"])
        * df["direction"] * NQ_MULT)

    # Some sanity: V_A fill_px should be ≈ bar1_close_px (no-delay enters
    # at bar1_close + 1s, so price ≈ bar1 close). Diff should be tiny.
    diff = (df["fill_px"] - df["bar1_close_px"]) * df["direction"]
    print(f"\n  fill_px - bar1_close_px (signed by direction):")
    print(f"    median: {diff.median():.4f} pts")
    print(f"    mean:   {diff.mean():.4f} pts")
    print(f"    p10/p90: {diff.quantile(0.1):.4f} / {diff.quantile(0.9):.4f}")

    # Compare the two unr_pnl values
    print(f"\n  Distribution of f_unr_pnl_T_5m (V_A-anchor):")
    f1 = df[df['alive_5m']]["f_unr_pnl_T_5m"]
    print(f"    median: ${f1.median():.0f}  q80: ${f1.quantile(0.80):.0f}  "
          f"q90: ${f1.quantile(0.90):.0f}")
    print(f"  Distribution of f_unr_pnl_anc_T_5m (bar1-anchor):")
    f2 = df[df['alive_5m']]["f_unr_pnl_anc_T_5m"]
    print(f"    median: ${f2.median():.0f}  q80: ${f2.quantile(0.80):.0f}  "
          f"q90: ${f2.quantile(0.90):.0f}")
    print(f"  Mean abs difference: ${(f1 - f2).abs().mean():.2f}")

    # ===== Apply each filter, fit IS-only =====
    is_alive = df[df["alive_5m"] & df["year"].isin([2024, 2025])]
    thr_va = is_alive["f_unr_pnl_T_5m"].quantile(0.80)
    thr_anc = is_alive["f_unr_pnl_anc_T_5m"].quantile(0.80)
    print(f"\n  IS-q80 thresholds:")
    print(f"    V_A-anchor:   ${thr_va:.0f}")
    print(f"    bar1-anchor:  ${thr_anc:.0f}")

    alive = df[df["alive_5m"]].copy()
    c_va = alive[alive["f_unr_pnl_T_5m"] >= thr_va]
    c_anc = alive[alive["f_unr_pnl_anc_T_5m"] >= thr_anc]

    m_va = metrics(c_va, "d_pnl_5m")
    m_anc = metrics(c_anc, "d_pnl_5m")

    # Cohort overlap
    overlap = (alive["f_unr_pnl_T_5m"] >= thr_va) & (
        alive["f_unr_pnl_anc_T_5m"] >= thr_anc)
    only_va = (alive["f_unr_pnl_T_5m"] >= thr_va) & ~(
        alive["f_unr_pnl_anc_T_5m"] >= thr_anc)
    only_anc = ~(alive["f_unr_pnl_T_5m"] >= thr_va) & (
        alive["f_unr_pnl_anc_T_5m"] >= thr_anc)

    print(f"\n  Cohort overlap analysis:")
    print(f"    V_A-anchor cohort size:    {(alive['f_unr_pnl_T_5m'] >= thr_va).sum():,}")
    print(f"    bar1-anchor cohort size:   {(alive['f_unr_pnl_anc_T_5m'] >= thr_anc).sum():,}")
    print(f"    Both:                      {overlap.sum():,}")
    print(f"    Only V_A-anchor:           {only_va.sum():,}")
    print(f"    Only bar1-anchor:          {only_anc.sum():,}")

    # Compare PnL by subset
    print(f"\n{'='*120}")
    print("HEAD-TO-HEAD: V_A-anchor C vs bar1-anchor C  (no-delay V_A data)")
    print(f"{'='*120}")
    print(f"  {'strategy':<35}  {'n':>5}  {'total$':>10}  {'$/tr':>7}  "
          f"{'WR%':>5}  {'max DD':>10}  "
          f"{'2024':>10}  {'2025':>10}  {'2026':>10}  {'+mo':>6}")

    def pr(label, m):
        pos = f"{m['pos_months']}/{m['total_months']}"
        print(f"  {label:<35}  {m['n']:>5,}  ${m['total']:>+8,.0f}  "
              f"{m['per_tr']:>+6.2f}  {m['wr_pct']:>4.1f}  "
              f"${m['max_dd']:>+8,.0f}  "
              f"${m['y2024']:>+8,.0f}  ${m['y2025']:>+8,.0f}  "
              f"${m['y2026']:>+8,.0f}  {pos:>6}")

    pr(f"V_A-anchor C (>= ${thr_va:.0f})", m_va)
    pr(f"bar1-anchor C (>= ${thr_anc:.0f})", m_anc)

    # PnL of subsets (by exclusivity)
    print(f"\n  PnL contribution by cohort subset:")
    for label, mask in [
        ("Both (overlap)", overlap),
        ("Only V_A-anchor", only_va),
        ("Only bar1-anchor", only_anc),
    ]:
        sub = alive[mask]
        if len(sub) == 0: continue
        m = metrics(sub, "d_pnl_5m")
        pr(f"  {label}", m)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
