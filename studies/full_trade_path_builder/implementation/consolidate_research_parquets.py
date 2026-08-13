"""Consolidate accepted canonical Parquet partitions without semantic changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from .run_phase_a_collect import ROOT, atomic_json, sha256_file


BASE = ROOT / "studies/full_trade_path_builder"


@dataclass(frozen=True)
class Source:
    path: Path
    manifest: Path
    year: int
    month: int
    direction: str
    model: str
    schema_sha256: str
    collector_version: str
    rows: int
    sha256: str


def schema_hash(path: Path) -> str:
    payload = pq.ParquetFile(path).schema_arrow.to_string(
        show_field_metadata=True,
        show_schema_metadata=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def normalized_schema(paths: Iterable[Path]) -> pa.Schema:
    paths = list(paths)
    if not paths:
        raise RuntimeError("no source parquet files discovered")
    schemas = [pq.ParquetFile(path).schema_arrow for path in paths]
    expected_names = schemas[0].names
    expected_metadata = schemas[0].metadata
    for path, actual in zip(paths[1:], schemas[1:]):
        if actual.names != expected_names:
            missing = [name for name in expected_names if name not in actual.names]
            extra = [name for name in actual.names if name not in expected_names]
            raise RuntimeError(
                f"schema columns/order mismatch: {path}; missing={missing}; extra={extra}"
            )
        if actual.metadata != expected_metadata:
            raise RuntimeError(f"schema metadata mismatch: {path}")
    fields = []
    for index, name in enumerate(expected_names):
        candidates = [schema.field(index) for schema in schemas]
        non_null_types = {field.type for field in candidates if not pa.types.is_null(field.type)}
        if len(non_null_types) > 1:
            raise RuntimeError(
                f"incompatible non-null types for {name}: "
                f"{sorted(map(str, non_null_types))}"
            )
        if len({field.nullable for field in candidates}) > 1:
            raise RuntimeError(f"nullability mismatch for {name}")
        if len({canonical_hash(field.metadata) for field in candidates}) > 1:
            raise RuntimeError(f"field metadata mismatch for {name}")
        target_type = next(iter(non_null_types), pa.null())
        fields.append(
            pa.field(
                name,
                target_type,
                nullable=candidates[0].nullable,
                metadata=candidates[0].metadata,
            )
        )
    return pa.schema(fields, metadata=expected_metadata)


def validate_schemas(paths: Iterable[Path]) -> str:
    schema = normalized_schema(paths)
    return hashlib.sha256(
        schema.to_string(
            show_field_metadata=True,
            show_schema_metadata=True,
        ).encode()
    ).hexdigest()


def discover_observations() -> list[Source]:
    paths = sorted(
        (BASE / "_work/phase_b_monthly").glob(
            "year=*/month=*/canonical_model_scores.parquet"
        )
    )
    common_schema = validate_schemas(paths)
    result = []
    for path in paths:
        manifest_path = path.with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text())
        digest = sha256_file(path)
        if manifest.get("status") != "complete":
            raise RuntimeError(f"incomplete observation source: {path}")
        if digest != manifest.get("canonical_model_scores_sha256"):
            raise RuntimeError(f"observation source hash mismatch: {path}")
        result.append(
            Source(
                path,
                manifest_path,
                int(path.parent.parent.name.split("=")[1]),
                int(path.parent.name.split("=")[1]),
                "DUAL_MODEL_CHECKPOINT",
                "BULLISH_STRICT_top25_gbt_v2+LONG_STRICT_top25_gbt_v2",
                common_schema,
                canonical_hash(manifest["runtime_identity"]),
                pq.ParquetFile(path).metadata.num_rows,
                digest,
            )
        )
    return result


def discover_canonical(root: Path, grain: str) -> list[Source]:
    paths = sorted(root.glob("entry_year=*/entry_month=*/trade_direction=*/**/part-00000.parquet"))
    common_schema = validate_schemas(paths)
    result = []
    for path in paths:
        manifest_path = path.with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text())
        digest = sha256_file(path)
        if manifest.get("status") != "complete" or manifest.get("artifact") != grain:
            raise RuntimeError(f"incompatible canonical source: {path}")
        if digest != manifest.get("output_sha256"):
            raise RuntimeError(f"canonical source hash mismatch: {path}")
        direction = manifest["trade_direction"]
        model = (
            "LONG_STRICT_top25_gbt_v2"
            if direction == "LONG"
            else "BULLISH_STRICT_top25_gbt_v2"
        )
        result.append(
            Source(
                path,
                manifest_path,
                int(manifest["entry_year"]),
                int(manifest["entry_month"]),
                direction,
                model,
                common_schema,
                manifest["validation_sha256"],
                int(manifest["row_count"]),
                digest,
            )
        )
    return result


def source_scan(sources: list[Source]) -> pl.LazyFrame:
    schema = pl.Schema(normalized_schema(source.path for source in sources))
    return pl.scan_parquet(
        [str(source.path) for source in sources],
        include_file_paths="source_file",
        low_memory=True,
        schema=schema,
        cast_options=pl.ScanCastOptions(
            integer_cast="forbid",
            float_cast="forbid",
            datetime_cast="forbid",
            categorical_to_string="forbid",
        ),
    ).with_columns(
        pl.col("source_file")
        .str.extract(r"(?:study_|entry_)?year=(\d{4})", 1)
        .cast(pl.Int32)
        .alias("source_year"),
        pl.col("source_file")
        .str.extract(r"(?:study_|entry_)?month=(\d{2})", 1)
        .cast(pl.Int8)
        .alias("source_month"),
    )


def duplicate_report(frame: pl.LazyFrame, keys: list[str]) -> dict:
    duplicate_keys = (
        frame.group_by(keys)
        .len()
        .filter(pl.col("len") > 1)
    )
    duplicates = duplicate_keys.select(
        pl.len().alias("duplicate_key_count"), pl.col("len").sum().alias("rows")
    ).collect(engine="streaming").row(0, named=True)
    duplicate_key_count = int(duplicates["duplicate_key_count"] or 0)
    exact = 0
    conflicting = 0
    if duplicate_key_count:
        classified = (
            frame.join(duplicate_keys.select(keys), on=keys, how="inner")
            .with_columns(pl.struct(pl.all()).hash(seed=20260726).alias("__row_hash"))
            .group_by(keys)
            .agg(pl.col("__row_hash").n_unique().alias("__distinct_rows"))
            .select(
                (pl.col("__distinct_rows") == 1).sum().alias("exact"),
                (pl.col("__distinct_rows") > 1).sum().alias("conflicting"),
            )
            .collect(engine="streaming")
            .row(0, named=True)
        )
        exact = int(classified["exact"])
        conflicting = int(classified["conflicting"])
    return {
        "keys": keys,
        "duplicate_key_count": duplicate_key_count,
        "duplicate_rows": int(duplicates["rows"] or 0),
        "exact_duplicates": exact,
        "conflicting_duplicates": conflicting,
        "expected_multi_model_observations": 0,
    }


def fingerprint(frame: pl.LazyFrame, keys: list[str], numeric: list[str]) -> dict:
    schema = frame.collect_schema()
    nulls = (
        frame.select([pl.col(name).null_count().alias(name) for name in schema.names()])
        .collect(engine="streaming")
        .row(0, named=True)
    )
    expressions = [pl.len().alias("row_count")]
    for name in numeric:
        if name in schema:
            expressions.extend(
                [
                    pl.col(name).min().alias(f"{name}__min"),
                    pl.col(name).max().alias(f"{name}__max"),
                    pl.col(name).sum().alias(f"{name}__sum"),
                ]
            )
    stats = frame.select(expressions).collect(engine="streaming").row(0, named=True)
    key_hash = (
        frame.select(
            pl.concat_str([pl.col(key).cast(pl.String) for key in keys], separator="|")
            .hash(seed=20260726)
            .sum()
            .alias("immutable_key_hash_sum_u64")
        )
        .collect(engine="streaming")
        .item()
    )
    return {
        **stats,
        "null_count_by_column": nulls,
        "immutable_key_hash_sum_u64": int(key_hash),
    }


def fingerprints_equal(source: dict, result: dict) -> tuple[bool, list[dict]]:
    differences = []
    all_keys = sorted(set(source) | set(result))
    for key in all_keys:
        left, right = source.get(key), result.get(key)
        if key.endswith("__sum") and left is not None and right is not None:
            equal = math.isclose(
                float(left),
                float(right),
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
        else:
            equal = left == right
        if not equal:
            differences.append({"field": key, "source": left, "result": right})
    return not differences, differences


def atomic_sink(frame: pl.LazyFrame, path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    if tmp.exists():
        tmp.unlink()
    frame.sink_parquet(
        tmp,
        compression=config["compression"],
        compression_level=config["compression_level"],
        row_group_size=config["row_group_size"],
        maintain_order=True,
        mkdir=True,
    )
    os.replace(tmp, path)


def coverage(
    frame: pl.LazyFrame,
    year: str,
    month: str,
    model: str,
    direction: str,
    timestamp: str,
    regime: str | None,
    observation: str | None,
    trade: str | None,
) -> list[dict]:
    dimensions = [year, month, model, direction]
    aggregations = [
        pl.len().alias("row_count"),
        pl.col(timestamp).min().alias("minimum_timestamp"),
        pl.col(timestamp).max().alias("maximum_timestamp"),
    ]
    for column, alias in (
        (regime, "unique_regime_count"),
        (observation, "unique_observation_count"),
        (trade, "unique_trade_count"),
    ):
        aggregations.append(
            pl.lit(None).alias(alias)
            if column is None
            else pl.col(column).n_unique().alias(alias)
        )
    return (
        frame.group_by(dimensions)
        .agg(aggregations)
        .sort(dimensions)
        .collect(engine="streaming")
        .to_dicts()
    )


def inventory_rows(sources: list[Source], root: Path) -> list[dict]:
    return [
        {
            "year": source.year,
            "month": source.month,
            "direction_model": f"{source.direction}/{source.model}",
            "schema_version": source.schema_sha256,
            "collector_version": source.collector_version,
            "row_count": source.rows,
            "source_file": str(source.path.relative_to(root)),
            "source_sha256": source.sha256,
            "manifest_sha256": sha256_file(source.manifest),
        }
        for source in sources
    ]


def expected_group_counts(sources: list[Source]) -> list[dict]:
    counts: dict[tuple[int, int, str, str], int] = {}
    for source in sources:
        key = (source.year, source.month, source.model, source.direction)
        counts[key] = counts.get(key, 0) + source.rows
    return [
        {
            "source_year": key[0],
            "source_month": key[1],
            "model_id": key[2],
            "trade_direction": key[3],
            "row_count": count,
        }
        for key, count in sorted(counts.items())
    ]


def coverage_group_counts(rows: list[dict], direction_field: str) -> list[dict]:
    return [
        {
            "source_year": row["source_year"],
            "source_month": row["source_month"],
            "model_id": row["model_id"],
            "trade_direction": row[direction_field],
            "row_count": row["row_count"],
        }
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--progress-file", required=True)
    args = parser.parse_args()
    output = Path(args.output_root)
    progress = Path(args.progress_file)
    config = yaml.safe_load((BASE / "config/consolidation.yaml").read_text())

    observations = discover_observations()
    summaries = discover_canonical(BASE / "canonical_trade_population", "canonical_trade_population")
    paths = discover_canonical(BASE / "canonical_trade_paths", "canonical_trade_paths")
    if len(observations) != 60 or len(summaries) != 120 or len(paths) != 5307:
        raise RuntimeError(
            f"unexpected source counts: {len(observations)}, {len(summaries)}, {len(paths)}"
        )
    all_sources = observations + summaries + paths
    empty_sources = [str(source.path) for source in all_sources if source.rows == 0]
    if empty_sources:
        raise RuntimeError(f"empty accepted source files: {empty_sources[:5]}")
    before_hashes = {str(source.path): source.sha256 for source in all_sources}
    inventory = {
        "status": "accepted",
        "source_counts": {
            "observations": len(observations),
            "trade_summaries": len(summaries),
            "trade_paths": len(paths),
        },
        "accepted": {
            "observations": inventory_rows(observations, ROOT),
            "trade_summaries": inventory_rows(summaries, ROOT),
            "trade_paths": inventory_rows(paths, ROOT),
        },
        "schema_normalization": (
            "Physical Arrow null types are normalized only when all non-null "
            "partitions agree on one concrete type. Conflicting concrete types, "
            "column order, nullability, or metadata fail closed."
        ),
        "excluded": [],
        "empty_files": [],
    }
    atomic_json(inventory, output / "SOURCE_INVENTORY.json")

    obs = source_scan(observations).with_columns(
        pl.lit("DUAL_MODEL_CHECKPOINT").alias("trade_direction"),
        pl.lit("BULLISH_STRICT_top25_gbt_v2+LONG_STRICT_top25_gbt_v2").alias("model_id"),
    )
    summary = source_scan(summaries).with_columns(
        pl.col("entry_model_id").alias("model_id")
    )
    mapping = summary.select("trade_id", "model_id", "trade_direction").unique()
    path = (
        source_scan(paths)
        .join(mapping, on="trade_id", how="left", suffix="_summary", validate="m:1")
        .with_columns(
            pl.when(pl.col("trade_direction") == pl.col("trade_direction_summary"))
            .then(pl.col("trade_direction"))
            .otherwise(None)
            .alias("trade_direction_validated")
        )
    )
    invalid_mapping = (
        path.filter(
            pl.col("model_id").is_null()
            | pl.col("trade_direction_validated").is_null()
        )
        .select(pl.len())
        .collect(engine="streaming")
        .item()
    )
    if invalid_mapping:
        raise RuntimeError(f"{invalid_mapping} path rows lack a valid summary model mapping")
    path = path.drop("trade_direction_summary", "trade_direction").rename(
        {"trade_direction_validated": "trade_direction"}
    )

    datasets = {
        "observations": {
            "sources": observations,
            "frame": obs,
            "sort": config["sort_columns"]["observations"],
            "keys": config["duplicate_keys"]["observations"],
            "numeric": [
                "checkpoint_reference_price",
                "atr_at_checkpoint",
                "bullish_probability",
                "bearish_probability",
            ],
            "output": output / config["outputs"]["observations"],
            "coverage": (
                "source_year",
                "source_month",
                "model_id",
                "trade_direction",
                "checkpoint_decision_ns",
                "regime_start_ns",
                None,
                None,
            ),
        },
        "trade_summaries": {
            "sources": summaries,
            "frame": summary,
            "sort": config["sort_columns"]["trade_summaries"],
            "keys": config["duplicate_keys"]["trade_summaries"],
            "numeric": [
                "checkpoint_reference_price",
                "atr_at_entry",
                "entry_probability",
                "fallback_exit_mark_return_atr",
                "full_trade_mfe_atr",
                "full_trade_mae_atr",
            ],
            "output": output / config["outputs"]["trade_summaries"],
            "coverage": (
                "source_year",
                "source_month",
                "model_id",
                "trade_direction_name",
                "checkpoint_decision_ns",
                "regime_start_ns",
                None,
                "trade_id",
            ),
        },
        "trade_paths": {
            "sources": paths,
            "frame": path,
            "sort": config["sort_columns"]["trade_paths"],
            "keys": config["duplicate_keys"]["trade_paths"],
            "numeric": [
                "open",
                "high",
                "low",
                "close",
                "running_mfe_atr",
                "running_mae_atr",
            ],
            "output": output / config["outputs"]["trade_paths"],
            "coverage": (
                "source_year",
                "source_month",
                "model_id",
                "trade_direction_name",
                "timestamp_close_ns",
                None,
                None,
                "trade_id",
            ),
        },
    }

    report = {
        "status": "building",
        "config_sha256": sha256_file(BASE / "config/consolidation.yaml"),
        "sort_columns": {},
        "datasets": {},
        "annual_files_created": False,
        "annual_files_reason": (
            "Not created: lazy loader filters the primary artifacts, and annual "
            "files would substantially duplicate approximately 2.6 GiB."
        ),
    }
    for index, (name, item) in enumerate(datasets.items(), 1):
        duplicates = duplicate_report(item["frame"], item["keys"])
        if duplicates["duplicate_key_count"]:
            raise RuntimeError(
                f"{name} contains semantic-key duplicates: "
                f"exact={duplicates['exact_duplicates']} "
                f"conflicting={duplicates['conflicting_duplicates']}"
            )
        source_fp = fingerprint(item["frame"], item["keys"], item["numeric"])
        source_coverage = coverage(item["frame"], *item["coverage"])
        sorted_frame = item["frame"].sort(item["sort"], maintain_order=True)
        atomic_sink(sorted_frame, item["output"], config)
        result_scan = pl.scan_parquet(item["output"], low_memory=True)
        result_fp = fingerprint(result_scan, item["keys"], item["numeric"])
        fingerprints_match, fingerprint_differences = fingerprints_equal(
            source_fp, result_fp
        )
        if not fingerprints_match:
            raise RuntimeError(
                f"{name} fingerprint mismatch after consolidation: "
                f"{fingerprint_differences[:5]}"
            )
        result_coverage = coverage(result_scan, *item["coverage"])
        if source_coverage != result_coverage:
            raise RuntimeError(f"{name} coverage changed after consolidation")
        direction_field = item["coverage"][3]
        expected_groups = expected_group_counts(item["sources"])
        actual_groups = coverage_group_counts(result_coverage, direction_field)
        if expected_groups != actual_groups:
            raise RuntimeError(f"{name} year/month/model/direction reconciliation failed")
        report["sort_columns"][name] = item["sort"]
        report["datasets"][name] = {
            "source_file_count": len(item["sources"]),
            "source_row_count": sum(source.rows for source in item["sources"]),
            "combined_row_count": result_fp["row_count"],
            "duplicate_report": duplicates,
            "source_fingerprint": source_fp,
            "combined_fingerprint": result_fp,
            "fingerprint_reconciliation": {
                "status": "PASS",
                "floating_sum_tolerance": {
                    "relative": 1e-12,
                    "absolute": 1e-9,
                },
            },
            "coverage": result_coverage,
            "source_group_counts": expected_groups,
            "group_reconciliation": "PASS",
            "output_path": str(item["output"]),
            "output_sha256": sha256_file(item["output"]),
            "compressed_bytes": item["output"].stat().st_size,
        }
        if name == "trade_summaries":
            report["datasets"][name]["path_completion_coverage"] = (
                result_scan.group_by("path_is_complete", "is_right_censored")
                .agg(pl.len().alias("trade_count"))
                .sort("path_is_complete", "is_right_censored")
                .collect(engine="streaming")
                .to_dicts()
            )
        if name == "trade_paths":
            final_coverage = result_scan.select(
                pl.col("trade_id").n_unique().alias("unique_trade_count"),
                pl.col("trade_id")
                .filter(pl.col("is_final_path_bar"))
                .n_unique()
                .alias("trades_with_final_path_row"),
                pl.col("is_final_path_bar").sum().alias("final_path_row_count"),
            ).collect(engine="streaming").row(0, named=True)
            final_coverage["trades_missing_final_path_row"] = (
                final_coverage["unique_trade_count"]
                - final_coverage["trades_with_final_path_row"]
            )
            report["datasets"][name]["final_path_coverage"] = final_coverage
        atomic_json(
            {"status": "building", "datasets_completed": index, "last_dataset": name},
            progress,
        )

    after_hashes = {str(source.path): sha256_file(source.path) for source in all_sources}
    changed = [path for path, digest in before_hashes.items() if after_hashes[path] != digest]
    if changed:
        raise RuntimeError(f"source files changed during consolidation: {changed[:5]}")
    report["source_files_unchanged"] = True
    report["status"] = "PASS"
    report["excluded_files"] = []
    intended_months = {(year, month) for year in range(2021, 2026) for month in range(1, 13)}
    report["missing_months"] = {
        name: sorted(
            [f"{year}-{month:02d}" for year, month in intended_months - {(s.year, s.month) for s in item["sources"]}]
        )
        for name, item in datasets.items()
    }
    report["missing_sides_or_models"] = {
        name: [
            f"{year}-{month:02d}:{direction}/{model}"
            for year, month in sorted(intended_months)
            for direction, model in (
                (
                    [("DUAL_MODEL_CHECKPOINT", "BULLISH_STRICT_top25_gbt_v2+LONG_STRICT_top25_gbt_v2")]
                    if name == "observations"
                    else [
                        ("LONG", "LONG_STRICT_top25_gbt_v2"),
                        ("SHORT", "BULLISH_STRICT_top25_gbt_v2"),
                    ]
                )
            )
            if not any(
                source.year == year
                and source.month == month
                and source.direction == direction
                and source.model == model
                for source in item["sources"]
            )
        ]
        for name, item in datasets.items()
    }
    report["empty_files"] = []
    report["source_overlap_note"] = (
        "Path partitions overlap in wall-clock time by design for simultaneous "
        "trades; semantic keys remain unique."
    )
    report["timestamp_gap_assessment"] = (
        "No consolidation-created gaps: source and output coverage ranges and "
        "group counts match exactly. Overnight/session gaps and upstream explicit "
        "missing-dispatch rows retain their accepted source semantics."
    )
    atomic_json(report, output / "RECONCILIATION_REPORT.json")
    atomic_json(report, progress)


if __name__ == "__main__":
    main()
