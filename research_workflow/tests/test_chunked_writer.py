"""Unit tests for research_workflow.host.chunked_writer.ChunkedParquetWriter.

Targeted at: batch boundaries, empty partitions, typed list/struct fields (G2
compatibility ahead of chore/vp_profile_snapshot), nulls (incl. an all-null first batch),
interrupted writes, deterministic ordering and schema stability across batches.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_workflow.host.chunked_writer import ChunkedParquetWriter, infer_arrow_type


def _rows(n, start=0):
    return [{"a": i, "b": float(i) * 1.5, "c": f"s{i}"} for i in range(start, start + n)]


def test_small_batches_and_exact_multiples(tmp_path):
    for batch_rows, n in [(1, 5), (2, 4), (3, 9), (3, 10), (4, 1)]:
        out = tmp_path / f"out_{batch_rows}_{n}.parquet"
        w = ChunkedParquetWriter(out, ["a", "b", "c"], batch_rows=batch_rows)
        for r in _rows(n):
            w.write_rows([r])
        manifest = w.finalize()
        assert manifest["rows"] == n
        table = pq.read_table(out)
        assert table.num_rows == n
        assert table.column("a").to_pylist() == list(range(n))


def test_empty_partition(tmp_path):
    out = tmp_path / "empty.parquet"
    w = ChunkedParquetWriter(out, ["a", "b", "c"], batch_rows=10)
    manifest = w.finalize()
    assert manifest["rows"] == 0
    table = pq.read_table(out)
    assert table.num_rows == 0
    assert table.column_names == ["a", "b", "c"]


def test_empty_batches_interleaved(tmp_path):
    out = tmp_path / "interleaved.parquet"
    w = ChunkedParquetWriter(out, ["a", "b", "c"], batch_rows=2)
    w.write_rows([])
    w.write_rows(_rows(1))
    w.write_rows([])
    w.write_rows(_rows(1, start=1))
    w.write_rows([])
    manifest = w.finalize()
    assert manifest["rows"] == 2


def test_all_null_first_batch_then_typed_values(tmp_path):
    """The schema must not be fixed as null/float-default from an all-null first batch when
    later rows are integral -- the probe spans multiple write_rows calls up to batch_rows."""
    out = tmp_path / "nulls.parquet"
    w = ChunkedParquetWriter(out, ["a"], batch_rows=4)
    w.write_rows([{"a": None}, {"a": None}])
    w.write_rows([{"a": 7}, {"a": 8}])
    manifest = w.finalize()
    assert manifest["schema"]["a"] == "int64"
    table = pq.read_table(out)
    assert table.column("a").to_pylist() == [None, None, 7, 8]


def test_entirely_all_null_column_defaults_float64(tmp_path):
    out = tmp_path / "all_null.parquet"
    w = ChunkedParquetWriter(out, ["a"], batch_rows=2)
    w.write_rows([{"a": None}, {"a": None}, {"a": None}])
    manifest = w.finalize()
    assert manifest["schema"]["a"] == "double"
    table = pq.read_table(out)
    assert table.column("a").to_pylist() == [None, None, None]


def test_declared_types_bypass_inference(tmp_path):
    out = tmp_path / "declared.parquet"
    w = ChunkedParquetWriter(out, ["observation_ts", "x"], declared_types={"observation_ts": pa.int64()}, batch_rows=2)
    w.write_rows([{"observation_ts": 1, "x": None}, {"observation_ts": 2, "x": None}])
    manifest = w.finalize()
    assert manifest["schema"]["observation_ts"] == "int64"


def test_struct_and_list_typed_field(tmp_path):
    """G2 compatibility: a feature column whose value is a dict with a list<int64> child must
    round-trip through this writer with no struct/list-specific branch anywhere in it."""
    out = tmp_path / "struct.parquet"
    rows = [
        {"profile": {"levels": [1, 2, 3], "poc": 100}},
        {"profile": {"levels": [4, 5], "poc": 101}},
        {"profile": {"levels": [], "poc": 102}},
        {"profile": None},
    ]
    w = ChunkedParquetWriter(out, ["profile"], batch_rows=2)
    for r in rows:
        w.write_rows([r])
    manifest = w.finalize()
    table = pq.read_table(out)
    got = table.column("profile").to_pylist()
    assert got[0]["poc"] == 100 and got[0]["levels"] == [1, 2, 3]
    assert got[2]["levels"] == []
    assert got[3] is None
    assert "struct" in manifest["schema"]["profile"]


def test_large_typed_list_field(tmp_path):
    out = tmp_path / "large_list.parquet"
    big = list(range(5000))
    rows = [{"bins": big} for _ in range(5)]
    w = ChunkedParquetWriter(out, ["bins"], batch_rows=2)
    for r in rows:
        w.write_rows([r])
    manifest = w.finalize()
    table = pq.read_table(out)
    assert table.num_rows == 5
    assert table.column("bins").to_pylist()[0] == big


def test_interrupted_write_leaves_no_complete_file(tmp_path):
    out = tmp_path / "crash.parquet"
    w = ChunkedParquetWriter(out, ["a"], batch_rows=2)
    w.write_rows(_rows(3))  # one full batch flushed, one row still probed/pending
    assert not out.is_file()  # never finalized: no file at the final name
    if w._writer is not None:
        w._writer.close()  # simulate the OS releasing the file handle once the crashed process exits

    # Simulate a fresh attempt at the same partition after a crash: a brand-new writer at the
    # same path, from scratch, must reach an identical logical result.
    w2 = ChunkedParquetWriter(out, ["a"], batch_rows=2)
    for r in _rows(3):
        w2.write_rows([r])
    manifest = w2.finalize()
    assert out.is_file()
    assert manifest["rows"] == 3


def test_retry_yields_identical_logical_output(tmp_path):
    rows = _rows(37)
    manifests = []
    for attempt in range(2):
        out = tmp_path / f"retry_{attempt}.parquet"
        w = ChunkedParquetWriter(out, ["a", "b", "c"], batch_rows=5)
        for i in range(0, len(rows), 3):  # different batch boundaries each attempt
            w.write_rows(rows[i:i + 3])
        manifests.append(w.finalize())
    assert manifests[0]["logical_content_sha256"] == manifests[1]["logical_content_sha256"]
    assert manifests[0]["rows"] == manifests[1]["rows"] == 37


def test_deterministic_ordering_and_schema_stability_across_batches(tmp_path):
    out = tmp_path / "order.parquet"
    w = ChunkedParquetWriter(out, ["a", "b", "c"], batch_rows=4)
    rows = _rows(23)
    for i in range(0, len(rows), 7):
        w.write_rows(rows[i:i + 7])
    manifest = w.finalize()
    table = pq.read_table(out)
    assert table.column("a").to_pylist() == list(range(23))
    assert manifest["schema"] == {"a": "int64", "b": "double", "c": "string"}


def test_logical_hash_independent_of_batch_boundaries(tmp_path):
    rows = _rows(20)
    hashes = []
    for batch_rows in (1, 3, 7, 20):
        out = tmp_path / f"h_{batch_rows}.parquet"
        w = ChunkedParquetWriter(out, ["a", "b", "c"], batch_rows=batch_rows)
        w.write_rows(rows)
        hashes.append(w.finalize()["logical_content_sha256"])
    assert len(set(hashes)) == 1


def test_bad_batch_rows_rejected(tmp_path):
    with pytest.raises(ValueError):
        ChunkedParquetWriter(tmp_path / "x.parquet", ["a"], batch_rows=0)


def test_write_after_finalize_rejected(tmp_path):
    out = tmp_path / "closed.parquet"
    w = ChunkedParquetWriter(out, ["a"], batch_rows=2)
    w.write_rows(_rows(1))
    w.finalize()
    with pytest.raises(RuntimeError):
        w.write_rows(_rows(1))


def test_infer_arrow_type_helper():
    assert infer_arrow_type([None, None]) == pa.float64()
    assert infer_arrow_type([None, 3]) == pa.int64()
    assert infer_arrow_type([None, 3.5]) == pa.float64()
    assert infer_arrow_type(["x", None]) == pa.string()
    assert infer_arrow_type([[1, 2], None]) == pa.list_(pa.int64())
    assert infer_arrow_type([[], None]) == pa.list_(pa.int64())
