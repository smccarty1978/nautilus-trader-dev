"""Analysis 3: Multi-timeframe regime alignment.

Tests whether 5m and 15m regime alignment with the 1m flip direction
predicts better bracket outcomes.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

from _common import load_trades, summarize_segment, print_segment_row
import pandas as pd


def main():
    print("=" * 100)
    print("ANALYSIS 3: Multi-Timeframe Regime Alignment")
    print("=" * 100)
    trades = load_trades()
    print(f"\n  {len(trades):,} trades loaded")

    TAG = "075_075"
    PT = 0.75
    SL = 0.75

    # regime_alignment_score: 1, 2, or 3 (1m + 5m + 15m)
    print("\n\n--- Regime alignment score (1m/5m/15m) ---\n")
    for score in sorted(trades["regime_alignment_score"].unique()):
        sub = trades[trades["regime_alignment_score"] == score]
        label = f"alignment_score={score}"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # 5m alignment only
    print("\n\n--- 5m alignment only ---\n")
    for val in [1, 0]:
        sub = trades[trades["regime_5m_aligned"] == val]
        label = f"regime_5m_aligned={val}"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # 15m alignment only
    print("\n\n--- 15m alignment only ---\n")
    for val in [1, 0]:
        sub = trades[trades["regime_15m_aligned"] == val]
        label = f"regime_15m_aligned={val}"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # All three aligned
    print("\n\n--- all_regimes_aligned (1m+5m+15m same direction) ---\n")
    for val in [1, 0]:
        sub = trades[trades["all_regimes_aligned"] == val]
        label = f"all_regimes_aligned={val}"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # 5m regime duration — maybe bigger HTF regimes = stronger confirmation
    print("\n\n--- 5m regime duration (quintiles) ---\n")
    trades["_q"] = pd.qcut(trades["regime_5m_duration_bars"], q=5,
                            labels=False, duplicates="drop")
    for q in sorted(trades["_q"].dropna().unique()):
        sub = trades[trades["_q"] == q]
        q_lo = sub["regime_5m_duration_bars"].min()
        q_hi = sub["regime_5m_duration_bars"].max()
        label = f"Q{int(q)+1} 5m dur [{q_lo:.0f}, {q_hi:.0f}]"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    # 15m regime duration
    print("\n\n--- 15m regime duration (quintiles) ---\n")
    trades["_q"] = pd.qcut(trades["regime_15m_duration_bars"], q=5,
                            labels=False, duplicates="drop")
    for q in sorted(trades["_q"].dropna().unique()):
        sub = trades[trades["_q"] == q]
        q_lo = sub["regime_15m_duration_bars"].min()
        q_hi = sub["regime_15m_duration_bars"].max()
        label = f"Q{int(q)+1} 15m dur [{q_lo:.0f}, {q_hi:.0f}]"
        s = summarize_segment(label, sub, TAG, PT, SL)
        print_segment_row(s)

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
