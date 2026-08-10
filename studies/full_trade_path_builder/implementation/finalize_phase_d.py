"""Finalize validated monthly Phase D outputs into canonical partitions."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .run_phase_a_collect import atomic_json, sha256_file


def atomic_parquet(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def finalize(source: Path, output: Path, validation: Path) -> dict:
    validation_payload = json.loads(validation.read_text())
    if validation_payload.get("status") != "PASS":
        raise RuntimeError("Phase D validation must pass before finalization")
    global_source_hash = sha256_file(source / "global_path_manifest.json")
    if global_source_hash != validation_payload.get("source_global_manifest_sha256"):
        raise RuntimeError("validated Phase D global source manifest changed")
    bindings = {
        Path(item["partition"]).resolve(): item
        for item in validation_payload.get("source_bindings", [])
    }
    if len(bindings) != 60:
        raise RuntimeError(f"expected 60 validated source bindings, found {len(bindings)}")
    population_root = output / "canonical_trade_population"
    paths_root = output / "canonical_trade_paths"
    partitions = []
    total_trades = 0
    total_rows = 0
    for month_dir in sorted(source.glob("entry_year=*/entry_month=*")):
        binding = bindings.get(month_dir.resolve())
        if binding is None:
            raise RuntimeError(f"source partition was not validated: {month_dir}")
        source_manifest = month_dir / "manifest.json"
        summary_file = month_dir / "trade_population.parquet"
        paths_file = month_dir / "trade_paths.parquet"
        if sha256_file(source_manifest) != binding["manifest_sha256"]:
            raise RuntimeError(f"validated manifest changed: {source_manifest}")
        if sha256_file(summary_file) != binding["summary_sha256"]:
            raise RuntimeError(f"validated summary changed: {summary_file}")
        if sha256_file(paths_file) != binding["path_sha256"]:
            raise RuntimeError(f"validated paths changed: {paths_file}")
        summary = pq.read_table(summary_file)
        paths = pq.read_table(paths_file)
        year = int(summary["entry_year"][0].as_py())
        month = int(summary["entry_month"][0].as_py())
        for direction_value, direction_name in ((1, "LONG"), (-1, "SHORT")):
            summary_part = summary.filter(pc.equal(summary["trade_direction"], direction_value))
            if summary_part.num_rows:
                target = (
                    population_root
                    / f"entry_year={year}"
                    / f"entry_month={month:02d}"
                    / f"trade_direction={direction_name}"
                )
                data_path = target / "part-00000.parquet"
                atomic_parquet(summary_part, data_path)
                manifest = {
                    "status": "complete",
                    "artifact": "canonical_trade_population",
                    "entry_year": year,
                    "entry_month": month,
                    "trade_direction": direction_name,
                    "row_count": summary_part.num_rows,
                    "source_sha256": binding["summary_sha256"],
                    "source_manifest_sha256": binding["manifest_sha256"],
                    "validation_sha256": sha256_file(validation),
                    "output_sha256": sha256_file(data_path),
                    "timestamp_min_ns": pc.min(summary_part["checkpoint_decision_ns"]).as_py(),
                    "timestamp_max_ns": pc.max(summary_part["checkpoint_decision_ns"]).as_py(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
                atomic_json(manifest, target / "manifest.json")
                total_trades += summary_part.num_rows
            path_direction = paths.filter(pc.equal(paths["trade_direction"], direction_value))
            for prefix in sorted(set(path_direction["trade_id_prefix"].to_pylist())):
                path_part = path_direction.filter(
                    pc.equal(path_direction["trade_id_prefix"], prefix)
                )
                target = (
                    paths_root
                    / f"entry_year={year}"
                    / f"entry_month={month:02d}"
                    / f"trade_direction={direction_name}"
                    / f"trade_id_prefix={prefix}"
                )
                data_path = target / "part-00000.parquet"
                atomic_parquet(path_part, data_path)
                manifest = {
                    "status": "complete",
                    "artifact": "canonical_trade_paths",
                    "entry_year": year,
                    "entry_month": month,
                    "trade_direction": direction_name,
                    "trade_id_prefix": prefix,
                    "row_count": path_part.num_rows,
                    "trade_count": pc.count_distinct(path_part["trade_id"]).as_py(),
                    "source_sha256": binding["path_sha256"],
                    "source_manifest_sha256": binding["manifest_sha256"],
                    "validation_sha256": sha256_file(validation),
                    "output_sha256": sha256_file(data_path),
                    "timestamp_min_ns": pc.min(path_part["timestamp_open_ns"]).as_py(),
                    "timestamp_max_ns": pc.max(path_part["timestamp_close_ns"]).as_py(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
                atomic_json(manifest, target / "manifest.json")
                total_rows += path_part.num_rows
                partitions.append(manifest)
    result = {
        "status": "complete",
        "trade_count": total_trades,
        "path_row_count": total_rows,
        "population_partition_count": len(
            list(population_root.glob("entry_year=*/entry_month=*/trade_direction=*/manifest.json"))
        ),
        "path_partition_count": len(partitions),
        "validation_sha256": sha256_file(validation),
        "source_global_manifest_sha256": global_source_hash,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if total_trades != 5836 or total_rows != 6589582:
        raise RuntimeError(f"canonical count mismatch: {total_trades}, {total_rows}")
    atomic_json(result, output / "canonical_phase_d_manifest.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--validation", required=True)
    args = parser.parse_args()
    print(json.dumps(finalize(Path(args.source), Path(args.output), Path(args.validation)), indent=2))


if __name__ == "__main__":
    main()
