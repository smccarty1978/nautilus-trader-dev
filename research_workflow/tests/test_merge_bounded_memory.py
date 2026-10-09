"""Merge stage: nested (G2 profile-shaped) partitions merge by streaming bounded Arrow batches.

chore/merge_bounded_memory. Before it, the nested merge read every partition into pandas AND as
whole Arrow tables, concatenated, ``take``-permuted the whole table and hashed nested columns via
``repr`` of pandas objects: 7.71 GiB peak RSS for 13,501 rows of the nq_vp_g2_location_pilot,
linear in rows. These tests pin: exact logical equality with the whole-table reference for any
batch size / source row-group layout / partition count / permutation, exact nested types and
nulls, deterministic output, the scalar part of the identity equal to ``frame_content_identity``,
a nested identity that is layout-independent and not truncated, and an Arrow-pool peak that does
not grow with the row count.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import research_workflow.lifecycle_v2 as lv2
from research.analysis.modeling import frame_content_identity
from research_workflow.host.chunked_writer import recompute_logical_content_sha256
from research_workflow.lifecycle_v2 import (KEY, LifecycleV2Error, _merge_key_order, _merge_partition_file,
                                            _stream_merged_parquet, _streaming_frame_content_identity)

REPO = Path(__file__).resolve().parents[2]
BIG = 1_641_821_640_000_000_123  # > 2**53, not exact as float64
PROFILE = pa.struct([("snapshot_ts", pa.int64()), ("lo_tick", pa.int64()), ("tick", pa.float64()), ("allocation", pa.string()),
                     ("window_complete", pa.bool_()), ("weights_fp", pa.list_(pa.int64())), ("triplet_tick", pa.list_(pa.int64()))])
SCHEMA = pa.schema([("observation_ts", pa.int64()), ("regime_start_ns", pa.float64()), ("checkpoint_index", pa.float64()),
                    ("score", pa.float64()), ("n", pa.int64()), ("label", pa.string()), ("profile_a", PROFILE), ("profile_b", PROFILE)])


def _profile(i: int):
    k = i % 6
    if k == 0:
        return None                                                            # null struct
    return {"snapshot_ts": BIG + i, "lo_tick": None if k == 1 else BIG - i, "tick": 0.25, "allocation": "close",
            "window_complete": None if k == 2 else bool(i % 2),
            "weights_fp": None if k == 3 else ([] if k == 4 else [i, None, BIG] if k == 5 else list(range(i % 5))),
            "triplet_tick": [BIG + j for j in range(i % 4)]}


def _rows(ts_values, offset=0):
    return [{"observation_ts": int(ts), "regime_start_ns": None if j % 3 == 0 else float(j), "checkpoint_index": float(j % 2),
             "score": None if j % 7 == 0 else j * 0.1, "n": None if j % 5 == 0 else j, "label": None if j % 4 == 0 else f"r{j}",
             "profile_a": _profile(j + offset), "profile_b": _profile(j + offset + 1)} for j, ts in enumerate(ts_values)]


def _write(path: Path, rows, group_sizes):
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    with pq.ParquetWriter(path, SCHEMA) as w:
        s = 0
        for g in group_sizes:
            if s < table.num_rows:
                w.write_table(table.slice(s, g), row_group_size=g)
            s += g
        if s < table.num_rows:
            w.write_table(table.slice(s))
    return path


def _sources(tmp_path, layout=(7, 1, 30, 4), shuffled=True):
    rng = np.random.default_rng(7)
    ts_a = BIG + np.arange(60) * 10
    ts_b = BIG + np.arange(45) * 10 + 5
    if shuffled:
        ts_a, ts_b = rng.permutation(ts_a), rng.permutation(ts_b)
    a = _write(tmp_path / "2022" / "candidates.parquet", _rows(ts_a), list(layout) * 20)
    b = _write(tmp_path / "2023" / "candidates.parquet", _rows(ts_b, offset=3), [13, 2] * 20)
    return [a, b]


def _reference(sources, order):
    return pa.concat_tables([pq.read_table(p) for p in sources]).take(pa.array(order, type=pa.int64()))


def _logical(path):
    return recompute_logical_content_sha256(path, pq.read_schema(path).names, batch_size=3)


@pytest.mark.parametrize("batch_rows", [1, 2, 3, 16, 64, 10_000])
def test_streamed_merge_equals_whole_table_reference_for_any_batch_size(tmp_path, batch_rows):
    sources = _sources(tmp_path)
    _, order = _merge_key_order(sources)
    assert order.tolist() != list(range(len(order)))                           # a real (non-identity) permutation
    out = tmp_path / "m.parquet"
    stats = _stream_merged_parquet(out, sources, order, batch_rows=batch_rows)
    ref = _reference(sources, order)
    got = pq.read_table(out)
    assert got.schema.equals(ref.schema, check_metadata=True)                  # exact nested types
    assert got.num_rows == ref.num_rows == 105 == stats["rows"]
    assert got.to_pylist() == ref.to_pylist()                                  # every field, null, empty list, int64 > 2**53
    assert got.column("observation_ts").to_pylist() == sorted(got.column("observation_ts").to_pylist())
    assert pq.ParquetFile(out).metadata.num_row_groups == -(-105 // batch_rows) == stats["output_row_groups"]
    ref_path = tmp_path / "ref.parquet"
    pq.write_table(ref, ref_path)
    assert _logical(out) == _logical(ref_path)


def test_streamed_merge_is_independent_of_source_row_group_layout_and_deterministic(tmp_path):
    hashes, idents, phys = set(), set(), set()
    for i, layout in enumerate([(1,), (7, 1, 30, 4), (200,)]):
        d = tmp_path / f"layout{i}"
        sources = _sources(d, layout=layout)
        _, order = _merge_key_order(sources)
        for b in (3, 50):
            out = d / f"m{b}.parquet"
            _stream_merged_parquet(out, sources, order, batch_rows=b)
            hashes.add(_logical(out))
            idents.add(_streaming_frame_content_identity(out)["identity"])
            if b == 50:
                out2 = d / "m50_again.parquet"
                _stream_merged_parquet(out2, sources, order, batch_rows=b)
                assert out.read_bytes() == out2.read_bytes()                   # deterministic bytes for one batch size
                phys.add(hashlib.sha256(out.read_bytes()).hexdigest())
    assert len(hashes) == 1 and len(idents) == 1


def test_default_chunks_are_byte_bounded_and_exact(tmp_path, monkeypatch):
    sources = _sources(tmp_path)
    _, order = _merge_key_order(sources)
    widest = max(pq.read_table(p).slice(i, 1).nbytes for p in sources for i in range(pq.ParquetFile(p).metadata.num_rows))
    target = 4 * widest
    monkeypatch.setattr(lv2, "MERGE_TARGET_BATCH_BYTES", target)
    out = tmp_path / "m.parquet"
    stats = _stream_merged_parquet(out, sources, order)
    assert stats["output_row_groups"] > 3 and stats["batch_rows"] is None
    assert stats["max_chunk_arrow_bytes"] <= 3 * target                       # estimate-driven, never the whole file
    assert pq.read_table(out).to_pylist() == _reference(sources, order).to_pylist()


def test_chunk_bounds_split_by_estimated_bytes():
    b = lv2._merge_chunk_bounds(np.array([5.0, 5.0, 5.0, 20.0, 1.0, 1.0]), 10)
    assert b.tolist()[0] == 0 and b.tolist()[-1] == 6 and all(x < y for x, y in zip(b[:-1], b[1:]))
    assert b.tolist() == [0, 2, 4, 6]                                           # a chunk overshoots by at most one row
    assert lv2._merge_chunk_bounds(np.zeros(0), 10).tolist() == [0]


def test_in_order_merge_reads_each_source_row_group_once(tmp_path, monkeypatch):
    sources = _sources(tmp_path, shuffled=False)
    _, order = _merge_key_order(sources)
    reads = []
    orig = pq.ParquetFile.read_row_group

    def counting(self, i, *a, **k):
        reads.append(i)
        return orig(self, i, *a, **k)
    monkeypatch.setattr(pq.ParquetFile, "read_row_group", counting)
    stats = _stream_merged_parquet(tmp_path / "m.parquet", sources, order, batch_rows=5)
    assert len(reads) == stats["source_row_groups"]


def test_empty_partitions_write_an_empty_file_with_the_declared_schema(tmp_path):
    a = _write(tmp_path / "a.parquet", [], [])
    b = _write(tmp_path / "b.parquet", [], [])
    _, order = _merge_key_order([a, b])
    _stream_merged_parquet(tmp_path / "m.parquet", [a, b], order)
    t = pq.read_table(tmp_path / "m.parquet")
    assert t.num_rows == 0 and t.schema.equals(SCHEMA)


def test_streamed_path_still_rejects_duplicate_keys(tmp_path):
    rows = _rows([BIG, BIG + 1, BIG])
    for r in rows:
        r["regime_start_ns"], r["checkpoint_index"] = 1.0, 0.0
    src = _write(tmp_path / "2022" / "c.parquet", rows, [2, 1])
    with pytest.raises(LifecycleV2Error, match="MERGE_DUPLICATE_KEYS"):
        _merge_partition_file([src], tmp_path / "m.parquet", check_dup=True)
    assert not (tmp_path / "m.parquet").exists()


def test_order_must_be_a_permutation(tmp_path):
    sources = _sources(tmp_path)
    with pytest.raises(LifecycleV2Error, match="not a permutation"):
        _stream_merged_parquet(tmp_path / "m.parquet", sources, np.zeros(105, dtype=np.int64))


def test_scalar_identity_columns_equal_frame_content_identity(tmp_path, monkeypatch):
    """Every non-nested column type the merge can carry hashes exactly as frame_content_identity did."""
    monkeypatch.setattr(lv2, "MERGE_IDENTITY_SCALAR_BATCH_ROWS", 3)           # force many batches
    n = 10
    t = pa.table({
        "observation_ts": pa.array(range(n), pa.int64()),
        "i_nulls": pa.array([None if i in (1, 8) else BIG + i for i in range(n)], pa.int64()),   # null only in some batches
        "f": pa.array([i / 3 for i in range(n)], pa.float64()),
        "b_nulls": pa.array([None if i == 4 else bool(i % 2) for i in range(n)], pa.bool_()),
        "s": pa.array([None if i == 2 else f"x{i}" for i in range(n)], pa.string()),
        "s_all_null": pa.array([None] * n, pa.string()),
        "s_numeric": pa.array([str(i * 1.5) for i in range(n)], pa.string()),
        "s_late_text": pa.array([str(i) if i < 7 else "text" for i in range(n)], pa.string()),   # float OK until batch 3
        "ts": pa.array(range(n), pa.timestamp("ns", tz="UTC")),
    })
    p = tmp_path / "s.parquet"
    pq.write_table(t, p, row_group_size=4)
    assert _streaming_frame_content_identity(p)["identity"] == frame_content_identity(pd.read_parquet(p))


def test_nested_identity_is_layout_independent_and_not_truncated(tmp_path):
    long = list(range(2000))
    changed = list(long); changed[1500] = -1                                   # beyond numpy repr's 1000-element summary
    schema = pa.schema([("observation_ts", pa.int64()), ("p", pa.struct([("w", pa.list_(pa.int64())), ("c", pa.int64())]))])

    def mk(name, w, groups):
        rows = [{"observation_ts": i, "p": {"w": w if i == 3 else [i], "c": None if i == 1 else i}} for i in range(6)]
        path = tmp_path / name
        with pq.ParquetWriter(path, schema) as wr:
            for s, g in groups:
                wr.write_table(pa.Table.from_pylist(rows[s:s + g], schema=schema))
        return path
    a = mk("a.parquet", long, [(0, 6)])
    b = mk("b.parquet", long, [(0, 1), (1, 2), (3, 3)])                       # same content, other chunking (null child in its own group)
    c = mk("c.parquet", changed, [(0, 6)])
    ia, ib, ic = (_streaming_frame_content_identity(x)["identity"] for x in (a, b, c))
    assert ia == ib and ia != ic


_BOUND_SCRIPT = textwrap.dedent("""
    import json, sys
    import numpy as np, pyarrow as pa, pyarrow.parquet as pq
    from research_workflow.lifecycle_v2 import _merge_key_order, _stream_merged_parquet
    tmp, n = sys.argv[1], int(sys.argv[2])
    schema = pa.schema([("observation_ts", pa.int64()), ("regime_start_ns", pa.float64()), ("checkpoint_index", pa.float64()),
                        ("p", pa.struct([("w", pa.list_(pa.int64())), ("c", pa.int64())]))])
    srcs = []
    for part in range(2):
        path = f"{tmp}/src{part}.parquet"
        with pq.ParquetWriter(path, schema) as w:
            for s in range(0, n, 250):
                m = min(250, n - s)
                ts = np.arange(s, s + m, dtype=np.int64) * 2 + part
                w.write_table(pa.table({"observation_ts": ts, "regime_start_ns": np.zeros(m), "checkpoint_index": np.zeros(m),
                                        "p": pa.StructArray.from_arrays([pa.array([list(range(500))] * m, pa.list_(pa.int64())),
                                                                         pa.array(ts)], ["w", "c"])}, schema=schema))
        srcs.append(path)
    _, order = _merge_key_order(srcs)
    pool = pa.default_memory_pool()
    base = pool.bytes_allocated()
    _stream_merged_parquet(f"{tmp}/m.parquet", srcs, order, batch_rows=200)
    print(json.dumps({"peak": pool.max_memory(), "base": base, "rows": 2 * n}))
""")


def test_streamed_merge_arrow_peak_does_not_grow_with_rows(tmp_path):
    """Arrow-pool peak of the whole streamed merge (fresh process) is flat in the row count."""
    out = {}
    for n in (1_000, 4_000):
        d = tmp_path / str(n); d.mkdir()
        r = subprocess.run([sys.executable, "-c", _BOUND_SCRIPT, str(d), str(n)], cwd=str(REPO), capture_output=True, text=True, check=True)
        out[n] = json.loads(r.stdout.strip().splitlines()[-1])
    small, large = out[1_000]["peak"], out[4_000]["peak"]
    # 4x the rows (each row 4 KB of list<int64> -> 8 MB vs 32 MB of profile payload): the peak must stay
    # within a small constant of the 1x peak, and far below the 32 MB a whole-table merge must hold.
    assert large < 1.5 * small + (2 << 20), out
    assert large < 16 << 20, out
