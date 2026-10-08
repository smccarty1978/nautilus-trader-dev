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
    estimate_row_bytes, estimate_value_bytes, sha256_file, recompute_logical_content_sha256,
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


def _wide_row(i, n_lists=9, list_len=200):
    """A row shaped like the real volume-profile case: several list<int64> fields."""
    return {"a": i, "b": float(i), "c": "x",
            **{f"lst{k}": list(range(i, i + list_len)) for k in range(n_lists)}}


def test_wide_rows_flush_on_bytes_before_batch_rows(tmp_path):
    """A wide row makes the ROW threshold alone unsafe (see module docstring); the BYTE
    threshold must cut a batch well before batch_rows is reached."""
    out = tmp_path / "wide.parquet"
    cols = ["a", "b", "c"] + [f"lst{k}" for k in range(9)]
    # Each row's estimated size is large; batch_rows is deliberately huge so only the byte
    # threshold can be the thing that triggers a flush.
    w = ChunkedParquetWriter(out, cols, batch_rows=1_000_000, batch_bytes=50_000)
    for i in range(50):
        w.write_rows([_wide_row(i)])
    assert w.batches_written >= 2  # byte threshold forced more than one physical batch
    manifest = w.finalize()
    assert manifest["rows"] == 50
    assert manifest["batch_bytes"] == 50_000
    table = pq.read_table(out)
    assert table.num_rows == 50


def test_byte_threshold_logical_output_identical_to_unchunked(tmp_path):
    """Byte-threshold chunking must not change row content, order, or count -- only where
    physical batch boundaries fall."""
    cols = ["a", "b", "c"] + [f"lst{k}" for k in range(9)]
    rows = [_wide_row(i) for i in range(37)]

    out_bytes = tmp_path / "by_bytes.parquet"
    w1 = ChunkedParquetWriter(out_bytes, cols, batch_rows=1_000_000, batch_bytes=20_000)
    for r in rows:
        w1.write_rows([r])
    m1 = w1.finalize()

    out_unchunked = tmp_path / "unchunked.parquet"
    w2 = ChunkedParquetWriter(out_unchunked, cols, batch_rows=1_000_000, batch_bytes=0)
    w2.write_rows(rows)
    m2 = w2.finalize()

    assert m1["logical_content_sha256"] == m2["logical_content_sha256"]
    t1, t2 = pq.read_table(out_bytes), pq.read_table(out_unchunked)
    assert t1.to_pylist() == t2.to_pylist()


def test_byte_threshold_deterministic_across_repeated_runs(tmp_path):
    cols = ["a", "b", "c"] + [f"lst{k}" for k in range(9)]
    rows = [_wide_row(i) for i in range(23)]
    hashes = []
    for attempt in range(2):
        out = tmp_path / f"det_{attempt}.parquet"
        w = ChunkedParquetWriter(out, cols, batch_rows=1_000_000, batch_bytes=15_000)
        for r in rows:
            w.write_rows([r])
        hashes.append(w.finalize()["logical_content_sha256"])
    assert hashes[0] == hashes[1]


def test_estimate_value_bytes_recurses_struct_and_list():
    scalar = estimate_value_bytes(5)
    assert scalar > 0
    nested = estimate_value_bytes({"weights_fp": list(range(100)), "poc": 1.5})
    assert nested > 100 * estimate_value_bytes(1)  # dominated by the nested list


def test_estimate_row_bytes_only_counts_declared_columns():
    row = {"a": 1, "b": 2.0, "ignored": "x" * 1000}
    assert estimate_row_bytes(row, ["a", "b"]) == estimate_value_bytes(1) + estimate_value_bytes(2.0)


def test_estimate_bytes_calibrated_against_tracemalloc_on_vp_shaped_rows():
    """Calibration check (not a tight bound -- tracemalloc/CPython allocator behaviour is not
    guaranteed bit-identical across builds): on rows shaped like the real volume-profile
    rolling tracker's output (9 struct columns, each with several ~200-element int/float list
    children, UNIQUE large values so CPython's small-int cache cannot mask real allocation),
    this module's estimator must land within a generous order-of-magnitude band of the
    tracemalloc-measured real allocation -- proving it is not off by 20x the way a naive
    fixed-per-scalar-byte-count estimate was (see estimate_value_bytes's docstring)."""
    import random
    import tracemalloc

    def vp_row(i):
        rnd = random.Random(i)
        row = {"regime_start_ns": 1_700_000_000_000_000_000 + i, "observation_ts": 1_700_000_000_000_000_000 + i}
        for k in range(9):
            row[f"profile_{k}"] = {
                "price_levels": [rnd.random() * 20_000 for _ in range(200)],
                "weights_fp": [rnd.randint(10_000, 99_999_999) for _ in range(200)],
            }
            row[f"poc_{k}"] = rnd.random() * 20_000
        return row

    rows_for_measurement = []
    tracemalloc.start()
    snap0 = tracemalloc.take_snapshot()
    for i in range(50):
        rows_for_measurement.append(vp_row(i))
    snap1 = tracemalloc.take_snapshot()
    measured = sum(s.size_diff for s in snap1.compare_to(snap0, "lineno") if s.size_diff > 0)
    tracemalloc.stop()

    cols = list(rows_for_measurement[0].keys())
    estimated = sum(estimate_row_bytes(r, cols) for r in rows_for_measurement)
    ratio = measured / estimated
    # Generous band: a correctly-order-of-magnitude estimator, not an exact one.
    assert 0.2 <= ratio <= 5.0, f"estimator is off by more than 5x from measured allocation (ratio={ratio!r})"


def test_logical_hash_recomputable_from_the_finalized_file(tmp_path):
    """Defect fix: the manifest's logical_content_sha256 must be recomputable from the
    FILE actually written -- not just equal to a second hash of the writer's own
    pre-conversion input. Exercises a mixed int/float column (the column is fixed to
    float64 by a declared type while some input rows are plain ints), nulls, and a struct
    with a list<int64> child -- the three shapes most likely to make a pre-conversion hash
    diverge from a post-conversion one."""
    out = tmp_path / "recompute.parquet"
    cols = ["a_float_col", "b_nullable", "c_struct"]
    declared = {"a_float_col": pa.float64(), "c_struct": pa.struct([pa.field("x", pa.int64()), pa.field("lst", pa.list_(pa.int64()))])}
    w = ChunkedParquetWriter(out, cols, declared_types=declared, batch_rows=3)
    rows = [
        {"a_float_col": 1, "b_nullable": None, "c_struct": {"x": 1, "lst": [1, 2, 3]}},   # int into a float64 column
        {"a_float_col": 2.5, "b_nullable": "v", "c_struct": {"x": 2, "lst": []}},
        {"a_float_col": 3, "b_nullable": None, "c_struct": None},
        {"a_float_col": 4, "b_nullable": "w", "c_struct": {"x": 4, "lst": [7]}},
        {"a_float_col": 5.5, "b_nullable": None, "c_struct": {"x": 5, "lst": [8, 9]}},
    ]
    for r in rows:
        w.write_rows([r])
    manifest = w.finalize()
    recomputed = recompute_logical_content_sha256(out, cols)
    assert recomputed == manifest["logical_content_sha256"], (
        "logical_content_sha256 recomputed from the finalized file must match the manifest's "
        "value computed at write time -- a mismatch means the hash was taken over values that "
        "were never actually written (the pre-conversion defect)")


def test_sha256_file_streaming_matches_whole_file_digest(tmp_path):
    """Defect fix: the streaming sha256 helper must produce the IDENTICAL digest to a plain
    whole-file read, on a file small enough to check both ways, and must not depend on the
    chunk boundary (forced tiny here via direct byte comparison, not by monkeypatching the
    chunk size, to keep this test independent of the implementation's internal constant)."""
    import hashlib
    p = tmp_path / "f.bin"
    data = bytes(range(256)) * 5000  # a few hundred KB, several chunk-sizes either way
    p.write_bytes(data)
    assert sha256_file(p) == hashlib.sha256(data).hexdigest()


def test_on_flush_observer_called_at_each_stage(tmp_path):
    out = tmp_path / "observed.parquet"
    events = []
    w = ChunkedParquetWriter(out, ["a"], batch_rows=2, on_flush=lambda ev, info: events.append((ev, info["rows"])))
    for r in _rows(4):
        w.write_rows([r])
    w.finalize()
    assert events.count(("pre_emit", 2)) >= 1
    assert events.count(("post_conversion", 2)) >= 1
    assert events.count(("post_emit", 2)) >= 1
    # observer fires in the documented order for at least one batch
    first_triplet = events[:3]
    assert [e[0] for e in first_triplet] == ["pre_emit", "post_conversion", "post_emit"]
