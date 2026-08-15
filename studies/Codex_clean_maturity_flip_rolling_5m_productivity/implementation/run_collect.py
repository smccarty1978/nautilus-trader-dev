"""Bounded NT-only collection for the explicitly waived exploratory diagnostic."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import CleanFlipCollector, CleanFlipCollectorConfig
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.phase0 import write_manifest
from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument


ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
NS = 1_000_000_000


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def collect(start: datetime, end: datetime, output_dir: Path) -> dict:
    if not (datetime(2021, 1, 1, tzinfo=timezone.utc) <= start < end <= datetime(2025, 1, 1, tzinfo=timezone.utc)):
        raise ValueError("exploratory collection is restricted to 2021-2024")
    output_dir.mkdir(parents=True, exist_ok=True)
    phase0_path = output_dir / "phase0_source_manifest.json"
    write_manifest(phase0_path)
    catalog = ParquetDataCatalog(str(CATALOG))
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"], start=start, end=end)
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"], start=start, end=end)
    engine = BacktestEngine(BacktestEngineConfig(trader_id="CLEAN-FLIP-EXPLORATORY", logging=LoggingConfig(log_level="ERROR", bypass_logging=False)))
    engine.add_venue(venue=Venue("XCME"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
                     base_currency=USD, starting_balances=[Money(5_000_000, USD)], bar_execution=True,
                     bar_adaptive_high_low_ordering=True)
    engine.add_instrument(create_instrument()); engine.add_data(bars_1s); engine.add_data(bars_1m)
    strategy = CleanFlipCollector(CleanFlipCollectorConfig(phase0_manifest_path=str(phase0_path), authorized_years=tuple(range(2021, 2025))))
    engine.add_strategy(strategy); started = time.time(); engine.run(start=start, end=end)
    features_path, regimes_path = output_dir / "features.parquet", output_dir / "regimes.parquet"
    pl.DataFrame(strategy.feature_rows, infer_schema_length=None).write_parquet(features_path, compression="zstd")
    pl.DataFrame(strategy.regime_rows, infer_schema_length=None).write_parquet(regimes_path, compression="zstd")
    engine.dispose()
    manifest = {"mode": "EXPLORATORY_CONTRACT_GATE_BLOCKED", "start": start.isoformat(), "end": end.isoformat(),
                "rows": len(strategy.feature_rows), "regimes": len(strategy.regime_rows), "runtime_seconds": time.time() - started,
                "features_sha256": _sha(features_path), "regimes_sha256": _sha(regimes_path),
                "phase0_sha256": _sha(phase0_path), "source": "NautilusTrader event-loop"}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2)); return manifest


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--start", required=True); parser.add_argument("--end", required=True); parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(); print(json.dumps(collect(parse_utc(args.start), parse_utc(args.end), Path(args.output_dir)), indent=2))


if __name__ == "__main__": main()
