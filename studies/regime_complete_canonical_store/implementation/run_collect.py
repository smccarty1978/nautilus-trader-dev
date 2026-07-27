"""Bounded, resumable monthly runner for the regime-complete collector.

One invocation collects one closed month inside a real NautilusTrader
BacktestEngine, writes three Parquet partitions plus a manifest, and is
idempotent: rerunning a completed partition verifies hashes and returns the
existing manifest rather than recollecting.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
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

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument  # noqa: E402
from studies.full_trade_path_builder.implementation.phase_a_strategy import (  # noqa: E402
    is_rth_decision,
)
from studies.full_trade_path_builder.implementation.run_phase_a_collect import (  # noqa: E402
    BAR_1M,
    BAR_1S,
    CATALOG,
    SEALED_BOUNDARY,
    atomic_json,
    frozen_catalog_identity,
    parse_utc,
    sha256_file,
)
from studies.regime_complete_canonical_store.implementation.collector import (  # noqa: E402
    RegimeCompleteCollector,
    RegimeCompleteCollectorConfig,
)
from studies.regime_complete_canonical_store.implementation.identity import (  # noqa: E402
    CONTRACT_VERSION,
    collector_version,
    regime_engine_version,
)
from studies.regime_complete_canonical_store.implementation.writer import (  # noqa: E402
    build_paths,
    build_regimes,
    build_scores,
)

NS = 1_000_000_000
WARMUP_DAYS = 4

OUTPUTS = {
    "regimes": "canonical_regimes.parquet",
    "scores": "canonical_regime_scores.parquet",
    "paths": "canonical_regime_paths.parquet",
    "missing": "missing_dispatch.parquet",
}


def _write(frame, path: Path) -> None:
    """Atomic Parquet write: a killed process must not leave a valid-looking
    partition behind for the resume logic to trust."""
    tmp = path.with_suffix(".parquet.tmp")
    frame.write_parquet(tmp, compression="zstd", statistics=True)
    tmp.replace(path)


def collect(
    start: datetime, end: datetime, output_dir: Path, overwrite: bool = False
) -> dict:
    if end <= start or start >= SEALED_BOUNDARY or end > SEALED_BOUNDARY:
        raise RuntimeError("invalid or sealed collection window")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists() and not overwrite:
        manifest = json.loads(manifest_path.read_text())
        for key, name in OUTPUTS.items():
            if sha256_file(output_dir / name) != manifest["sha256"][key]:
                raise RuntimeError(f"corrupt resumable partition: {name}")
        manifest["resumed"] = True
        return manifest

    partition = f"{start:%Y-%m}"
    load_start = start - timedelta(days=WARMUP_DAYS)
    load_end = min(end, SEALED_BOUNDARY)

    catalog = ParquetDataCatalog(str(CATALOG))
    bars_1s = catalog.bars(bar_types=[BAR_1S], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=[BAR_1M], start=load_start, end=load_end)

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="REGIME-COMPLETE",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(5_000_000, USD)],
        bar_execution=True, bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(create_instrument())
    # Equal-ts_init tie-break: the finer stream must be added first so 1s bars
    # are delivered before their parent 1m bar.
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    strategy = RegimeCompleteCollector(RegimeCompleteCollectorConfig(repo_root=str(ROOT)))
    engine.add_strategy(strategy)

    t0 = time.time()
    engine.run(start=load_start, end=load_end)
    strategy.finalize()
    runtime_seconds = time.time() - t0

    start_ns, end_ns = int(start.timestamp() * NS), int(end.timestamp() * NS)

    def in_window(value) -> bool:
        return value is not None and start_ns <= value < end_ns

    regimes = build_regimes(
        [r for r in strategy.regimes if in_window(r["regime_start_decision_ns"])],
        partition,
    )
    # Paths and scores are filtered by their own timestamps, not by regime
    # membership: a regime that starts before the window still owns the seconds
    # that fall inside it, and dropping them would puncture the path stream.
    all_regimes = build_regimes(strategy.regimes, partition)
    paths = build_paths(strategy.paths, all_regimes, partition).filter(
        (pl.col("path_init_ns") >= start_ns) & (pl.col("path_init_ns") < end_ns)
    )
    scored_rows = [r for r in strategy.rows if in_window(r["checkpoint_decision_ns"])]
    scores = build_scores(scored_rows, partition)
    missing = build_missing(
        start_ns, end_ns, {r["checkpoint_decision_ns"] for r in scored_rows}
    )

    for key, frame in (
        ("regimes", regimes), ("scores", scores), ("paths", paths), ("missing", missing)
    ):
        _write(frame, output_dir / OUTPUTS[key])

    manifest = {
        "status": "complete",
        "contract_version": CONTRACT_VERSION,
        "partition": partition,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "load_start": load_start.isoformat(),
        "load_end": load_end.isoformat(),
        "warmup_days": WARMUP_DAYS,
        "rows": {
            "regimes": regimes.height,
            "scores": scores.height,
            "paths": paths.height,
            "missing": missing.height,
        },
        "warmup_flips_skipped": strategy._warmup_flips_skipped,
        "runtime_seconds": runtime_seconds,
        "sha256": {
            key: sha256_file(output_dir / name) for key, name in OUTPUTS.items()
        },
        "collector_version": collector_version(),
        "regime_engine_version": regime_engine_version(),
        "catalog_identity": frozen_catalog_identity(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "resumed": False,
    }
    atomic_json(manifest, manifest_path)
    engine.dispose()
    return manifest


def build_missing(start_ns: int, end_ns: int, scored: set[int]) -> pl.DataFrame:
    """Every 5s slot in the window with no score row.

    Reconciled against the complete window grid rather than detected as the
    stream advances, so `scores + missing` equals the expected slot count by
    construction -- including slots that run to the end of the window, which an
    incremental detector cannot see.

    Gaps are retained separately and never imputed into the score table.
    """
    schema = {
        "checkpoint_decision_ns": pl.Int64,
        "session": pl.String,
        "suppression_reason": pl.String,
    }
    gaps = [t for t in range(start_ns, end_ns, 5 * NS) if t not in scored]
    if not gaps:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(
        {
            "checkpoint_decision_ns": gaps,
            "session": ["RTH" if is_rth_decision(t) else "ETH" for t in gaps],
            "suppression_reason": ["missing_dispatch_bar"] * len(gaps),
        },
        schema=schema,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    manifest = collect(
        parse_utc(args.start), parse_utc(args.end), Path(args.output_dir), args.overwrite
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
