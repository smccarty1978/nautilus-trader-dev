"""Phase 2 driver for ALL_FLIPS: old (flip-close-anchored) vs corrected
(entry-fill-anchored) skew audit across the full 2021-2026 history.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from studies._shared_exit_mgmt.skew_audit import (
    load_old_atlas_window, trade_level_from_atlas,
    entry_price_vs_flip_close, match_and_compare, summarize_skew,
)

STUDY_ROOT = Path(__file__).parent
RESULTS_ROOT = STUDY_ROOT / "results"
AUDIT_ROOT = STUDY_ROOT / "audit"
CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
START = pd.Timestamp("2021-01-01", tz="UTC")
END = pd.Timestamp("2026-04-30 23:59:59", tz="UTC")


def main():
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    atlas = pd.read_parquet(RESULTS_ROOT / "corrected_weakness_atlas.parquet")
    print(f"Loaded atlas: {len(atlas):,} rows ({time.time()-t0:.0f}s)")

    trade_level = trade_level_from_atlas(atlas)
    print(f"Trade-level rows: {len(trade_level):,}")

    t0 = time.time()
    catalog = ParquetDataCatalog(CATALOG_PATH)
    bars_1m_raw = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"], start=START, end=END)
    bars_1m = pd.DataFrame([
        {"close_ts": int(b.ts_init), "close": float(b.close)}
        for b in bars_1m_raw])
    print(f"Loaded {len(bars_1m):,} 1m bars ({time.time()-t0:.0f}s)")

    trade_level_ext = entry_price_vs_flip_close(trade_level, bars_1m)
    entry_skew_path = RESULTS_ROOT / "train_serve_skew_audit.parquet"
    trade_level_ext.to_parquet(entry_skew_path, index=False)
    print(f"Wrote {entry_skew_path}")

    t0 = time.time()
    old_atlas = load_old_atlas_window(int(START.value), int(END.value))
    print(f"Loaded old atlas window: {len(old_atlas):,} rows "
             f"({time.time()-t0:.0f}s)")

    report_lines = ["# ALL_FLIPS Train/Serve (Old vs Corrected) Skew Audit\n"]
    report_lines.append(f"Built: {pd.Timestamp.utcnow()}\n")
    report_lines.append(
        "\n## entry_price_minus_flip_close_atr (property of the "
        "corrected atlas's own entries, no old-atlas dependency)\n")
    desc = trade_level_ext["entry_price_minus_flip_close_atr"].describe()
    report_lines.append(desc.to_string())
    report_lines.append("\n")

    for mode in ("backward", "nearest"):
        t0 = time.time()
        matched = match_and_compare(trade_level_ext, old_atlas, atlas,
                                        match_mode=mode)
        elapsed = time.time() - t0
        rep = summarize_skew(matched)
        n_trades_matched = (matched["trade_id"].nunique()
                                if len(matched) else 0)
        print(f"[{mode}] matched {len(matched):,} checkpoint rows, "
                 f"{n_trades_matched:,}/{trade_level_ext.shape[0]:,} trades "
                 f"({elapsed:.0f}s)")
        matched.to_parquet(
            RESULTS_ROOT / f"train_serve_skew_matched_{mode}.parquet",
            index=False)
        report_lines.append(f"\n## match_mode={mode}\n")
        report_lines.append(
            f"- trades matched: {n_trades_matched:,} / "
            f"{trade_level_ext.shape[0]:,} "
            f"({100*n_trades_matched/max(1,trade_level_ext.shape[0]):.1f}%)\n")
        for k, v in rep.items():
            report_lines.append(f"- {k}: {v}\n")
        if mode == "backward":
            report_lines.append(
                "\n(backward-only match is causally conservative but "
                "biases MFE/giveback comparisons downward by "
                "construction -- see nearest-match figures above for "
                "an unbiased skew estimate; see "
                "studies/_shared_exit_mgmt/skew_audit.py docstring)\n")

    report_path = AUDIT_ROOT / "train_serve_skew_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
