"""Bounded monthly NautilusTrader Phase B collector and post-collection label join."""
from __future__ import annotations

import argparse
import bisect
import json
import importlib.metadata
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument
from studies.full_trade_path_builder.implementation.phase_b_strategy import (
    PhaseBCollector, PhaseBCollectorConfig,
)
from studies.full_trade_path_builder.implementation.phase_b_adapter import BEAR_DEPENDENCIES
from studies.full_trade_path_builder.implementation.phase_b_grid import (
    expected_rth_grid_ns,
)
from studies.full_trade_path_builder.implementation.run_phase_a_collect import (
    CATALOG, BAR_1M, BAR_1S, SEALED_BOUNDARY, atomic_json, atomic_parquet,
    frozen_catalog_identity, parse_utc, sha256_file,
)

NS = 1_000_000_000


def runtime_identity() -> dict:
    local = (
        "phase_b_adapter.py",
        "phase_b_strategy.py",
        "phase_b_grid.py",
        "run_phase_b_collect.py",
    )
    return {
        "phase_b_code": {
            name: sha256_file(Path(__file__).parent / name) for name in local
        },
        "bear_dependencies": {
            name: sha256_file(ROOT / name) for name in BEAR_DEPENDENCIES
        },
        "bull_model": sha256_file(
            ROOT / "studies/full_trade_path_builder/artifacts/"
            "BULLISH_STRICT_top25_gbt_v2/model.joblib"
        ),
        "bear_model": sha256_file(
            ROOT / "studies/freeze_long_strict_models_v2/artifacts/"
            "LONG_STRICT_top25_gbt_v2/model.joblib"
        ),
        "bear_feature_mapping": sha256_file(
            ROOT / "studies/freeze_long_strict_models_v2/artifacts/"
            "LONG_STRICT_top25_gbt_v2/feature_mapping.json"
        ),
        "runtime_versions": {
            name: importlib.metadata.version(name)
            for name in ("nautilus_trader", "numpy", "scipy", "scikit-learn", "numba")
        },
    }


def add_bars_causal_order(engine: BacktestEngine, bars_1s, bars_1m) -> None:
    """Stable equal-ts_init tie-break: the finer stream must be added first."""
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)


def next_after(t: int, sorted_times: list[int]) -> int | None:
    i = bisect.bisect_right(sorted_times, t)
    return sorted_times[i] if i < len(sorted_times) else None


def add_labels(row: dict, bull: list[int], bear: list[int], observation_end: int) -> dict:
    t = row["checkpoint_decision_ns"]
    nb, nr = next_after(t, bull), next_after(t, bear)
    c300, c600 = observation_end < t + 300 * NS, observation_end < t + 600 * NS
    def seconds(value):
        return None if value is None else (value - t) / NS
    sb, sr = seconds(nb), seconds(nr)
    return {
        **row,
        "seconds_to_next_bullish_confirm_flip": sb,
        "seconds_to_next_bearish_confirm_flip": sr,
        "next_bullish_flip_le_300": None if c300 else bool(sb is not None and sb <= 300),
        "next_bearish_flip_le_300": None if c300 else bool(sr is not None and sr <= 300),
        "next_bullish_flip_le_600": None if c600 else bool(sb is not None and sb <= 600),
        "next_bearish_flip_le_600": None if c600 else bool(sr is not None and sr <= 600),
        "bullish_confirm_within_300s": None if c300 else bool(sb is not None and sb <= 300),
        "bearish_confirm_within_300s": None if c300 else bool(sr is not None and sr <= 300),
        "bullish_confirm_within_600s": None if c600 else bool(sb is not None and sb <= 600),
        "bearish_confirm_within_600s": None if c600 else bool(sr is not None and sr <= 600),
        "label_300_is_right_censored": c300,
        "label_600_is_right_censored": c600,
        "label_is_right_censored": c600,
        "observation_end_ns": observation_end,
    }


def collect(
    start: datetime, end: datetime, output_dir: Path, overwrite=False,
    warmup_days: int = 4,
) -> dict:
    if end <= start or start >= SEALED_BOUNDARY or end > SEALED_BOUNDARY:
        raise RuntimeError("invalid or sealed Phase B window")
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists() and not overwrite:
        manifest = json.loads(manifest_path.read_text())
        score_path = output_dir / "canonical_model_scores.parquet"
        if sha256_file(score_path) != manifest["canonical_model_scores_sha256"]:
            raise RuntimeError("corrupt resumable Phase B partition")
        return manifest
    if warmup_days < 4 or warmup_days > 45:
        raise RuntimeError("Phase B warmup must be within [4,45] days")
    load_start = start - timedelta(days=warmup_days)
    load_end = min(end + timedelta(seconds=601), SEALED_BOUNDARY)
    catalog = ParquetDataCatalog(str(CATALOG))
    bars_1s = catalog.bars(bar_types=[BAR_1S], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=[BAR_1M], start=load_start, end=load_end)
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="FULLPATH-PHASE-B",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(5_000_000, USD)],
        bar_execution=True, bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(create_instrument())
    add_bars_causal_order(engine, bars_1s, bars_1m)
    strategy = PhaseBCollector(PhaseBCollectorConfig(repo_root=str(ROOT)))
    engine.add_strategy(strategy)
    t0 = time.time()
    engine.run(start=load_start, end=load_end)
    start_ns, end_ns = int(start.timestamp() * NS), int(end.timestamp() * NS)
    rows = [r for r in strategy.rows if start_ns <= r["checkpoint_decision_ns"] < end_ns]
    flips = sorted(strategy.flips, key=lambda r: r["confirm_flip_ns"])
    bull = [r["confirm_flip_ns"] for r in flips if r["new_direction"] == 1]
    bear = [r["confirm_flip_ns"] for r in flips if r["new_direction"] == -1]
    observation_end = int(strategy.observation_end_ns or 0)
    labeled = [add_labels(r, bull, bear, observation_end) for r in rows]
    emitted_keys = {row["checkpoint_decision_ns"] for row in labeled}
    missing = [
        {
            "checkpoint_decision_ns": timestamp_ns,
            "suppression_reason": "missing_dispatch_bar",
        }
        for timestamp_ns in expected_rth_grid_ns(start_ns, end_ns)
        if timestamp_ns not in emitted_keys
    ]
    score_path = output_dir / "canonical_model_scores.parquet"
    flip_path = output_dir / "confirmed_flips.parquet"
    missing_path = output_dir / "missing_dispatch.parquet"
    atomic_parquet(labeled, score_path)
    atomic_parquet(flips, flip_path)
    atomic_parquet(missing, missing_path)
    manifest = {
        "status": "scores_complete_labels_provisional",
        "start": start.isoformat(), "end": end.isoformat(),
        "load_start": load_start.isoformat(), "load_end": load_end.isoformat(),
        "warmup_days": warmup_days,
        "n_rows": len(labeled), "n_flips": len(flips), "n_missing": len(missing),
        "runtime_seconds": time.time() - t0,
        "canonical_model_scores_sha256": sha256_file(score_path),
        "confirmed_flips_sha256": sha256_file(flip_path),
        "missing_dispatch_sha256": sha256_file(missing_path),
        "config_sha256": sha256_file(ROOT / "studies/full_trade_path_builder/config/phase_b.yaml"),
        "catalog_identity": frozen_catalog_identity(),
        "runtime_identity": runtime_identity(),
        "labels_finalized_globally": False,
    }
    atomic_json(manifest, manifest_path)
    engine.dispose()
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--warmup-days", type=int, default=4)
    a = p.parse_args()
    print(json.dumps(collect(
        parse_utc(a.start), parse_utc(a.end), Path(a.output_dir),
        a.overwrite, a.warmup_days,
    ), indent=2))


if __name__ == "__main__":
    main()
