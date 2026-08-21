"""Bounded monthly NT collection of structural snapshots, 2021-2024 only."""
from __future__ import annotations

import argparse
import hashlib
import json
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

from studies.Codex_structural_regime_geometry_maturity.implementation.collector import (
    StructuralOnlyCollector, StructuralOnlyCollectorConfig,
)
from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument
from studies.full_trade_path_builder.implementation.run_phase_a_collect import BAR_1M, BAR_1S, CATALOG, parse_utc

ROOT = Path(__file__).resolve().parents[3]
NS, WARMUP_DAYS = 1_000_000_000, 4
SEALED = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retain_after_warmup(frame: pl.DataFrame, start_ns: int, end_ns: int) -> pl.DataFrame:
    """Retain only decision rows after the complete four-day warmup interval."""
    retained = frame.filter((pl.col("checkpoint_decision_ns") >= start_ns) & (pl.col("checkpoint_decision_ns") < end_ns))
    if retained.height and int(retained["checkpoint_decision_ns"].min()) < start_ns:
        raise RuntimeError("warmup row escaped retained target interval")
    if retained.height and int(retained["checkpoint_decision_ns"].max()) >= end_ns:
        raise RuntimeError("next-month row escaped retained target interval")
    return retained


def assert_retained_rows_ready(frame: pl.DataFrame, start_ns: int, end_ns: int) -> None:
    """Fail if the first retained decision was emitted before tracker readiness."""
    retained = retain_after_warmup(frame, start_ns, end_ns)
    if retained.is_empty():
        return
    if "structural_available" not in retained.columns:
        raise RuntimeError("collector output omitted structural readiness")
    first_ready = bool(retained.sort("checkpoint_decision_ns")["structural_available"][0])
    if not first_ready:
        raise RuntimeError("warmup readiness failed: first retained snapshot unavailable")


def collect(start: datetime, end: datetime, output_dir: Path) -> dict:
    if not (start < end <= SEALED):
        raise ValueError("collection must lie wholly in 2021-2024; 2025/2026 are forbidden")
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path, manifest_path = output_dir / "structural_rows.parquet", output_dir / "manifest.json"
    if data_path.exists() and manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old.get("sha256") == _sha(data_path):
            old["resumed"] = True; return old
        raise RuntimeError("existing structural partition hash mismatch")
    load_start = start - timedelta(days=WARMUP_DAYS)
    catalog = ParquetDataCatalog(str(CATALOG))
    bars_1s = catalog.bars(bar_types=[BAR_1S], start=load_start, end=end)
    bars_1m = catalog.bars(bar_types=[BAR_1M], start=load_start, end=end)
    engine = BacktestEngine(BacktestEngineConfig(trader_id="STRUCTURAL-GEOMETRY",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False)))
    engine.add_venue(venue=Venue("XCME"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
                     base_currency=USD, starting_balances=[Money(5_000_000, USD)],
                     bar_execution=True, bar_adaptive_high_low_ordering=True)
    engine.add_instrument(create_instrument())
    engine.add_data(bars_1s); engine.add_data(bars_1m)  # finer stream first is load-bearing
    strategy = StructuralOnlyCollector(StructuralOnlyCollectorConfig())
    engine.add_strategy(strategy); t0 = time.time(); engine.run(start=load_start, end=end)
    a, b = int(start.timestamp()*NS), int(end.timestamp()*NS)
    raw_frame = pl.DataFrame(strategy.geometry_rows, infer_schema_length=None)
    assert_retained_rows_ready(raw_frame, a, b)
    frame = retain_after_warmup(raw_frame, a, b)
    frame.write_parquet(data_path, compression="zstd", statistics=True)
    engine.dispose()
    manifest = {"status": "complete", "start": start.isoformat(), "end": end.isoformat(),
                "load_start": load_start.isoformat(), "warmup_days": WARMUP_DAYS,
                "warmup_ready_not_before": start.isoformat(),
                "warmup_readiness_verified": True,
                "rows": frame.height, "sha256": _sha(data_path), "runtime_seconds": time.time()-t0,
                "resumed": False, "sealed_boundary": SEALED.isoformat()}
    manifest_path.write_text(json.dumps(manifest, indent=2)); return manifest


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--start", required=True); p.add_argument("--end", required=True); p.add_argument("--output-dir", required=True)
    a = p.parse_args(); print(json.dumps(collect(parse_utc(a.start), parse_utc(a.end), Path(a.output_dir)), indent=2))


if __name__ == "__main__": main()
