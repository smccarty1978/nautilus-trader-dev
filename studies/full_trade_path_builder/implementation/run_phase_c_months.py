"""Sequential restart-safe NautilusTrader Phase C selector."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument

from .phase_c_strategy import PhaseCSelector, PhaseCSelectorConfig
from .phase_b_grid import canonical_partition_bounds
from .run_phase_a_collect import (
    BAR_1S,
    CATALOG,
    ROOT,
    atomic_json,
    parse_utc,
    sha256_file,
)

SELECTION_SCHEMA = pa.schema(
    [
        ("trade_id", pa.string()),
        ("trade_id_prefix", pa.string()),
        ("instrument_id", pa.string()),
        ("entry_model_id", pa.string()),
        ("trade_direction", pa.int64()),
        ("trade_direction_name", pa.string()),
        ("entry_regime_direction", pa.int64()),
        ("regime_start_ns", pa.int64()),
        ("checkpoint_decision_ns", pa.int64()),
        ("entry_year", pa.int64()),
        ("entry_month", pa.int64()),
        ("session", pa.string()),
        ("checkpoint_reference_price", pa.float64()),
        ("atr_at_entry", pa.float64()),
        ("entry_raw_score", pa.float64()),
        ("entry_probability", pa.float64()),
        ("entry_percentile", pa.float64()),
        ("entry_decile", pa.int64()),
        ("entry_top_2_5_threshold", pa.float64()),
        ("threshold_membership_operator", pa.string()),
        ("threshold_reference_overlap_waiver", pa.bool_()),
        ("bullish_raw_score_at_entry", pa.float64()),
        ("bullish_probability_at_entry", pa.float64()),
        ("bullish_percentile_at_entry", pa.float64()),
        ("bullish_in_domain_at_entry", pa.bool_()),
        ("bearish_raw_score_at_entry", pa.float64()),
        ("bearish_probability_at_entry", pa.float64()),
        ("bearish_percentile_at_entry", pa.float64()),
        ("bearish_in_domain_at_entry", pa.bool_()),
        ("confirm_flip_ns", pa.int64()),
        ("confirm_flip_direction", pa.int64()),
        ("seconds_entry_to_confirm", pa.float64()),
        ("confirmed_within_300s", pa.bool_()),
        ("confirmed_within_600s", pa.bool_()),
        ("selection_regime_key", pa.string()),
        ("source_feature_vector_hash", pa.string()),
    ]
)
OVERLAP_DISCLOSURE = (
    "The threshold reference population overlaps calendar year 2025 of the "
    "study population. Results are descriptive and must not be represented "
    "as threshold-out-of-sample for 2025."
)


def selected_state_hash(keys: set[str]) -> str:
    payload = json.dumps(sorted(keys), separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def load_phase_c_contract() -> tuple[dict, float, float]:
    base = ROOT / "studies/full_trade_path_builder"
    config = yaml.safe_load((base / "config/phase_c.yaml").read_text(encoding="utf-8"))
    waiver = json.loads(
        (base / "THRESHOLD_OVERLAP_WAIVER.json").read_text(encoding="utf-8")
    )
    bull_source = json.loads(
        (
            base / "artifacts/BULLISH_STRICT_top25_gbt_v2/thresholds.json"
        ).read_text(encoding="utf-8")
    )
    bear_source = json.loads(
        (
            ROOT / "studies/freeze_long_strict_models_v2/artifacts/"
            "LONG_STRICT_top25_gbt_v2/metrics_2025.json"
        ).read_text(encoding="utf-8")
    )
    bull = float(config["bullish"]["top_2_5_threshold"])
    bear = float(config["bearish"]["top_2_5_threshold"])
    if waiver.get("authorized") is not True:
        raise RuntimeError("threshold-overlap waiver is not authorized")
    if config.get("membership_operator") != ">=" or waiver.get(
        "membership_operator"
    ) != ">=":
        raise RuntimeError("Phase C membership operator must be >=")
    comparisons = (
        (bull, float(waiver["bullish_top_2_5_threshold"]), "Bull waiver"),
        (bear, float(waiver["bearish_top_2_5_threshold"]), "Bear waiver"),
        (bull, float(bull_source["thresholds"]["top_2_5"]), "Bull source"),
        (bear, float(bear_source["top_2_5pct_threshold"]), "Bear source"),
    )
    for actual, expected, name in comparisons:
        if actual != expected:
            raise RuntimeError(f"{name} threshold mismatch: {actual} != {expected}")
    identity = {
        "code": {
            name: sha256_file(base / "implementation" / name)
            for name in ("phase_c_strategy.py", "run_phase_c_months.py")
        },
        "config": sha256_file(base / "config/phase_c.yaml"),
        "waiver": sha256_file(base / "THRESHOLD_OVERLAP_WAIVER.json"),
        "bullish_threshold_manifest": sha256_file(
            base / "artifacts/BULLISH_STRICT_top25_gbt_v2/thresholds.json"
        ),
        "bearish_threshold_source": sha256_file(
            ROOT / "studies/freeze_long_strict_models_v2/artifacts/"
            "LONG_STRICT_top25_gbt_v2/metrics_2025.json"
        ),
        "executed_contract": {
            "bullish_top_2_5_threshold": bull,
            "bearish_top_2_5_threshold": bear,
            "membership_operator": ">=",
            "waiver_authorized": True,
        },
        "phase_b_global_integrity": sha256_file(
            base / "results/phase_b_global_integrity.json"
        ),
    }
    return identity, bull, bear


def write_selection(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        pa.Table.from_pylist(rows, schema=SELECTION_SCHEMA), tmp, compression="zstd"
    )
    os.replace(tmp, path)


def validate_existing(
    output_dir: Path,
    phase_b_manifest: dict,
    identity: dict,
    prior_hash: str,
) -> dict | None:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        return None
    if manifest.get("phase_c_identity") != identity:
        raise RuntimeError(f"Phase C identity mismatch: {output_dir}")
    if manifest.get("phase_b_score_sha256") != phase_b_manifest[
        "canonical_model_scores_sha256"
    ]:
        raise RuntimeError(f"Phase B input mismatch: {output_dir}")
    if manifest.get("prior_selected_state_sha256") != prior_hash:
        raise RuntimeError(f"Phase C prior-state mismatch: {output_dir}")
    selection_path = output_dir / "selected_trade_entries.parquet"
    if sha256_file(selection_path) != manifest.get("selection_sha256"):
        raise RuntimeError(f"Phase C output hash mismatch: {selection_path}")
    return manifest


def run_month(
    score_path: Path,
    phase_b_manifest: dict,
    output_dir: Path,
    prior_selected: set[str],
    identity: dict,
    bullish_threshold: float,
    bearish_threshold: float,
) -> dict:
    start, end = parse_utc(phase_b_manifest["start"]), parse_utc(phase_b_manifest["end"])
    catalog = ParquetDataCatalog(str(CATALOG))
    bars = catalog.bars(bar_types=[BAR_1S], start=start, end=end)
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="FULLPATH-PHASE-C",
            logging=LoggingConfig(log_level="ERROR", bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=Venue("XCME"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(5_000_000, USD)],
        bar_execution=True,
        bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(create_instrument())
    engine.add_data(bars)
    strategy = PhaseCSelector(
        PhaseCSelectorConfig(
            score_path=str(score_path),
            prior_selected_json=json.dumps(sorted(prior_selected)),
            bullish_threshold=bullish_threshold,
            bearish_threshold=bearish_threshold,
        )
    )
    engine.add_strategy(strategy)
    started = time.time()
    engine.run(start=start, end=end)
    engine.dispose()
    if strategy.dispatched_keys != strategy.score_keys:
        raise RuntimeError(
            "Phase C dispatch-key mismatch: "
            f"missing={len(strategy.score_keys-strategy.dispatched_keys)} "
            f"extra={len(strategy.dispatched_keys-strategy.score_keys)}"
        )
    rows = sorted(strategy.selections, key=lambda row: row["checkpoint_decision_ns"])
    selection_path = output_dir / "selected_trade_entries.parquet"
    write_selection(rows, selection_path)
    manifest = {
        "status": "complete",
        "start": phase_b_manifest["start"],
        "end": phase_b_manifest["end"],
        "phase_b_score_sha256": phase_b_manifest["canonical_model_scores_sha256"],
        "phase_c_identity": identity,
        "prior_selected_state_sha256": selected_state_hash(prior_selected),
        "result_selected_state_sha256": selected_state_hash(strategy.selected_keys),
        "score_rows_dispatched": strategy.dispatched_score_rows,
        "selection_rows": len(rows),
        "long_rows": sum(row["trade_direction"] == 1 for row in rows),
        "short_rows": sum(row["trade_direction"] == -1 for row in rows),
        "selection_sha256": sha256_file(selection_path),
        "runtime_seconds": time.time() - started,
        "threshold_reference_overlap_waiver": True,
        "threshold_reference_overlap_disclosure": OVERLAP_DISCLOSURE,
    }
    atomic_json(manifest, output_dir / "manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-b-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--progress-file", required=True)
    args = parser.parse_args()
    phase_b_root, output_root = Path(args.phase_b_root), Path(args.output_root)
    progress_path = Path(args.progress_file)
    identity, bullish_threshold, bearish_threshold = load_phase_c_contract()
    accepted_phase_b_root = (
        ROOT / "studies/full_trade_path_builder/_work/phase_b_monthly"
    ).resolve()
    if phase_b_root.resolve() != accepted_phase_b_root:
        raise RuntimeError(
            f"Phase C requires accepted Phase B root {accepted_phase_b_root}; "
            f"received {phase_b_root.resolve()}"
        )
    integrity = json.loads(
        (
            ROOT
            / "studies/full_trade_path_builder/results/phase_b_global_integrity.json"
        ).read_text(encoding="utf-8")
    )
    if integrity.get("status") != "PASS" or integrity.get("partition_count") != 60:
        raise RuntimeError("accepted Phase B global-integrity gate is absent")
    selected: set[str] = set()
    completed = []
    for year in range(2021, 2026):
        for month in range(1, 13):
            source_dir = phase_b_root / f"year={year}" / f"month={month:02d}"
            phase_b_manifest = json.loads(
                (source_dir / "manifest.json").read_text(encoding="utf-8")
            )
            if phase_b_manifest.get("status") != "complete":
                raise RuntimeError(f"Phase B partition incomplete: {source_dir}")
            expected_start, expected_end = canonical_partition_bounds(year, month)
            if (
                phase_b_manifest.get("start") != expected_start.isoformat()
                or phase_b_manifest.get("end") != expected_end.isoformat()
            ):
                raise RuntimeError(f"non-canonical Phase B interval: {source_dir}")
            score_path = source_dir / "canonical_model_scores.parquet"
            if sha256_file(score_path) != phase_b_manifest.get(
                "canonical_model_scores_sha256"
            ):
                raise RuntimeError(f"Phase B score hash mismatch: {score_path}")
            output_dir = output_root / f"year={year}" / f"month={month:02d}"
            prior_hash = selected_state_hash(selected)
            manifest = validate_existing(
                output_dir, phase_b_manifest, identity, prior_hash
            )
            if manifest is None:
                manifest = run_month(
                    score_path,
                    phase_b_manifest,
                    output_dir,
                    selected,
                    identity,
                    bullish_threshold,
                    bearish_threshold,
                )
            rows = pq.read_table(
                output_dir / "selected_trade_entries.parquet",
                columns=["selection_regime_key"],
            )["selection_regime_key"].to_pylist()
            selected.update(rows)
            if selected_state_hash(selected) != manifest["result_selected_state_sha256"]:
                raise RuntimeError(f"Phase C resulting-state mismatch: {output_dir}")
            completed.append(manifest["selection_rows"])
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(
                {
                    "status": "building",
                    "months_completed": len(completed),
                    "last_completed": f"{year}-{month:02d}",
                    "selected_trades": sum(completed),
                },
                progress_path,
            )
    result = {
        "status": "complete",
        "months_completed": len(completed),
        "selected_trades": sum(completed),
        "selected_state_sha256": selected_state_hash(selected),
        "phase_c_identity": identity,
        "threshold_reference_overlap_waiver": True,
        "threshold_reference_overlap_disclosure": OVERLAP_DISCLOSURE,
    }
    atomic_json(result, output_root / "global_selection_manifest.json")
    atomic_json(result, progress_path)


if __name__ == "__main__":
    main()
