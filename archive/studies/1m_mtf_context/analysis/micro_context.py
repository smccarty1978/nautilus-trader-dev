"""Analysis 6: 5s micro-context."""

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


def quintile_section(trades, col, tag, pt, sl, fmt=".3f"):
    print(f"\n\n--- Quintile: {col} ---\n")
    trades["_q"] = pd.qcut(trades[col], q=5, labels=False,
                            duplicates="drop")
    for q in sorted(trades["_q"].dropna().unique()):
        sub = trades[trades["_q"] == q]
        q_lo = sub[col].min()
        q_hi = sub[col].max()
        label = f"Q{int(q)+1} [{q_lo:{fmt}}, {q_hi:{fmt}}]"
        s = summarize_segment(label, sub, tag, pt, sl)
        print_segment_row(s)


def main():
    print("=" * 100)
    print("ANALYSIS 6: 5s Micro-Context")
    print("=" * 100)
    trades = load_trades()
    print(f"\n  {len(trades):,} trades loaded")

    TAG = "075_075"
    PT = 0.75
    SL = 0.75

    quintile_section(trades, "micro_trend_12bar_5s", TAG, PT, SL)
    quintile_section(trades, "micro_vol_acceleration_5s", TAG, PT, SL)
    quintile_section(trades, "micro_range_compression_5s", TAG, PT, SL)
    quintile_section(trades, "micro_body_pct_avg_5s", TAG, PT, SL)
    quintile_section(trades, "micro_hh_count_12_5s", TAG, PT, SL, fmt=".0f")
    quintile_section(trades, "micro_hl_count_12_5s", TAG, PT, SL, fmt=".0f")
    quintile_section(trades, "micro_up_vol_pct_12_5s", TAG, PT, SL)
    quintile_section(trades, "micro_max_retracement_5s", TAG, PT, SL)
    quintile_section(trades, "bar1_internals_up_pct", TAG, PT, SL)
    quintile_section(trades, "bar1_internals_trend_5s", TAG, PT, SL)

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
