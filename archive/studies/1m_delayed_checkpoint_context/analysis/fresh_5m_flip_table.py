"""Analysis C — Fresh 5m flip checkpoint table.

Group trades by regime_5m_flip_checkpoint (root-level).
For each group, evaluate using the SAME T's checkpoint fields
(not pooled across delays).

Examples:
  - flip_cp = 120 → use _120 checkpoint fields
  - flip_cp = 0   → use _000 checkpoint fields (already aligned at T0)
  - flip_cp = NaN → never aligned during window; use T=0 fields for context

All metrics from checkpoint_entry_fill_price_T of the matching T.
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


def group_stats(label, df, T):
    """Compute stats for a subset of trades evaluated at their T."""
    tag = f"{T:03d}"
    fillable_col = f"fillable_at_T_{tag}"
    fwd_pnl = df[f"forward_regime_pnl_dollars_T_{tag}"]
    peak_mfe = df[f"forward_peak_mfe_atr_T_{tag}"]
    peak_mae = df[f"forward_peak_mae_atr_T_{tag}"]
    fill_mask = df[fillable_col] == 1

    n_total = len(df)
    n_fill = fill_mask.sum()

    if n_fill == 0:
        return {
            "group": label, "n": n_total, "n_fillable": 0,
            "wr%": np.nan, "avg$": np.nan, "med$": np.nan, "pf": np.nan,
            "med_mfe": np.nan, "med_mae": np.nan, "med_ratio": np.nan,
            "RTH_avg$": np.nan, "ETH_avg$": np.nan,
        }

    sub = df[fill_mask]
    pnl = fwd_pnl[fill_mask]
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    med = pnl.median()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")

    sub_mfe = peak_mfe[fill_mask]
    sub_mae = peak_mae[fill_mask]
    ratio = sub_mfe / sub_mae.replace(0, np.nan)

    # RTH/ETH avg
    is_rth = sub["is_rth"]
    rth_pnl = pnl[is_rth == 1]
    eth_pnl = pnl[is_rth == 0]
    rth_avg = rth_pnl.mean() if len(rth_pnl) > 0 else np.nan
    eth_avg = eth_pnl.mean() if len(eth_pnl) > 0 else np.nan

    return {
        "group": label, "n": n_total, "n_fillable": int(n_fill),
        "wr%": wr, "avg$": avg, "med$": med, "pf": pf,
        "med_mfe": sub_mfe.median(),
        "med_mae": sub_mae.median(),
        "med_ratio": ratio.median(),
        "RTH_avg$": rth_avg, "ETH_avg$": eth_avg,
    }


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
    n = len(df)
    print(f"Loaded {n:,} trades")
    print(f"  (Each row below evaluated at its OWN T checkpoint, not T0)")

    flip_cp = df["regime_5m_flip_checkpoint"]

    # Buckets: 0, 30, 60, ..., 600, NaN
    buckets = []
    for T in list(range(0, 601, 30)):
        sub = df[flip_cp == T]
        buckets.append((f"flip@{T}s", sub, T))
    # NaN (never aligned)
    nan_sub = df[flip_cp.isna()]
    # For NaN group, use T=0 fields for context
    buckets.append(("never_aligned", nan_sub, 0))

    rows = []
    for label, sub, T in buckets:
        row = group_stats(label, sub, T)
        row["eval_at_T"] = T
        rows.append(row)

    # Print
    print(f"\n{'='*130}")
    print("TABLE C — FRESH 5m FLIP OUTCOMES")
    print("  (each group evaluated using its own T's checkpoint fields)")
    print(f"{'='*130}")
    print(f"  {'Group':<15} {'Eval@':>6} {'N':>6} {'nFill':>6} {'WR%':>6} "
          f"{'Avg$':>7} {'Med$':>7} {'PF':>5} "
          f"{'MFE':>5} {'MAE':>5} {'Ratio':>5}  "
          f"{'RTH$':>8} {'ETH$':>8}")
    print("  " + "-" * 128)
    for r in rows:
        if pd.isna(r["wr%"]):
            print(f"  {r['group']:<15} {r['eval_at_T']:>5}s "
                  f"{r['n']:>6,}  (no fillable trades)")
            continue
        pf = r["pf"]
        pf_s = f"{pf:>5.2f}" if pf != float("inf") else "  inf"
        print(
            f"  {r['group']:<15} {r['eval_at_T']:>5}s "
            f"{r['n']:>6,} {r['n_fillable']:>6,} "
            f"{r['wr%']:>5.1f}% "
            f"${r['avg$']:>+6.1f} "
            f"${r['med$']:>+6.1f} "
            f"{pf_s} "
            f"{r['med_mfe']:>5.2f} "
            f"{r['med_mae']:>5.2f} "
            f"{r['med_ratio']:>5.2f}  "
            f"${r['RTH_avg$']:>+7.1f} "
            f"${r['ETH_avg$']:>+7.1f}"
        )

    # Save
    tdf = pd.DataFrame(rows)
    out = Path("studies/1m_delayed_checkpoint_context/results/"
                "fresh_5m_flip_table.parquet")
    tdf.to_parquet(out, index=False)
    print(f"\n  Saved: {out}")


if __name__ == "__main__":
    main()
