"""MFE gate analysis — what threshold at 60s eliminates 90% of losers?

For each bracket, show MFE@60s distribution by outcome (PT, SL, neither).
Find the MFE threshold T such that 90% of losers have mfe_at_60s < T.
Compute % of winners kept at that threshold.
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

NQ_MULT = 20.0
COMMISSION = 5.0


BRACKETS = [
    ("050_050", 0.50, 0.50),
    ("075_075", 0.75, 0.75),
    ("100_050", 1.00, 0.50),
    ("100_100", 1.00, 1.00),
    ("150_075", 1.50, 0.75),
]
TIME_SNAPS = [30, 60, 120]


def distribution(label, vals):
    vals = np.asarray(vals)
    vals = vals[~pd.isna(vals)]
    if len(vals) == 0:
        return f"  {label}: no data"
    return (f"  {label:<12}  N={len(vals):>6,}  "
            f"P10={np.percentile(vals, 10):>5.2f}  "
            f"P25={np.percentile(vals, 25):>5.2f}  "
            f"P50={np.percentile(vals, 50):>5.2f}  "
            f"P75={np.percentile(vals, 75):>5.2f}  "
            f"P90={np.percentile(vals, 90):>5.2f}  "
            f"mean={vals.mean():>5.2f}")


def find_loser_pct_threshold(loser_mfe, target_filter_pct=90.0):
    """Find T s.t. target_filter_pct% of losers have mfe < T."""
    vals = np.asarray(loser_mfe)
    vals = vals[~pd.isna(vals)]
    if len(vals) == 0:
        return None
    return np.percentile(vals, target_filter_pct)


def gate_analysis(trades, tag, pt, sl, label, snap_col):
    """For one bracket + one snap time, build the MFE gate analysis."""
    res = trades[f"bracket_{tag}_result"].values
    mfe = trades[snap_col].values
    atr = trades["atr_at_entry"].values
    reg_pnl = trades["regime_pnl_dollars"].values

    # Define winners/losers by bracket outcome
    pt_mask = res == "PT"
    sl_mask = res == "SL"
    nei_mask = res == "neither"
    loser_mask = sl_mask | nei_mask

    pt_mfe = mfe[pt_mask]
    sl_mfe = mfe[sl_mask]
    nei_mfe = mfe[nei_mask]
    all_loser_mfe = mfe[loser_mask]

    print(f"\n{'-'*78}")
    print(f"  {label}  bracket {tag}  ({snap_col})")
    print(f"{'-'*78}")
    print(distribution("PT", pt_mfe))
    print(distribution("SL", sl_mfe))
    if len(nei_mfe):
        print(distribution("Neither", nei_mfe))
    print(distribution("ALL Losers", all_loser_mfe))

    # Find threshold that filters 90% of losers
    for filter_pct in [50, 75, 90, 95]:
        thr = find_loser_pct_threshold(all_loser_mfe, filter_pct)
        if thr is None:
            continue
        # How many winners pass (mfe >= thr)
        pt_kept = (pt_mfe >= thr).sum()
        sl_kept = (sl_mfe >= thr).sum()
        nei_kept = (nei_mfe >= thr).sum() if len(nei_mfe) else 0
        loser_kept = sl_kept + nei_kept
        total_kept = pt_kept + loser_kept
        if total_kept == 0:
            continue
        pt_pct_kept = pt_kept / len(pt_mfe) * 100
        loser_pct_kept = loser_kept / len(all_loser_mfe) * 100
        new_pt_pct = pt_kept / total_kept * 100

        # PnL on kept trades
        kept_mask = (mfe >= thr) & ~pd.isna(mfe)
        kept_res = res[kept_mask]
        kept_atr = atr[kept_mask]
        kept_reg = reg_pnl[kept_mask]
        pnl = np.zeros(kept_mask.sum())
        pnl[kept_res == "PT"] = pt * kept_atr[kept_res == "PT"] * NQ_MULT - COMMISSION
        pnl[kept_res == "SL"] = -sl * kept_atr[kept_res == "SL"] * NQ_MULT - COMMISSION
        pnl[kept_res == "neither"] = kept_reg[kept_res == "neither"]
        avg = pnl.mean() if len(pnl) else 0
        total = pnl.sum() if len(pnl) else 0

        be = sl / (pt + sl) * 100
        new_pt_resolved = (
            pt_kept / (pt_kept + sl_kept) * 100
            if (pt_kept + sl_kept) > 0 else 0)
        edge = new_pt_resolved - be
        flag = " ★" if avg > 0 else ""
        print(f"  Filter {filter_pct}% losers @ MFE >= {thr:>5.3f}: "
              f"keep {total_kept:,} trades ({pt_pct_kept:.0f}% PT, "
              f"{loser_pct_kept:.0f}% losers).  "
              f"new PT/(PT+SL)={new_pt_resolved:.1f}% vs BE={be:.1f}% "
              f"(edge {edge:+.1f}pp).  Avg=${avg:+.1f}  Tot=${total:+,.0f}{flag}")


def main():
    print("=" * 78)
    print("MFE GATE — distributions and threshold analysis")
    print("=" * 78)

    trades = pd.read_parquet(
        "studies/1m_mtf_context/results/trades_all.parquet").copy()
    print(f"\n  {len(trades):,} trades loaded")

    # Confirm MFE columns exist
    missing = [c for c in [f"mfe_at_{t}s" for t in TIME_SNAPS]
                if c not in trades.columns]
    if missing:
        print(f"  Missing columns: {missing}")
        return
    print(f"  MFE snapshot columns OK: {[f'mfe_at_{t}s' for t in TIME_SNAPS]}")

    # Q1 subset
    trades["_q"] = pd.qcut(trades["two_bar_close_vs_open_pct"], q=5,
                            labels=False, duplicates="drop")
    q1 = trades[trades["_q"] == 0].copy()

    # ---- ALL trades ----
    print(f"\n{'='*78}")
    print(f"ALL TRADES (N={len(trades):,})")
    print(f"{'='*78}")
    for tag, pt, sl in BRACKETS:
        for t in TIME_SNAPS:
            gate_analysis(trades, tag, pt, sl,
                           f"ALL trades", f"mfe_at_{t}s")

    # ---- Q1 subset ----
    print(f"\n{'='*78}")
    print(f"Q1 of two_bar_close_vs_open_pct (N={len(q1):,})")
    print(f"{'='*78}")
    for tag, pt, sl in BRACKETS:
        for t in TIME_SNAPS:
            gate_analysis(q1, tag, pt, sl,
                           f"Q1 subset", f"mfe_at_{t}s")

    print(f"\n{'='*78}")


if __name__ == "__main__":
    main()
