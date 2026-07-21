"""Analysis 7: Cohen's d scan on all 94 features for PT-first vs SL-first
at the 0.75/0.75 bracket.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

from _common import load_trades, cohens_d, summarize_segment, print_segment_row
import pandas as pd
import numpy as np


# Categorical / non-meaningful columns to exclude
EXCLUDE = {
    "trade_id", "flip_ts", "flip_time", "entry_ts", "entry_time",
    "exit_ts", "exit_time", "direction", "year", "hour_of_day",
    "minute_of_hour", "is_rth", "confirmed",
    "regime_5m", "regime_15m", "regime_5m_aligned", "regime_15m_aligned",
    "regime_alignment_score", "all_regimes_aligned",
    "bar1_close_above_flip_close", "bar1_close_above_50pct_range",
    "mfe_first",
}
BRACKET_TAG = "075_075"


def list_feature_cols(trades: pd.DataFrame) -> list:
    """All numeric columns that are plausibly features (not labels)."""
    exclude_prefixes = (
        "bracket_", "bars_to_", "mfe_at_", "mae_at_",
        "peak_mfe", "peak_mae", "mae_at_peak", "mfe_at_peak",
        "exit_price", "entry_price", "regime_pnl",
        "regime_duration", "bars_processed",
    )
    features = []
    for c in trades.columns:
        if c in EXCLUDE:
            continue
        if any(c.startswith(p) for p in exclude_prefixes):
            continue
        if trades[c].dtype.kind in "fiub":  # numeric
            features.append(c)
    return features


def main():
    print("=" * 100)
    print("ANALYSIS 7: Cohen's d scan — all features, PT vs SL "
          f"at bracket {BRACKET_TAG}")
    print("=" * 100)
    trades = load_trades()
    print(f"\n  {len(trades):,} trades")

    race = trades[f"bracket_{BRACKET_TAG}_result"].values
    pt_mask = race == "PT"
    sl_mask = race == "SL"
    print(f"  PT-first: {pt_mask.sum():,} ({pt_mask.mean()*100:.1f}%)")
    print(f"  SL-first: {sl_mask.sum():,} ({sl_mask.mean()*100:.1f}%)")
    print(f"  Neither:  {(race == 'neither').sum():,}")

    features = list_feature_cols(trades)
    print(f"\n  Testing {len(features)} features\n")

    d_table = []
    for f in features:
        vals = trades[f].values.astype(float)
        d = cohens_d(vals[pt_mask], vals[sl_mask])
        pt_m = np.nanmean(vals[pt_mask]) if pt_mask.any() else float("nan")
        sl_m = np.nanmean(vals[sl_mask]) if sl_mask.any() else float("nan")
        d_table.append({
            "feat": f, "d": d, "pt_avg": pt_m, "sl_avg": sl_m,
        })

    d_table.sort(key=lambda r: -abs(r["d"]) if not pd.isna(r["d"]) else 0)

    print(f"{'Feature':<38} {'d':>8}  {'PT avg':>12}  {'SL avg':>12}  Flag")
    print("-" * 100)
    for r in d_table:
        d = r["d"]
        if pd.isna(d):
            continue
        flag = ""
        if abs(d) >= 0.20:
            flag = "★★"
        elif abs(d) >= 0.10:
            flag = "★"
        elif abs(d) >= 0.05:
            flag = "·"
        print(f"{r['feat']:<38} {d:>+8.3f}  {r['pt_avg']:>+12.4f}  "
              f"{r['sl_avg']:>+12.4f}  {flag}")

    # Quintile analysis on features with |d| >= 0.10
    promising = [r for r in d_table
                 if not pd.isna(r["d"]) and abs(r["d"]) >= 0.10]
    if promising:
        print(f"\n\n{'='*100}")
        print("QUINTILE ANALYSIS — features with |d| >= 0.10")
        print(f"{'='*100}")
        for r in promising:
            print(f"\n\n--- {r['feat']} (d={r['d']:+.3f}) ---\n")
            try:
                trades["_q"] = pd.qcut(trades[r["feat"]], q=5,
                                        labels=False, duplicates="drop")
            except ValueError:
                continue
            for q in sorted(trades["_q"].dropna().unique()):
                sub = trades[trades["_q"] == q]
                q_lo = sub[r["feat"]].min()
                q_hi = sub[r["feat"]].max()
                label = f"Q{int(q)+1} [{q_lo:.3f}, {q_hi:.3f}]"
                s = summarize_segment(label, sub, BRACKET_TAG, 0.75, 0.75)
                print_segment_row(s)
    else:
        print("\n  No features with |d| >= 0.10.")

    # Save sorted table
    out_df = pd.DataFrame(d_table)
    out_df.to_parquet(
        "studies/1m_mtf_context/results/cohens_d_full.parquet",
        index=False)
    print(f"\n  Saved: studies/1m_mtf_context/results/cohens_d_full.parquet")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
