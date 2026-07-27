from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from studies.full_trade_path_builder.implementation.canonical_research_loader import (
    scan_canonical_research_population,
)
from studies.full_trade_path_builder.implementation.consolidate_research_parquets import (
    duplicate_report,
    fingerprint,
    fingerprints_equal,
    normalized_schema,
    Source,
    source_scan,
    validate_schemas,
)


def write(path: Path, rows: list[dict], schema: pa.Schema) -> None:
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema() -> pa.Schema:
    return pa.schema(
        [
            ("instrument_id", pa.string(), False),
            ("checkpoint_decision_ns", pa.int64(), False),
            ("model_id", pa.string(), False),
            ("trade_direction", pa.string(), False),
            ("trade_id", pa.string(), False),
            ("value", pa.float64()),
            ("source_year", pa.int32(), False),
            ("source_month", pa.int8(), False),
            ("source_file", pa.string(), False),
        ]
    )


def rows() -> list[dict]:
    return [
        {
            "instrument_id": "NQ.XCME",
            "checkpoint_decision_ns": 1735689600000000000,
            "model_id": "LONG_MODEL",
            "trade_direction": "LONG",
            "trade_id": "b",
            "value": None,
            "source_year": 2025,
            "source_month": 1,
            "source_file": "b.parquet",
        },
        {
            "instrument_id": "NQ.XCME",
            "checkpoint_decision_ns": 1735689601000000000,
            "model_id": "SHORT_MODEL",
            "trade_direction": "SHORT",
            "trade_id": "a",
            "value": 2.0,
            "source_year": 2025,
            "source_month": 1,
            "source_file": "a.parquet",
        },
    ]


def test_schema_mismatch_detection(tmp_path: Path) -> None:
    one, two = tmp_path / "one.parquet", tmp_path / "two.parquet"
    write(one, rows(), schema())
    pq.write_table(pa.table({"different": [1]}), two)
    with pytest.raises(RuntimeError, match="schema columns/order mismatch"):
        validate_schemas([one, two])


def test_all_null_physical_type_normalizes_only_to_agreed_concrete_type(
    tmp_path: Path,
) -> None:
    null_path, typed_path = tmp_path / "null.parquet", tmp_path / "typed.parquet"
    pq.write_table(pa.table({"id": pa.array([None], type=pa.null())}), null_path)
    pq.write_table(pa.table({"id": pa.array([4], type=pa.int64())}), typed_path)
    assert normalized_schema([null_path, typed_path]).field("id").type == pa.int64()
    incompatible = tmp_path / "string.parquet"
    pq.write_table(pa.table({"id": pa.array(["4"], type=pa.string())}), incompatible)
    with pytest.raises(RuntimeError, match="incompatible non-null types"):
        normalized_schema([typed_path, incompatible])


def test_reconciliation_metadata_duplicates_order_and_source_immutability(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.parquet"
    output = tmp_path / "canonical_trade_summaries_all.parquet"
    write(source, rows(), schema())
    before = digest(source)
    frame = pl.scan_parquet(source)
    duplicate = duplicate_report(frame, ["trade_id"])
    assert duplicate["duplicate_key_count"] == 0
    source_fp = fingerprint(frame, ["trade_id"], ["value"])
    frame.sort(["trade_id", "checkpoint_decision_ns"]).sink_parquet(output)
    result = pl.scan_parquet(output)
    assert fingerprints_equal(
        source_fp, fingerprint(result, ["trade_id"], ["value"])
    )[0]
    collected = result.collect()
    assert collected["trade_id"].to_list() == ["a", "b"]
    assert collected["trade_direction"].to_list() == ["SHORT", "LONG"]
    assert collected["model_id"].to_list() == ["SHORT_MODEL", "LONG_MODEL"]
    assert collected["source_file"].null_count() == 0
    assert collected["value"].null_count() == 1
    assert digest(source) == before


def test_duplicate_detection() -> None:
    frame = pl.DataFrame({"trade_id": ["x", "x"], "value": [1, 2]}).lazy()
    result = duplicate_report(frame, ["trade_id"])
    assert result["conflicting_duplicates"] == 1
    exact = duplicate_report(
        pl.DataFrame({"trade_id": ["x", "x"], "value": [1, 1]}).lazy(),
        ["trade_id"],
    )
    assert exact["exact_duplicates"] == 1


def test_numeric_sum_reconciliation_is_stable_to_float_order() -> None:
    source = {
        "row_count": 3,
        "value__sum": 1.0,
        "null_count_by_column": {"value": 0},
    }
    reordered = {
        "row_count": 3,
        "value__sum": 1.0 + 5e-13,
        "null_count_by_column": {"value": 0},
    }
    assert fingerprints_equal(source, reordered)[0]


def test_partition_year_month_metadata_assignment(tmp_path: Path) -> None:
    partition = tmp_path / "year=2025" / "month=07"
    partition.mkdir(parents=True)
    path = partition / "part.parquet"
    pq.write_table(pa.table({"value": [1]}), path)
    source = Source(
        path=path,
        manifest=partition / "manifest.json",
        year=2025,
        month=7,
        direction="DUAL_MODEL_CHECKPOINT",
        model="DUAL",
        schema_sha256="schema",
        collector_version="collector",
        rows=1,
        sha256=digest(path),
    )
    row = source_scan([source]).select("source_year", "source_month").collect().row(0)
    assert row == (2025, 7)


def test_loader_filters_date_direction_and_model(tmp_path: Path) -> None:
    path = tmp_path / "canonical_trade_summaries_all.parquet"
    write(path, rows(), schema())
    result = scan_canonical_research_population(
        str(path),
        start="2025-01-01T00:00:00Z",
        end="2025-01-01T00:00:02Z",
        model_ids=["SHORT_MODEL"],
        directions=["SHORT"],
    ).collect()
    assert result["trade_id"].to_list() == ["a"]


def test_completion_coverage_expression() -> None:
    frame = pl.DataFrame(
        {
            "trade_id": ["a", "a", "b"],
            "is_final_path_bar": [False, True, True],
        }
    ).lazy()
    result = frame.select(
        pl.col("trade_id").n_unique().alias("unique_trade_count"),
        pl.col("trade_id")
        .filter(pl.col("is_final_path_bar"))
        .n_unique()
        .alias("trades_with_final_path_row"),
        pl.col("is_final_path_bar").sum().alias("final_path_row_count"),
    ).collect().row(0)
    assert result == (2, 2, 2)
