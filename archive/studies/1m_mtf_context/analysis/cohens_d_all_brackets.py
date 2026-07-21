"""Cohen's d scan across all 5 brackets.

For each (feature, bracket), compute d between PT-first and SL-first
populations. Show top features per bracket and a unified table.
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


BRACKETS = [
    ("050_050", 0.50, 0.50, "1:1"),
    ("075_075", 0.75, 0.75, "1:1"),
    ("100_050", 1.00, 0.50, "2:1"),
    ("100_100", 1.00, 1.00, "1:1"),
    ("150_075", 1.50, 0.75, "2:1"),
]

EXCLUDE = {
    "trade_id", "flip_ts", "flip_time", "entry_ts", "entry_time",
    "exit_ts", "exit_time", "direction", "year", "hour_of_day",
    "minute_of_hour", "is_rth", "confirmed",
    "regime_5m", "regime_15m", "regime_5m_aligned", "regime_15m_aligned",
    "regime_alignment_score", "all_regimes_aligned",
    "bar1_close_above_flip_close", "bar1_close_above_50pct_range",
    "mfe_first",
}


def list_feature_cols(trades):
    exclude_prefixes = (
        "bracket_", "bars_to_", "mfe_at_", "mae_at_",
        "peak_mfe", "peak_mae", "mae_at_peak", "mfe_at_peak",
        "exit_price", "entry_price", "regime_pnl",
        "regime_duration", "bars_processed",
    )
    return [c for c in trades.columns
            if c not in EXCLUDE
            and not any(c.startswith(p) for p in exclude_prefixes)
            and trades[c].dtype.kind in "fiub"]


def main():
    print("=" * 110)
    print("COHEN'S d SCAN — ALL 5 BRACKETS")
    print("=" * 110)
    trades = load_trades()
    print(f"\n  {len(trades):,} trades, 6 years")

    features = list_feature_cols(trades)
    print(f"  {len(features)} features tested\n")

    # Per-bracket: PT/SL counts + top |d| features
    per_bracket = {}
    for tag, pt, sl, ratio in BRACKETS:
        race = trades[f"bracket_{tag}_result"].values
        n_pt = (race == "PT").sum()
        n_sl = (race == "SL").sum()
        n_nei = (race == "neither").sum()
        be_wr = sl / (pt + sl) * 100
        actual_pt_pct = n_pt / len(trades) * 100
        edge = actual_pt_pct - be_wr
        print(f"  Bracket {tag} (PT={pt:.2f}/SL={sl:.2f}, {ratio}): "
              f"PT={actual_pt_pct:5.1f}% SL={n_sl/len(trades)*100:5.1f}% "
              f"Nei={n_nei/len(trades)*100:5.1f}% "
              f"BE={be_wr:5.1f}% edge={edge:+.1f}pp")

    # Now compute d for every (feature, bracket) combo
    print(f"\n{'='*110}")
    print(f"PER-BRACKET TOP 15 FEATURES BY |d|")
    print(f"{'='*110}")
    all_results = {}
    for tag, pt, sl, ratio in BRACKETS:
        race = trades[f"bracket_{tag}_result"].values
        pt_mask = race == "PT"
        sl_mask = race == "SL"
        rows = []
        for f in features:
            vals = trades[f].values.astype(float)
            d = cohens_d(vals[pt_mask], vals[sl_mask])
            rows.append({"feat": f, "d": d,
                         "pt_n": pt_mask.sum(), "sl_n": sl_mask.sum()})
        rows.sort(key=lambda r: -abs(r["d"]) if not pd.isna(r["d"]) else 0)
        all_results[tag] = rows

        print(f"\n--- Bracket {tag} (PT={pt:.2f}/SL={sl:.2f}) ---")
        print(f"  PT N={rows[0]['pt_n']:,} | SL N={rows[0]['sl_n']:,}")
        print(f"  {'Feature':<38} {'d':>8}  Flag")
        print(f"  {'-' * 60}")
        for r in rows[:15]:
            flag = ""
            if abs(r["d"]) >= 0.20: flag = "★★"
            elif abs(r["d"]) >= 0.10: flag = "★"
            elif abs(r["d"]) >= 0.05: flag = "·"
            print(f"  {r['feat']:<38} {r['d']:>+8.3f}  {flag}")

    # Unified comparison: features that show up in top of any bracket
    print(f"\n{'='*110}")
    print(f"UNIFIED COMPARISON — features ranked by max |d| across brackets")
    print(f"{'='*110}")
    feat_max = {}
    for f in features:
        ds = []
        for tag in [t[0] for t in BRACKETS]:
            row = next((r for r in all_results[tag] if r["feat"] == f), None)
            if row and not pd.isna(row["d"]):
                ds.append((tag, row["d"]))
        max_d = max(ds, key=lambda x: abs(x[1])) if ds else (None, 0)
        feat_max[f] = (max_d, ds)
    # Sort by max abs d
    sorted_feats = sorted(feat_max.items(),
                            key=lambda x: -abs(x[1][0][1]))

    print(f"\n  {'Feature':<38} "
          f"{'050/050':>9} {'075/075':>9} {'100/050':>9} "
          f"{'100/100':>9} {'150/075':>9}  Max Flag")
    print(f"  {'-' * 100}")
    for f, ((max_tag, max_d), ds) in sorted_feats[:30]:
        d_dict = dict(ds)
        cells = []
        for tag in [t[0] for t in BRACKETS]:
            d_val = d_dict.get(tag, 0)
            cells.append(f"{d_val:>+9.3f}")
        flag = ""
        if abs(max_d) >= 0.20: flag = "★★"
        elif abs(max_d) >= 0.10: flag = "★"
        elif abs(max_d) >= 0.05: flag = "·"
        print(f"  {f:<38} " + " ".join(cells) + f"  {flag}")

    # Quintile analysis on any feature with |d| >= 0.10 in ANY bracket
    print(f"\n{'='*110}")
    print(f"QUINTILE ANALYSIS — features with |d| >= 0.10 in any bracket")
    print(f"{'='*110}")
    promising = [(f, ms) for f, (ms, ds) in sorted_feats
                  if abs(ms[1]) >= 0.10]
    if not promising:
        print("\n  No features cross |d| >= 0.10 in any bracket.")
    else:
        for f, (max_tag, max_d) in promising[:5]:
            for tag, pt, sl, ratio in BRACKETS:
                if tag != max_tag:
                    continue
                print(f"\n--- {f}  bracket {tag}  (d={max_d:+.3f}) ---\n")
                try:
                    trades["_q"] = pd.qcut(trades[f], q=5, labels=False,
                                            duplicates="drop")
                except ValueError:
                    continue
                for q in sorted(trades["_q"].dropna().unique()):
                    sub = trades[trades["_q"] == q]
                    q_lo = sub[f].min()
                    q_hi = sub[f].max()
                    label = f"Q{int(q)+1} [{q_lo:.3f}, {q_hi:.3f}]"
                    s = summarize_segment(label, sub, tag, pt, sl)
                    print_segment_row(s)

    print(f"\n{'='*110}")


if __name__ == "__main__":
    main()
