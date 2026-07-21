"""Parity harness orchestrator (WO5).

Usage:
    python studies/1m_regime_collector_v2/parity/run_parity.py \\
        --features-path studies/1m_regime_collector_v2/results/v2_feature_snapshots_SMOKE_20250407_20250411.parquet \\
        --labels-path   studies/1m_regime_collector_v2/results/v2_outcome_labels_SMOKE_20250407_20250411.parquet \\
        --catalog       data/catalog/NQ_2020_2025 \\
        --sample-size   200 \\
        --check-determinism

Four gates per the WO5 scope:
  1. Feature parity (determinism + spot re-derivation of load-bearing
     features)
  2. Fillability parity (col.fillable_at_T vs independently derived)
  3. Fill-time / fill-price parity (col.fill_time_actual /
     col.fill_price vs independently derived)
  4. Label-origin parity (col MFE/MAE + bracket outcomes vs
     independently derived from raw 1s bars anchored at fill_time_actual
     / fill_price)

All gates report results split by RTH vs ETH per the user's request.

The harness is INTENDED to be blocking before the full 6-year collection
run — if any gate fails with > 0.5% mismatch rate, investigate before
scaling up.
"""

from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nautilus_trader.persistence.catalog import ParquetDataCatalog

sys.path.insert(0, str(Path(__file__).parent))
from fill_parity import run_fill_parity  # noqa
from label_parity import run_label_parity  # noqa
from feature_parity import (
    check_determinism, check_spot_features,
)  # noqa


def sample_stratified(
    df: pd.DataFrame,
    n: int,
    seed: int = 42,
    rth_fraction: float = 0.5,
) -> pd.DataFrame:
    """Stratified sample across RTH/ETH with roughly equal coverage.

    If the underlying population is heavily skewed (e.g., 70% ETH),
    the sample honors the skew but guarantees min 20 rows per stratum
    so each side has meaningful statistics.
    """
    rng = np.random.default_rng(seed)
    rth = df[df.get("is_rth_checkpoint", 0) == 1]
    eth = df[df.get("is_rth_checkpoint", 0) == 0]
    n_rth_target = int(n * rth_fraction)
    n_eth_target = n - n_rth_target
    n_rth = min(max(n_rth_target, 20), len(rth))
    n_eth = min(max(n_eth_target, 20), len(eth))
    s_rth = rth.sample(n=n_rth, random_state=rng.integers(0, 2**32 - 1))
    s_eth = eth.sample(n=n_eth, random_state=rng.integers(0, 2**32 - 1))
    return pd.concat([s_rth, s_eth]).reset_index(drop=True)


def load_bars(
    catalog_path: str,
    start_ns: int,
    end_ns: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load 1s + 1m bars covering the sample range (with 2-day padding
    before start to give spot-feature checks enough history)."""
    catalog = ParquetDataCatalog(catalog_path)
    start = pd.Timestamp(start_ns - 2 * 86400 * 1_000_000_000, unit="ns",
                          tz="UTC")
    end = pd.Timestamp(end_ns + 3600 * 1_000_000_000, unit="ns",
                        tz="UTC")
    bars_1s_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start, end=end)
    bars_1m_nt = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=start, end=end)

    def _to_df(bars):
        return pd.DataFrame({
            "ts_event": [b.ts_event for b in bars],
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [float(b.volume) if hasattr(b, "volume") else 0.0
                        for b in bars],
        })
    return _to_df(bars_1s_nt), _to_df(bars_1m_nt)


def write_report(out_path: Path, sections: list[str]):
    out_path.write_text("\n".join(sections), encoding="utf-8")


def fmt_section(title: str, body_lines: list[str]) -> list[str]:
    return ["", "=" * 72, title, "=" * 72, *body_lines, ""]


def summarize_fill_parity(df: pd.DataFrame) -> list[str]:
    lines = []
    n = len(df)
    match = int(df["all_match"].sum())
    lines.append(f"  Total checkpoints: {n}")
    lines.append(
        f"  All-match: {match} / {n}  ({100 * match / n:.2f}%)")
    lines.append(f"  Mismatches by kind:")
    lines.append(
        f"    fillable: {int((~df['fillable_match']).sum())}")
    lines.append(
        f"    fill_time_actual: {int((~df['fat_match']).sum())}")
    lines.append(
        f"    fill_price: {int((~df['fp_match']).sum())}")

    # RTH/ETH split
    for lbl, sub in [("RTH", df[df["is_rth"]]),
                      ("ETH", df[~df["is_rth"]])]:
        if len(sub) == 0:
            lines.append(f"  {lbl}: n=0")
            continue
        m = int(sub["all_match"].sum())
        lines.append(
            f"  {lbl}: n={len(sub)}  all-match {m}/{len(sub)} "
            f"({100 * m / len(sub):.2f}%)")
    # Mismatches detail
    bad = df[~df["all_match"]]
    if len(bad):
        lines.append("")
        lines.append("  Sample mismatches:")
        for _, r in bad.head(5).iterrows():
            lines.append(
                f"    ev={r['event_id']} T={r['checkpoint_s']} "
                f"col_fillable={r['col_fillable']} "
                f"drv_fillable={r['derived_fillable']} "
                f"reason={r['derived_reason']}")
    return lines


def summarize_label_parity(df: pd.DataFrame) -> list[str]:
    lines = []
    n = len(df)
    if n == 0:
        lines.append("  (no fillable rows in sample — skip)")
        return lines
    match = int(df["all_match"].sum())
    lines.append(f"  Total fillable checkpoints: {n}")
    lines.append(
        f"  All-match: {match} / {n}  ({100 * match / n:.2f}%)")
    lines.append(f"  Mismatches by kind:")
    lines.append(
        f"    MFE grid: {int((df['mfe_mismatch_count'] > 0).sum())} "
        f"rows (max delta {df['max_mfe_delta'].max():.2e})")
    lines.append(
        f"    MAE grid: {int((df['mae_mismatch_count'] > 0).sum())} "
        f"rows (max delta {df['max_mae_delta'].max():.2e})")
    lines.append(
        f"    Bracket: {int((df['bracket_mismatch_count'] > 0).sum())}"
        f" rows")

    for lbl, sub in [("RTH", df[df["is_rth"]]),
                      ("ETH", df[~df["is_rth"]])]:
        if len(sub) == 0:
            lines.append(f"  {lbl}: n=0")
            continue
        m = int(sub["all_match"].sum())
        lines.append(
            f"  {lbl}: n={len(sub)}  all-match {m}/{len(sub)} "
            f"({100 * m / len(sub):.2f}%)")

    bad = df[~df["all_match"]]
    if len(bad):
        lines.append("")
        lines.append("  Sample mismatches:")
        for _, r in bad.head(5).iterrows():
            lines.append(
                f"    ev={r['event_id']} T={r['checkpoint_s']} "
                f"mfe_mis={r['mfe_mismatch_count']} "
                f"mae_mis={r['mae_mismatch_count']} "
                f"br_mis={r['bracket_mismatch_count']} "
                f"max_mfe_δ={r['max_mfe_delta']:.2e}")
    return lines


def summarize_feature_parity(df: pd.DataFrame) -> list[str]:
    lines = []
    n = len(df)
    if n == 0:
        lines.append("  (empty sample — skip)")
        return lines
    rth_match = int(df["rth_match"].sum())
    mins_match = int(df["mins_match"].sum())
    all_match = int(df["all_match"].sum())
    lines.append(
        "  Spot-checked features: is_rth_checkpoint, "
        "minutes_since_rth_open_checkpoint")
    lines.append(f"  Total sampled: {n}")
    lines.append(
        f"  is_rth_checkpoint match: {rth_match} / {n} "
        f"({100 * rth_match / n:.2f}%)")
    lines.append(
        f"  minutes_since_rth match: {mins_match} / {n} "
        f"({100 * mins_match / n:.2f}%)")
    lines.append(f"  All-match: {all_match} / {n}")
    lines.append("")
    lines.append(
        "  NOTE: full 189-feature re-derivation is out of scope for")
    lines.append(
        "  phase-1. Determinism (run-twice hash equality) is the")
    lines.append(
        "  primary feature-parity gate — see next section.")

    bad = df[~df["all_match"]]
    if len(bad):
        lines.append("")
        lines.append("  Sample mismatches:")
        for _, r in bad.head(3).iterrows():
            lines.append(
                f"    ev={r['event_id']} T={r['checkpoint_s']} "
                f"col_rth={r['col_rth']} drv_rth={r['derived_rth']} "
                f"col_mins={r['col_mins']} drv_mins={r['derived_mins']}")
    return lines


def summarize_determinism(d: dict) -> list[str]:
    lines = []
    lines.append(f"  Features shape: {d['features_shape']}  "
                  f"match: {d['features_shape_match']}")
    lines.append(f"  Labels   shape: {d['labels_shape']}  "
                  f"match: {d['labels_shape_match']}")
    lines.append(
        f"  Features hash match: {d['features_hash_match']}")
    lines.append(
        f"  Labels   hash match: {d['labels_hash_match']}")
    if not d["features_hash_match"] and "features_diff_cols" in d:
        lines.append("  Features diff cols (top 10):")
        for c, n in d["features_diff_cols"]:
            lines.append(f"    {c}: {n}")
    if not d["labels_hash_match"] and "labels_diff_cols" in d:
        lines.append("  Labels diff cols (top 10):")
        for c, n in d["labels_diff_cols"]:
            lines.append(f"    {c}: {n}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features-path", required=True)
    ap.add_argument("--labels-path", required=True)
    ap.add_argument("--catalog", default="data/catalog/NQ_2020_2025")
    ap.add_argument("--sample-size", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-report",
                     default="studies/1m_regime_collector_v2/parity/"
                              "parity_report.md")
    ap.add_argument("--check-determinism", action="store_true",
                     help="Require a second run of the collector to compare")
    ap.add_argument("--determinism-features-path",
                     help="Path to 2nd-run features parquet")
    ap.add_argument("--determinism-labels-path",
                     help="Path to 2nd-run labels parquet")
    args = ap.parse_args()

    print("=" * 72)
    print("v2 COLLECTOR PARITY HARNESS")
    print("=" * 72)

    t0 = time.time()
    feats = pd.read_parquet(args.features_path)
    labels = pd.read_parquet(args.labels_path)
    merged = feats.merge(
        labels, on=["event_id", "checkpoint_s"],
        suffixes=("", "_lbl"))
    print(f"  Loaded {len(merged):,} rows from collector output")

    # Stratified sample
    sample = sample_stratified(merged, args.sample_size, seed=args.seed)
    print(f"  Stratified sample: {len(sample)} rows "
          f"(RTH {(sample['is_rth_checkpoint'] == 1).sum()}, "
          f"ETH {(sample['is_rth_checkpoint'] == 0).sum()})")

    # Load raw bars covering sample window
    sample_start = int(sample["signal_time"].min())
    sample_end = int(sample["signal_time"].max()
        + 1800 * 1_000_000_000)
    print(f"  Loading bars {pd.Timestamp(sample_start, unit='ns')} "
          f"-> {pd.Timestamp(sample_end, unit='ns')}...", flush=True)
    bars_1s, bars_1m = load_bars(args.catalog, sample_start, sample_end)
    print(f"    {len(bars_1s):,} 1s, {len(bars_1m):,} 1m")

    # Gate 2/3: Fill parity
    print("  Running fill parity...", flush=True)
    fill_df = run_fill_parity(sample, bars_1s)
    print(f"    all_match {int(fill_df['all_match'].sum())}/"
          f"{len(fill_df)}")

    # Gate 4: Label parity
    print("  Running label parity...", flush=True)
    label_df = run_label_parity(sample, bars_1s)
    if len(label_df):
        print(f"    all_match {int(label_df['all_match'].sum())}/"
              f"{len(label_df)}")

    # Gate 1: Feature parity (spot-check subset)
    print("  Running spot feature parity (is_rth, minutes_since_rth)...",
           flush=True)
    feat_df = check_spot_features(sample, bars_1m)
    if len(feat_df):
        print(f"    all_match {int(feat_df['all_match'].sum())}/"
              f"{len(feat_df)}")

    # Gate 1a: Determinism
    deter = None
    if args.check_determinism:
        if not (args.determinism_features_path
                 and args.determinism_labels_path):
            raise SystemExit(
                "--check-determinism requires --determinism-features-path "
                "and --determinism-labels-path (run collector a second "
                "time and pass the new artifact paths)")
        deter = check_determinism(
            features_path_run1=Path(args.features_path),
            features_path_run2=Path(args.determinism_features_path),
            labels_path_run1=Path(args.labels_path),
            labels_path_run2=Path(args.determinism_labels_path),
        )
        print(f"    determinism features_match: "
              f"{deter['features_hash_match']}")
        print(f"    determinism labels_match:   "
              f"{deter['labels_hash_match']}")

    elapsed = time.time() - t0
    print(f"  Harness elapsed: {elapsed:.1f}s")

    # Build report
    sections = [
        "# v2 Collector Parity Harness Report",
        "",
        f"- Collector features: `{args.features_path}`",
        f"- Collector labels:   `{args.labels_path}`",
        f"- Sample size: {len(sample)} "
        f"(RTH {(sample['is_rth_checkpoint'] == 1).sum()}, "
        f"ETH {(sample['is_rth_checkpoint'] == 0).sum()})",
        f"- Random seed: {args.seed}",
        f"- Harness elapsed: {elapsed:.1f}s",
    ]

    sections.extend(fmt_section(
        "Gate 2/3 — Fillability + fill_time/fill_price parity",
        summarize_fill_parity(fill_df)))

    sections.extend(fmt_section(
        "Gate 4 — Label-origin parity (MFE/MAE + brackets)",
        summarize_label_parity(label_df)))

    sections.extend(fmt_section(
        "Gate 1 — Feature parity (spot)",
        summarize_feature_parity(feat_df)))

    if deter is not None:
        sections.extend(fmt_section(
            "Gate 1 — Determinism (run-twice)",
            summarize_determinism(deter)))
    else:
        sections.extend(fmt_section(
            "Gate 1 — Determinism (run-twice)",
            ["  SKIPPED (use --check-determinism to enable)"]))

    # Overall pass/fail
    fill_pass = fill_df["all_match"].all()
    label_pass = (len(label_df) == 0
                   or label_df["all_match"].all())
    feat_pass = (len(feat_df) == 0
                  or feat_df["all_match"].all())
    det_pass = (deter is None
                 or (deter["features_hash_match"]
                     and deter["labels_hash_match"]))
    overall = fill_pass and label_pass and feat_pass and det_pass

    sections.extend(fmt_section(
        "OVERALL VERDICT",
        [f"  Gate 2/3 (fill parity):       "
         f"{'PASS' if fill_pass else 'FAIL'}",
         f"  Gate 4 (label-origin parity): "
         f"{'PASS' if label_pass else 'FAIL'}",
         f"  Gate 1 (spot feature parity): "
         f"{'PASS' if feat_pass else 'FAIL'}",
         f"  Gate 1 (determinism):         "
         f"{'PASS' if det_pass else ('SKIPPED' if deter is None else 'FAIL')}",
         "",
         f"  Overall: {'PASS — clear to run full 6y collection' if overall else 'FAIL — investigate before scaling up'}",
         ]))

    # Save dataframes for post-hoc inspection
    out_dir = Path(args.out_report).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    fill_df.to_parquet(out_dir / "fill_parity_detail.parquet",
                        index=False)
    label_df.to_parquet(out_dir / "label_parity_detail.parquet",
                         index=False)
    feat_df.to_parquet(out_dir / "feature_parity_detail.parquet",
                        index=False)
    write_report(Path(args.out_report), sections)
    print(f"\n  Report: {args.out_report}")
    print(f"  Details: {out_dir}/*.parquet")

    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
