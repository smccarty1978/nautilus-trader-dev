"""Bounded entry-month NautilusTrader Phase D full-path builder."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
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

from .phase_d_core import build_trade_plans
from .phase_d_strategy import PhaseDPathCollector, PhaseDPathConfig
from .run_phase_a_collect import (
    BAR_1S,
    CATALOG,
    ROOT,
    SEALED_BOUNDARY,
    atomic_json,
    parse_utc,
    sha256_file,
)

NS = 1_000_000_000


def flip_ledger(phase_b_root: Path) -> tuple[list[dict], str]:
    by_key = {}
    for path in sorted(phase_b_root.glob("year=*/month=*/confirmed_flips.parquet")):
        manifest = json.loads(path.with_name("manifest.json").read_text())
        if manifest.get("status") != "complete":
            raise RuntimeError(f"incomplete Phase B flip partition: {path}")
        if sha256_file(path) != manifest.get("confirmed_flips_sha256"):
            raise RuntimeError(f"Phase B flip hash mismatch: {path}")
        for row in pq.read_table(path).to_pylist():
            by_key[(row["confirm_flip_ns"], row["new_direction"])] = row
    rows = sorted(by_key.values(), key=lambda row: row["confirm_flip_ns"])
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    global_manifest = json.loads(
        (phase_b_root / "global_label_manifest.json").read_text()
    )
    if digest != global_manifest.get("global_flip_ledger_sha256"):
        raise RuntimeError("Phase B global flip-ledger hash mismatch")
    return rows, digest


def load_phase_d_contract() -> tuple[dict, dict]:
    base = ROOT / "studies/full_trade_path_builder"
    config = yaml.safe_load((base / "config/phase_d.yaml").read_text())
    bull_source = json.loads(
        (
            base / "artifacts/BULLISH_STRICT_top25_gbt_v2/thresholds.json"
        ).read_text()
    )
    bear_source = json.loads(
        (
            ROOT / "studies/freeze_long_strict_models_v2/artifacts/"
            "LONG_STRICT_top25_gbt_v2/metrics_2025.json"
        ).read_text()
    )
    waiver = json.loads((base / "THRESHOLD_OVERLAP_WAIVER.json").read_text())
    if bull_source.get("membership_operator") != ">=":
        raise RuntimeError("Bullish threshold membership operator must be >=")
    if waiver.get("membership_operator") != ">=":
        raise RuntimeError("Phase D waiver membership operator must be >=")
    thresholds = {
        "bullish_top_10": float(config["bullish_thresholds"]["top_10"]),
        "bullish_top_5": float(config["bullish_thresholds"]["top_5"]),
        "bullish_top_2_5": float(config["bullish_thresholds"]["top_2_5"]),
        "bearish_top_5": float(config["bearish_thresholds"]["top_5"]),
        "bearish_top_2_5": float(config["bearish_thresholds"]["top_2_5"]),
    }
    expected = {
        "bullish_top_10": float(bull_source["thresholds"]["top_10"]),
        "bullish_top_5": float(bull_source["thresholds"]["top_5"]),
        "bullish_top_2_5": float(bull_source["thresholds"]["top_2_5"]),
        "bearish_top_5": float(bear_source["top_5pct_threshold"]),
        "bearish_top_2_5": float(bear_source["top_2_5pct_threshold"]),
    }
    if thresholds != expected:
        raise RuntimeError(f"Phase D threshold mismatch: {thresholds} != {expected}")
    if waiver.get("authorized") is not True:
        raise RuntimeError("Phase D threshold-overlap waiver is not authorized")
    if thresholds["bullish_top_2_5"] != float(
        waiver["bullish_top_2_5_threshold"]
    ) or thresholds["bearish_top_2_5"] != float(
        waiver["bearish_top_2_5_threshold"]
    ):
        raise RuntimeError("Phase D waiver threshold mismatch")
    identity = {
        "code": {
            name: sha256_file(base / "implementation" / name)
            for name in (
                "phase_d_core.py",
                "phase_d_strategy.py",
                "run_phase_d_months.py",
            )
        },
        "config": sha256_file(base / "config/phase_d.yaml"),
        "task_packet": sha256_file(base / "PHASE_D_TASK_PACKET.md"),
        "phase_c_parity": sha256_file(base / "results/phase_c_selection_parity.json"),
        "phase_c_completion_audit": sha256_file(base / "audit/phase_c_completion.md"),
        "waiver": sha256_file(base / "THRESHOLD_OVERLAP_WAIVER.json"),
        "bullish_threshold_source": sha256_file(
            base / "artifacts/BULLISH_STRICT_top25_gbt_v2/thresholds.json"
        ),
        "bearish_threshold_source": sha256_file(
            ROOT
            / "studies/freeze_long_strict_models_v2/artifacts/"
            "LONG_STRICT_top25_gbt_v2/metrics_2025.json"
        ),
        "catalog": "data/catalog/NQ_v0_2020_2026",
        "membership_operator": ">=",
        "executed_opposite_thresholds": thresholds,
    }
    return identity, thresholds


def atomic_table(rows: list[dict], path: Path) -> None:
    if not rows:
        raise RuntimeError(f"refusing schema-less empty Phase D artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pylist(rows), tmp, compression="zstd")
    os.replace(tmp, path)


def score_paths_for(
    phase_b_root: Path, start_ns: int, end_ns: int
) -> tuple[list[Path], dict[str, str]]:
    lower_ns = start_ns - 40 * 24 * 3600 * NS
    paths = []
    hashes = {}
    for manifest_path in sorted(phase_b_root.glob("year=*/month=*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        partition_start = int(parse_utc(manifest["start"]).timestamp() * NS)
        partition_end = int(parse_utc(manifest["end"]).timestamp() * NS)
        if partition_end <= lower_ns or partition_start >= end_ns:
            continue
        path = manifest_path.with_name("canonical_model_scores.parquet")
        digest = sha256_file(path)
        if digest != manifest["canonical_model_scores_sha256"]:
            raise RuntimeError(f"Phase B score hash mismatch: {path}")
        paths.append(path)
        hashes[str(path)] = digest
    if not paths:
        raise RuntimeError("no Phase B score paths cover Phase D interval")
    return paths, hashes


def validate_existing(
    output_dir: Path, identity: dict, selection_hash: str, flip_hash: str
) -> dict | None:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        return None
    if manifest.get("phase_d_identity") != identity:
        raise RuntimeError(f"Phase D identity mismatch: {output_dir}")
    if manifest.get("phase_c_selection_sha256") != selection_hash:
        raise RuntimeError(f"Phase C selection mismatch: {output_dir}")
    if manifest.get("global_flip_ledger_sha256") != flip_hash:
        raise RuntimeError(f"flip ledger mismatch: {output_dir}")
    for raw_path, expected_hash in manifest.get("score_input_hashes", {}).items():
        path = Path(raw_path)
        if sha256_file(path) != expected_hash:
            raise RuntimeError(f"Phase D carried-score input mismatch: {path}")
    for name, field in (
        ("trade_paths.parquet", "path_sha256"),
        ("trade_population.parquet", "summary_sha256"),
        ("trade_plan.json", "trade_plan_sha256"),
    ):
        if sha256_file(output_dir / name) != manifest.get(field):
            raise RuntimeError(f"Phase D output hash mismatch: {output_dir/name}")
    return manifest


def run_month(
    selection_path: Path,
    phase_b_root: Path,
    output_dir: Path,
    flips: list[dict],
    flip_hash: str,
    identity: dict,
    thresholds: dict,
) -> dict:
    selections = pq.read_table(selection_path).to_pylist()
    plans = build_trade_plans(
        selections, flips, int(SEALED_BOUNDARY.timestamp() * NS)
    )
    if not plans:
        raise RuntimeError(f"no Phase D selections: {selection_path}")
    start_ns = min(row["checkpoint_decision_ns"] for row in plans)
    planned_end_ns = max(row["planned_path_end_ns"] for row in plans)
    run_end_ns = min(
        planned_end_ns + 2 * NS, int(SEALED_BOUNDARY.timestamp() * NS)
    )
    score_paths, score_hashes = score_paths_for(
        phase_b_root, start_ns, run_end_ns
    )
    relevant_flips = [
        row
        for row in flips
        if row["confirm_flip_ns"] < run_end_ns
    ]
    plan_payload = {"trades": plans, "regime_flips": relevant_flips}
    plan_path = output_dir / "trade_plan.json"
    atomic_json(plan_payload, plan_path)
    catalog = ParquetDataCatalog(str(CATALOG))
    start = datetime.fromtimestamp(start_ns / NS, tz=timezone.utc)
    end = datetime.fromtimestamp(run_end_ns / NS, tz=timezone.utc)
    bars = catalog.bars(bar_types=[BAR_1S], start=start, end=end)
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="FULLPATH-PHASE-D",
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
    strategy = PhaseDPathCollector(
        PhaseDPathConfig(
            plan_path=str(plan_path),
            score_paths_json=json.dumps([str(path) for path in score_paths]),
            **thresholds,
        )
    )
    engine.add_strategy(strategy)
    started = time.time()
    engine.run(start=start, end=end)
    engine.dispose()
    if len(strategy.summary_rows) != len(plans):
        raise RuntimeError(
            f"Phase D summary count mismatch {len(strategy.summary_rows)} != {len(plans)}"
        )
    paths_path = output_dir / "trade_paths.parquet"
    summary_path = output_dir / "trade_population.parquet"
    atomic_table(strategy.path_rows, paths_path)
    atomic_table(
        sorted(
            strategy.summary_rows, key=lambda row: row["checkpoint_decision_ns"]
        ),
        summary_path,
    )
    selection_hash = sha256_file(selection_path)
    manifest = {
        "status": "complete",
        "phase_d_identity": identity,
        "phase_c_selection_sha256": selection_hash,
        "global_flip_ledger_sha256": flip_hash,
        "score_input_hashes": score_hashes,
        "trade_plan_sha256": sha256_file(plan_path),
        "path_sha256": sha256_file(paths_path),
        "summary_sha256": sha256_file(summary_path),
        "trade_count": len(plans),
        "path_row_count": len(strategy.path_rows),
        "completed_trade_count": sum(
            row["path_is_complete"] for row in strategy.summary_rows
        ),
        "censored_trade_count": sum(
            row["is_right_censored"] for row in strategy.summary_rows
        ),
        "run_start": start.isoformat(),
        "run_end": end.isoformat(),
        "runtime_seconds": time.time() - started,
        "threshold_reference_overlap_disclosure": (
            "The threshold reference population overlaps calendar year 2025 "
            "of the study population. Results are descriptive and must not be "
            "represented as threshold-out-of-sample for 2025."
        ),
    }
    atomic_json(manifest, output_dir / "manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-b-root", required=True)
    parser.add_argument("--phase-c-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--progress-file", required=True)
    args = parser.parse_args()
    phase_b_root = Path(args.phase_b_root)
    phase_c_root = Path(args.phase_c_root)
    output_root = Path(args.output_root)
    progress = Path(args.progress_file)
    accepted_b = (
        ROOT / "studies/full_trade_path_builder/_work/phase_b_monthly"
    ).resolve()
    accepted_c = (
        ROOT / "studies/full_trade_path_builder/_work/phase_c_selections"
    ).resolve()
    if phase_b_root.resolve() != accepted_b or phase_c_root.resolve() != accepted_c:
        raise RuntimeError("Phase D inputs must be the canonical accepted B/C roots")
    cglobal = json.loads(
        (phase_c_root / "global_selection_manifest.json").read_text()
    )
    if cglobal.get("status") != "complete" or cglobal.get("selected_trades") != 5836:
        raise RuntimeError("accepted Phase C global manifest unavailable")
    parity = json.loads(
        (
            ROOT / "studies/full_trade_path_builder/results/"
            "phase_c_selection_parity.json"
        ).read_text()
    )
    if parity.get("status") != "PASS" or parity.get("selected_trades") != 5836:
        raise RuntimeError("accepted Phase C parity unavailable")
    flips, flip_hash = flip_ledger(phase_b_root)
    identity, thresholds = load_phase_d_contract()
    counts = []
    for year in range(2021, 2026):
        for month in range(1, 13):
            cdir = phase_c_root / f"year={year}" / f"month={month:02d}"
            selection_path = cdir / "selected_trade_entries.parquet"
            cmanifest = json.loads((cdir / "manifest.json").read_text())
            if cmanifest.get("status") != "complete":
                raise RuntimeError(f"incomplete Phase C partition: {cdir}")
            if cmanifest.get("phase_c_identity") != cglobal.get("phase_c_identity"):
                raise RuntimeError(f"Phase C identity mismatch: {cdir}")
            selection_hash = sha256_file(selection_path)
            if selection_hash != cmanifest["selection_sha256"]:
                raise RuntimeError(f"Phase C selection hash mismatch: {selection_path}")
            output_dir = output_root / f"entry_year={year}" / f"entry_month={month:02d}"
            manifest = validate_existing(
                output_dir, identity, selection_hash, flip_hash
            )
            if manifest is None:
                manifest = run_month(
                    selection_path,
                    phase_b_root,
                    output_dir,
                    flips,
                    flip_hash,
                    identity,
                    thresholds,
                )
            counts.append(manifest)
            atomic_json(
                {
                    "status": "building",
                    "months_completed": len(counts),
                    "last_completed": f"{year}-{month:02d}",
                    "trade_count": sum(item["trade_count"] for item in counts),
                    "path_row_count": sum(
                        item["path_row_count"] for item in counts
                    ),
                },
                progress,
            )
    result = {
        "status": "complete",
        "month_count": len(counts),
        "trade_count": sum(item["trade_count"] for item in counts),
        "path_row_count": sum(item["path_row_count"] for item in counts),
        "completed_trade_count": sum(
            item["completed_trade_count"] for item in counts
        ),
        "censored_trade_count": sum(
            item["censored_trade_count"] for item in counts
        ),
        "phase_d_identity": identity,
        "global_flip_ledger_sha256": flip_hash,
    }
    atomic_json(result, output_root / "global_path_manifest.json")
    atomic_json(result, progress)


if __name__ == "__main__":
    main()
