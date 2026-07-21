"""Data-validation step (not a code fix): confirm the two independent
1m bar sources consumed by ExitManagementBaseStrategy actually agree.

The strategy reads:
  1. The real `bar_type_1m` catalog subscription (OHLC used for HH/LL
     confirmation and flip_h/flip_l/flip_c).
  2. The TimeframeAggregator's synthetic 1m bucket, built by summing
     1s bars (regime/ATR normalizer).

Only timestamps are cross-checked at runtime (bar_data["ts_init"] ==
s_1m.close_ts). This script checks OHLC VALUES agree between the two
sources over a sample window, standalone (no NT engine needed) --
flagged as WARNING [D1-adjacent] in the pre-execution lookahead audit.

Usage: python studies/_shared_exit_mgmt/reconcile_1m_bar_sources.py
"""
from __future__ import annotations
import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from collectors.collector_v2.aggregator import TimeframeAggregator

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
SAMPLE_START = pd.Timestamp("2024-01-08", tz="UTC")
SAMPLE_END = pd.Timestamp("2024-01-15 23:59:59", tz="UTC")


def build_synthetic_1m(bars_1s) -> pd.DataFrame:
    rows = []

    def on_bucket_closed(tf, completed):
        if tf != "1m":
            return
        rows.append({
            "open_ts": completed.open_ts, "close_ts": completed.close_ts,
            "open": completed.open, "high": completed.high,
            "low": completed.low, "close": completed.close,
            "volume": completed.volume,
        })

    agg = TimeframeAggregator(on_bucket_closed=on_bucket_closed,
                                  timeframes=("1m",))
    for b in bars_1s:
        agg.on_1s_bar(int(b.ts_event), float(b.open), float(b.high),
                         float(b.low), float(b.close),
                         float(b.volume) if hasattr(b, "volume") else 0.0)
    return pd.DataFrame(rows)


def main():
    print(f"Loading {SAMPLE_START} -> {SAMPLE_END} from {CATALOG_PATH}...")
    catalog = ParquetDataCatalog(CATALOG_PATH)
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=SAMPLE_START, end=SAMPLE_END)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=SAMPLE_START, end=SAMPLE_END)
    print(f"  {len(bars_1s):,} 1s bars, {len(bars_1m):,} 1m catalog bars")

    df_real = pd.DataFrame([{
        "close_ts": int(b.ts_init), "open": float(b.open),
        "high": float(b.high), "low": float(b.low),
        "close": float(b.close),
    } for b in bars_1m])

    df_synth = build_synthetic_1m(bars_1s)

    merged = df_real.merge(df_synth, on="close_ts", how="outer",
                               suffixes=("_real", "_synth"), indicator=True)
    n_both = int((merged["_merge"] == "both").sum())
    n_real_only = int((merged["_merge"] == "left_only").sum())
    n_synth_only = int((merged["_merge"] == "right_only").sum())

    print(f"\nMatched close_ts: {n_both:,}")
    print(f"Real-only (no synthetic bucket): {n_real_only:,}")
    print(f"Synthetic-only (no real bar): {n_synth_only:,}")

    both = merged[merged["_merge"] == "both"].copy()
    max_abs_diffs = {}
    for col in ("open", "high", "low", "close"):
        diff = (both[f"{col}_real"] - both[f"{col}_synth"]).abs()
        max_abs_diffs[col] = float(diff.max()) if len(diff) else float("nan")
        n_mismatch = int((diff > 1e-6).sum())
        print(f"  {col}: max_abs_diff={max_abs_diffs[col]:.6f}, "
                 f"n_mismatch(>1e-6)={n_mismatch}")

    ok = (n_real_only == 0 and n_synth_only == 0
             and all(v <= 1e-6 for v in max_abs_diffs.values()))
    print(f"\n{'PASS' if ok else 'FAIL'}: bar sources "
             f"{'agree' if ok else 'DISAGREE'} over sample window.")

    report_path = _repo_root / "studies" / "_shared_exit_mgmt" / \
        "bar_source_reconciliation_report.md"
    with open(report_path, "w") as f:
        f.write("# 1m Bar Source Reconciliation\n\n")
        f.write(f"Sample window: {SAMPLE_START} -> {SAMPLE_END}\n")
        f.write(f"Catalog: {CATALOG_PATH}\n\n")
        f.write(f"- Matched close_ts: {n_both}\n")
        f.write(f"- Real-only (missing synthetic bucket): {n_real_only}\n")
        f.write(f"- Synthetic-only (missing real bar): {n_synth_only}\n")
        for col, v in max_abs_diffs.items():
            f.write(f"- max_abs_diff {col}: {v}\n")
        f.write(f"\n**Result: {'PASS' if ok else 'FAIL'}**\n")
    print(f"\nReport written: {report_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
