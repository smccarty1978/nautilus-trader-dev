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

from research_workflow.host.chunked_writer import (
    ChunkedParquetWriter, infer_arrow_type, dtype_tag_to_arrow, field_types_to_arrow,
)


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


def test_dtype_tag_to_arrow():
    assert dtype_tag_to_arrow("int64") == pa.int64()
    assert dtype_tag_to_arrow("float64") == pa.float64()
    assert dtype_tag_to_arrow("bool") == pa.bool_()
    assert dtype_tag_to_arrow("str") == pa.string()
    assert dtype_tag_to_arrow("int64[]") == pa.list_(pa.int64())
    assert dtype_tag_to_arrow("int64[]?") == pa.list_(pa.int64())  # nullable marker ignored for type
    with pytest.raises(TypeError):
        dtype_tag_to_arrow("bogus")


def test_field_types_to_arrow_struct():
    # Mirrors BaseBinding.FIELD_TYPES["profile"] shape (chore/vp_profile_snapshot), exercised
    # here against the generic synthetic schema (no VP-specific branch in the writer).
    spec = {"kind": "struct", "schema": {"poc": "float64", "levels": "int64[]", "label": "str"}}
    t = field_types_to_arrow(spec)
    assert pa.types.is_struct(t)
    assert t.field("poc").type == pa.float64()
    assert t.field("levels").type == pa.list_(pa.int64())
    assert t.field("label").type == pa.string()
    with pytest.raises(TypeError):
        field_types_to_arrow({"kind": "unknown_kind"})


def test_declared_type_locks_struct_even_when_probe_is_all_null(tmp_path):
    """Req A: a struct/list column that is null for the whole probe must NOT silently
    default to float64 when the caller declares its real type -- the real failure mode this
    was built for (a rolling tracker's profile struct, null for the first ~1440 minutes after
    a block start)."""
    out = tmp_path / "declared_struct.parquet"
    declared = {"profile": field_types_to_arrow({"kind": "struct", "schema": {"poc": "float64", "levels": "int64[]"}})}
    w = ChunkedParquetWriter(out, ["profile"], declared_types=declared, batch_rows=2)
    w.write_rows([{"profile": None}, {"profile": None}])  # whole probe null -- would default float64 if undeclared
    w.write_rows([{"profile": {"poc": 101.5, "levels": [1, 2, 3]}}])
    manifest = w.finalize()
    assert "struct" in manifest["schema"]["profile"]
    table = pq.read_table(out)
    got = table.column("profile").to_pylist()
    assert got[0] is None and got[1] is None
    assert got[2]["poc"] == 101.5 and got[2]["levels"] == [1, 2, 3]


def test_declared_metadata_types_reads_tracker_field_types(monkeypatch):
    """Req A wiring: a features.metadata column whose ref resolves to a tracker field declared
    in that tracker's BaseBinding.FIELD_TYPES gets the DECLARED Arrow type, not probe-based
    inference -- generic over whatever class the plan's tracker.implementation names (no VP
    branch here; a fake tracker class stands in for the real one)."""
    from research_workflow.host import strategy as strategy_mod

    class _FakeTrackerBinding:
        FIELD_TYPES = {"profile": {"kind": "struct", "schema": {"poc": "float64", "levels": "int64[]"}}}

    monkeypatch.setattr(strategy_mod, "_load", lambda dotted: _FakeTrackerBinding)
    plan = {
        "trackers": [{"id": "vp120", "implementation": "fake.module.FakeBinding"}],
        "columns": {"metadata": [
            {"column": "vp120_profile", "ref": "vp120.profile"},
            {"column": "vp120_undeclared", "ref": "vp120.not_in_field_types"},
            {"column": "orphan_col", "ref": "no_such_tracker.field"},
        ]},
    }
    out = strategy_mod.declared_metadata_types(plan)
    assert set(out.keys()) == {"vp120_profile"}
    assert pa.types.is_struct(out["vp120_profile"])
    assert out["vp120_profile"].field("poc").type == pa.float64()


def test_type_mismatch_fails_closed_before_writing(tmp_path):
    """A later batch carrying a value incompatible with the already-fixed type must raise a
    named, typed error BEFORE any byte of that batch is written -- never silently coerced,
    never partially written."""
    out = tmp_path / "mismatch.parquet"
    w = ChunkedParquetWriter(out, ["a"], declared_types={"a": pa.int64()}, batch_rows=2)
    w.write_rows([{"a": 1}, {"a": 2}])  # fixes + flushes first batch fine
    with pytest.raises(TypeError, match="CHUNKED_WRITER_TYPE_MISMATCH"):
        w.write_rows([{"a": {"unexpected": "struct"}}])
    assert w.rows_written == 2  # the bad batch never landed
    w._writer.close()
