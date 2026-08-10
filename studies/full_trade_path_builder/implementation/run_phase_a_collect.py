"""Bounded monthly NT collector for Phase A.

Pandas is not used for signal, feature, regime, or label construction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
from studies.full_trade_path_builder.implementation.phase_a_core import (
    label_checkpoint,
    next_flip_after,
)
from studies.full_trade_path_builder.implementation.phase_a_strategy import (
    PhaseABullishCollector,
    PhaseABullishCollectorConfig,
)

CATALOG = ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
BAR_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
BAR_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
SEALED_BOUNDARY = datetime(2026, 1, 1, tzinfo=timezone.utc)


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def code_identity() -> str:
    names = (
        "phase_a_core.py", "phase_a_candidate.py", "phase_a_adapter.py",
        "phase_a_strategy.py", "run_phase_a_collect.py",
    )
    h = hashlib.sha256()
    for name in names:
        h.update((Path(__file__).parent / name).read_bytes())
    return h.hexdigest()


def requested_load_end(end: datetime) -> datetime:
    return min(end + timedelta(seconds=301), SEALED_BOUNDARY)


def validate_window(start: datetime, end: datetime) -> None:
    if start >= SEALED_BOUNDARY or end > SEALED_BOUNDARY or end <= start:
        raise RuntimeError("sealed 2026 access prohibited or invalid Phase A window")


def frozen_catalog_identity() -> dict:
    manifest_path = ROOT / "studies/full_trade_path_builder/config/catalog_identity.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("identity_mode") != "trusted_precomputed_do_not_reopen_monolithic_files_in_phase_a":
        raise RuntimeError("untrusted catalog identity mode")
    # Deliberately do not stat/open/hash the monolithic catalog Parquet files:
    # they extend into sealed 2026. Phase A trusts this precomputed identity
    # record and constrains actual catalog reads with the requested time range.
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "catalog": payload["catalog"],
        "identity_mode": payload["identity_mode"],
    }


def validate_existing(output_dir: Path, start: datetime, end: datetime) -> dict:
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "checkpoints.parquet": manifest["checkpoints_sha256"],
        "flips.parquet": manifest["flips_sha256"],
        "missing_dispatch.parquet": manifest["missing_dispatch_sha256"],
    }
    for name, digest in expected.items():
        path = output_dir / name
        if not path.exists() or sha256_file(path) != digest:
            raise RuntimeError(f"corrupt or missing resumable partition artifact: {path}")
    if manifest.get("code_identity") != code_identity():
        raise RuntimeError("stale partition code identity; refusing resume")
    config_hash = sha256_file(ROOT / "studies/full_trade_path_builder/config/phase_a.yaml")
    if manifest.get("config_sha256") != config_hash:
        raise RuntimeError("stale partition config identity; refusing resume")
    if manifest.get("start") != start.isoformat() or manifest.get("end") != end.isoformat():
        raise RuntimeError("partition window mismatch; refusing resume")
    if manifest.get("catalog_identity") != frozen_catalog_identity():
        raise RuntimeError("catalog identity mismatch; refusing resume")
    return manifest


def atomic_parquet(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pylist(rows), tmp, compression="zstd")
    os.replace(tmp, path)


def atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def collect(start: datetime, end: datetime, output_dir: Path, overwrite: bool = False) -> dict:
    validate_window(start, end)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists() and not overwrite:
        return validate_existing(output_dir, start, end)

    # Warmup covers rolling 60m, prior-session levels, ATR, and any regime
    # which can still generate a <1800s checkpoint inside the requested range.
    load_start = start - timedelta(days=3)
    load_end = requested_load_end(end)
    catalog = ParquetDataCatalog(str(CATALOG))
    bars_1s = catalog.bars(bar_types=[BAR_1S], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=[BAR_1M], start=load_start, end=load_end)
    if not bars_1s or not bars_1m:
        raise RuntimeError("catalog returned no bars")

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="FULLPATH-PHASE-A",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(5_000_000, USD)],
        bar_execution=True, bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(create_instrument())
    engine.add_data(bars_1s)  # contractually first
    engine.add_data(bars_1m)
    strategy = PhaseABullishCollector(PhaseABullishCollectorConfig(repo_root=str(ROOT)))
    engine.add_strategy(strategy)
    t0 = time.time()
    engine.run(start=load_start, end=load_end)

    start_ns, end_ns = int(start.timestamp() * 1e9), int(end.timestamp() * 1e9)
    checkpoints = [
        row for row in strategy.checkpoint_rows
        if start_ns <= row["checkpoint_decision_ns"] < end_ns
    ]
    missing_rows = [
        row for row in strategy.missing_rows
        if start_ns <= row["checkpoint_decision_ns"] < end_ns
    ]
    flips = sorted(strategy.flip_rows, key=lambda x: x["confirm_flip_ns"])
    bearish_times = [x["confirm_flip_ns"] for x in flips if x["new_direction"] == -1]
    observation_end = int(strategy.observation_end_ns or 0)
    labeled = []
    for row in checkpoints:
        flip = next_flip_after(row["checkpoint_decision_ns"], bearish_times)
        lab = label_checkpoint(row["checkpoint_decision_ns"], flip, observation_end)
        labeled.append({
            **row,
            "label_flip_le_300": lab.label_flip_le_300,
            "label_censored": lab.censored,
            "confirm_flip_ns": lab.confirm_flip_ns,
            "seconds_to_flip": lab.seconds_to_flip,
            "observation_end_ns": observation_end,
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    cp_path, flip_path = output_dir / "checkpoints.parquet", output_dir / "flips.parquet"
    missing_path = output_dir / "missing_dispatch.parquet"
    atomic_parquet(labeled, cp_path)
    atomic_parquet(flips, flip_path)
    atomic_parquet(missing_rows, missing_path)
    manifest = {
        "status": "complete",
        "start": start.isoformat(), "end": end.isoformat(),
        "load_start": load_start.isoformat(), "load_end": load_end.isoformat(),
        "n_bars_1s": len(bars_1s), "n_bars_1m": len(bars_1m),
        "n_checkpoints": len(labeled), "n_flips": len(flips),
        "n_missing_dispatch": len(missing_rows),
        "n_censored": sum(bool(x["label_censored"]) for x in labeled),
        "runtime_seconds": time.time() - t0,
        "checkpoints_sha256": sha256_file(cp_path),
        "flips_sha256": sha256_file(flip_path),
        "missing_dispatch_sha256": sha256_file(missing_path),
        "config_sha256": sha256_file(ROOT / "studies/full_trade_path_builder/config/phase_a.yaml"),
        "code_identity": code_identity(),
        "catalog_identity": frozen_catalog_identity(),
    }
    atomic_json(manifest, manifest_path)
    engine.dispose()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = collect(parse_utc(args.start), parse_utc(args.end), Path(args.output_dir), args.overwrite)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
