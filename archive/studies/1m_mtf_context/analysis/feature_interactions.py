"""Analysis 8: Feature interactions.

For features with |d| >= 0.10 in the Cohen's d scan, test pairwise Q5
intersections. Does the intersection push PT-first > 52%?
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

from _common import (load_trades, summarize_segment, print_segment_row,
                      cohens_d)
import pandas as pd
import numpy as np

D_FILE = "studies/1m_mtf_context/results/cohens_d_full.parquet"


def main():
    print("=" * 100)
    print("ANALYSIS 8: Feature Interactions (pairwise Q5)")
    print("=" * 100)
    trades = load_trades()
    if not Path(D_FILE).exists():
        print("  Run cohens_d_full.py first.")
        return
    d_tab = pd.read_parquet(D_FILE)
    d_tab["abs_d"] = d_tab["d"].abs()
    # Select features with |d| >= 0.10, OR top 8 by |d| if fewer pass
    promising = d_tab[d_tab["abs_d"] >= 0.10].copy()
    if len(promising) < 2:
        promising = d_tab.nlargest(8, "abs_d").copy()
    print(f"\n  {len(promising)} promising features:")
    for _, r in promising.iterrows():
        print(f"    {r['feat']:<38} d={r['d']:+.3f}")

    TAG = "075_075"
    PT, SL = 0.75, 0.75

    # Single-feature Q5 baseline — what's PT% at each feature's Q5?
    print(f"\n\n--- Single-feature Q5 baseline ---\n")
    feat_q5 = {}
    for _, r in promising.iterrows():
        f = r["feat"]
        try:
            q_labels = pd.qcut(trades[f], q=5, labels=False,
                                duplicates="drop")
        except ValueError:
            continue
        # direction: if d > 0, PT trades have HIGHER feature values → top quintile
        # if d < 0, PT trades have LOWER feature values → bottom quintile
        if r["d"] > 0:
            mask = (q_labels == (q_labels.max()))  # top quintile
            label = f"{f} Q5 (top)"
        else:
            mask = (q_labels == 0)  # bottom quintile
            label = f"{f} Q1 (bottom)"
        feat_q5[f] = (mask, r["d"])
        sub = trades[mask]
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # Pairwise intersections
    print(f"\n\n--- Pairwise Q5 intersections ---\n")
    feats = list(feat_q5.keys())
    rows = []
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            fa = feats[i]
            fb = feats[j]
            ma, _ = feat_q5[fa]
            mb, _ = feat_q5[fb]
            inter = ma & mb
            if inter.sum() < 100:
                continue
            sub = trades[inter]
            label = f"{fa} ∩ {fb}"
            s = summarize_segment(label, sub, TAG, PT, SL)
            rows.append(s)
    # Sort by PT-first pct
    rows.sort(key=lambda r: -r["pt_pct"])
    for s in rows[:30]:
        print_segment_row(s)

    # Top triple intersection (if any)
    if len(feats) >= 3:
        print(f"\n\n--- Triple Q5 intersections (top 10 by PT%) ---\n")
        trows = []
        for i in range(len(feats)):
            for j in range(i + 1, len(feats)):
                for k in range(j + 1, len(feats)):
                    ma, _ = feat_q5[feats[i]]
                    mb, _ = feat_q5[feats[j]]
                    mc, _ = feat_q5[feats[k]]
                    inter = ma & mb & mc
                    if inter.sum() < 50:
                        continue
                    sub = trades[inter]
                    label = f"{feats[i][:12]}∩{feats[j][:12]}∩{feats[k][:12]}"
                    s = summarize_segment(label, sub, TAG, PT, SL)
                    trows.append(s)
        trows.sort(key=lambda r: -r["pt_pct"])
        for s in trows[:10]:
            print_segment_row(s)

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
