"""How long does each exit type take to resolve?

For each bracket and each outcome (PT/SL/neither), report the
distribution of resolution time in 1s bars (seconds since entry).
The path tracker recorded bracket_TAG_bar when the bracket resolved
and bars_processed_1s for the full trade duration (for neither trades
this equals time to regime exit).

Special focus: Q1 of two_bar_close_vs_open_pct subset at 1.00/1.00,
since that's where we found the +4.9pp resolved edge.
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


BRACKETS = [
    ("050_050", 0.50, 0.50),
    ("075_075", 0.75, 0.75),
    ("100_050", 1.00, 0.50),
    ("100_100", 1.00, 1.00),
    ("150_075", 1.50, 0.75),
]


def fmt_time(seconds):
    """Format seconds → 'Xm Ys' or 'Ys'."""
    if seconds is None or pd.isna(seconds):
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60:02d}s"


def report_distribution(label, vals, total_n=None):
    vals = np.asarray(vals)
    vals = vals[~pd.isna(vals)]
    if len(vals) == 0:
        print(f"  {label}: no data")
        return
    n = len(vals)
    pct_str = f" ({n/total_n*100:.1f}% of {total_n:,})" if total_n else ""
    print(f"  {label}{pct_str}: N={n:,}")
    print(f"    P25={fmt_time(np.percentile(vals, 25))}  "
          f"P50={fmt_time(np.percentile(vals, 50))}  "
          f"P75={fmt_time(np.percentile(vals, 75))}  "
          f"P90={fmt_time(np.percentile(vals, 90))}  "
          f"P95={fmt_time(np.percentile(vals, 95))}  "
          f"P99={fmt_time(np.percentile(vals, 99))}")
    print(f"    mean={fmt_time(vals.mean())}  "
          f"max={fmt_time(vals.max())}")


def per_bracket_report(trades, label):
    print(f"\n{'='*84}")
    print(f"  {label}  (N={len(trades):,})")
    print(f"{'='*84}")

    for tag, pt, sl in BRACKETS:
        col = f"bracket_{tag}_bar"
        if col not in trades.columns:
            continue
        result_col = f"bracket_{tag}_result"
        results = trades[result_col].values
        bars = trades[col].values
        total = len(trades)

        n_pt = (results == "PT").sum()
        n_sl = (results == "SL").sum()
        n_nei = (results == "neither").sum()

        print(f"\n  Bracket {tag} (PT={pt:.2f}/SL={sl:.2f})  "
              f"PT={n_pt} SL={n_sl} Nei={n_nei}")

        # PT bars
        pt_bars = bars[results == "PT"]
        if len(pt_bars):
            report_distribution(f"    PT first", pt_bars, total)
        sl_bars = bars[results == "SL"]
        if len(sl_bars):
            report_distribution(f"    SL first", sl_bars, total)
        # Neither: use bars_processed_1s
        if "bars_processed_1s" in trades.columns:
            nei_bars = trades.loc[
                trades[result_col] == "neither", "bars_processed_1s"].values
            if len(nei_bars):
                report_distribution(
                    f"    Neither (regime exit)", nei_bars, total)


def cumulative_resolution_table(trades, tag, pt, sl, label):
    """Show what % of losers (SL + neither) have resolved by N seconds."""
    col = f"bracket_{tag}_bar"
    result_col = f"bracket_{tag}_result"
    results = trades[result_col].values
    bars = trades[col].values
    bp = trades["bars_processed_1s"].values

    # SL resolution times (seconds)
    sl_times = bars[results == "SL"]
    sl_times = sl_times[~pd.isna(sl_times)].astype(int)

    # Neither resolution times = total trade duration
    nei_times = bp[results == "neither"].astype(int)

    # Combined LOSING resolution times
    losing_times = np.concatenate([sl_times, nei_times])

    if len(losing_times) == 0:
        return

    print(f"\n{'='*84}")
    print(f"  {label} — cumulative resolution % of all LOSERS")
    print(f"  Bracket {tag} (PT={pt:.2f}/SL={sl:.2f})")
    print(f"{'='*84}")
    print(f"  Total losers (SL + neither): {len(losing_times):,}")
    print(f"\n    Time     SL resolved  Nei resolved  Combined %")
    print(f"    {'-'*52}")
    for cap_s in [30, 60, 90, 120, 180, 240, 300, 420, 600,
                   900, 1200, 1800, 2400, 3600, 7200]:
        sl_done = (sl_times <= cap_s).sum()
        nei_done = (nei_times <= cap_s).sum()
        combined_done = sl_done + nei_done
        pct = combined_done / len(losing_times) * 100
        print(f"    {fmt_time(cap_s):<8} "
              f"{sl_done:>5,}/{len(sl_times):<6} "
              f"{nei_done:>5,}/{len(nei_times):<6} "
              f"{pct:>6.1f}%")


def main():
    print("=" * 84)
    print("RESOLUTION TIMING — bars to PT/SL/neither across brackets")
    print("=" * 84)

    trades = pd.read_parquet(
        "studies/1m_mtf_context/results/trades_all.parquet").copy()
    print(f"\n  {len(trades):,} trades loaded")

    if "bars_processed_1s" not in trades.columns:
        print("  WARN: bars_processed_1s missing — neither timing not avail.")

    # Full population
    per_bracket_report(trades, "ALL trades")

    # Q1 subset (most counter-flip 2-bar body)
    trades["_q"] = pd.qcut(trades["two_bar_close_vs_open_pct"], q=5,
                            labels=False, duplicates="drop")
    q1 = trades[trades["_q"] == 0].copy()
    per_bracket_report(q1, "Q1 of two_bar_close_vs_open_pct")

    # Cumulative resolution % focus tables
    for tag, pt, sl in BRACKETS:
        cumulative_resolution_table(
            trades, tag, pt, sl, "ALL trades")
    for tag, pt, sl in [("100_100", 1.00, 1.00), ("075_075", 0.75, 0.75)]:
        cumulative_resolution_table(
            q1, tag, pt, sl, "Q1 subset (counter-flip 2-bar)")

    print(f"\n{'='*84}")


if __name__ == "__main__":
    main()
