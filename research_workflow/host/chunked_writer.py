"""Generic bounded-memory incremental parquet writer.

Used by the collection sink (``research_workflow/host/sink.py``) to flush candidate /
observation rows to disk as they are produced, instead of holding a whole year-partition
in Python lists until one ``to_parquet()`` call at the end (the memory blow-up this module
exists to fix: see ``artifacts/platform_v2/chunked_sink_flush/README.md``).

Design points (do not relax without re-reading the packet this module was built for):

* The physical schema is FIXED once, at or before the first physical batch is written to
  disk, and never re-inferred per batch. Columns whose Arrow type is already known (the
  caller's ``declared_types``) use that type outright. Any other column's type is inferred
  from a PROBE buffer that may span several logical ``write_rows`` calls -- never from a
  single batch -- so an all-null first batch does not lock in the wrong type. Once fixed,
  every subsequent batch is cast explicitly to the fixed type (never re-inferred), so an
  int column that is all-null in one batch and integral in the next cannot silently upcast
  to float the way a per-batch pandas ``to_parquet`` would.
* No branch here knows what "volume profile" or any other feature is. A column's value may
  be a plain scalar, a dict (-> Arrow struct) or a list (-> Arrow list), recursively, with no
  special-casing: this is what lets a future struct/list-typed tracker field (declared via
  ``BaseBinding.FIELD_TYPES`` on chore/vp_profile_snapshot) round-trip through this writer
  unchanged.
* The physical parquet bytes are a function of batch/row-group layout and are NOT the
  identity anything should compare on across a chunked vs. unchunked run. A separate
  LOGICAL content hash (sha256 over each row's canonical JSON, in emission order) is
  maintained instead, and is what callers should compare for equivalence. The physical
  file's own sha256 remains available (``physical_sha256``) for any consumer that already
  keys off "the exact file we wrote", but only this module's own completed file.
* Writes land at a temporary path and are atomically renamed into place only in
  ``finalize()``. No manifest is written by this module (the caller owns that, as it
  already does for ``manifest.json``); the point is that nothing with the FINAL name
  exists until the write is complete, so a crash mid-partition leaves no file any stage
  will mistake for a finished partition.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

# Default probe/batch size: flush every this many buffered rows. Chosen so a single flushed
# batch's in-memory footprint stays small relative to the 8 GiB process budget even for a
# ~42 KB/row typed-list field (50_000 * 42 KB ~= 2 GiB worst case per buffer; two buffers
# -- candidates and observations -- plus headroom still clears an 8 GiB budget. Callers with
# a heavier row (e.g. multiple struct/list tracker fields per row) should pass a smaller value).
DEFAULT_BATCH_ROWS = 50_000  # host-constant: default flush threshold, see module docstring

# A wide row (e.g. a struct column carrying several multi-hundred-element lists, measured at
# ~380 KB/row as Python objects for the volume-profile rolling tracker's 9-instance case --
# see artifacts/platform_v2/chunked_sink_flush/README.md) makes DEFAULT_BATCH_ROWS alone unsafe:
# 50_000 such rows would buffer ~19 GiB before the first physical flush. DEFAULT_BATCH_BYTES is
# a second, independent flush trigger -- the probe/batch is cut on whichever threshold (rows or
# estimated bytes) is reached first -- so a caller that only ever configures the row threshold
# still gets a bounded-memory probe for an unexpectedly wide row shape. 256 MiB is chosen so
# even a single buffer's worst-case batch stays a small fraction of an 8 GiB process budget with
# two buffers (candidates + observations) held at once, plus engine/catalog baseline headroom.
DEFAULT_BATCH_BYTES = 256 * 1024 * 1024  # host-constant: default byte flush threshold


def estimate_value_bytes(value: Any) -> int:
    """Cheap, deterministic estimate of one value's in-memory footprint. Used ONLY to decide
    WHEN a buffered batch should flush -- never to decide correctness or written content.

    Calibrated against ``tracemalloc`` on realistic (non-cached-small-int) nested
    struct/list rows shaped like the real volume-profile tracker's ``profile`` column (9
    struct columns, each with several ~200-element ``int64``/``float64`` list children):
    this recursive ``sys.getsizeof``-based estimate came within ~7% of the tracemalloc-
    measured actual allocation for that fixture (measured was the larger of the two --
    i.e. this estimator is very slightly OPTIMISTIC, not pessimistic, so a flush threshold
    sized off it is not over-conservative but is also not unsafely loose). A naive
    fixed-8-bytes-per-scalar estimate (the previous draft of this function) was ~20x too
    SMALL for the same fixture, because CPython ints/floats/containers carry real per-object
    header overhead that a fixed constant misses entirely -- ``sys.getsizeof`` captures that
    overhead directly and cheaply (a C-level call, no serialization). Determinism (same
    value -> same estimate, every time, within one Python build) is what keeps the flush/
    batch boundary reproducible; the LOGICAL content hash is independent of batch boundaries
    regardless (see ``test_logical_hash_independent_of_batch_boundaries``), so this estimate
    never needs to be exact or cross-platform-identical to be correct -- only cheap, non-zero,
    and roughly proportional to real memory use."""
    if value is None:
        return sys.getsizeof(None)
    if isinstance(value, (bool, int, float, str)):
        return sys.getsizeof(value)
    if isinstance(value, Mapping):
        return sys.getsizeof(value) + sum(sys.getsizeof(k) + estimate_value_bytes(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return sys.getsizeof(value) + sum(estimate_value_bytes(v) for v in value)
    return sys.getsizeof(value)  # unknown type: still a real, non-zero, cheap estimate


def estimate_row_bytes(row: Mapping[str, Any], columns: Sequence[str]) -> int:
    """Sum of ``estimate_value_bytes`` over one row's declared columns only (ignores any key
    the row carries that is not in ``columns``, matching what is actually written/buffered)."""
    return sum(estimate_value_bytes(row.get(c)) for c in columns)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _infer_scalar_type(value: Any) -> pa.DataType:
    if isinstance(value, bool):
        return pa.bool_()
    if isinstance(value, int):
        return pa.int64()
    if isinstance(value, float):
        return pa.float64()
    if isinstance(value, str):
        return pa.string()
    raise TypeError(f"CHUNKED_WRITER_UNSUPPORTED_SCALAR: {type(value)!r}")


def infer_arrow_type(samples: Sequence[Any]) -> pa.DataType:
    """Infer one Arrow type from a sequence of observed (non-schema-fixed) values for one
    column, recursively for dict (-> struct) and list (-> list) values. ``None`` entries are
    skipped when looking for a representative sample; an all-``None`` sequence (never a
    representative value observed) defaults to ``float64`` -- the same default a fully-empty
    numeric feature column already gets today via pandas/parquet, preserved here rather than
    invented."""
    for v in samples:
        if v is None:
            continue
        if isinstance(v, Mapping):
            fields = []
            keys = sorted(v.keys())
            for k in keys:
                # one representative value per key, pooled from every sample that has it
                sub_samples = [s.get(k) for s in samples if isinstance(s, Mapping) and k in s]
                fields.append(pa.field(k, infer_arrow_type(sub_samples)))
            return pa.struct(fields)
        if isinstance(v, (list, tuple)):
            elems = [e for item in samples if isinstance(item, (list, tuple)) for e in item]
            elem_type = infer_arrow_type(elems) if elems else pa.int64()
            return pa.list_(elem_type)
        return _infer_scalar_type(v)
    return pa.float64()


def dtype_tag_to_arrow(tag: str) -> pa.DataType:
    """One declarative dtype tag (as used by ``BaseBinding.FIELD_TYPES`` schemas, e.g.
    ``"int64"``, ``"float64"``, ``"bool"``, ``"str"``, ``"int64[]"``) -> the matching Arrow
    type. A trailing ``"?"`` (nullable-list marker, e.g. ``"int64[]?"``) does not change the
    Arrow TYPE -- Arrow arrays are nullable regardless -- so it is stripped and ignored here."""
    t = tag.rstrip("?")
    is_list = t.endswith("[]")
    if is_list:
        t = t[:-2]
    scalar = {"int64": pa.int64(), "float64": pa.float64(), "bool": pa.bool_(), "str": pa.string()}.get(t)
    if scalar is None:
        raise TypeError(f"CHUNKED_WRITER_UNKNOWN_DTYPE_TAG: {tag!r}")
    return pa.list_(scalar) if is_list else scalar


def field_types_to_arrow(spec: Mapping[str, Any]) -> pa.DataType:
    """One ``BaseBinding.FIELD_TYPES[field]`` declaration (e.g.
    ``{"kind": "struct", "schema": {"sub": "int64", ...}}``) -> the matching Arrow type.
    Generic over whatever tracker declares it -- no feature-specific branch; a future
    binding with a different ``kind`` only needs to extend this one mapping, not the
    writer."""
    kind = spec.get("kind")
    if kind == "struct":
        schema = spec.get("schema") or {}
        fields = [pa.field(k, dtype_tag_to_arrow(v)) for k, v in schema.items()]
        return pa.struct(fields)
    raise TypeError(f"CHUNKED_WRITER_UNKNOWN_FIELD_TYPES_KIND: {kind!r}")


def _build_array(values: Sequence[Any], arrow_type: pa.DataType) -> pa.Array:
    """Build one Arrow array of EXACTLY ``arrow_type``, never re-inferring. A column whose
    runtime values mix ``int`` and ``float`` (e.g. ``horizon_end_ts`` computed as an exact
    int in one row and a float in another) already gets ONE float64 dtype for the WHOLE
    column today via pandas/to_parquet, silently losing integer precision on the int-valued
    rows -- pandas never raises on that, so this writer pre-casts an int value to ``float``
    in Python BEFORE handing it to pyarrow when the fixed column type is floating, matching
    that existing silent-precision-loss contract instead of pyarrow's (stricter) default
    sequence-to-array range check. A genuine SHAPE conflict (e.g. a string landing in a fixed
    int64 column) still raises -- this only relaxes the float-precision case."""
    if pa.types.is_floating(arrow_type):
        values = [None if v is None else float(v) for v in values]
    return pa.array(list(values), type=arrow_type)


class ChunkedParquetWriter:
    """Incremental, schema-stable parquet writer for one columnar output (candidates or
    observations). One instance is owned by the caller across however many logical
    ``write_rows`` calls make up ONE partition replay (potentially several declared
    windows); ``finalize()`` is called exactly once, after the last row of the partition."""

    def __init__(self, path: Path, columns: Sequence[str], *, declared_types: Optional[Mapping[str, pa.DataType]] = None,
                 batch_rows: int = DEFAULT_BATCH_ROWS, batch_bytes: int = DEFAULT_BATCH_BYTES,
                 on_flush: Optional[Any] = None) -> None:
        if batch_rows < 1:
            raise ValueError(f"CHUNKED_WRITER_BAD_BATCH_ROWS: {batch_rows}")
        if batch_bytes < 0:
            raise ValueError(f"CHUNKED_WRITER_BAD_BATCH_BYTES: {batch_bytes}")
        self.path = Path(path)
        self.tmp_path = self.path.with_suffix(self.path.suffix + ".inprogress")
        self.columns = list(columns)
        self.declared_types = dict(declared_types or {})
        self.batch_rows = int(batch_rows)
        self.batch_bytes = int(batch_bytes)  # 0 disables the byte trigger; rows-only, as before
        # Generic, OFF-BY-DEFAULT observer hook: on_flush(event, info) is called at three
        # points around each physical batch write -- "pre_emit" (batch about to be built/
        # written, info={"rows": N}), "post_conversion" (Arrow arrays built, about to call
        # write_table, info={"rows": N}), "post_emit" (write_table has returned, info=
        # {"rows": N, "batches_written": N}). No feature/measurement logic lives here -- the
        # hook itself decides what to sample (e.g. RSS) and where to record it; this writer
        # never measures memory on its own. A raising observer is NOT caught: the caller's
        # own instrumentation bug must surface, never be silently swallowed mid-write.
        self.on_flush = on_flush
        self._probe: List[Dict[str, Any]] = []
        self._probe_bytes = 0
        self.schema: Optional[pa.Schema] = None
        self._field_types: Dict[str, pa.DataType] = {}
        self._writer: Optional[pq.ParquetWriter] = None
        self.rows_written = 0
        self.batches_written = 0
        self._hasher = hashlib.sha256()
        self._finalized = False
        self.tmp_path.parent.mkdir(parents=True, exist_ok=True)
        if self.tmp_path.is_file():
            self.tmp_path.unlink()  # a stale .inprogress from a previous crashed attempt

    # -- schema -------------------------------------------------------------------------
    def _fix_schema(self, probe_rows: Sequence[Mapping[str, Any]]) -> None:
        fields = []
        for col in self.columns:
            if col in self.declared_types:
                t = self.declared_types[col]
            else:
                t = infer_arrow_type([r.get(col) for r in probe_rows])
            self._field_types[col] = t
            fields.append(pa.field(col, t))
        self.schema = pa.schema(fields)
        self._writer = pq.ParquetWriter(str(self.tmp_path), self.schema)

    # -- write --------------------------------------------------------------------------
    def _emit_batch(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        if self.on_flush is not None:
            self.on_flush("pre_emit", {"rows": len(rows), "batches_written": self.batches_written})
        # Build every column's array before writing anything: a later batch carrying a value
        # incompatible with the column's already-fixed type (e.g. a struct landing in a
        # column the probe locked to float64) must fail CLOSED -- named, typed, before any
        # byte of this batch reaches disk -- never silently coerced and never partially
        # written.
        arrays = []
        for c in self.columns:
            try:
                arrays.append(_build_array([r.get(c) for r in rows], self._field_types[c]))
            except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError, TypeError, ValueError) as exc:
                raise TypeError(
                    f"CHUNKED_WRITER_TYPE_MISMATCH: column {c!r} fixed as {self._field_types[c]!s}; "
                    f"a later batch carries a value incompatible with that type ({exc})") from exc
        if self.on_flush is not None:
            self.on_flush("post_conversion", {"rows": len(rows), "batches_written": self.batches_written})
        table = pa.Table.from_arrays(arrays, schema=self.schema)
        self._writer.write_table(table)
        for r in rows:
            self._hasher.update(_canonical_json({c: r.get(c) for c in self.columns}).encode("utf-8"))
            self._hasher.update(b"\n")
        self.rows_written += len(rows)
        self.batches_written += 1
        if self.on_flush is not None:
            self.on_flush("post_emit", {"rows": len(rows), "batches_written": self.batches_written})

    def _iter_batches(self, rows: Sequence[Mapping[str, Any]]):
        """Split ``rows`` (ALREADY in emission order) into sub-batches, cutting a batch as
        soon as EITHER ``batch_rows`` is reached OR (if ``batch_bytes`` is set) the running
        estimated byte size of the current batch would exceed ``batch_bytes`` -- whichever
        comes first. Row order and row content are untouched; only where a batch boundary
        falls changes, which does not affect the logical content hash
        (``test_logical_hash_independent_of_batch_boundaries``)."""
        batch: List[Mapping[str, Any]] = []
        batch_bytes = 0
        for r in rows:
            rb = estimate_row_bytes(r, self.columns) if self.batch_bytes else 0
            if batch and (len(batch) >= self.batch_rows or (self.batch_bytes and batch_bytes + rb > self.batch_bytes)):
                yield batch
                batch = []
                batch_bytes = 0
            batch.append(r)
            batch_bytes += rb
        if batch:
            yield batch

    def write_rows(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if self._finalized:
            raise RuntimeError("CHUNKED_WRITER_CLOSED: write_rows() after finalize()")
        if not rows:
            return
        if self.schema is None:
            self._probe.extend(rows)
            if self.batch_bytes:
                self._probe_bytes += sum(estimate_row_bytes(r, self.columns) for r in rows)
            if len(self._probe) >= self.batch_rows or (self.batch_bytes and self._probe_bytes >= self.batch_bytes):
                self._fix_schema(self._probe)
                probe, self._probe = self._probe, []
                self._probe_bytes = 0
                for b in self._iter_batches(probe):
                    self._emit_batch(b)
            return
        for b in self._iter_batches(list(rows)):
            self._emit_batch(b)

    def flush(self) -> None:
        """Force any buffered probe rows to disk as a real batch (fixing the schema first if
        this partition never reached ``batch_rows``/``batch_bytes`` in total)."""
        if self._finalized or not self._probe:
            return
        if self.schema is None:
            self._fix_schema(self._probe)
        probe, self._probe = self._probe, []
        self._probe_bytes = 0
        for b in self._iter_batches(probe):
            self._emit_batch(b)

    def finalize(self) -> Dict[str, Any]:
        """Flush, close, atomically rename into place, and return the manifest the caller
        folds into its own ``manifest.json``. Idempotent-safe to call at most once."""
        if self._finalized:
            raise RuntimeError("CHUNKED_WRITER_ALREADY_FINALIZED")
        self.flush()
        if self.schema is None:
            # Never wrote a single row (empty partition): still fix an (all-default) schema
            # so an empty-but-valid, correctly-typed parquet file is produced.
            self._fix_schema([])
        self._writer.close()
        physical_sha256 = hashlib.sha256(self.tmp_path.read_bytes()).hexdigest()
        os.replace(self.tmp_path, self.path)  # atomic finalize: no file at the final name until now
        self._finalized = True
        return {
            "rows": self.rows_written,
            "batches": self.batches_written,
            "columns": list(self.columns),
            "schema": {c: str(self._field_types[c]) for c in self.columns},
            "logical_content_sha256": self._hasher.hexdigest(),
            "physical_sha256": physical_sha256,
            "batch_rows": self.batch_rows,
            "batch_bytes": self.batch_bytes,
            "path": str(self.path),
        }


__all__ = ["ChunkedParquetWriter", "infer_arrow_type", "dtype_tag_to_arrow", "field_types_to_arrow",
           "DEFAULT_BATCH_ROWS", "DEFAULT_BATCH_BYTES", "estimate_value_bytes", "estimate_row_bytes"]
