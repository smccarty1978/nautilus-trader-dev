"""Analysis 4: Volume at flip + bar+1."""

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


def quintile_section(trades, col, label_prefix, tag, pt, sl, fmt=".2f"):
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
    print("ANALYSIS 4: Volume at flip + bar+1")
    print("=" * 100)
    trades = load_trades()
    print(f"\n  {len(trades):,} trades loaded")

    TAG = "075_075"
    PT = 0.75
    SL = 0.75

    quintile_section(trades, "flip_vol_vs_20avg",
                      "flip_vol_vs_20avg", TAG, PT, SL)
    quintile_section(trades, "bar1_vol_vs_20avg",
                      "bar1_vol_vs_20avg", TAG, PT, SL)
    quintile_section(trades, "bar1_vol_vs_flip_vol",
                      "bar1_vol_vs_flip_vol", TAG, PT, SL)
    quintile_section(trades, "flip_bar_bullish_volume_pct",
                      "flip_bar_bullish_volume_pct", TAG, PT, SL, fmt=".3f")
    quintile_section(trades, "bar1_bullish_volume_pct",
                      "bar1_bullish_volume_pct", TAG, PT, SL, fmt=".3f")
    quintile_section(trades, "cumulative_volume_bias_10",
                      "cumulative_volume_bias_10", TAG, PT, SL, fmt=".3f")
    quintile_section(trades, "vol_acceleration_5bar",
                      "vol_acceleration_5bar", TAG, PT, SL)
    quintile_section(trades, "flip_bar_vol_rank_20",
                      "flip_bar_vol_rank_20", TAG, PT, SL, fmt=".3f")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
