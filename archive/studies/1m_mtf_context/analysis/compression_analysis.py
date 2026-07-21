"""Analysis 5: Pre-flip compression. Compressed price → bigger move?"""

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


def quintile_section(trades, col, tag, pt, sl, fmt=".2f"):
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
    print("ANALYSIS 5: Pre-Flip Compression")
    print("=" * 100)
    trades = load_trades()
    print(f"\n  {len(trades):,} trades loaded")

    TAG = "075_075"
    PT = 0.75
    SL = 0.75

    # Lower range = more compressed = potentially larger expansion
    quintile_section(trades, "pre_flip_3bar_range_atr", TAG, PT, SL)
    quintile_section(trades, "pre_flip_5bar_range_atr", TAG, PT, SL)
    quintile_section(trades, "pre_flip_3bar_body_direction", TAG, PT, SL)
    quintile_section(trades, "consecutive_trend_bars_pre_flip", TAG, PT, SL,
                      fmt=".0f")
    quintile_section(trades, "pre_flip_volume_trend", TAG, PT, SL)
    quintile_section(trades, "prior_regime_duration_bars", TAG, PT, SL,
                      fmt=".0f")
    quintile_section(trades, "prior_regime_mfe_atr", TAG, PT, SL)
    quintile_section(trades, "regime_flips_last_30min", TAG, PT, SL,
                      fmt=".0f")
    quintile_section(trades, "atr_14", TAG, PT, SL)

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
