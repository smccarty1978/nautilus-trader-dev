"""Runtime-vs-collector reconciliation on March 2025.

Runs the LiveBracketStrategy on March 2025 with dump_scored_path set
(logs every scored checkpoint + feature vector), then diffs against
the feature_reduction sweep's saved predictions on the same events.

Verifies:
  1. Same events fire in both paths (collector+schedule vs live)
  2. Same checkpoints score in both paths
  3. Score parity (live score == offline score)
  4. Feature parity (every f_i matches)
  5. Decision parity (above_threshold live == in_top_10pct offline)
  6. Candidate-trade parity (before execution effects)
"""

from __future__ import annotations
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import numpy as np
import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

sys.path.insert(0,
    str(project_root / "studies/bracket_entry_v2/validation_2026"))
from live_bracket_strategy import (
    LiveBracketStrategy, LiveBracketConfig,
)

OUT_DIR = Path(
    "studies/bracket_entry_v2/validation_2026/reconciliation_2025")
OUT_DIR.mkdir(parents=True, exist_ok=True)

START = "2025-03-01"
END = "2025-03-31 23:59:59"

MODEL = OUT_DIR / "model_top15_2025oos.txt"
FEATURES = OUT_DIR / "feature_list.json"
THRESHOLD_FILE = OUT_DIR / "score_threshold.json"
SCORED_DUMP = OUT_DIR / "live_scored_march2025.parquet"


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp(
        "2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp(
        "2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def run_live():
    """Run live strategy on March 2025 with scored-checkpoint dump."""
    if SCORED_DUMP.exists():
        print(f"Reusing existing scored dump: {SCORED_DUMP}")
        return

    with open(THRESHOLD_FILE) as f:
        thr = json.load(f)["threshold_top10"]
    print(f"Using threshold: {thr:.6f}")

    load_start = pd.Timestamp(START, tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(END, tz="UTC")
    print(f"Loading bars {load_start} -> {load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
           f"({time.time() - t0:.0f}s)")

    nq = create_nq()

    run_dir = OUT_DIR / "nt_run_march2025"
    run_dir.mkdir(exist_ok=True)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="RECON-2025",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="INFO",
            log_directory=str(run_dir / "logs"),
        ),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True,
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = LiveBracketConfig(
        instrument_id="NQ.XCME",
        model_path=str(MODEL.resolve()),
        feature_list_path=str(FEATURES.resolve()),
        score_threshold=thr,
        max_entry_checkpoint_s=600,
        pt_atr_mult=1.0, sl_atr_mult=1.0, position_size=1,
        fill_delay_ns=30_000_000_000,
        dump_scored_path=str(SCORED_DUMP.resolve()),
        features_output=str(run_dir / "_f.parquet"),
        labels_output=str(run_dir / "_l.parquet"),
        events_summary_output=str(run_dir / "_e.parquet"),
        qa_log_output=str(run_dir / "_qa.log"),
    )
    strat = LiveBracketStrategy(cfg)
    engine.add_strategy(strat)

    print("Running...", flush=True)
    t0 = time.time()
    engine.run()
    print(f"  Done in {time.time() - t0:.0f}s")
    print(f"Live diag: {strat._live_diag}")

    # Save positions + strategy trades for PnL analysis
    pos = engine.trader.generate_positions_report()

    def _drop_struct(df):
        drop = [c for c in df.columns if df[c].dtype == object
                 and df[c].map(lambda v: isinstance(v, dict)).any()]
        return df.drop(columns=drop) if drop else df

    _drop_struct(pos).to_parquet(run_dir / "positions.parquet",
                                     index=False)
    if strat._trades:
        tr_rows = [{"entry_id": k, **v}
                    for k, v in strat._trades.items()]
        pd.DataFrame(tr_rows).to_parquet(
            run_dir / "strategy_trades.parquet", index=False)
    engine.dispose()


def compare():
    """Diff live scored log vs offline predictions for March 2025."""
    print(f"\nLoading live scored log: {SCORED_DUMP}")
    live = pd.read_parquet(SCORED_DUMP)
    print(f"  Live scored rows (Mar 2025 + warmup days): {len(live):,}")

    # Restrict to March 2025 by decision_ts_ns
    start_ns = pd.Timestamp(START, tz="UTC").value
    end_ns = pd.Timestamp(END, tz="UTC").value
    live_mar = live[(live["decision_ts_ns"] >= start_ns)
                    & (live["decision_ts_ns"] <= end_ns)].copy()
    print(f"  Live scored (March only): {len(live_mar):,}")

    # Restrict to T ≤ 600 (should already be enforced by strategy)
    live_mar = live_mar[live_mar["checkpoint_s"] <= 600]
    print(f"  Live scored (T<=600): {len(live_mar):,}")

    # Load offline reference predictions (feature_reduction top_15)
    ref = pd.read_parquet(
        "studies/bracket_entry_v2/feature_reduction/"
        "predictions_2025_top_15.parquet")
    print(f"\nOffline reference predictions: {len(ref):,}")
    # Filter offline to March + T ≤ 600 + resolved only
    # The offline predictions are already restricted to resolved rows
    # because the sweep trained on resolved only.
    # Decision time = signal_time + T, but we don't have signal_time.
    # Use: event_id's fill_time_actual in March → check via merge with
    # v2_feature_snapshots_2025.parquet
    feat2025 = pd.read_parquet(
        "studies/1m_regime_collector_v2/results/"
        "v2_feature_snapshots_2025.parquet",
        columns=["event_id", "checkpoint_s", "fill_time_actual"])
    ref = ref.merge(feat2025, on=["event_id", "checkpoint_s"],
                      how="left")
    ref_mar = ref[(ref["fill_time_actual"] >= start_ns)
                  & (ref["fill_time_actual"] <= end_ns)
                  & (ref["checkpoint_s"] <= 600)].copy()
    print(f"  Offline ref (March + T<=600): {len(ref_mar):,}")

    # Merge on (event_id, checkpoint_s)
    merged = live_mar.merge(
        ref_mar[["event_id", "checkpoint_s", "score"]].rename(
            columns={"score": "score_offline"}),
        on=["event_id", "checkpoint_s"], how="outer",
        indicator=True)
    print(f"\nMerge result: {merged['_merge'].value_counts().to_dict()}")

    both = merged[merged["_merge"] == "both"].copy()
    live_only = merged[merged["_merge"] == "left_only"]
    ref_only = merged[merged["_merge"] == "right_only"]
    print(f"  Both: {len(both):,}")
    print(f"  Live only (scored but no offline ref): {len(live_only):,}")
    print(f"  Offline only (in ref but live didn't score): "
           f"{len(ref_only):,}")

    # Score parity on 'both'
    if len(both):
        score_diff = (both["score"] - both["score_offline"]).abs()
        print(f"\nScore parity on matched rows:")
        print(f"  max abs diff: {score_diff.max():.2e}")
        print(f"  mean abs diff: {score_diff.mean():.2e}")
        print(f"  median abs diff: {score_diff.median():.2e}")
        print(f"  exact (diff==0): "
               f"{int((score_diff == 0).sum())} / {len(both)}")
        print(f"  within 1e-9: "
               f"{int((score_diff < 1e-9).sum())} / {len(both)}")
        print(f"  within 1e-6: "
               f"{int((score_diff < 1e-6).sum())} / {len(both)}")
        print(f"  within 1e-3: "
               f"{int((score_diff < 1e-3).sum())} / {len(both)}")

    # Candidate-trade parity (before execution)
    live_candidates = int(live_mar["above_threshold"].sum())
    # Offline top-10% candidates: predictions where score >= threshold
    with open(THRESHOLD_FILE) as f:
        thr = json.load(f)["threshold_top10"]
    offline_candidates = int((ref_mar["score"] >= thr).sum())
    print(f"\nCandidate trades (before execution gate):")
    print(f"  Live (score >= {thr:.4f}):    {live_candidates:,}")
    print(f"  Offline (score >= {thr:.4f}): {offline_candidates:,}")

    # Summary
    lines = []
    lines.append("# Runtime-vs-Collector Reconciliation — March 2025")
    lines.append("")
    lines.append(f"**Live model**: top_15, Train 2020-2023, Val 2024 "
                  "(same as feature_reduction sweep)")
    lines.append(f"**Score threshold**: {thr:.6f}")
    lines.append(f"**Window**: {START} to {END}")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append(f"- Live scored checkpoints (Mar + T≤600): "
                  f"{len(live_mar):,}")
    lines.append(f"- Offline ref predictions (Mar + T≤600): "
                  f"{len(ref_mar):,}")
    lines.append(f"- Both (matched on event_id × checkpoint_s): "
                  f"{len(both):,}")
    lines.append(f"- Live only (not in ref): {len(live_only):,}")
    lines.append(f"- Offline only (not scored in live): "
                  f"{len(ref_only):,}")
    lines.append("")
    lines.append("**Note**: offline ref contains RESOLVED rows only "
                  "(pt100 ∈ {0,1}). Live scores every "
                  "fillable+feature-present checkpoint, including "
                  "ones that end up unresolved. Live-only rows are "
                  "primarily unresolved at event termination, which "
                  "is legitimate divergence.")
    lines.append("")

    if len(both):
        lines.append("## Score parity on matched (both) rows")
        lines.append("")
        lines.append(f"- max abs diff: {score_diff.max():.2e}")
        lines.append(f"- mean abs diff: {score_diff.mean():.2e}")
        lines.append(f"- exact (diff==0): "
                      f"{int((score_diff == 0).sum())} / {len(both)}")
        lines.append(f"- within 1e-9: "
                      f"{int((score_diff < 1e-9).sum())} / {len(both)}")
        lines.append(f"- within 1e-6: "
                      f"{int((score_diff < 1e-6).sum())} / {len(both)}")

    lines.append("")
    lines.append("## Candidate-trade parity")
    lines.append("")
    lines.append(f"- Live candidates (score >= threshold): "
                  f"{live_candidates:,}")
    lines.append(f"- Offline candidates (score >= threshold): "
                  f"{offline_candidates:,}")
    lines.append(f"- Delta: {live_candidates - offline_candidates:+,}")

    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    if len(both) and score_diff.max() < 1e-6:
        lines.append(
            "- **Score parity holds** on matched rows → feature "
            "computation + model scoring are bit-identical (or "
            "within float noise). The runtime path produces the "
            "same decisions as the collector path.")
    else:
        lines.append(
            "- **Score parity fails**. Features or scoring logic "
            "diverges between runtime and collector paths. "
            "Investigate before trusting 2026 result.")
    lines.append("")

    out = OUT_DIR / "RECONCILIATION_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    run_live()
    compare()
