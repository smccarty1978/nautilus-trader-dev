"""Merge stage: partitions carrying a typed nested column (e.g. a tracker's `profile` struct) merge in Arrow.

Before chore/merge_nested_schema the merge round-tripped every partition through pandas: pyarrow's
to_pandas turns an int64 struct child into Python floats in any row group where that child has a
null, and to_parquet re-inferred the struct and failed with `ArrowInvalid ... not exactly
representable` (seen on the real nq_vp_g2_location_pilot collection). Non-nested studies must stay
byte-identical.
"""
from __future__ import annotations

import hashlib

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_workflow.lifecycle_v2 import KEY, LifecycleV2Error, _write_merged_parquet

BIG = 1_641_821_640_000_000_123          # > 2**53 and not a multiple of 2**k for k >= 1: not exact as float64
PROFILE = pa.struct([("snapshot_ts", pa.int64()), ("segment_start_ts", pa.int64()), ("tick", pa.float64()),
                     ("weights_fp", pa.list_(pa.int64())), ("allocation", pa.string())])


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _table(rows):
    cols = {k: [r[i] for r in rows] for i, k in enumerate(KEY)}
    schema = pa.schema([(k, pa.int64()) for k in KEY] + [("score", pa.float64()), ("profile", PROFILE)])
    return pa.table({**cols, "score": [r[len(KEY)] for r in rows], "profile": [r[len(KEY) + 1] for r in rows]}, schema=schema)


def _prof(ts, seg):
    return {"snapshot_ts": ts, "segment_start_ts": seg, "tick": 0.25, "weights_fp": [ts % 7, 3, 5], "allocation": "close"}


def _partitions(tmp_path):
    # Partition A: two row groups -- the first has a NULL struct child (segment_start_ts), which is
    # what makes to_pandas emit floats for that child in that row group only.
    a1 = _table([(BIG + 30, None, None, 1.0, _prof(BIG + 30, None)), (BIG + 10, None, None, 2.0, None)])
    a2 = _table([(BIG + 20, None, None, 3.0, _prof(BIG + 20, BIG + 1))])
    b = _table([(BIG + 5, None, None, 4.0, _prof(BIG + 5, BIG + 2)), (BIG + 40, None, None, 5.0, _prof(BIG + 40, BIG + 3))])
    pa_, pb = tmp_path / "2021" / "candidates.parquet", tmp_path / "2022" / "candidates.parquet"
    pa_.parent.mkdir(); pb.parent.mkdir()
    with pq.ParquetWriter(pa_, a1.schema) as w:
        w.write_table(a1); w.write_table(a2)
    pq.write_table(b, pb)
    return [pa_, pb]


def _merged_frame(sources):
    """Exactly the merge stage's pandas steps (concat, stable KEY sort)."""
    frame = pd.concat([pd.read_parquet(p) for p in sources], ignore_index=True)
    order = frame.sort_values(list(KEY), kind="mergesort").index.to_numpy()
    return frame.iloc[order].reset_index(drop=True), order


def test_pre_fix_pandas_round_trip_fails_on_a_nested_int64_child(tmp_path):
    sources = _partitions(tmp_path)
    frame, _ = _merged_frame(sources)
    with pytest.raises(pa.ArrowInvalid):
        frame.to_parquet(tmp_path / "old.parquet", index=False)


def test_nested_merge_keeps_population_order_values_and_types(tmp_path):
    sources = _partitions(tmp_path)
    frame, order = _merged_frame(sources)
    out = tmp_path / "merged.parquet"
    _write_merged_parquet(frame, out, sources, order)
    got = pq.read_table(out)
    src = pa.concat_tables([pq.read_table(p) for p in sources])
    assert got.schema.remove_metadata().equals(src.schema.remove_metadata())            # declared types kept
    assert got.num_rows == len(frame) == 5                                               # population
    assert got.column("observation_ts").to_pylist() == sorted(src.column("observation_ts").to_pylist())  # ordering
    assert got.column("observation_ts").to_pylist() == frame["observation_ts"].tolist()
    assert got.column("score").to_pylist() == frame["score"].tolist()
    assert got.to_pylist() == src.take(pa.array(order)).to_pylist()                      # exact values, incl. int64 > 2**53
    profs = {r["observation_ts"]: r["profile"] for r in got.to_pylist()}
    assert profs[BIG + 20]["segment_start_ts"] == BIG + 1 and profs[BIG + 30]["segment_start_ts"] is None
    assert profs[BIG + 10] is None


def test_non_nested_merge_is_byte_identical_to_the_previous_path(tmp_path):
    t1 = pa.table({"observation_ts": [3, 1], "regime_start_ns": [None, None], "checkpoint_index": [None, None], "x": [0.5, 1.5]})
    t2 = pa.table({"observation_ts": [2], "regime_start_ns": [None], "checkpoint_index": [None], "x": [2.5]})
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    pa_, pb = tmp_path / "a" / "c.parquet", tmp_path / "b" / "c.parquet"
    pd.DataFrame(t1.to_pydict()).to_parquet(pa_, index=False); pd.DataFrame(t2.to_pydict()).to_parquet(pb, index=False)
    frame, order = _merged_frame([pa_, pb])
    old, new = tmp_path / "old.parquet", tmp_path / "new.parquet"
    frame.to_parquet(old, index=False)
    _write_merged_parquet(frame, new, [pa_, pb], order)
    assert _sha(old) == _sha(new)


def test_nested_partitions_with_different_schemas_fail_closed(tmp_path):
    sources = _partitions(tmp_path)
    other = pq.read_table(sources[1]).cast(pa.schema([(k, pa.int64()) for k in KEY] + [("score", pa.float32()), ("profile", PROFILE)]))
    pq.write_table(other, sources[1])
    frame, order = _merged_frame(sources)
    with pytest.raises(LifecycleV2Error, match="MERGE_NESTED_SCHEMA_MISMATCH"):
        _write_merged_parquet(frame, tmp_path / "m.parquet", sources, order)
