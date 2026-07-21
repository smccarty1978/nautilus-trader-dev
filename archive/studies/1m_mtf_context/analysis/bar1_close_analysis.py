"""Analysis 1-2: Bar+1 close features.

1. bar1_close_above_flip_close: does bar+1 closing in the flip direction
   relative to flip bar's close predict better outcomes?
2. bar1_close_above_50pct_range: does bar+1 closing in the upper half
   (direction-aware) predict better?
3. bar1_close_location: quintile analysis.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
import os
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

from _common import (load_trades, summarize_segment, print_segment_row,
                      cohens_d, bracket_pnl)
import pandas as pd
import numpy as np


def main():
    print("=" * 100)
    print("ANALYSIS 1-2: Bar+1 Close Features")
    print("=" * 100)
    trades = load_trades()
    print(f"\n  {len(trades):,} trades loaded")

    TAG = "075_075"
    PT = 0.75
    SL = 0.75

    # Binary split 1: bar1_close_above_flip_close
    print("\n\n--- Split 1: bar1_close_above_flip_close (1=bar+1 closed "
          "beyond flip close in flip direction) ---\n")
    for val in [1, 0]:
        sub = trades[trades["bar1_close_above_flip_close"] == val]
        label = f"bar1_above_flip={val}"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # Binary split 2: bar1_close_above_50pct_range
    print("\n\n--- Split 2: bar1_close_above_50pct_range (direction-aware) ---\n")
    for val in [1, 0]:
        sub = trades[trades["bar1_close_above_50pct_range"] == val]
        label = f"bar1_above_50pct_range={val}"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # Quintile on bar1_close_location (0=low, 1=high)
    # Direction-aware: for longs higher = better, for shorts flip it
    print("\n\n--- Quintile: bar1_close_location (direction-aware) ---\n")
    cl = trades["bar1_close_location"].copy()
    # direction-aware: for shorts, flip (1 - cl)
    cl_adj = np.where(trades["direction"] == 1, cl, 1 - cl)
    trades["_cl_adj"] = cl_adj
    trades["_q"] = pd.qcut(trades["_cl_adj"], q=5, labels=False,
                            duplicates="drop")
    for q in sorted(trades["_q"].dropna().unique()):
        sub = trades[trades["_q"] == q]
        q_lo = sub["_cl_adj"].min()
        q_hi = sub["_cl_adj"].max()
        label = f"Q{int(q)+1} [{q_lo:.2f}, {q_hi:.2f}]"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # Quintile on bar1_body_pct
    print("\n\n--- Quintile: bar1_body_pct (body as % of range) ---\n")
    trades["_q"] = pd.qcut(trades["bar1_body_pct"], q=5, labels=False,
                            duplicates="drop")
    for q in sorted(trades["_q"].dropna().unique()):
        sub = trades[trades["_q"] == q]
        q_lo = sub["bar1_body_pct"].min()
        q_hi = sub["bar1_body_pct"].max()
        label = f"Q{int(q)+1} [{q_lo:.2f}, {q_hi:.2f}]"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # Quintile on bar1_hh_amount_atr (strength of HH/LL confirmation)
    print("\n\n--- Quintile: bar1_hh_amount_atr (strength of confirmation) ---\n")
    trades["_q"] = pd.qcut(trades["bar1_hh_amount_atr"], q=5, labels=False,
                            duplicates="drop")
    for q in sorted(trades["_q"].dropna().unique()):
        sub = trades[trades["_q"] == q]
        q_lo = sub["bar1_hh_amount_atr"].min()
        q_hi = sub["bar1_hh_amount_atr"].max()
        label = f"Q{int(q)+1} [{q_lo:.3f}, {q_hi:.3f}]"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
