"""Platform-v2 lifecycle leaves: the stage implementations the governed controller runs
for a study authored in the six-kind grammar.

Stages (same vocabulary as the v1 controller):
    compile -> prepare -> readiness -> preflight -> tests -> causal_audit -> contract_audit -> seal
    -> smoke -> collection -> reconcile -> merge -> fit -> freeze -> oos -> analyze -> close

Every leaf returns the controller's receipt contract ``{"status": "PASS", "outputs": [...]}``
(``partitions`` for collection/oos) and writes deterministic artifacts under the study.
Long work (collection partitions) runs in child processes with a progress heartbeat and
resumes from partition manifests.  Nothing here imports a study or the legacy collector.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
NS = 1_000_000_000
PLAN_NAME = "compiled_plan.json"
KEY = ("observation_ts", "regime_start_ns", "checkpoint_index")
# Run by the `tests` stage before a study may seal. Kept to fast, capability-level guarantees:
# the golden host fixture, the grammar/compiler, the host core, date-bounded partition
# authorization, and the analysis operations. The slower end-to-end controller runs
# (test_lifecycle_v2, test_declarative_analysis) stay repo tests.
PLATFORM_TESTS = ("research_workflow/tests/test_golden_fixture.py", "research_workflow/tests/test_grammar_v2.py",
                  "research_workflow/tests/test_host_core.py", "research_workflow/tests/test_chronology_windows.py",
                  "research/analysis/tests/test_diagnostic_ops.py",
                  "research_workflow/tests/test_train_provenance_attestation.py")

# Re-exported for audit_packets_v2 and existing callers; one producer declaration.
from research_workflow.grammar.deliverables import DELIVERABLES, FIT_TUNING_DELIVERABLES



class CapabilityGapBlocked(RuntimeError):
    def __init__(self, report: Dict[str, Any]) -> None:
        super().__init__("CAPABILITY_GAP: " + ", ".join(report.get("kinds") or []))
        self.report = report


class LifecycleV2Error(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SHA_CHUNK_BYTES = 4 * 1024 * 1024  # streaming hash chunk size: bounds peak RSS of _sha()
# regardless of file size -- a full-year G2 partition can be several GB; Path.read_bytes()
# would spike peak RSS by that whole size at every finalize/verify call site that uses this.


def _sha(path: Path) -> Optional[str]:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            chunk = f.read(_SHA_CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _read(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _model_record_name(m: Mapping[str, Any]) -> str:
    """Stable key for one model record, across both shapes it is written in.

    Score mode writes ``name``; a multi-arm/multi-cell TRAIN fit writes ``arm``/``cell`` and no
    ``name`` (the model's own lineage calls that pair ``model_role``). freeze and oos key
    ``model_hashes`` / ``model_canonical_sha256`` by this name, so the two stages MUST derive it
    the same way or the freeze's canonical sha is unfindable at OOS.
    """
    if m.get("name"):
        return str(m["name"])
    if m.get("arm") or m.get("cell"):
        return f"{m.get('arm') or 'primary'}:{m.get('cell') or 'all'}"
    raise LifecycleV2Error(f"MODEL_RECORD_UNNAMED: model record has neither 'name' nor 'arm'/'cell': {sorted(m)}")


def _model_record_id(m: Mapping[str, Any]) -> str:
    """The model-store id of one record: score mode writes ``id``, a TRAIN fit writes ``model_id``."""
    mid = m.get("id") or m.get("model_id")
    if not mid:
        raise LifecycleV2Error(f"MODEL_RECORD_UNIDENTIFIED: model record has neither 'id' nor 'model_id': {sorted(m)}")
    return str(mid)


def _model_record_subset(m: Mapping[str, Any]) -> Dict[str, Any]:
    """The population slice a model record was fit on.

    Absent on a record written before the subset travelled with the record. Defaulting that to
    "no filter" is the dangerous reading: a direction-specific cell would then be scored over the
    whole undirected population and report a plausible, wrong number. Refuse instead -- the
    remedy is a refit under the current platform, which the composite change already forces.
    """
    if "subset" in m:
        return dict(m.get("subset") or {})
    if m.get("arm") or m.get("cell"):
        raise LifecycleV2Error(
            f"MODEL_RECORD_SUBSET_MISSING: record {_model_record_name(m)!r} carries no 'subset'; refit under the current platform")
    return {}


def _model_record_metrics(models: Mapping[str, Any]) -> Any:
    """TRAIN metrics for the freeze record.

    A single-arm/single-cell fit mirrors its metrics to the top level; a multi-cell fit keeps them
    per record. Reading only the top level makes the freeze of a multi-cell study carry no TRAIN
    metrics at all.
    """
    if models.get("metrics") is not None:
        return models["metrics"]
    records = models.get("models") or []
    return {_model_record_name(m): m.get("metrics") for m in records} or None


def spec_sha256(study: Path) -> Optional[str]:
    p = Path(study) / "study.yaml"
    if not p.is_file():
        return None
    from research_workflow.grammar.plan import canonical_json
    from research_workflow.grammar.compiler import load_spec
    return hashlib.sha256(canonical_json(load_spec(p)).encode("utf-8")).hexdigest()


from research_workflow.study_kind import is_v2_study  # noqa: E402  (leaf predicate; re-exported for existing callers)


def load_plan(study: Path) -> Dict[str, Any]:
    plan = _read(Path(study) / PLAN_NAME)
    if not plan:
        raise LifecycleV2Error("COMPILED_PLAN_MISSING: run --through compile")
    return plan


def _strict_int_year(y: Any) -> int:
    """Normalize a requested year to ``int`` without ever truncating a fractional value.
    ``bool`` is rejected even though it is an ``int`` subclass (``True``/``False`` are not
    years). An integral float/str (``2023.0`` / ``"2023"``) normalizes to ``int``; a
    fractional float/str (``2023.5`` / ``"2023.5"``) raises rather than silently truncating."""
    if isinstance(y, bool):
        raise ValueError(f"{y!r} is a bool, not a year")
    if isinstance(y, int):
        return y
    if isinstance(y, float):
        if y.is_integer():
            return int(y)
        raise ValueError(f"{y!r} is not an integral year")
    if isinstance(y, str):
        try:
            f = float(y)
        except ValueError:
            raise ValueError(f"{y!r} is not a numeric year")
        if f.is_integer():
            return int(f)
        raise ValueError(f"{y!r} is not an integral year")
    raise ValueError(f"{y!r} is not a year")


def authorized_years(plan: Dict[str, Any], period: str, requested: Optional[Sequence[Any]], *,
                      authorization: Optional[Mapping[str, Any]] = None) -> List[int]:
    """Resolve the exact years a stage may execute against its authorized chronology role.

    ``period`` is ``"train"`` (collection/reconcile/merge/fit) or ``"oos"``/``"dev"``
    (oos/analyze; ``"dev"`` is an alias of ``"oos"``). The CLI may only NARROW the role's
    declared years, never expand them, and a prohibited year is never executable under
    either role. ``requested=None`` resolves to exactly the role's authorized years; an
    empty requested list is rejected outright (it is not "everything").

    If ``authorization`` (the parsed ``artifacts/experiment_authorization.json``) is
    supplied, its recorded train_years/oos_years/prohibited_years for this role must agree
    with the plan's chronology, or the authorization artifact is stale and the request is
    rejected -- a plan re-compiled after PREPARE wrote the authorization artifact must not
    silently execute against the old, unauthorized role years.
    """
    if period not in ("train", "oos", "dev"):
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: unknown period {period!r}")
    role = "train" if period == "train" else "dev"
    chron = plan.get("chronology") or {}
    try:
        role_years = sorted({int(y) for y in (chron.get(role) or [])})
    except (TypeError, ValueError) as exc:
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: plan.chronology.{role} is malformed: {exc}")
    prohibited = {int(y) for y in (chron.get("prohibited") or [])}

    if authorization is not None:
        auth_role_key = "train_years" if role == "train" else "oos_years"
        auth_years = sorted({int(y) for y in (authorization.get(auth_role_key) or [])})
        auth_prohibited = {int(y) for y in (authorization.get("prohibited_years") or [])}
        if auth_years != role_years or auth_prohibited != prohibited:
            raise LifecycleV2Error(
                f"YEARS_NOT_AUTHORIZED: period={period} stale experiment_authorization.json "
                f"(plan.chronology.{role}={role_years}/prohibited={sorted(prohibited)} != "
                f"authorization.{auth_role_key}={auth_years}/prohibited_years={sorted(auth_prohibited)})")
        # A window narrows an authorized year to explicit dates. If the plan's windows and the
        # recorded authorization's windows disagree, the authorization artifact is stale against
        # a re-compiled plan and the run is refused rather than executed against the old dates.
        plan_windows = windows_identity((chron.get("windows") or []))
        auth_windows = sorted(str(w) for w in (authorization.get("partition_windows") or []))
        if auth_windows != plan_windows:
            raise LifecycleV2Error(
                f"WINDOWS_NOT_AUTHORIZED: stale experiment_authorization.json "
                f"(plan.chronology.windows={plan_windows} != authorization.partition_windows={auth_windows})")

    if requested is None:
        overlap = sorted(set(role_years) & prohibited)
        if overlap:
            raise LifecycleV2Error(
                f"YEARS_NOT_AUTHORIZED: role years intersect prohibited (period={period} role={role} "
                f"years={role_years} prohibited={sorted(prohibited)} overlap={overlap})")
        return role_years
    try:
        req = sorted({_strict_int_year(y) for y in requested})
    except ValueError as exc:
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: period={period} non-integer year: {exc}")
    if not req:
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: period={period} requested=[] authorized={role_years} prohibited={sorted(prohibited)}")
    if any(y in prohibited for y in req) or any(y not in role_years for y in req):
        raise LifecycleV2Error(
            f"YEARS_NOT_AUTHORIZED: period={period} requested={req} authorized={role_years} prohibited={sorted(prohibited)}")
    return req


MERGE_TARGET_BATCH_BYTES = 64 * 1024 * 1024  # host-constant: target Arrow bytes per streamed merge
# write batch. Bounds the merge's working set (plus one source row group, see
# _stream_merged_parquet) independently of the partition row count.
MERGE_IDENTITY_SCALAR_BATCH_ROWS = 65_536  # host-constant: upper bound on rows per batch when hashing
# the scalar columns of a streamed merged file.
MERGE_IDENTITY_SCALAR_TARGET_BYTES = 16 * 1024 * 1024  # host-constant: target Python-object bytes per
# scalar-column hashing batch (estimated with the chunked writer's calibrated estimator).


def _sources_nested(sources: Sequence[Path]) -> bool:
    """True when the partitions' Arrow schema carries any nested (struct/list/map) column."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    return bool(sources) and any(pa.types.is_nested(f.type) for f in pq.read_schema(sources[0]))


def _merge_key_order(sources: Sequence[Path]) -> tuple[Any, Any]:
    """The KEY columns of ``sources`` (concatenated in order) and the stable KEY sort permutation.

    Reads ONLY the KEY columns. The permutation equals the one the whole-frame pandas merge used
    (``frame.sort_values(KEY, kind="mergesort")`` depends only on the KEY values, their pandas
    dtypes and the concatenation order, all identical here).
    """
    import pandas as pd
    keys = pd.concat([pd.read_parquet(p, columns=list(KEY)) for p in sources], ignore_index=True)
    return keys, keys.sort_values(list(KEY), kind="mergesort").index.to_numpy()


def _merge_row_group_bytes_per_row(pfs: Sequence[Any], groups: Sequence[tuple]) -> Any:
    """Estimated in-memory Arrow bytes/row of every source row group (``groups`` order).

    Row width varies a lot within one partition (a profile's bin count grows and shrinks with the
    session), so one global bytes/row would mis-size chunks. Each row group's footer ``total_byte_size``
    is scaled by a per-source decode ratio measured on that source's largest row group (one bounded
    read per source). The raw footer size alone is NOT usable: it counts encoded (dictionary/RLE)
    bytes and understated the decoded Arrow size of the G2 pilot's profile structs ~5.6x.
    """
    import numpy as np
    ratio: Dict[int, float] = {}
    for fi, pf in enumerate(pfs):
        md = pf.metadata
        if not md.num_rows:
            continue
        gi = max(range(md.num_row_groups), key=lambda i: md.row_group(i).total_byte_size)
        t = pf.read_row_group(gi)
        ratio[fi] = t.nbytes / max(1, md.row_group(gi).total_byte_size)
        del t
    return np.array([pfs[fi].metadata.row_group(gi).total_byte_size * ratio.get(fi, 1.0) / max(1, n) for fi, gi, n in groups], dtype=np.float64)


def _merge_chunk_bounds(row_cost: Any, target_bytes: int) -> Any:
    """Split consecutive output rows (estimated bytes each) into chunks of about ``target_bytes``.

    Returns the chunk start offsets plus the final end. A chunk exceeds ``target_bytes`` by at most
    one row, and every chunk holds at least one row.
    """
    import numpy as np
    n = len(row_cost)
    if n == 0:
        return np.array([0], dtype=np.int64)
    start_offset = np.cumsum(row_cost) - row_cost
    cid = np.floor_divide(start_offset, float(max(1, target_bytes))).astype(np.int64)
    return np.concatenate([[0], np.flatnonzero(np.diff(cid)) + 1, [n]]).astype(np.int64)


def _stream_merged_parquet(path: Path, sources: Sequence[Path], order: Any, *, batch_rows: Optional[int] = None) -> Dict[str, Any]:
    """Write one merged file from ``sources`` permuted by ``order`` with bounded memory (Arrow only).

    ``order`` is the positional permutation of the concatenated ``sources`` (``_merge_key_order``).
    The output is produced in consecutive chunks of OUTPUT positions -- about
    ``MERGE_TARGET_BATCH_BYTES`` of estimated Arrow bytes each (``_merge_chunk_bounds``), or exactly
    ``batch_rows`` rows when given (tests/evidence): each chunk's rows are taken from the source row groups that hold them (the most recently read row group of
    each source is cached, so a merge whose order is monotone within each source -- the normal
    case, interleaved or not -- reads every row group exactly once), reassembled in output order
    and appended to a ``ParquetWriter`` as one row group. Nothing is converted to pandas or Python
    objects, every column keeps its exact Arrow type, and the working set is one chunk plus at most
    one row group per source, independent of the partition row count. Partitions must carry
    identical Arrow schemas (``MERGE_NESTED_SCHEMA_MISMATCH`` otherwise). The file is written to a
    temporary sibling and atomically renamed into place.

    (Before chore/merge_bounded_memory the nested path read every partition into pandas AND as a
    whole Arrow table, concatenated, ``take``-permuted the whole table and wrote one row group:
    7.71 GiB peak RSS for 13,501 rows of the G2 pilot, linear in rows.)
    """
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    path = Path(path)
    schemas = [pq.read_schema(p) for p in sources]
    if not schemas:
        raise LifecycleV2Error(f"MERGE_NO_PARTITIONS: {path.name}")
    if any(not s.remove_metadata().equals(schemas[0].remove_metadata()) for s in schemas[1:]):
        raise LifecycleV2Error(f"MERGE_NESTED_SCHEMA_MISMATCH: partitions of {path.name} carry different Arrow schemas")
    pfs = [pq.ParquetFile(str(p)) for p in sources]
    groups = [(fi, gi, pf.metadata.row_group(gi).num_rows) for fi, pf in enumerate(pfs) for gi in range(pf.metadata.num_row_groups)]
    sizes = np.array([n for _, _, n in groups], dtype=np.int64)
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]]) if len(sizes) else np.zeros(0, dtype=np.int64)
    total = int(sizes.sum())
    order = np.asarray(order, dtype=np.int64)
    if len(order) != total or (total and (order.min() < 0 or order.max() >= total)) or len(np.unique(order)) != total:
        raise LifecycleV2Error(f"MERGE_NESTED_SCHEMA_MISMATCH: {path.name} order is not a permutation of the {total} partition rows")
    g_all = np.searchsorted(starts, order, side="right") - 1 if total else np.zeros(0, dtype=np.int64)
    if batch_rows:
        bounds = np.unique(np.concatenate([np.arange(0, total, int(batch_rows), dtype=np.int64), [total]]))
    else:
        bounds = _merge_chunk_bounds(_merge_row_group_bytes_per_row(pfs, groups)[g_all] if total else np.zeros(0), MERGE_TARGET_BATCH_BYTES)
    tmp = path.with_name(path.name + ".tmp")
    cached: Dict[int, Any] = {}  # source file -> (global row group, table): at most ONE row group per source

    def _group(g: int):
        fi, gi, _ = groups[g]
        hit = cached.get(fi)
        if hit is None or hit[0] != g:
            cached.pop(fi, None)  # release this source's previous row group before reading the next
            cached[fi] = (g, pfs[fi].read_row_group(gi))
        return cached[fi][1]

    out_groups, max_chunk_rows, max_chunk_bytes = 0, 0, 0
    try:
        with pq.ParquetWriter(str(tmp), schemas[0]) as writer:
            for s, e in zip(bounds[:-1], bounds[1:]):
                pos = order[s:e]
                g_of = g_all[s:e]
                pieces, slots = [], []
                for g in np.unique(g_of):
                    sel = np.nonzero(g_of == g)[0]
                    pieces.append(_group(int(g)).take(pa.array(pos[sel] - starts[g], type=pa.int64())))
                    slots.append(sel)
                chunk = pa.concat_tables(pieces) if len(pieces) > 1 else pieces[0]
                if len(pieces) > 1:
                    chunk = chunk.take(pa.array(np.argsort(np.concatenate(slots), kind="stable"), type=pa.int64()))
                writer.write_table(chunk, row_group_size=max(1, chunk.num_rows))
                out_groups += 1
                max_chunk_rows, max_chunk_bytes = max(max_chunk_rows, chunk.num_rows), max(max_chunk_bytes, chunk.nbytes)
                del pieces, chunk
            if total == 0:
                writer.write_table(schemas[0].empty_table())
        cached.clear()
        os.replace(tmp, path)
    finally:
        cached.clear()
        if tmp.exists():
            tmp.unlink()
    return {"rows": total, "batch_rows": int(batch_rows) if batch_rows else None, "target_chunk_bytes": None if batch_rows else MERGE_TARGET_BATCH_BYTES,
            "max_chunk_rows": max_chunk_rows, "max_chunk_arrow_bytes": max_chunk_bytes, "source_row_groups": len(groups),
            "output_row_groups": out_groups, "sources": len(sources)}


class MergedFile(NamedTuple):
    """One merged file's record: content identity, persisted column names, row count, merge method."""
    identity: str
    columns: List[str]
    rows: int
    method: Dict[str, Any]


def _merge_partition_file(sources: Sequence[Path], dest: Path, *, check_dup: bool) -> MergedFile:
    """Merge one partition file kind (candidates or observations) into ``dest`` in stable KEY order.

    Partitions carrying a nested (struct/list) column are merged by STREAMING bounded Arrow batches
    (``_stream_merged_parquet``); only their KEY columns are ever read whole (duplicate check and
    the stable sort order). Scalar-only partitions keep the previous whole-frame pandas path
    unchanged, byte for byte, with the unchanged ``frame_content_identity``.
    """
    import pandas as pd
    import pyarrow.parquet as pq

    from research.analysis.modeling import frame_content_identity
    if _sources_nested(sources):
        keys, order = _merge_key_order(sources)
        if check_dup and len(keys) and keys.duplicated(list(KEY)).any():
            raise LifecycleV2Error("MERGE_DUPLICATE_KEYS")
        del keys
        stats = _stream_merged_parquet(dest, sources, order)
        ident = _streaming_frame_content_identity(dest)
        return MergedFile(identity=ident["identity"], columns=list(pq.read_schema(dest).names), rows=stats["rows"],
                          method={"write": "arrow_stream_v1", "identity": ident["method"], **stats})
    frame = pd.concat([pd.read_parquet(p) for p in sources], ignore_index=True)
    if check_dup and len(frame) and frame.duplicated(list(KEY)).any():
        raise LifecycleV2Error("MERGE_DUPLICATE_KEYS")
    frame = frame.sort_values(list(KEY), kind="mergesort").reset_index(drop=True)
    frame.to_parquet(dest, index=False)
    return MergedFile(identity=frame_content_identity(frame), columns=[str(c) for c in frame.columns], rows=int(len(frame)),
                      method={"write": "pandas_to_parquet", "identity": "frame_content_identity"})


def _row_group_slices(pf: Any, columns: Sequence[str], rows: int):
    """Yield ``columns`` of ``pf`` as consecutive tables of at most ``rows`` rows, with ONE batch reader
    per row group. A single whole-file ``ParquetFile.iter_batches`` over nested columns keeps Arrow
    buffers alive across the whole iteration in pyarrow 25 (measured linear growth); a reader
    restricted to one row group releases them when exhausted (flat) and still streams within it."""
    import pyarrow as pa
    n = max(1, int(rows))
    for gi in range(pf.metadata.num_row_groups):
        for batch in pf.iter_batches(batch_size=n, columns=list(columns), row_groups=[gi]):
            for start in range(0, batch.num_rows, n):
                yield pa.Table.from_batches([batch.slice(start, n)])


def _streaming_frame_content_identity(path: Path) -> Dict[str, Any]:
    """Column-ordered content identity of a merged parquet file, computed by streaming it.

    For every NON-nested column the per-column digest is exactly ``frame_content_identity``'s
    (``research.analysis.modeling``): the sha256 of the 12-dp-rounded float64 bytes when the whole
    column converts to float64, else the sha256 of the ``"\\x1f"``-joined ``repr`` of its pandas
    values -- both are row-streamable, and a column takes the repr digest iff any batch fails the
    float conversion (which is iff the whole column fails). A NESTED column's legacy digest was the
    repr of pandas objects, which truncates arrays and depends on the physical row-group chunking
    (to_pandas floats an int64 child in any chunk holding a null), so it is not a content identity;
    nested columns are digested instead as the ``"\\x1f"``-joined canonical JSON of their exact
    Arrow values (``to_pylist``), converted in byte-bounded slices of one row group at a time. The combined value is
    ``canonical_sha256([[column, digest], ...])`` as before.
    """
    import hashlib as _h

    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    from research.analysis.identity import canonical_sha256
    from research_workflow.host.chunked_writer import (DEFAULT_RECOMPUTE_TARGET_BATCH_BYTES, _bytes_bounded_batch_rows,
                                                       _canonical_json)
    pf = pq.ParquetFile(str(path))
    schema = pf.schema_arrow
    names = list(schema.names)
    nested = [n for n in names if pa.types.is_nested(schema.field(n).type)]
    scalar = [n for n in names if n not in nested]
    flt = {n: _h.sha256() for n in scalar}
    rep = {n: _h.sha256() for n in scalar}
    float_ok = {n: True for n in scalar}
    # A numeric/boolean Arrow column always converts to float64 (nulls -> NaN), so only the other
    # scalar types (strings, timestamps, ...) need the repr digest kept alongside.
    numeric = {n for n in scalar if pa.types.is_integer(schema.field(n).type) or pa.types.is_floating(schema.field(n).type)
               or pa.types.is_boolean(schema.field(n).type)}
    first = {n: True for n in names}
    if scalar:
        # Byte-bounded like the nested pass: a fixed 65,536-row batch over ~190 scalar columns (many of
        # them JSON strings) grew the pass's peak with the file until the cap (2.09 -> 2.97 GiB from
        # 13,501 to 108,008 rows in the merge-mechanics stress).
        scalar_rows = min(MERGE_IDENTITY_SCALAR_BATCH_ROWS, _bytes_bounded_batch_rows(pf, scalar, MERGE_IDENTITY_SCALAR_TARGET_BYTES))
        for batch in _row_group_slices(pf, scalar, scalar_rows):
            for n in scalar:
                series = batch.column(n).to_pandas()
                if float_ok[n]:
                    try:
                        flt[n].update(np.round(np.asarray(series.to_numpy(dtype="float64", na_value=np.nan), dtype="float64"), 12).tobytes())
                    except (TypeError, ValueError):
                        if n in numeric:
                            raise LifecycleV2Error(f"MERGE_IDENTITY_INTERNAL: numeric column {n!r} did not convert to float64")
                        float_ok[n] = False
                if n in numeric:
                    continue
                values = series.tolist()
                if values:
                    rep[n].update((("" if first[n] else "\x1f") + "\x1f".join(map(repr, values))).encode("utf-8"))
                    first[n] = False
    nested_digest: Dict[str, str] = {}
    for n in nested:
        h = _h.sha256()
        rows = _bytes_bounded_batch_rows(pf, [n], DEFAULT_RECOMPUTE_TARGET_BATCH_BYTES)
        for batch in _row_group_slices(pf, [n], rows):
            for v in batch.column(0).to_pylist():
                h.update((("" if first[n] else "\x1f") + _canonical_json(v)).encode("utf-8"))
                first[n] = False
        nested_digest[n] = h.hexdigest()
    per_column = [[n, nested_digest[n] if n in nested_digest else (flt[n] if float_ok[n] else rep[n]).hexdigest()] for n in names]
    return {"identity": canonical_sha256(per_column), "nested_columns": nested,
            "method": "streaming_frame_content_identity_v1: scalar columns = frame_content_identity; nested columns = canonical JSON of Arrow values"}


def _merge_window_stats(stats: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-window run stats into one partition-level record.

    Numeric counters sum; anything structured (nested per-stream dicts, strings) is kept as the
    ordered per-window list so a merged partition never fabricates a single value for something
    that was actually measured once per window.
    """
    merged: Dict[str, Any] = {}
    for key in sorted({k for s in stats for k in s}):
        values = [s.get(key) for s in stats]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values if v is not None):
            merged[key] = sum(v for v in values if v is not None)
        else:
            merged[key] = values
    return merged


def partition_windows(plan: Dict[str, Any], year: int) -> List[Dict[str, Any]]:
    """The declared date-bounded windows for one role year, or [] when the year runs whole.

    ``chronology.windows`` narrows an already-authorized role year to explicit inclusive date
    ranges; a year with no declared window keeps whole-year behaviour.
    """
    return [w for w in ((plan.get("chronology") or {}).get("windows") or []) if int(w["year"]) == int(year)]


def authorized_windows(plan: Dict[str, Any], requested: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Resolve the windows a run may execute. ``requested`` (CLI ``--windows``) may only NARROW
    the declared set: an unknown window id is refused rather than executed."""
    declared = list((plan.get("chronology") or {}).get("windows") or [])
    if requested is None:
        return declared
    wanted = {str(w).strip().replace("..", "_") for w in requested}
    if not wanted:
        raise LifecycleV2Error("WINDOWS_NOT_AUTHORIZED: requested=[] is not 'everything'")
    known = {w["id"] for w in declared}
    unknown = sorted(wanted - known)
    if unknown:
        raise LifecycleV2Error(f"WINDOWS_NOT_AUTHORIZED: requested={unknown} declared={sorted(known)}")
    return [w for w in declared if w["id"] in wanted]


def windows_identity(windows: Sequence[Mapping[str, Any]]) -> List[str]:
    return sorted(f"{w['year']}:{w['start']}..{w['end']}" for w in windows)


@dataclass
class V2Options:
    execute: bool = False
    smoke_date: Optional[str] = None
    years: Optional[List[int]] = None
    windows: Optional[List[str]] = None
    closure: Optional[Dict[str, str]] = None
    studies_root: Optional[Path] = None
    datasets_dir: Optional[Path] = None
    extra_bindings: Optional[Mapping[str, Any]] = None
    bar_source: Optional[Callable[[str, str], Any]] = None      # test hook: (start_date, end_date) -> [BarView]
    session_table_spec: Optional[Mapping[str, Any]] = None      # test hook
    # None (default): the replay lead-in is the compiled plan's chronology.warmup.days_before_partition
    # (spec default 5). An explicit int is an operator override (tests / diagnostics only).
    warmup_days: Optional[int] = None
    max_runtime: float = 6 * 3600
    progress_every_bars: int = 200_000
    in_process_partitions: bool = False
    # Bounded-memory collection: 0 (default) preserves the exact pre-existing behaviour --
    # a partition's candidates/observations are held fully in memory and written with one
    # to_parquet() call at partition end. A positive value switches `collection` (run_partition)
    # to the chunked sink path (research_workflow.host.chunked_writer): rows are flushed to disk
    # every `chunked_batch_rows` rows during the replay instead of accumulating for the whole
    # partition. Smoke and the pure bar_source test path are unaffected by this option; only
    # run_partition reads it. See artifacts/platform_v2/chunked_sink_flush/README.md.
    chunked_batch_rows: int = 0
    # Secondary, byte-estimate flush trigger -- INERT unless chunking is already enabled via
    # chunked_batch_rows > 0 above (does not itself turn chunking on, so the "0 is a no-op"
    # guarantee for every study that never opts in is unaffected). Once chunking is on, a row
    # threshold alone is unsafe for a wide row (e.g. several struct/list tracker fields per
    # row can be ~380 KB/row as Python objects -- see the README); the sink/writer flush on
    # whichever of chunked_batch_rows or chunked_batch_bytes is reached first. Defaults to the
    # module's DEFAULT_BATCH_BYTES (256 MiB) so an operator who sets only chunked_batch_rows
    # still gets byte-bounded memory for an unexpectedly wide row shape.
    chunked_batch_bytes: int = 256 * 1024 * 1024
    # W-5: when set, every model-store call this lifecycle makes (fit/score/authenticate)
    # writes to and reads from THIS root instead of the operator's real durable store
    # (research_workflow.roots.resolve_model_root()). None preserves the configured root --
    # every non-test caller keeps writing to the real store exactly as before.
    model_root: Optional[Path] = None


class V2Lifecycle:
    def __init__(self, study: Path, *, repo_root: Path = REPO_ROOT, options: Optional[V2Options] = None) -> None:
        self.study = Path(study).resolve()
        self.repo_root = Path(repo_root).resolve()
        self.opts = options or V2Options()
        self.work = self.study / "_work" / "controller"
        self.audit = self.study / "audit"
        self.artifacts = self.study / "artifacts"

    # -- identities ---------------------------------------------------------------
    def compile_outcome(self):
        from research_workflow.grammar.compiler import compile_study, load_spec
        return compile_study(load_spec(self.study), repo_root=self.repo_root, datasets_dir=self.opts.datasets_dir,
                             extra_bindings=self.opts.extra_bindings)

    def current_composite(self) -> Optional[str]:
        try:
            out = self.compile_outcome()
        except Exception:
            return None
        return out.plan.closure["composite_sha256"] if out.ok else None

    def fingerprints(self) -> Dict[str, Optional[str]]:
        plan = _read(self.study / PLAN_NAME)
        frozen = _read(self.audit / "frozen_execution_manifest.json")
        return {
            "study_spec": spec_sha256(self.study), "compiled_plan": _sha(self.study / PLAN_NAME),
            "plan_sha256": plan.get("plan_sha256"), "plan_spec_sha256": plan.get("spec_sha256"),
            "plan_closure_composite": (plan.get("closure") or {}).get("composite_sha256"),
            "execution_freeze": _sha(self.audit / "frozen_execution_manifest.json"),
            "execution_composite": frozen.get("frozen_execution_composite_sha256"),
            "current_execution_composite": self.current_composite(),
            "preflight": _sha(self.audit / "preflight.json"), "causal_status": _sha(self.audit / "status.json"),
            "contract_status": _sha(self.audit / "contract_status.json"), "seal": _sha(self.artifacts / "preexec_audit_seal.json"),
            "train_freeze": _sha(self.artifacts / "train_experiment_freeze.json"),
        }

    def _authorized_years(self, plan: Dict[str, Any], period: str, requested: Optional[Sequence[Any]] = None) -> List[int]:
        auth_path = self.artifacts / "experiment_authorization.json"
        authorization = _read(auth_path) if auth_path.is_file() else None
        return authorized_years(plan, period, requested, authorization=authorization)

    def _require_execute(self, stage: str) -> None:
        """Guard so a direct programmatic caller of a post-seal leaf (bypassing
        V2StudyController.run's EXECUTION_NOT_AUTHORIZED gate) cannot execute without
        --execute-authorized either."""
        if not self.opts.execute:
            raise LifecycleV2Error(f"EXECUTION_NOT_AUTHORIZED: {stage} requires --execute-authorized")

    def _zero_study_python(self) -> tuple[List[str], Optional[str]]:
        """R10 / ZERO_STUDY_PYTHON: any committed study-local executable Python (or notebook)
        is a reject unless the study id has a platform-sanctioned exception. Returns
        (python_files, exception_reason_or_None)."""
        from research_workflow.policy import STUDY_PYTHON_EXCEPTIONS, scan_study_python
        py_files = scan_study_python(self.study)
        return py_files, (STUDY_PYTHON_EXCEPTIONS.get(self.study.name) if py_files else None)

    def _seal_identities(self) -> Dict[str, str]:
        seal = _read(self.artifacts / "preexec_audit_seal.json")
        if not seal.get("composite_seal_hash"):
            raise LifecycleV2Error("PREEXEC_SEAL_MISSING")
        return {"composite_seal_hash": seal["composite_seal_hash"], "execution_manifest_sha256": seal.get("execution_manifest_composite_sha256")}

    # -- stages -------------------------------------------------------------------------
    def compile(self, study: Path | None = None) -> Dict[str, Any]:
        out = self.compile_outcome()
        if not out.ok:
            report = out.gaps.to_dict()
            _write(self.work / "capability_gap.json", report)
            raise CapabilityGapBlocked(report)
        path = out.plan.write(self.study / PLAN_NAME)
        card = out.plan.card()
        _write(self.artifacts / "compile_card.json", {**card, "written_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)], "card": card}

    def prepare(self, study: Path | None = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        chron = plan["chronology"]
        auth_path = self.artifacts / "experiment_authorization.json"
        if chron.get("dev"):
            from research_workflow.experiment import authorize_experiment
            authorize_experiment(self.study, write=True)
        else:
            from research.analysis.identity import canonical_sha256
            body = {"schema_version": 1, "study_id": plan["study"]["id"], "study_path": f"studies/{self.study.name}",
                    "train_years": list(chron["train"]), "oos_years": [], "prohibited_years": list(chron.get("prohibited") or []),
                    "generated_at_utc": _now()}
            body["authorization_sha256"] = canonical_sha256({k: v for k, v in body.items() if k != "generated_at_utc"})
            _write(auth_path, body)
        # Date-bounded authorization is recorded next to the year roles for BOTH branches, so a
        # stale authorization (a plan re-compiled with different windows after PREPARE) is caught
        # by authorized_years() before any partition streams a bar.
        if chron.get("windows"):
            body = _read(auth_path)
            body["partition_windows"] = windows_identity(chron["windows"])
            _write(auth_path, body)
        frozen = {"schema_version": 2, "hash_algorithm": plan["closure"]["hash_algorithm"], "authority": "platform_v2_plan_closure",
                  "plan_sha256": plan["plan_sha256"], "spec_sha256": plan["spec_sha256"],
                  "frozen_execution_composite_sha256": plan["closure"]["composite_sha256"], "files": plan["closure"]["files"],
                  "file_count": plan["closure"]["file_count"], "stages": plan["closure"].get("stages") or {}, "generated_at_utc": _now()}
        path = _write(self.audit / "frozen_execution_manifest.json", frozen)
        return {"status": "PASS", "outputs": [str(path), str(auth_path)]}

    def readiness(self, study: Path | None = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        checks: List[Dict[str, Any]] = []
        # R1 dataset identity + bytes (skipped only for an injected synthetic bar source)
        for sym, inst in plan["instruments"].items():
            if self.opts.bar_source is not None:
                checks.append({"id": f"R1_{sym}", "passed": True, "detail": "SYNTHETIC_BAR_SOURCE: no catalog to resolve"})
                continue
            try:
                from research_workflow.roots import resolve_dataset, verify_dataset_bytes
                r = resolve_dataset(inst["dataset_id"], self.repo_root)
                ok = (inst.get("dataset_digest") in (None, r.logical_digest))
                digest = verify_dataset_bytes(r.catalog_path, r.logical_digest)["logical_digest"] if r.logical_digest else None
                checks.append({"id": f"R1_{sym}", "passed": bool(ok and (digest is None or digest == r.logical_digest)),
                               "detail": f"{inst['dataset_id']} resolved via {r.resolution}; digest {str(r.logical_digest)[:12]} bytes verified"})
            except Exception as exc:
                checks.append({"id": f"R1_{sym}", "passed": False, "detail": f"{type(exc).__name__}: {exc}"})
        from scripts.lint_host import HOST_DIR, lint_file
        findings = [f for p in sorted(HOST_DIR.glob("*.py")) for f in lint_file(p)]
        checks.append({"id": "R8_host_boundary_lint", "passed": not findings, "detail": f"{len(findings)} findings"})
        unbound = [b for b in plan["binding_proof"] if not b.get("bound")]
        checks.append({"id": "R5_binding_proof", "passed": not unbound, "detail": f"{len(plan['binding_proof'])} primitives bound; unbound={[b['id'] for b in unbound]}"})
        try:
            from research_workflow.sessions import build_session_table, resolve_calendar_session_spec
            raw_spec = dict(self.opts.session_table_spec or plan["session"])
            resolved_spec = resolve_calendar_session_spec(raw_spec, self.repo_root)
            build_session_table(resolved_spec)
            detail = {"kind": resolved_spec.get("kind"), "session": resolved_spec.get("session"),
                      "censor_session": resolved_spec.get("censor_session"), "reference_digest": resolved_spec.get("reference_digest"),
                      "window_count": len(resolved_spec.get("rows") or []) if resolved_spec.get("kind") == "calendar" else None,
                      "reference_row_counts": resolved_spec.get("reference_row_counts")}
            checks.append({"id": "R3_session_table", "passed": True, "detail": json.dumps(detail, default=str)})
        except Exception as exc:
            checks.append({"id": "R3_session_table", "passed": False, "detail": f"{type(exc).__name__}: {exc}"})
        current = self.current_composite()
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        checks.append({"id": "R9_closure_current", "passed": bool(current and current == frozen), "detail": f"current={str(current)[:12]} frozen={str(frozen)[:12]}"})
        py_files, py_exception = self._zero_study_python()
        checks.append({"id": "R10_zero_study_python", "passed": not py_files or py_exception is not None,
                       "detail": json.dumps({"python_files": py_files, "exception": py_exception})})
        overall = all(c["passed"] for c in checks)
        path = _write(self.audit / "readiness.json", {"schema_version": 2, "overall_status": "PASS" if overall else "FAIL", "checks": checks,
                                                       "execution_composite_sha256": frozen, "plan_sha256": plan["plan_sha256"], "generated_at_utc": _now()})
        if not overall:
            raise LifecycleV2Error("READINESS_FAILED: " + "; ".join(c["id"] for c in checks if not c["passed"]))
        return {"status": "PASS", "outputs": [str(path)]}

    def preflight(self, study: Path | None = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        outcomes: Dict[str, str] = {}
        outcomes["PLAN_BOUND_TO_SPEC"] = "PASSED" if plan.get("spec_sha256") == spec_sha256(self.study) else "FAILED"
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        outcomes["EXECUTION_MANIFEST"] = "PASSED" if frozen and frozen == self.current_composite() else "FAILED"
        if plan["outcome"]["kernel"] == "none":
            # Descriptive (outcome: none) study: no entry reference to resolve -- it declares no
            # outcome contract at all.
            outcomes["ENTRY_REFERENCE_EXECUTABLE"] = "PASSED"
        else:
            from research_workflow.entry_references import resolve_entry_reference
            _, problem = resolve_entry_reference(plan["outcome"]["entry_reference"], plan["outcome"]["contract"])
            outcomes["ENTRY_REFERENCE_EXECUTABLE"] = "PASSED" if problem is None or plan["outcome"]["kernel"] == "flip" else "FAILED"
        from research_workflow.forward_outcomes.guard import find_outcome_columns
        leaked = find_outcome_columns(list(plan["columns"]["features"]) + [m["column"] for m in plan["columns"]["metadata"]])
        outcomes["FORWARD_OUTCOME_GUARD"] = "PASSED" if not leaked else "FAILED"
        model = plan.get("model") or {}
        outcomes["CHRONOLOGY_ROLE_TABLE"] = "PASSED" if (not model or (model.get("validation") or {}).get("year_role_table") is not None or model.get("validation") is None) else "FAILED"
        py_files, py_exception = self._zero_study_python()
        outcomes["ZERO_STUDY_PYTHON"] = "PASSED" if (not py_files or py_exception is not None) else f"FAILED: {py_files}"
        try:
            from research_workflow.host.predicate_eval import compile_predicate
            ef = {t["id"]: set(t.get("epoch_fields") or ()) for t in plan["trackers"]}
            if plan["population"].get("qualify"):
                compile_predicate(plan["population"]["qualify"]["ast"], epoch_fields=ef, allow_events=False)
            trig = plan["triggers"]
            if trig.get("kind") == "graph":
                for st in trig["states"].values():
                    compile_predicate(st["enter_when"]["ast"], epoch_fields=ef)
                    if st.get("expire_when"):
                        compile_predicate(st["expire_when"]["ast"], epoch_fields=ef)
                if trig.get("entry"):
                    compile_predicate(trig["entry"]["when"]["ast"], epoch_fields=ef)
            outcomes["PREDICATES_COMPILE"] = "PASSED"
        except Exception as exc:
            outcomes["PREDICATES_COMPILE"] = f"FAILED: {exc}"
        outcomes["CAUSAL_INVARIANTS"] = "PASSED" if all(v == "PASSED" for k, v in outcomes.items()) else "FAILED"
        ready = all(v == "PASSED" for v in outcomes.values())
        path = _write(self.audit / "preflight.json", {"schema_version": 2, "status": "CLEAR" if ready else "BLOCKED", "audit_ready": ready,
                                                       "check_outcomes": outcomes, "required_checks": list(outcomes), "execution_composite_sha256": frozen,
                                                       "plan_sha256": plan["plan_sha256"], "leaked_outcome_columns": leaked,
                                                       "study_python": {"python_files": py_files, "exception": py_exception}, "generated_at_utc": _now()})
        if not ready:
            raise LifecycleV2Error("PREFLIGHT_BLOCKED: " + ", ".join(k for k, v in outcomes.items() if v != "PASSED"))
        return {"status": "PASS", "outputs": [str(path)]}

    def tests(self, study: Path | None = None) -> Dict[str, Any]:
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        files = [str(self.repo_root / t) for t in PLATFORM_TESTS if (self.repo_root / t).is_file()]
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=str(self.repo_root),
                           capture_output=True, text=True)
        tail = (r.stdout + r.stderr)[-3000:]
        import re
        m = re.search(r"(\d+) passed", tail); f = re.search(r"(\d+) failed", tail)
        counts = {"passed": int(m.group(1)) if m else 0, "failed": int(f.group(1)) if f else 0}
        status = "PASS" if r.returncode == 0 else "FAIL"
        path = _write(self.work / "test_summary.json", {"status": status, "counts": counts, "files": files, "execution_composite_sha256": frozen, "tail": tail})
        if status != "PASS":
            raise LifecycleV2Error(f"PLATFORM_TESTS_FAILED: {counts}")
        return {"status": "PASS", "outputs": [str(path)]}

    def seal(self, study: Path | None = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        audits = {}
        collect = plan.get("stage") == "collect"
        for kind, name in (("causal", "status.json"), ("contract", "contract_status.json")):
            if collect and kind == "contract":
                # A frame makes no claim: there are no deliverables, no TRAIN/OOS separation and no
                # terminal label for a contract audit to vouch for. The FRAME SEAL binds the closure
                # composite and the causal audit only, and says so rather than leaving the slot empty.
                audits[kind] = {"status": "NOT_REQUIRED", "reason": "stage: collect produces a frame and makes no claim; the contract audit belongs to the research study that binds it"}
                continue
            st = _read(self.audit / name)
            if st.get("verdict") != "CLEAR" or st.get("audited_execution_composite_sha256") != frozen:
                raise LifecycleV2Error(f"AUDIT_NOT_CLEAR_OR_STALE: {kind}")
            audits[kind] = {"auditor": st.get("auditor"), "report_sha256": st.get("audit_report_sha256"), "status_sha256": _sha(self.audit / name)}
        body = {"schema_version": 2, "platform": "v2", "study_id": plan["study"]["id"], "plan_sha256": plan["plan_sha256"],
                "execution_manifest_composite_sha256": frozen, "audits": audits, "registry_sha256": plan.get("registry_sha256"), "sealed_at_utc": _now()}
        if collect:
            body["seal_kind"] = "frame"
        body["composite_seal_hash"] = hashlib.sha256(json.dumps({k: v for k, v in body.items() if k != "sealed_at_utc"}, sort_keys=True).encode()).hexdigest()
        path = _write(self.artifacts / "preexec_audit_seal.json", body)
        return {"status": "PASS", "outputs": [str(path)]}

    # -- execution ----------------------------------------------------------------------------
    def _warmup_days(self, plan: Mapping[str, Any]) -> int:
        """Calendar days of lead-in bars replayed before a partition/window start.

        The study DECLARES this (``chronology.warmup.days_before_partition``, compiled into the plan);
        the replay must honour it. A fixed 5-day lead-in silently streamed bars the study had not
        authorized -- e.g. a window starting 2022-01-03 read 2021-12-29.. bars although 2021 was
        prohibited, and a declared ``days_before_partition: 0`` was ignored. ``V2Options.warmup_days``
        stays an explicit operator override; the same value keys the replay-closure binding, so a
        partition collected under one lead-in is never reused under another.
        """
        if self.opts.warmup_days is not None:
            return int(self.opts.warmup_days)
        days = ((plan.get("chronology") or {}).get("warmup") or {}).get("days_before_partition", 5)
        days = int(days)
        if days < 0:
            raise LifecycleV2Error(f"INVALID_WARMUP_DAYS: chronology.warmup.days_before_partition={days}")
        return days

    def _run_window(self, plan: Dict[str, Any], start: str, end: str, primary: tuple, *, progress: Optional[Path], ledger: bool = False,
                    chunked_writers: Optional[Any] = None) -> Dict[str, Any]:
        flush_every = self.opts.chunked_batch_rows if chunked_writers is not None else 0
        flush_bytes = self.opts.chunked_batch_bytes if chunked_writers is not None else 0
        if self.opts.bar_source is not None:
            from research_workflow.host_runner import run_plan_on_bars
            from research_workflow.sessions import build_session_table, resolve_calendar_session_spec
            bars = self.opts.bar_source(start, end)
            table = build_session_table(resolve_calendar_session_spec(dict(self.opts.session_table_spec or plan["session"]), self.repo_root))
            ledger_rows: List[Dict[str, Any]] = [] if ledger else None
            run = run_plan_on_bars(plan, bars, session_table=table, primary_interval=primary, ledger=ledger_rows,
                                   chunked_writers=chunked_writers, chunked_flush_every=flush_every, chunked_flush_bytes=flush_bytes)
            run["dataset"] = {"dataset_id": "synthetic", "logical_digest": None, "bytes_verification": "SYNTHETIC"}
            run["ledger"] = ledger_rows
            return run
        from research_workflow.host_runner import run_plan_on_catalog
        return run_plan_on_catalog(plan, start_date=start, end_date=end, repo_root=self.repo_root, primary_interval=primary,
                                   warmup_days=self._warmup_days(plan), progress_path=progress, progress_every_bars=self.opts.progress_every_bars,
                                   session_table_spec=self.opts.session_table_spec, studies_root=self.opts.studies_root or (self.repo_root / "studies"), ledger=ledger,
                                   chunked_writers=chunked_writers, chunked_flush_every=flush_every, chunked_flush_bytes=flush_bytes)

    @staticmethod
    def _persist(run: Dict[str, Any], out_dir: Path, extra: Mapping[str, Any]) -> Dict[str, Any]:
        out_dir.mkdir(parents=True, exist_ok=True)
        c, o = out_dir / "candidates.parquet", out_dir / "observations.parquet"
        run["candidates"].to_parquet(c, index=False)
        run["observations"].to_parquet(o, index=False)
        manifest = {**extra, "status": "PASS", "candidates_sha256": _sha(c), "observations_sha256": _sha(o),
                    "rows": {"candidates": int(len(run["candidates"])), "observations": int(len(run["observations"]))},
                    "stats": run["stats"], "elapsed_s": run["elapsed_s"], "dataset": run.get("dataset"), "written_at_utc": _now()}
        _write(out_dir / "manifest.json", manifest)
        return manifest

    @staticmethod
    def _persist_chunked(stats: Mapping[str, Any], elapsed_s: float, dataset: Optional[Mapping[str, Any]],
                         writer_manifests: Mapping[str, Dict[str, Any]], out_dir: Path, extra: Mapping[str, Any]) -> Dict[str, Any]:
        """Bounded-memory counterpart of ``_persist``: the candidates/observations parquet
        files were already written incrementally (ChunkedParquetWriter.finalize() has already
        performed the atomic temp->final rename for each). The physical file's own sha256
        (``*_sha256`` below) is preserved for existing consumers that key off it (reconcile,
        replay_closure partition reuse, receipts); ``*_logical_content_sha256`` is the new,
        row-group-layout-independent identity, present alongside it, never instead of it."""
        c, o = out_dir / "candidates.parquet", out_dir / "observations.parquet"
        cand_m, obs_m = writer_manifests["candidates"], writer_manifests["observations"]
        assert _sha(c) == cand_m["physical_sha256"] and _sha(o) == obs_m["physical_sha256"], "CHUNKED_WRITER_FINALIZE_HASH_MISMATCH"
        manifest = {**extra, "status": "PASS", "candidates_sha256": cand_m["physical_sha256"], "observations_sha256": obs_m["physical_sha256"],
                    "candidates_logical_content_sha256": cand_m["logical_content_sha256"],
                    "observations_logical_content_sha256": obs_m["logical_content_sha256"],
                    "rows": {"candidates": int(cand_m["rows"]), "observations": int(obs_m["rows"])},
                    "chunked": {"candidates": {k: v for k, v in cand_m.items() if k != "path"},
                               "observations": {k: v for k, v in obs_m.items() if k != "path"}},
                    "stats": stats, "elapsed_s": elapsed_s, "dataset": dataset, "written_at_utc": _now()}
        _write(out_dir / "manifest.json", manifest)
        return manifest

    def _chunked_writers_for(self, plan: Dict[str, Any], out_dir: Path) -> Any:
        from research_workflow.host.chunked_writer import ChunkedParquetWriter
        from research_workflow.host.strategy import plan_output_columns, declared_metadata_types
        import pyarrow as pa
        cand_cols, obs_cols = plan_output_columns(plan)
        identity_cols = set(plan["columns"]["identity"])
        # Metadata columns whose tracker declares a struct/list shape (BaseBinding.FIELD_TYPES)
        # get that declared type outright, same as identity/feature columns -- never left to
        # probe-based inference, which would lock in float64 for a column that is all-null for
        # the whole probe (e.g. a rolling tracker's profile struct before its first complete
        # window). See declared_metadata_types's docstring.
        declared_meta = declared_metadata_types(plan)
        declared_cand = ({c: pa.int64() for c in identity_cols} | declared_meta
                         | {c: pa.float64() for c in (plan["columns"].get("features") or []) if c not in declared_meta})
        declared_obs = {c: pa.int64() for c in identity_cols if c in obs_cols} | {c: t for c, t in declared_meta.items() if c in obs_cols}
        out_dir.mkdir(parents=True, exist_ok=True)
        batch_rows = self.opts.chunked_batch_rows
        batch_bytes = self.opts.chunked_batch_bytes
        cand_w = ChunkedParquetWriter(out_dir / "candidates.parquet", cand_cols, declared_types=declared_cand,
                                      batch_rows=batch_rows, batch_bytes=batch_bytes)
        obs_w = ChunkedParquetWriter(out_dir / "observations.parquet", obs_cols, declared_types=declared_obs,
                                     batch_rows=batch_rows, batch_bytes=batch_bytes)
        return cand_w, obs_w

    def smoke(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("smoke")
        plan = load_plan(self.study)
        ids = self._seal_identities()
        date = self.opts.smoke_date or ((plan["chronology"].get("authorized_dates") or [None])[0])
        if not date:
            raise LifecycleV2Error("SMOKE_DATE_REQUIRED: pass --smoke-date or declare chronology.authorized_dates")
        import pandas as pd
        s, e = int(pd.Timestamp(f"{date} 00:00:00", tz="UTC").value), int(pd.Timestamp(f"{date} 23:59:59.999999999", tz="UTC").value)
        run_dir = self.study / "runs" / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{self.study.name}_smoke"
        # Empirical replay-closure membership proof: every repository module imported while the smoke
        # replay runs must be inside the compiled plan's collection-stage closure (the partition-reuse
        # key). An escape is a hard failure, never an automatic widening.
        from research_workflow.replay_closure import ImportTrace, collection_closure, merge_trace_union, repo_files_for_modules
        preloaded = repo_files_for_modules(list(sys.modules), self.repo_root)
        with ImportTrace() as trace:
            run = self._run_window(plan, date, date, (s, e), progress=self.work / "smoke.progress.json")
        traced = repo_files_for_modules(trace.names, self.repo_root)
        closure = collection_closure(plan)
        escapes = sorted(set(traced) - set(closure["files"]))
        merge_trace_union(self.artifacts / "replay_closure_trace.json", {
            "kind": "smoke", "plan_sha256": plan["plan_sha256"], "date": date, "closure_stage": closure["stage"],
            "replay_closure_composite_sha256": closure["composite_sha256"], "replay_closure_file_count": len(closure["files"]),
            "traced_repo_files": traced, "escapes": escapes, "verdict": "WITHIN_CLOSURE" if not escapes else "REPLAY_CLOSURE_ESCAPE",
            "preloaded_repo_files_outside_closure": sorted(set(preloaded) - set(closure["files"])),
            "note": "traced = repo modules first imported during the replay; preloaded = repo modules already imported by the "
                    "controller process before the replay (reported, not asserted); partition children start from a bare "
                    "interpreter, so their traces are complete", "generated_at_utc": _now()})
        manifest = self._persist(run, run_dir / "collection", {"kind": "smoke", "date": date, "plan_sha256": plan["plan_sha256"], **ids})
        cands, obs = run["candidates"], run["observations"]
        keys_c = set(map(tuple, cands[list(KEY)].itertuples(index=False, name=None))) if len(cands) else set()
        keys_o = set(map(tuple, obs[list(KEY)].itertuples(index=False, name=None))) if len(obs) else set()
        from research_workflow.forward_outcomes.guard import find_outcome_columns
        leaked = find_outcome_columns([c for c in cands.columns if c not in KEY])
        checks = {"candidates_nonempty": len(cands) > 0, "observation_per_candidate": keys_c == keys_o,
                  "no_outcome_columns_in_candidates": not leaked, "primary_window_respected": bool(len(cands) == 0 or (cands["observation_ts"].between(s, e).all())),
                  "pending_resolved_at_run_end": run["stats"].get("pending_at_end") == 0,
                  "replay_imports_within_collection_closure": not escapes}
        accepted = all(checks.values())
        path = _write(self.artifacts / "smoke_acceptance.json", {"status": "ACCEPTED" if accepted else "REJECTED", "study_name": self.study.name, "date": date,
                                                                 "sealed_composite_sha256": ids["composite_seal_hash"], "execution_manifest_composite_sha256": ids["execution_manifest_sha256"],
                                                                 "run_dir": str(run_dir), "candidates_count_total": int(len(cands)), "observations_count_total": int(len(obs)),
                                                                 "checks": checks, "manifest": manifest, "validator": "research_workflow.lifecycle_v2", "generated_at_utc": _now()})
        if not accepted:
            raise LifecycleV2Error("SMOKE_REJECTED: " + ", ".join(k for k, v in checks.items() if not v))
        return {"status": "PASS", "outputs": [str(path), str(run_dir / "collection" / "candidates.parquet"), str(run_dir / "collection" / "observations.parquet")]}

    def _partition_bounds(self, plan: Dict[str, Any], year: int, period: str) -> Dict[str, Any]:
        """Whole-year bounds for one role year, with the outcome lookahead tail."""
        import pandas as pd
        years = set(plan["chronology"]["train"]) | set(plan["chronology"].get("dev") or [])
        horizon_ns = max([a["horizon_ns"] for a in plan["outcome"].get("arms") or []] + [((plan["outcome"].get("flip") or {}).get("horizon_ns") or 0)])
        primary_start, primary_end = f"{year}-01-01", f"{year}-12-31"
        end = pd.Timestamp(primary_end, tz="UTC") + pd.Timedelta(days=1) + pd.Timedelta(seconds=horizon_ns // NS)
        run_end = end.strftime("%Y-%m-%d") if end.year in years else primary_end
        s = int(pd.Timestamp(primary_start, tz="UTC").value)
        e = int((pd.Timestamp(primary_end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value)
        return {"id": f"{period}-{year}", "year": year, "period": period, "primary_start": primary_start, "primary_end": primary_end, "run_end": run_end, "primary_ns": (s, e)}

    def _window_bounds(self, plan: Dict[str, Any], window: Mapping[str, Any], period: str) -> Dict[str, Any]:
        """Bounds for one declared date window.

        The window is a HARD data boundary: unlike a whole-year partition there is no forward
        lookahead tail, because a tail would stream bars the study never authorized. Any candidate
        whose outcome cannot resolve inside the window is left pending, and ``run_partition``
        refuses the partition rather than silently censoring it -- an unresolved row is proof the
        declared window is too narrow for the declared outcome, which is a spec defect, not data.
        """
        import pandas as pd
        start, end = str(window["start"]), str(window["end"])
        s = int(pd.Timestamp(start, tz="UTC").value)
        e = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value)
        return {"id": f"{period}-{window['id']}", "year": int(window["year"]), "period": period, "window_id": str(window["id"]),
                "primary_start": start, "primary_end": end, "run_end": end, "primary_ns": (s, e)}

    def _partition_valid(self, out_dir: Path, plan_sha: str, seal: str) -> bool:
        m = _read(out_dir / "manifest.json")
        if not m or m.get("status") != "PASS" or m.get("plan_sha256") != plan_sha or m.get("composite_seal_hash") != seal:
            return False
        return _sha(out_dir / "candidates.parquet") == m.get("candidates_sha256") and _sha(out_dir / "observations.parquet") == m.get("observations_sha256")

    # -- partition reuse (replay-closure key; research_workflow.replay_closure) -------------------------
    def _authorization_sha256(self) -> Optional[str]:
        return _read(self.artifacts / "experiment_authorization.json").get("authorization_sha256")

    @staticmethod
    def _plan_dataset(plan: Dict[str, Any]) -> Dict[str, Any]:
        sym = next((s for s, f in plan["instruments"].items() if f.get("role") == "execution"), None)
        inst = plan["instruments"].get(sym) or {}
        return {"dataset_id": inst.get("dataset_id"), "logical_digest": inst.get("dataset_digest")}

    def _replay_binding(self, plan: Dict[str, Any], partition: Mapping[str, Any]) -> Dict[str, Any]:
        from research_workflow.replay_closure import replay_closure_binding
        return replay_closure_binding(plan, dataset=self._plan_dataset(plan), partition=partition,
                                      authorization_sha256=self._authorization_sha256(), warmup_days=self._warmup_days(plan),
                                      repo_root=self.repo_root)

    def _expected_partition(self, plan: Dict[str, Any], year: int, period: str) -> Dict[str, Any]:
        """The interval component of the reuse key for one role year, derived exactly as run_partition
        derives the bounds it replays (whole year, or the declared windows)."""
        declared = partition_windows(plan, int(year))
        if not declared:
            b = self._partition_bounds(plan, int(year), period)
            return {k: v for k, v in b.items() if k != "primary_ns"} | {"windows": []}
        bounds = [{k: v for k, v in self._window_bounds(plan, w, period).items() if k != "primary_ns"} for w in declared]
        return {"id": f"{period}-{year}", "year": int(year), "period": period, "primary_start": bounds[0]["primary_start"],
                "primary_end": bounds[-1]["primary_end"], "run_end": bounds[-1]["run_end"],
                "windows": [{"id": b["id"], "primary_start": b["primary_start"], "primary_end": b["primary_end"]} for b in bounds]}

    def _partition_reusable(self, plan: Dict[str, Any], year: int, period: str, out_dir: Path) -> Dict[str, Any]:
        """Reuse proof for one existing partition under the CURRENT plan. Never mutates the partition."""
        from research_workflow.replay_closure import verify_reusable
        m = _read(out_dir / "manifest.json")
        expected = self._replay_binding(plan, self._expected_partition(plan, year, period))
        pid = f"{period}-{year}"
        ok, reason = verify_reusable(m, out_dir, expected, attestation=self._closure_attestation(),
                                     partition_id=pid) if m else (False, "NO_MANIFEST")
        declared_digest = self._plan_dataset(plan).get("logical_digest")
        seen_digest = ((m.get("dataset") or {}).get("logical_digest") if m else None)
        if ok and declared_digest and seen_digest and declared_digest != seen_digest:
            ok, reason = False, "DATASET_DIGEST_MISMATCH"
        # Smoke seeds the key: a partition is served only after THIS plan's smoke replay traced its imports
        # inside the replay-stage closure. No clean smoke trace for the current plan -> no reuse.
        if ok:
            trace = _read(self.artifacts / "replay_closure_trace.json")
            smokes = [r for r in (trace.get("runs") or []) if r.get("kind") == "smoke" and r.get("plan_sha256") == plan["plan_sha256"]]
            if not smokes or smokes[-1].get("verdict") != "WITHIN_CLOSURE":
                ok, reason = False, "NO_CLEAN_SMOKE_TRACE_FOR_PLAN"
        return {"id": pid, "year": int(year), "reusable": bool(ok), "reason": reason,
                "expected_replay_closure_sha256": expected["replay_closure_sha256"],
                "recorded_replay_closure_sha256": ((m.get("replay_closure") or {}).get("replay_closure_sha256") if m else None),
                "manifest_plan_sha256": (m.get("plan_sha256") if m else None), "manifest_seal": (m.get("composite_seal_hash") if m else None),
                "candidates_sha256": (m.get("candidates_sha256") if m else None), "observations_sha256": (m.get("observations_sha256") if m else None)}

    def _closure_attestation(self) -> Optional[Dict[str, Any]]:
        """The study's committed partition re-attestation receipt, if any (never machine-local state)."""
        from research_workflow.replay_closure import ATTESTATION_FILE
        return _read(self.artifacts / ATTESTATION_FILE) or None

    def partition_reuse_preview(self, period: str = "train") -> Dict[str, Any]:
        """What `collection` WOULD reuse under the current plan and seal (read-only; audit surface)."""
        from research_workflow.replay_closure import reuse_policy
        plan = load_plan(self.study)
        policy = reuse_policy(plan)
        seal = _read(self.artifacts / "preexec_audit_seal.json").get("composite_seal_hash")
        rows = []
        try:
            years = self._authorized_years(plan, period, self.opts.years)
        except Exception as exc:  # authorization missing at packet time: still report the declared policy
            return {"declared": policy, "period": period, "partitions": [], "note": f"years unresolved: {exc}"}
        for year in years:
            out_dir = self.work / "partitions" / period / str(year)
            if not (out_dir / "manifest.json").is_file():
                rows.append({"id": f"{period}-{year}", "year": int(year), "reusable": False, "reason": "NO_PARTITION"})
                continue
            if seal and self._partition_valid(out_dir, plan["plan_sha256"], seal):
                rows.append({"id": f"{period}-{year}", "year": int(year), "reusable": False, "reason": "CURRENT_PLAN_AND_SEAL"})
                continue
            rows.append(self._partition_reusable(plan, int(year), period, out_dir))
        return {"declared": policy, "period": period, "effective": policy["mode"] if period == "train" else "off",
                "partitions": rows, "would_reuse": [r["id"] for r in rows if r.get("reusable") and policy["mode"] != "off" and period == "train"]}

    def _shadow_verify(self, plan: Dict[str, Any], period: str, reused: List[Dict[str, Any]], ids: Dict[str, str]) -> Dict[str, Any]:
        """Recompute one reused partition into a shadow directory and require byte-identity."""
        from research_workflow.replay_closure import reuse_policy, select_shadow
        policy = reuse_policy(plan)
        chosen = select_shadow([r["id"] for r in reused], ids["composite_seal_hash"], shadow_policy=policy["shadow"])
        record: Dict[str, Any] = {"policy": policy["shadow"], "seed": ids["composite_seal_hash"], "reused": [r["id"] for r in reused],
                                  "selected": chosen, "status": "SKIPPED_BY_POLICY" if chosen is None else "PENDING", "generated_at_utc": _now()}
        if chosen is None:
            _write(self.work / "partition_reuse_shadow.json", record)
            return record
        year = int(chosen.rsplit("-", 1)[1])
        served = self.work / "partitions" / period / str(year)
        shadow = self.work / "partitions_shadow" / period / str(year)
        # A resumed run keeps a shadow already computed under THIS plan and seal; anything else is recomputed.
        if not self._partition_valid(shadow, plan["plan_sha256"], ids["composite_seal_hash"]):
            self._run_partition_child(plan, ids, int(year), period, shadow)
        sm, rm = _read(shadow / "manifest.json"), _read(served / "manifest.json")
        # Identity for this comparison, per output: the LOGICAL content hash
        # (candidates_logical_content_sha256 / observations_logical_content_sha256) when BOTH the
        # served and the recomputed-shadow manifest carry it (i.e. both were written chunked) --
        # row-group/batch-boundary layout is not part of what "the same data" means, and the served
        # partition's batch_rows need not equal the CURRENT run's chunked_batch_rows (an opt-in
        # V2Options value, not plan/seal identity) for them to be the same logical partition.
        # Falls back to the physical file hash (candidates_sha256 / observations_sha256) whenever
        # either side lacks a logical hash (the unchunked path, where none exists) -- unchanged
        # behaviour for every study that never opts into chunking.
        def _identity_pair(logical_key: str, physical_key: str) -> Dict[str, Any]:
            sl, rl = sm.get(logical_key), rm.get(logical_key)
            if sl and rl:
                return {"served": rl, "shadow": sl, "basis": "logical_content"}
            return {"served": rm.get(physical_key), "shadow": sm.get(physical_key), "basis": "physical"}
        cmp = {"candidates": _identity_pair("candidates_logical_content_sha256", "candidates_sha256"),
               "observations": _identity_pair("observations_logical_content_sha256", "observations_sha256")}
        identical = all(v["served"] and v["served"] == v["shadow"] for v in cmp.values())
        record.update({"status": "IDENTICAL" if identical else "MISMATCH", "comparison": cmp, "shadow_dir": str(shadow),
                       "shadow_elapsed_s": sm.get("elapsed_s"), "generated_at_utc": _now()})
        _write(self.work / "partition_reuse_shadow.json", record)
        if not identical:
            raise LifecycleV2Error(f"PARTITION_REUSE_SHADOW_MISMATCH: {chosen} recomputed bytes differ from the reused partition; "
                                   f"the replay-closure key is unsound -- halt, do not retry, every reuse since is suspect")
        return record

    def _run_partition_child(self, plan: Dict[str, Any], ids: Dict[str, str], year: int, period: str, out_dir: Path) -> None:
        progress = out_dir / "progress.json"
        if self.opts.in_process_partitions or self.opts.bar_source is not None:
            self.run_partition(int(year), period, out_dir, progress=progress)
        else:
            cmd = [sys.executable, "-m", "research_workflow.lifecycle_v2", "partition", "--study", str(self.study), "--period", period,
                   "--year", str(year), "--out-dir", str(out_dir), "--progress", str(progress), "--repo-root", str(self.repo_root)]
            if self.opts.studies_root:
                cmd += ["--studies-root", str(self.opts.studies_root)]
            if self.opts.windows:
                cmd += ["--windows", ",".join(self.opts.windows)]
            if self.opts.chunked_batch_rows > 0:
                # Bounded-memory collection is a runtime option (V2Options.chunked_batch_rows),
                # not plan/seal identity -- it must cross the subprocess boundary explicitly
                # here, the same as every other opts field this child command already forwards,
                # or a governed run that opts in would silently collect unchunked in the child.
                cmd += ["--chunked-batch-rows", str(self.opts.chunked_batch_rows)]
                cmd += ["--chunked-batch-bytes", str(self.opts.chunked_batch_bytes)]
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "child.log", "w", encoding="utf-8") as log:
                r = subprocess.run(cmd, cwd=str(self.repo_root), stdout=log, stderr=subprocess.STDOUT, timeout=self.opts.max_runtime)
            if r.returncode != 0:
                raise LifecycleV2Error(f"PARTITION_FAILED: {period}-{year} (see {out_dir / 'child.log'})")
        if not self._partition_valid(out_dir, plan["plan_sha256"], ids["composite_seal_hash"]):
            raise LifecycleV2Error(f"PARTITION_FAILED: {period}-{year} (see {out_dir / 'child.log'})")
        # Persist the child's replay trace into the study's cumulative trace (union across runs).
        from research_workflow.replay_closure import merge_trace_union
        entry = _read(out_dir / "replay_trace.json")
        if entry:
            merge_trace_union(self.artifacts / "replay_closure_trace.json", entry)

    def _reattest_partition_reuse(self, plan: Dict[str, Any], base: Path, years: Sequence[int], findings: List[str]) -> Dict[str, Any]:
        """Deterministic re-attestation of every reused partition (reconcile owns this, not the audit).

        A partition whose manifest was written under a different plan is admissible ONLY IF (1) the
        collection receipt records its reuse, (2) the key re-derived from the CURRENT plan equals the
        key recorded in the manifest and the recorded components re-hash to it, (3) the parquet bytes
        hash to the manifest, and (4) the shadow verification for this run is IDENTICAL (or skipped by
        a declared sampled policy). Anything else is a reconcile finding.
        """
        from research_workflow.replay_closure import REUSE_MODE_REPLAY_CLOSURE, SHADOW_EVERY_RUN, reuse_policy
        policy = reuse_policy(plan)
        receipt = _read(self.work / "train_partition_reuse.json")
        shadow = _read(self.work / "partition_reuse_shadow.json")
        recorded = {r["id"]: r for r in (receipt.get("reused") or [])} if receipt.get("plan_sha256") == plan["plan_sha256"] else {}
        rows: List[Dict[str, Any]] = []
        for y in years:
            d = base / str(y)
            m = _read(d / "manifest.json")
            if not m or m.get("plan_sha256") == plan["plan_sha256"]:
                continue  # produced under this plan: the plan/seal identity already vouches for it
            pid = f"train-{y}"
            att = self._partition_reusable(plan, int(y), "train", d)
            att["receipt_recorded"] = pid in recorded
            rows.append(att)
            if policy["mode"] != REUSE_MODE_REPLAY_CLOSURE:
                findings.append(f"partition {y}: manifest plan {str(m.get('plan_sha256'))[:12]} != current plan and partition_reuse is off")
                continue
            if pid not in recorded:
                findings.append(f"partition {y}: reused without a collection receipt")
            if not att["reusable"]:
                findings.append(f"partition {y}: reuse re-attestation failed ({att['reason']})")
            elif recorded.get(pid, {}).get("candidates_sha256") not in (None, att["candidates_sha256"]):
                findings.append(f"partition {y}: artifact bytes changed since the reuse receipt")
        if rows and policy["mode"] == REUSE_MODE_REPLAY_CLOSURE:
            if shadow.get("seed") != (_read(self.artifacts / "preexec_audit_seal.json").get("composite_seal_hash")):
                findings.append("partition reuse: no shadow verification record for this seal")
            elif shadow.get("status") == "MISMATCH":
                findings.append("partition reuse: shadow verification MISMATCH (terminal)")
            elif shadow.get("status") != "IDENTICAL" and not (policy["shadow"] != SHADOW_EVERY_RUN and shadow.get("status") == "SKIPPED_BY_POLICY"):
                findings.append(f"partition reuse: shadow verification status {shadow.get('status')}")
        return {"policy": policy, "reattested": rows, "shadow": {k: shadow.get(k) for k in ("policy", "selected", "status")} if rows else None}

    def run_partition(self, year: int, period: str, out_dir: Path, *, progress: Optional[Path] = None) -> Dict[str, Any]:
        """One partition for one role year.

        A year with declared ``chronology.windows`` runs one bounded sub-run per window and
        concatenates them into the single per-year partition every downstream stage already
        reads; a year with no window keeps the whole-year path unchanged.
        """
        import pandas as pd
        plan = load_plan(self.study)
        ids = self._seal_identities()
        windows = [w for w in authorized_windows(plan, self.opts.windows) if int(w["year"]) == int(year)]
        declared_for_year = partition_windows(plan, year)
        if declared_for_year and not windows:
            raise LifecycleV2Error(f"WINDOWS_NOT_AUTHORIZED: {period}-{year} declares windows but none were selected")
        # The reuse binding is derived BEFORE the replay so that its own (shell) imports never enter the
        # replay import trace below.
        from research_workflow.replay_closure import ImportTrace, collection_closure, repo_files_for_modules
        chunked = self.opts.chunked_batch_rows > 0
        chunked_writers = self._chunked_writers_for(plan, out_dir) if chunked else None
        if not declared_for_year:
            b = self._partition_bounds(plan, year, period)
            bare = {k: v for k, v in b.items() if k != "primary_ns"}
            extra = {"kind": "partition", **bare, "windows": [], "plan_sha256": plan["plan_sha256"], **ids,
                     "replay_closure": self._replay_binding(plan, {**bare, "windows": []})}
            with ImportTrace() as trace:
                run = self._run_window(plan, b["primary_start"], b["run_end"], b["primary_ns"], progress=progress,
                                       chunked_writers=chunked_writers)
        else:
            bounds = [{k: v for k, v in self._window_bounds(plan, w, period).items()} for w in windows]
            interval = {"id": f"{period}-{year}", "year": int(year), "period": period,
                        "primary_start": bounds[0]["primary_start"], "primary_end": bounds[-1]["primary_end"], "run_end": bounds[-1]["run_end"],
                        "windows": [{"id": b["id"], "primary_start": b["primary_start"], "primary_end": b["primary_end"]} for b in bounds]}
            extra = {"kind": "partition", "id": f"{period}-{year}", "year": int(year), "period": period,
                     "primary_start": bounds[0]["primary_start"], "primary_end": bounds[-1]["primary_end"],
                     "run_end": bounds[-1]["run_end"], "date_bounded": True,
                     "windows": [{k: b[k] for k in ("id", "window_id", "primary_start", "primary_end")} for b in bounds],
                     "plan_sha256": plan["plan_sha256"], **ids, "replay_closure": self._replay_binding(plan, interval)}
            runs = []
            with ImportTrace() as trace:
                for b in bounds:
                    # The SAME chunked_writers pair (if any) is reused across every window in this
                    # partition and finalized exactly once, after the loop: a windowed year's rows
                    # stream into one continuous parquet file, never a per-window frame concatenated
                    # in memory.
                    r = self._run_window(plan, b["primary_start"], b["run_end"], b["primary_ns"], progress=progress,
                                         chunked_writers=chunked_writers)
                    pending = int((r.get("stats") or {}).get("pending_at_end") or 0)
                    if pending:
                        raise LifecycleV2Error(
                            f"WINDOW_OUTCOME_UNRESOLVED: {b['id']} left {pending} candidate(s) unresolved at the window "
                            f"boundary; the declared window cannot resolve the declared outcome")
                    runs.append(r)
            if chunked:
                run = {"stats": _merge_window_stats([r.get("stats") or {} for r in runs]),
                       "elapsed_s": sum(float(r.get("elapsed_s") or 0.0) for r in runs), "dataset": runs[0].get("dataset")}
            else:
                run = {"candidates": pd.concat([r["candidates"] for r in runs], ignore_index=True),
                       "observations": pd.concat([r["observations"] for r in runs], ignore_index=True),
                       "stats": _merge_window_stats([r.get("stats") or {} for r in runs]),
                       "elapsed_s": sum(float(r.get("elapsed_s") or 0.0) for r in runs),
                       "dataset": runs[0].get("dataset")}
            digests = {json.dumps(r.get("dataset") or {}, sort_keys=True) for r in runs}
            if len(digests) > 1:
                raise LifecycleV2Error(f"WINDOW_DATASET_MISMATCH: {period}-{year} windows read different datasets")
            extra["window_rows"] = [int((r.get("stats") or {}).get("candidates") or 0) for r in runs]
        # Cumulative replay trace (Reading 2, §3.2): every partition run records the repo modules first
        # imported during its replay; any module outside the plan's replay-stage closure is a HALT --
        # the partition is not persisted and the key is never widened.
        closure = collection_closure(plan)
        traced = repo_files_for_modules(trace.names, self.repo_root)
        escapes = sorted(set(traced) - set(closure["files"]))
        out_dir.mkdir(parents=True, exist_ok=True)
        _write(out_dir / "replay_trace.json", {"kind": "partition", "id": f"{period}-{year}", "plan_sha256": plan["plan_sha256"],
                                                "closure_stage": closure["stage"], "replay_closure_composite_sha256": closure["composite_sha256"],
                                                "traced_repo_files": traced, "escapes": escapes,
                                                "verdict": "WITHIN_CLOSURE" if not escapes else "REPLAY_CLOSURE_ESCAPE", "generated_at_utc": _now()})
        if escapes:
            raise LifecycleV2Error(f"REPLAY_CLOSURE_ESCAPE: {period}-{year} imported {escapes} during replay, outside the "
                                   f"{closure['stage']}-stage closure; the reuse key is wrong -- halt, every reuse since is suspect")
        if chunked:
            # Every window's HostCore/strategy already streamed its rows into the SAME two
            # writer objects via chunked_writers; finalize() is only reached here, once, after
            # every window of this partition has run.
            cand_w, obs_w = chunked_writers
            writer_manifests = {"candidates": cand_w.finalize(), "observations": obs_w.finalize()}
            return self._persist_chunked(run["stats"], run["elapsed_s"], run.get("dataset"), writer_manifests, out_dir, extra)
        return self._persist(run, out_dir, extra)

    def _collect_period(self, period: str) -> Dict[str, Any]:
        plan = load_plan(self.study)
        ids = self._seal_identities()
        years = self._authorized_years(plan, period, self.opts.years)
        if not years:
            raise LifecycleV2Error(f"NO_YEARS_FOR_PERIOD: {period}")
        base = self.work / "partitions" / period
        partitions, outputs = [], []
        # Partition reuse is a declared, opt-in policy and applies to TRAIN only in this phase; OOS keeps
        # whole-plan/seal matching. `off` is byte-for-byte the pre-existing behaviour.
        from research_workflow.replay_closure import REUSE_MODE_REPLAY_CLOSURE, reuse_policy
        policy = reuse_policy(plan)
        reuse_on = policy["mode"] == REUSE_MODE_REPLAY_CLOSURE and period == "train"
        reused: List[Dict[str, Any]] = []
        recomputed: List[str] = []
        refused: List[Dict[str, Any]] = []
        for year in years:
            out_dir = base / str(year)
            if not self._partition_valid(out_dir, plan["plan_sha256"], ids["composite_seal_hash"]):
                decision = self._partition_reusable(plan, int(year), period, out_dir) if reuse_on and (out_dir / "manifest.json").is_file() else None
                if decision and decision["reusable"]:
                    reused.append(decision)
                else:
                    if decision:
                        refused.append(decision)
                    recomputed.append(f"{period}-{year}")
                    self._run_partition_child(plan, ids, int(year), period, out_dir)
            m = _read(out_dir / "manifest.json")
            partitions.append({"id": m["id"], "year": int(year), "status": "PASS", "rows": m.get("rows"), "manifest": str(out_dir / "manifest.json"),
                               **({"reused": True, "manifest_plan_sha256": m.get("plan_sha256")} if any(r["id"] == m["id"] for r in reused) else {})})
            outputs += [str(out_dir / "candidates.parquet"), str(out_dir / "observations.parquet")]
            _write(self.work / f"{period}_collection_progress.json", {"period": period, "completed": [p["id"] for p in partitions], "of": len(years), "updated_at_utc": _now()})
        receipt = {"period": period, "policy": policy, "effective": "replay_closure" if reuse_on else "off", "plan_sha256": plan["plan_sha256"],
                   "composite_seal_hash": ids["composite_seal_hash"], "reused": reused, "recomputed": recomputed, "refused": refused,
                   "generated_at_utc": _now()}
        if reuse_on:
            receipt_path = _write(self.work / f"{period}_partition_reuse.json", receipt)
            outputs.append(str(receipt_path))
            if reused:
                shadow = self._shadow_verify(plan, period, reused, ids)
                outputs.append(str(self.work / "partition_reuse_shadow.json"))
                receipt["shadow"] = {k: shadow.get(k) for k in ("policy", "selected", "status")}
                _write(receipt_path, receipt)
        return {"status": "PASS", "outputs": outputs, "partitions": partitions,
                **({"partition_reuse": {"reused": [r["id"] for r in reused], "recomputed": recomputed}} if reuse_on else {})}

    def collection(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("collection")
        return self._collect_period("train")

    def reconcile(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("reconcile")
        import pandas as pd
        plan = load_plan(self.study)
        base = self.work / "partitions" / "train"
        years = self._authorized_years(plan, "train", self.opts.years)
        findings: List[str] = []
        schemas, digests, rows = [], set(), 0
        seen_keys = 0
        for y in years:
            d = base / str(y)
            m = _read(d / "manifest.json")
            if m.get("status") != "PASS":
                findings.append(f"partition {y} not PASS"); continue
            c = pd.read_parquet(d / "candidates.parquet"); o = pd.read_parquet(d / "observations.parquet")
            schemas.append((tuple(c.columns), tuple(o.columns)))
            if (m.get("dataset") or {}).get("logical_digest"):
                digests.add(m["dataset"]["logical_digest"])
            if len(c) != len(o):
                findings.append(f"partition {y}: candidates {len(c)} != observations {len(o)}")
            if len(c) and c.duplicated(list(KEY)).any():
                findings.append(f"partition {y}: duplicate candidate keys")
            if len(c) and not pd.to_datetime(c["observation_ts"], unit="ns", utc=True).dt.year.eq(int(y)).all():
                findings.append(f"partition {y}: rows outside the primary year")
            # A date-bounded year is only reconciled against its DECLARED windows: proving rows sit
            # inside the calendar year would not detect a partition that streamed unauthorized dates.
            declared = partition_windows(plan, int(y))
            if declared and len(c):
                ts = pd.to_datetime(c["observation_ts"], unit="ns", utc=True)
                inside = False
                for w in declared:
                    lo = pd.Timestamp(w["start"], tz="UTC")
                    hi = pd.Timestamp(w["end"], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
                    inside = ((ts >= lo) & (ts <= hi)) if inside is False else (inside | ((ts >= lo) & (ts <= hi)))
                outside = int((~inside).sum())
                if outside:
                    findings.append(f"partition {y}: {outside} row(s) outside the declared windows "
                                    f"{[w['id'] for w in declared]}")
                if [str(x) for x in (m.get("windows") or [])] == []:
                    findings.append(f"partition {y}: manifest records no windows for a date-bounded year")
            rows += len(c); seen_keys += len(c)
        if len(set(schemas)) > 1:
            findings.append("partition output schema mismatch")
        if len(digests) > 1:
            findings.append(f"partitions read different dataset digests: {sorted(digests)}")
        reuse = self._reattest_partition_reuse(plan, base, years, findings)
        path = _write(self.work / "reconcile.json", {"passed": not findings, "findings": findings, "years": list(years), "rows": rows,
                                                    "authority": "plan.chronology.train",
                                                    "partition_windows": windows_identity((plan.get("chronology") or {}).get("windows") or []),
                                                    "dataset_digests": sorted(digests),
                                                    "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                                                    "partition_reuse": reuse,
                                                    "generated_at_utc": _now()})
        if findings:
            raise LifecycleV2Error("RECONCILE_FAILED: " + "; ".join(findings))
        return {"status": "PASS", "outputs": [str(path)]}

    def merge(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("merge")
        plan = load_plan(self.study)
        years = self._authorized_years(plan, "train", self.opts.years)
        base = self.work / "partitions" / "train"
        out = self.work / "merged"; out.mkdir(parents=True, exist_ok=True)
        from research_workflow.host.chunked_writer import recompute_logical_content_sha256
        cand = _merge_partition_file([base / str(y) / "candidates.parquet" for y in years], out / "candidates.parquet", check_dup=True)
        obs = _merge_partition_file([base / str(y) / "observations.parquet" for y in years], out / "observations.parquet", check_dup=False)
        # PERSISTED-SCHEMA ASSERTION. The sink buffers from the kernel's own column list, so a
        # column the plan declares can be emitted into the row dict and then silently dropped on
        # the way to parquet -- that is exactly how a whole C1 terminal block went missing from a
        # completed collection with every stage reporting PASS. Fail the merge instead.
        declared = list((plan.get("outcome") or {}).get("observation_columns") or [])
        missing = [c for c in declared if c not in obs.columns]
        if missing:
            raise LifecycleV2Error(
                "MERGE_PERSISTED_SCHEMA_MISSING_COLUMNS: the plan declares observation columns that "
                f"are absent from the merged frame: {missing}. The kernel's observation_columns and "
                "the compiled plan's observation_columns must agree; the sink buffers from the former.")
        ident = _write(out / "identity.json", {"candidates_identity": cand.identity, "observations_identity": obs.identity,
                                                "declared_observation_columns": declared, "persisted_observation_columns": obs.columns,
                                                "rows": cand.rows, "years": list(years), "authority": "plan.chronology.train", "plan_sha256": plan["plan_sha256"],
                                                "candidates_sha256": _sha(out / "candidates.parquet"), "observations_sha256": _sha(out / "observations.parquet"),
                                                # Canonical row-major logical-content hash (the chunked writer's own,
                                                # byte-bounded streaming recompute): independent of row-group layout.
                                                "candidates_logical_content_sha256": recompute_logical_content_sha256(out / "candidates.parquet", cand.columns),
                                                "observations_logical_content_sha256": recompute_logical_content_sha256(out / "observations.parquet", obs.columns),
                                                "merge_method": {"candidates": cand.method, "observations": obs.method},
                                                "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(out / "candidates.parquet"), str(out / "observations.parquet"), str(ident)]}

    # -- modeling -------------------------------------------------------------------------------
    def _train_frame(self, plan: Dict[str, Any]):
        import pandas as pd
        merged = self.work / "merged"
        c = pd.read_parquet(merged / "candidates.parquet"); o = pd.read_parquet(merged / "observations.parquet")
        label = plan["outcome"].get("label_column") or "target_flip_within_horizon"
        frame = c.merge(o[list(KEY) + [label, "disposition"]], on=list(KEY), how="inner")
        frame["_year"] = pd.to_datetime(frame["observation_ts"], unit="ns", utc=True).dt.year
        return frame, label

    def fit(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("fit")
        plan = load_plan(self.study)
        model = plan.get("model")
        if not model:
            path = _write(self.artifacts / "fit_summary.json", {"status": "NO_MODEL_DECLARED", "plan_sha256": plan["plan_sha256"], "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)]}
        if model.get("mode") == "score":
            return self._fit_score_mode(plan, model)
        import numpy as np
        import pandas as pd

        from research.analysis.metrics import brier, pr_auc, roc_auc
        from research.analysis.modeling import _build_estimator, frame_content_identity
        from research_workflow.forward_outcomes.guard import assert_causal_feature_surface
        from research_workflow.model_store import GOLDEN_MIN_ROWS, ModelLineage, store_model
        if model.get("target"):
            # A declared target is derived from OUTCOME columns, so the fit frame must carry every observation
            # column (the default fit frame carries only the label and the disposition).
            frame = self._train_frame_all_labels(plan)
            label = plan["outcome"].get("label_column") or "target_flip_within_horizon"
        else:
            frame, label = self._train_frame(plan)
        # MODEL TARGET. When the plan declares `model.target`, the label is DERIVED here, after collection,
        # from columns the frame already carries -- the persisted partition is never touched. Outcome columns
        # are legitimate target inputs (a label resolves after its entry); the feature surface is guarded
        # separately below and still refuses them.
        target_record = None
        if model.get("target"):
            from research.analysis.expressions import Evaluator, ExpressionError, parse
            spec_t = model["target"]
            try:
                ev = Evaluator(frame)
                value = ev.eval(parse(str(spec_t["expr"])))
            except ExpressionError as exc:
                raise LifecycleV2Error(f"MODEL_TARGET_UNRESOLVED: {spec_t['id']}: {exc}") from exc
            if value.kind not in ("bool", "null"):
                raise LifecycleV2Error(
                    f"MODEL_TARGET_NOT_BINARY: {spec_t['id']} evaluates to {value.kind}; a model target must be a "
                    "boolean expression resolving to {0, 1, null}")
            import pandas as _pd
            series = ev.materialize(value)
            label = f"__target_{spec_t['id']}"
            frame[label] = _pd.array([None if _pd.isna(v) else int(bool(v)) for v in series], dtype="Int64")
            target_record = {**{k: spec_t[k] for k in ("id", "expr", "expression_sha256")},
                             "eligible_n": int(frame[label].notna().sum()), "positive_n": int((frame[label] == 1).sum()),
                             "negative_n": int((frame[label] == 0).sum()), "null_n": int(frame[label].isna().sum())}
            if target_record["positive_n"] == 0 or target_record["negative_n"] == 0:
                raise LifecycleV2Error(
                    f"MODEL_TARGET_SINGLE_CLASS: {spec_t['id']} resolves to one class only "
                    f"({target_record['positive_n']} positive / {target_record['negative_n']} negative / "
                    f"{target_record['null_n']} null of {len(frame)} rows); a fit on it would be vacuous")
        # The MODEL INPUT SURFACE. `model.feature_columns`, when the plan declares it, is the explicit
        # surface the compiler validated column by column (identity, observation/outcome and guard-refused
        # names are already rejected there); otherwise it is the declared feature surface, unchanged.
        features = [str(c) for c in (model.get("feature_columns") or [])] or (
            list(plan["columns"]["features"]) + list(plan["columns"].get("derived") or []))
        assert_causal_feature_surface(features, context="v2 fit feature surface")
        if model.get("target") and label in features:
            raise LifecycleV2Error(f"MODEL_TARGET_IN_FEATURE_SURFACE: {label} is the derived target")
        unbound = [c for c in features if c not in frame.columns]
        if unbound:
            raise LifecycleV2Error(f"MODEL_FEATURE_COLUMNS_UNBOUND: the collected frame has no column(s) {unbound}")
        binary = frame[frame[label].isin([0, 1, 0.0, 1.0])].copy()
        family = str(model["family"]).split(".", 1)[-1]
        params = dict(model.get("params") or {})
        seed = int(params.pop("random_state", params.pop("seed", 42)))
        validation = model.get("validation") or {}
        tuning = [int(y) for y in (validation.get("tuning_years") or plan["chronology"]["train"])]
        final_years = [int(y) for y in (validation.get("final_train_validation_years") or [])]
        closure = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")

        def _fit(rows):
            est = _build_estimator(family, seed, params)
            est.fit(rows[features], rows[label].astype(int))
            return est

        def _metrics(est, rows):
            if rows.empty or rows[label].nunique() < 2:
                return {"n": int(len(rows)), "roc_auc": None, "pr_auc": None, "brier": None}
            s = est.predict_proba(rows[features])[:, 1]
            return {"n": int(len(rows)), "roc_auc": roc_auc(rows[label], s).to_dict().get("value"), "pr_auc": pr_auc(rows[label], s).to_dict().get("value"),
                    "brier": brier(rows[label], s).to_dict().get("value")}

        merge_identity = _read(self.work / "merged" / "identity.json").get("candidates_identity")
        tuning_report = None
        if model.get("search_space"):
            from research_workflow.tuning import tune
            tuning_report = tune(study_id=plan["study"]["id"], frame=binary, features=features, label=label, family=family, base_params=params, seed=seed,
                                 search_space=model["search_space"], validation=validation, artifacts_dir=self.artifacts,
                                 identities={"plan_sha256": plan["plan_sha256"], "population_identity": merge_identity, "execution_closure_composite": closure,
                                             "target_contract_sha256": hashlib.sha256(json.dumps(plan["outcome"], sort_keys=True, default=str).encode()).hexdigest(),
                                             "feature_contract_sha256": hashlib.sha256(json.dumps(features).encode()).hexdigest(), "preprocessing_contract_sha256": "identity"})
            params = dict(tuning_report["selected"]["params"])
        # ---- arms x cells ---------------------------------------------------------------
        # An arm is a feature architecture; a cell is a population slice with its own fixed
        # hyperparameters. Each (arm, cell) is fit INDEPENDENTLY on the identical collected
        # population, which is what makes the comparison paired. A study that declares neither
        # keeps the historical single-model behaviour exactly.
        arms = [a for a in (model.get("arms") or []) if isinstance(a, dict)] or [
            {"id": "primary", "features": [], "params": {}, "baseline": True}]
        cells = list(model.get("cells") or []) or [{"id": "all", "subset": {}, "params": {}}]
        month_folds = list((validation or {}).get("month_folds") or [])
        if month_folds:
            ts = pd.to_datetime(binary["observation_ts"], unit="ns", utc=True)
            binary["_month"] = ts.dt.year.astype(str) + "-" + ts.dt.month.map("{:02d}".format)

        def _rows_for(cell):
            rows = binary
            for col, val in (cell.get("subset") or {}).items():
                if col not in rows.columns:
                    raise LifecycleV2Error(f"CELL_SUBSET_COLUMN_MISSING: cell {cell['id']!r} filters on {col!r}")
                rows = rows[rows[col] == val]
            return rows

        def _fit_cfg(rows, cols, cfg):
            est = _build_estimator(family, seed, cfg)
            est.fit(rows[cols], rows[label].astype(int))
            return est

        def _metrics_cfg(est, rows, cols):
            if rows.empty or rows[label].nunique() < 2:
                return {"n": int(len(rows)), "positives": int(rows[label].sum()) if len(rows) else 0,
                        "base_rate": None, "roc_auc": None, "pr_auc": None, "brier": None}
            s = est.predict_proba(rows[cols])[:, 1]
            base = float(rows[label].mean())
            pr = pr_auc(rows[label], s).to_dict().get("value")
            return {"n": int(len(rows)), "positives": int(rows[label].sum()), "base_rate": base,
                    "roc_auc": roc_auc(rows[label], s).to_dict().get("value"), "pr_auc": pr,
                    "pr_auc_over_base_rate": (pr / base if pr is not None and base else None),
                    "brier": brier(rows[label], s).to_dict().get("value"),
                    "unique_regimes": int(rows["regime_start_ns"].nunique()) if "regime_start_ns" in rows.columns else None}

        trained: List[Dict[str, Any]] = []
        for arm in arms:
            arm_cols = [f for f in (arm.get("features") or features)]
            missing = [c for c in arm_cols if c not in binary.columns]
            if missing:
                raise LifecycleV2Error(f"ARM_FEATURES_UNBOUND: arm {arm['id']!r} needs {missing}")
            assert_causal_feature_surface(arm_cols, context=f"v2 fit arm {arm['id']}")
            for cell in cells:
                cfg = {**params, **(cell.get("params") or {}), **(arm.get("params") or {})}
                cell_rows = _rows_for(cell)
                folds: List[Dict[str, Any]] = []
                if month_folds:
                    for f in month_folds:
                        fit_rows = cell_rows[cell_rows["_month"].isin(f["fit_months"])]
                        val_rows = cell_rows[cell_rows["_month"].isin(f["validation_months"])]
                        if fit_rows.empty or fit_rows[label].nunique() < 2:
                            folds.append({"fold": f["fold"], **{k: f[k] for k in ("fit_months", "validation_months")},
                                          "status": "SKIPPED_DEGENERATE_FIT_WINDOW", "metrics": None,
                                          "train_rows": int(len(fit_rows)),
                                          "train_unique_regimes": int(fit_rows["regime_start_ns"].nunique()) if "regime_start_ns" in fit_rows.columns else None})
                            continue
                        est = _fit_cfg(fit_rows, arm_cols, cfg)
                        # TRAIN-derived thresholds: quantiles of the FIT window's own score
                        # distribution, applied UNCHANGED to the validation window. Deriving
                        # them from the validation rows would be the leak this exists to avoid.
                        fit_scores = est.predict_proba(fit_rows[arm_cols])[:, 1]
                        thresholds = {q: float(np.quantile(fit_scores, p)) for q, p in (("p90", 0.90), ("p95", 0.95))}
                        m = _metrics_cfg(est, val_rows, arm_cols)
                        diag = {}
                        if not val_rows.empty:
                            vs = est.predict_proba(val_rows[arm_cols])[:, 1]
                            base = float(val_rows[label].mean()) if len(val_rows) else None
                            for q, thr in thresholds.items():
                                keep = vs >= thr
                                sel = val_rows[keep]
                                prec = float(sel[label].mean()) if len(sel) else None
                                diag[q] = {"threshold": thr, "retained_fraction": float(keep.mean()),
                                           "retained_n": int(keep.sum()), "precision": prec,
                                           "precision_lift_vs_base_rate": (prec / base if prec is not None and base else None)}
                        folds.append({"fold": f["fold"], **{k: f[k] for k in ("fit_months", "validation_months")},
                                      "status": "OK", "train_rows": int(len(fit_rows)),
                                      "train_unique_regimes": int(fit_rows["regime_start_ns"].nunique()) if "regime_start_ns" in fit_rows.columns else None,
                                      "metrics": m, "train_derived_thresholds": diag})
                else:
                    for i, y in enumerate(sorted(tuning)):
                        if i == 0:
                            continue
                        fit_years = [t for t in sorted(tuning) if t < y]
                        est = _fit_cfg(cell_rows[cell_rows["_year"].isin(fit_years)], arm_cols, cfg)
                        folds.append({"fold": f"fold_{y}", "fit_years": fit_years, "validation_year": y,
                                      "status": "OK", "metrics": _metrics_cfg(est, cell_rows[cell_rows["_year"] == y], arm_cols)})
                final_rows = cell_rows[cell_rows["_year"].isin(tuning)]
                if final_rows.empty or final_rows[label].nunique() < 2:
                    raise LifecycleV2Error(f"CELL_FINAL_FIT_DEGENERATE: arm {arm['id']!r} cell {cell['id']!r} has no fittable rows")
                final_est = _fit_cfg(final_rows, arm_cols, cfg)
                final_val = _metrics_cfg(final_est, cell_rows[cell_rows["_year"].isin(final_years)], arm_cols) if final_years else None
                direction = next((str(v) for k, v in (cell.get("subset") or {}).items() if "direction" in k), "both")
                lineage = ModelLineage(study_id=plan["study"]["id"], cell_id=cell["id"], direction=direction,
                                       target_arm=arm["id"], fold_id="final", config_id="C00", seed=seed, ordered_inputs=arm_cols,
                                       feature_contract_sha256=hashlib.sha256(json.dumps(arm_cols).encode()).hexdigest(),
                                       preprocessing_contract_sha256="identity",
                                       target_contract_sha256=hashlib.sha256(json.dumps(plan["outcome"], sort_keys=True, default=str).encode()).hexdigest(),
                                       target_frame_identity=merge_identity, training_population_identity=merge_identity,
                                       train_years=sorted(tuning), validation_years=final_years, hyperparameters=cfg, family=family,
                                       closure_identities={"plan_closure": closure, "plan_sha256": plan["plan_sha256"]},
                                       model_role=f"{arm['id']}:{cell['id']}")
                mid = hashlib.sha256(json.dumps(lineage.__dict__, sort_keys=True, default=str).encode()).hexdigest()
                cell_metrics = {"folds": folds, "final_validation": final_val,
                                "tuning": (None if tuning_report is None else {k: tuning_report[k] for k in ("ledger", "sampler", "n_trials", "selected")})}
                manifest = store_model(model_id=mid, estimator=final_est, lineage=lineage, tier="registry", selection_status="selected",
                                       metrics=cell_metrics, golden_train_frame=final_rows[arm_cols],
                                       golden_rows=min(GOLDEN_MIN_ROWS, int(len(final_rows))), model_root=self.opts.model_root)
                trained.append({"arm": arm["id"], "cell": cell["id"], "baseline_arm": bool(arm.get("baseline")),
                                "model_id": mid, "features": arm_cols, "n_features": len(arm_cols),
                                # The cell's own population filter travels WITH the record: OOS must score
                                # each frozen cell on the identical slice it was fit on, and re-deriving that
                                # from the plan at OOS time would let a recompiled plan silently re-slice it.
                                "subset": dict(cell.get("subset") or {}),
                                "hyperparameters": cfg, "direction": direction,
                                "final_fit_rows": int(len(final_rows)),
                                "final_fit_unique_regimes": int(final_rows["regime_start_ns"].nunique()) if "regime_start_ns" in final_rows.columns else None,
                                "model_store_tier": manifest.get("tier"), "metrics": cell_metrics})

        # B: a fit that trained nothing is a FAILURE, not a PASS. Before this, an empty `trained` wrote a
        # receipt with zero models and the controller reported PASS -- a vacuous fit that looks like a result.
        if not trained:
            raise LifecycleV2Error(
                "MODEL_FIT_PRODUCED_NO_MODELS: every requested arm x cell was skipped (no eligible rows, or a "
                f"single target class) for label {label!r} over {len(binary)} binary rows of {len(frame)}; "
                "nothing was fitted, so there is nothing to freeze or score")
        expected = len(arms) * len(cells)
        if len(trained) != expected:
            missing = sorted({(a["id"], c["id"]) for a in arms for c in cells}
                             - {(t["arm"], t["cell"]) for t in trained})
            raise LifecycleV2Error(f"MODEL_FIT_INCOMPLETE: {len(trained)} of {expected} requested arm x cell "
                                   f"models were fitted; missing {missing}")
        paired = self._paired_arm_deltas(trained)
        references = self._score_models(self._train_frame_all_labels(plan), model.get("reference_models") or []) if model.get("reference_models") else []
        for r in references:
            assert_causal_feature_surface(r["inputs"], context=f"reference model {r['name']} inputs")
        single = trained[0] if len(trained) == 1 else None
        body = {"schema_version": 3, "plan_sha256": plan["plan_sha256"], "family": family, "label_column": label,
                "rows": {"total": int(len(frame)), "binary": int(len(binary))},
                "target": target_record,
                "tuning_years": sorted(tuning), "final_train_validation_years": final_years,
                "fold_protocol": ("walk_forward_months" if month_folds else "expanding_years"),
                "month_folds": month_folds, "models": trained, "paired_deltas_vs_baseline_arm": paired,
                "reference_models": references, "new_models_trained": True,
                "training_population_identity": merge_identity, "generated_at_utc": _now()}
        if single is not None:
            # One arm, one cell: keep the schema-2 keys the freeze/analyze stages already read.
            body.update({"model_id": single["model_id"], "features": single["features"],
                         "hyperparameters": single["hyperparameters"], "metrics": single["metrics"],
                         "model_store_tier": single["model_store_tier"]})
        path = _write(self.artifacts / "experiment_models.json", body)
        return {"status": "PASS", "outputs": [str(path)]}

    @staticmethod
    def _paired_arm_deltas(trained: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Per-cell, per-fold metric deltas of every arm against the baseline arm.

        Paired on the IDENTICAL validation rows: same cell, same fold, same population. A
        pooled comparison would let one strong fold carry an arm; these are reported fold by
        fold with the sign counts, so a single-fold win is visible as one.
        """
        out: Dict[str, Any] = {}
        by_cell: Dict[str, List[Dict[str, Any]]] = {}
        for t in trained:
            by_cell.setdefault(t["cell"], []).append(t)
        for cell, entries in by_cell.items():
            base = next((e for e in entries if e["baseline_arm"]), None)
            if base is None or len(entries) < 2:
                continue
            base_folds = {f["fold"]: f for f in base["metrics"]["folds"]}
            cell_out: Dict[str, Any] = {"baseline_arm": base["arm"], "arms": {}}
            for e in entries:
                if e["arm"] == base["arm"]:
                    continue
                rows, deltas = [], {k: [] for k in ("roc_auc", "pr_auc_over_base_rate", "brier")}
                for f in e["metrics"]["folds"]:
                    b = base_folds.get(f["fold"])
                    if not b or not f.get("metrics") or not b.get("metrics"):
                        continue
                    if f["metrics"]["n"] != b["metrics"]["n"]:
                        # Not paired: a delta over different rows is not a comparison.
                        rows.append({"fold": f["fold"], "status": "UNPAIRED_ROW_COUNT_MISMATCH",
                                     "arm_n": f["metrics"]["n"], "baseline_n": b["metrics"]["n"]})
                        continue
                    d = {}
                    for k in deltas:
                        av, bv = f["metrics"].get(k), b["metrics"].get(k)
                        d[k] = (av - bv) if (av is not None and bv is not None) else None
                        if d[k] is not None:
                            deltas[k].append(d[k])
                    rows.append({"fold": f["fold"], "status": "OK", "n": f["metrics"]["n"], "delta": d})
                summary = {}
                for k, vals in deltas.items():
                    if not vals:
                        summary[k] = None
                        continue
                    s = sorted(vals)
                    n = len(s)
                    summary[k] = {"n_folds": n, "mean": sum(s) / n, "median": s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2,
                                  "p25": s[max(0, int(0.25 * (n - 1)))], "p75": s[min(n - 1, int(0.75 * (n - 1)))],
                                  "best": s[-1], "worst": s[0],
                                  "folds_positive": sum(1 for v in s if v > 0), "folds_negative": sum(1 for v in s if v < 0)}
                cell_out["arms"][e["arm"]] = {"per_fold": rows, "summary": summary}
            out[cell] = cell_out
        return out

    def _train_frame_all_labels(self, plan: Dict[str, Any], base: Path | None = None, years: List[int] | None = None):
        """Candidates joined with every observation column (all arms), for frozen-model scoring."""
        import pandas as pd
        if base is None:
            merged = self.work / "merged"
            c = pd.read_parquet(merged / "candidates.parquet"); o = pd.read_parquet(merged / "observations.parquet")
        else:
            c = pd.concat([pd.read_parquet(base / str(y) / "candidates.parquet") for y in years or []], ignore_index=True)
            o = pd.concat([pd.read_parquet(base / str(y) / "observations.parquet") for y in years or []], ignore_index=True)
        dup = [col for col in o.columns if col in c.columns and col not in KEY]
        frame = c.merge(o.drop(columns=dup), on=list(KEY), how="inner")
        frame["_year"] = pd.to_datetime(frame["observation_ts"], unit="ns", utc=True).dt.year
        return frame

    def _score_models(self, frame, models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Score each frozen model on its declared subset; metrics per year plus a score digest for parity."""
        import hashlib as _h
        import numpy as np
        from research.analysis.metrics import brier, pr_auc, roc_auc
        from research_workflow.model_store import authenticate_model, read_manifest, score
        model_root = self.opts.model_root
        out = []
        for m in models:
            expect = dict(m.get("expect") or {})
            authentication = authenticate_model(m["id"], expect=expect or None, model_root=model_root)
            manifest = read_manifest(m["id"], model_root)
            inputs = list(manifest["lineage"]["ordered_inputs"])
            missing = [c for c in inputs if c not in frame.columns]
            if missing:
                raise LifecycleV2Error(f"MODEL_INPUTS_UNBOUND: {m['name']} needs {missing}")
            rows = frame
            for col, val in (m.get("subset") or {}).items():
                if col not in rows.columns:
                    raise LifecycleV2Error(f"MODEL_SUBSET_COLUMN_MISSING: {col}")
                rows = rows[rows[col] == val]
            label = m["label"]
            binary = rows[rows[label].isin([0, 1, 0.0, 1.0])]
            per_year = {}
            for y, part in binary.groupby("_year"):
                if part[label].nunique() < 2:
                    per_year[int(y)] = {"n": int(len(part)), "roc_auc": None, "pr_auc": None, "brier": None}
                    continue
                s = score(m["id"], part[inputs], model_root=model_root)
                per_year[int(y)] = {"n": int(len(part)), "positives": int(part[label].sum()), "roc_auc": roc_auc(part[label], s).to_dict().get("value"),
                                    "pr_auc": pr_auc(part[label], s).to_dict().get("value"), "brier": brier(part[label], s).to_dict().get("value"),
                                    "score_digest": _h.sha256(np.round(np.asarray(s, dtype=float), 10).tobytes()).hexdigest()}
            out.append({**m, "inputs": inputs, "lineage": {k: manifest["lineage"].get(k) for k in ("study_id", "cell_id", "direction", "target_arm", "train_years", "family")},
                        "rows_scored": int(len(binary)), "metrics_by_year": per_year,
                        "model_authentication": {k: authentication[k] for k in ("model_id", "identity_rule", "canonical_sha256", "feature_contract_sha256", "golden", "tier", "selection_status")}})
        return out

    def _freeze_bound_fitted_models(self, plan: Dict[str, Any], models: Mapping[str, Any], label: str) -> List[Dict[str, Any]]:
        """This study's own fitted model records, each bound to the canonical bytes its TRAIN freeze committed to.

        WARN-1: a post-freeze estimator substitution that refreshes its own canonical/golden bytes
        under the unchanged model_id would otherwise re-authenticate silently, so every record
        carries ``expect.canonical_sha256`` read from the freeze. One producer for the two consumers
        that score the study's own model after the freeze (OOS analysis, declared analysis with
        ``model_scores``), keyed exactly as the freeze keys ``model_canonical_sha256``.
        """
        freeze_path = self.artifacts / "train_experiment_freeze.json"
        if not freeze_path.is_file():
            raise LifecycleV2Error(f"FREEZE_CANONICAL_SHA_MISSING: no TRAIN freeze found for study '{plan['study']['id']}'")
        freeze_canonical = _read(freeze_path).get("model_canonical_sha256") or {}
        if models.get("mode") == "score":
            raise LifecycleV2Error("OWN_MODEL_SCORES_UNAVAILABLE: experiment_models.json is mode=score; a frozen external "
                                   "model's scores are a derived input, not the study's own fitted model")
        if models.get("model_id"):
            csha = freeze_canonical.get("primary")
            if not csha:
                raise LifecycleV2Error("FREEZE_CANONICAL_SHA_MISSING: no primary canonical sha in TRAIN freeze")
            return [{"name": "primary", "id": str(models["model_id"]), "subset": {}, "label": label,
                     "expect": {"study_id": plan["study"]["id"], "canonical_sha256": csha}}]
        if models.get("models"):
            bound = []
            for m in models["models"]:
                nm = _model_record_name(m)
                csha = freeze_canonical.get(nm)
                if not csha:
                    raise LifecycleV2Error(f"FREEZE_CANONICAL_SHA_MISSING: model '{nm}' has no TRAIN freeze canonical sha")
                bound.append({"name": nm, "id": _model_record_id(m), "subset": _model_record_subset(m),
                              "label": label, "expect": {"study_id": plan["study"]["id"], "canonical_sha256": csha}})
            return bound
        raise LifecycleV2Error(
            f"OOS_MODEL_RECORDS_UNRECOGNISED: experiment_models.json (mode={models.get('mode')!r}) carries no scorable models")

    def _join_own_model_scores(self, frame, bound: List[Dict[str, Any]]):
        """Score every freeze-bound fitted record on its own subset of ``frame`` into ``score__<name>``.

        Every subset row is scored, censored ones included: a candidate's score does not depend on
        its label, and an op that needs binary labels excludes and counts those rows itself
        (tail_lift reports ``rows_non_binary_label`` separately from ``rows_null_score``). Rows
        outside a record's subset stay null in that record's column. Returns the widened frame and
        one lineage record per model (rows scored, score digest for parity, authentication).
        """
        import numpy as np
        import pandas as pd
        from research_workflow.model_store import authenticate_model, read_manifest, score
        model_root = self.opts.model_root
        out = frame.copy()
        records: List[Dict[str, Any]] = []
        for m in bound:
            authentication = authenticate_model(m["id"], expect=m["expect"], model_root=model_root)
            inputs = list(read_manifest(m["id"], model_root)["lineage"]["ordered_inputs"])
            missing = [c for c in inputs if c not in out.columns]
            if missing:
                raise LifecycleV2Error(f"MODEL_INPUTS_UNBOUND: {m['name']} needs {missing}")
            mask = pd.Series(True, index=out.index)
            for col, val in (m.get("subset") or {}).items():
                if col not in out.columns:
                    raise LifecycleV2Error(f"MODEL_SUBSET_COLUMN_MISSING: {col}")
                mask &= out[col] == val
            column = f"score__{m['name']}"
            if column in out.columns:
                raise LifecycleV2Error(f"OWN_MODEL_SCORE_COLUMN_COLLIDES: {column!r} already exists in the analysis frame")
            out[column] = np.nan
            digest = None
            if bool(mask.any()):
                s = np.asarray(score(m["id"], out.loc[mask, inputs], model_root=model_root), dtype=float)
                out.loc[mask, column] = s
                digest = hashlib.sha256(np.round(s, 10).tobytes()).hexdigest()
            records.append({"name": m["name"], "id": m["id"], "column": column, "subset": dict(m.get("subset") or {}),
                            "inputs": inputs, "rows_scored": int(mask.sum()), "score_digest": digest,
                            "model_authentication": {k: authentication[k] for k in ("model_id", "identity_rule", "canonical_sha256",
                                                                                     "feature_contract_sha256", "golden", "tier", "selection_status")}})
        return out, records

    def _fit_score_mode(self, plan: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
        from research_workflow.forward_outcomes.guard import assert_causal_feature_surface
        frame = self._train_frame_all_labels(plan)
        scored = self._score_models(frame, model["models"])
        for m in scored:
            assert_causal_feature_surface(m["inputs"], context=f"frozen model {m['name']} inputs")
        merge_identity = _read(self.work / "merged" / "identity.json").get("candidates_identity")
        path = _write(self.artifacts / "experiment_models.json", {"schema_version": 2, "mode": "score", "plan_sha256": plan["plan_sha256"], "model_id": None,
                                                                   "reused_model_ids": [m["id"] for m in scored], "models": scored, "rows": {"total": int(len(frame))},
                                                                   "features": list(plan["columns"]["features"]), "training_population_identity": merge_identity,
                                                                   "model_authentication": [m["model_authentication"] for m in scored],
                                                                   "new_models_trained": False, "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)]}

    def freeze(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("freeze")
        from research_workflow.experiment import write_train_freeze
        plan = load_plan(self.study)
        # A study with no dev years has no protected OOS: there is no later stage whose access
        # this freeze would gate. Writing a normal TRAIN freeze would be a gate that vouches for
        # nothing, so the freeze records explicitly that no protected period exists. The stage
        # still produces its declared deliverable, so the deliverables contract is unchanged.
        if not (plan["chronology"].get("dev") or []):
            path = _write(self.artifacts / "train_experiment_freeze.json", {
                "schema_version": 1, "partition": "train", "platform": "v2",
                "status": "NO_PROTECTED_OOS", "protected_oos": False,
                "study_id": plan["study"]["id"], "plan_sha256": plan["plan_sha256"],
                "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                "feature_sets": {"primary": list(plan["columns"]["features"])}, "preprocessing_hash": "identity",
                "model_hashes": {}, "model_canonical_sha256": {}, "thresholds": {}, "deciles": {},
                "new_models_trained": False, "merge_identity": _read(self.work / "merged" / "identity.json"),
                "label_column": plan["outcome"].get("label_column"), "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)]}
        models = _read(self.artifacts / "experiment_models.json")
        ident = _read(self.work / "merged" / "identity.json")
        # W-1: bind the frozen record to the model's actual estimator BYTES, not only the
        # (lineage-derived) model_id -- a substituted estimator that refreshes its own
        # canonical/golden bytes under the unchanged model_id would otherwise authenticate
        # identically. model_canonical_sha256 keys by the same name as model_hashes.
        if models.get("model_id"):
            from research_workflow.model_store import read_manifest as _read_manifest
            manifest = _read_manifest(models["model_id"], self.opts.model_root)
            model_canonical_sha256 = {"primary": manifest.get("canonical", {}).get("byte_sha256")}
        elif models.get("mode") == "score":
            model_canonical_sha256 = {
                m["name"]: (m.get("model_authentication") or {}).get("canonical_sha256") for m in models.get("models") or []
            }
        else:
            # A multi-arm/multi-cell TRAIN fit: every (arm, cell) is its own stored model with its own
            # id, and the record carries no inline authentication block. Bind to the model store's
            # canonical BYTES exactly as the single-model branch does. Writing a null sha here instead
            # would leave a freeze that authenticates nothing while still reading as PASS.
            from research_workflow.model_store import read_manifest as _read_manifest
            model_canonical_sha256 = {}
            for m in models.get("models") or []:
                csha = (_read_manifest(_model_record_id(m), self.opts.model_root).get("canonical") or {}).get("byte_sha256")
                if not csha:
                    raise LifecycleV2Error(
                        f"FREEZE_CANONICAL_SHA_MISSING: model '{_model_record_name(m)}' has no canonical byte sha in the model store")
                model_canonical_sha256[_model_record_name(m)] = csha
        payload = {"partition": "train", "platform": "v2", "plan_sha256": plan["plan_sha256"],
                   "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                   "feature_sets": {"primary": list(plan["columns"]["features"])}, "preprocessing_hash": "identity",
                   "model_hashes": ({"primary": models["model_id"]} if models.get("model_id")
                                    else {_model_record_name(m): _model_record_id(m) for m in models.get("models") or []}),
                   "model_canonical_sha256": model_canonical_sha256,
                   "thresholds": {}, "deciles": {},
                   # Provenance is a fact of the FIT, not of whether that fit happened to mirror a
                   # single model to the top level. Keying either field on `model_id` made a
                   # multi-cell study's freeze declare that it trained no models and carry no TRAIN
                   # metrics -- a false record, in the artifact reuse paths and the platform cards read.
                   "new_models_trained": bool(models.get("new_models_trained") or models.get("model_id")),
                   "merge_identity": ident, "metrics": _model_record_metrics(models), "label_column": plan["outcome"].get("label_column")}
        path = write_train_freeze(self.study, payload)
        return {"status": "PASS", "outputs": [str(path)]}

    def oos(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("oos")
        plan = load_plan(self.study)
        # Nothing to open: a study that declared no dev years never had a protected period.
        # This is a receipt that the stage ran and found nothing authorized -- not a silent skip.
        if not (plan["chronology"].get("dev") or []):
            path = _write(self.work / "oos_no_protected_period.json", {
                "status": "NO_PROTECTED_OOS", "dev_years": [], "plan_sha256": plan["plan_sha256"],
                "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                "detail": "chronology.dev is empty; no protected out-of-sample period exists to open",
                "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)],
                    "partitions": [{"id": "oos-none", "status": "PASS", "rows": {"candidates": 0, "observations": 0}}]}
        from research_workflow.experiment import assert_oos_open
        assert_oos_open(self.study)
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        if self.current_composite() != frozen:
            raise LifecycleV2Error("TRAIN_CLOSURE_STALE: the plan closure changed after the TRAIN freeze")
        return self._collect_period("oos")

    def _declared_analysis(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Run the study's declared ``analysis:`` pipeline over its own collected frame.

        Steps run in declaration order (the compiler already proved the pipeline is a DAG and
        that every op is registered), each producing a frame that later steps may consume and a
        JSON-able payload. Only the artifacts the study DECLARED are written, so the analyze
        stage's deliverable set is knowable before execution and auditable after it.
        """
        import pandas as pd
        from research.analysis.ops import run_op
        from research.analysis.identity import canonical_sha256
        spec = plan["analysis"]
        if spec["source"] == "oos":
            from research_workflow.experiment import assert_oos_open
            assert_oos_open(self.study)
            base = self.work / "partitions" / "oos"
            years = [int(y) for y in self._authorized_years(plan, "oos", self.opts.years)]
            frame = self._train_frame_all_labels(plan, base, years)
        else:
            years = [int(y) for y in self._authorized_years(plan, "train", self.opts.years)]
            frame = self._train_frame_all_labels(plan)
        frames: Dict[str, Any] = {"frame": frame}
        refs = {s["rows"] for s in spec["steps"]} | {r for s in spec["steps"] for r in (s.get("inputs") or {}).values()}
        if "train_frame" in refs:
            # The compiler admits `train_frame` only under source: oos, where it is the TRAIN
            # partition beside the OOS frame (a threshold frozen on TRAIN, applied to OOS).
            frames["train_frame"] = self._train_frame_all_labels(plan)
        own_scores: Optional[Dict[str, Any]] = None
        if spec.get("model_scores"):
            label = plan["outcome"].get("label_column") or "target_flip_within_horizon"
            models_path = self.artifacts / "experiment_models.json"
            if not models_path.is_file():
                raise LifecycleV2Error("OWN_MODEL_SCORES_UNAVAILABLE: analysis.model_scores needs the fit stage's experiment_models.json")
            bound = self._freeze_bound_fitted_models(plan, _read(models_path), label)
            own_scores = {}
            for name in list(frames):
                frames[name], own_scores[name] = self._join_own_model_scores(frames[name], bound)
        # Machine-local resolution only -- never part of the plan identity: where an operator
        # keeps their files is not a scientific fact. `study_dir`/`model_root` let a gate read
        # THIS study's own execution artifacts (e.g. the fitted arms of `fit`, which precedes
        # `analyze`) without the study having to declare a path to itself.
        from research_workflow.analysis_pipeline import AnalysisPipelineError, run_pipeline
        context = {"studies_root": str(self.opts.studies_root or (self.repo_root / "studies")),
                   "study_dir": str(self.study), "artifacts_dir": str(self.artifacts),
                   "model_root": (str(self.opts.model_root) if self.opts.model_root else None)}
        try:
            ran = run_pipeline(spec["steps"], spec["artifacts"], frames, out_dir=self.artifacts, context=context)
        except AnalysisPipelineError as exc:
            raise LifecycleV2Error(str(exc)) from exc
        steps, written, payloads = ran["steps"], ran["artifacts"], ran["payloads"]
        lineage = {"source": spec["source"], "years": years, "rows": int(len(frame)),
                   "partition_windows": windows_identity((plan.get("chronology") or {}).get("windows") or []),
                   "plan_sha256": plan["plan_sha256"],
                   "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                   "ops": list(spec["ops"]), "steps": steps, "artifacts": written}
        if "train_frame" in frames:
            lineage["train_frame"] = {"years": [int(y) for y in self._authorized_years(plan, "train", self.opts.years)],
                                      "rows": int(len(frames["train_frame"]))}
        if own_scores is not None:
            # Keyed only when declared, so a study that never asked for its own scores keeps the
            # lineage (and analysis identity) it had before this key existed.
            lineage["model_scores"] = own_scores
        lineage["analysis_identity_sha256"] = canonical_sha256(lineage)
        return {"declared_analysis": lineage, "payloads": payloads}

    def analyze(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("analyze")
        import pandas as pd
        plan = load_plan(self.study)
        # A study that declares an `analysis:` pipeline is analysed by it. Its own declared
        # source decides whether the protected OOS gate applies: a train-source diagnostic
        # never opens a dev year, so demanding assert_oos_open of it would be a gate that
        # cannot vouch for anything it actually did.
        if plan.get("analysis"):
            declared = self._declared_analysis(plan)
            analyze_name = Path(DELIVERABLES["analyze"][0]).name
            path = _write(self.artifacts / analyze_name, {"schema_version": 2, "contract": plan["outcome"]["contract"],
                                                          "plan_sha256": plan["plan_sha256"], "authority": f"plan.analysis.source={plan['analysis']['source']}",
                                                          **declared, "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)] + [str(self.artifacts / a["name"]) for a in plan["analysis"]["artifacts"]]}
        from research_workflow.experiment import assert_oos_open
        assert_oos_open(self.study)
        label = plan["outcome"].get("label_column") or "target_flip_within_horizon"
        base = self.work / "partitions" / "oos"
        years = self._authorized_years(plan, "oos", self.opts.years)
        c = pd.concat([pd.read_parquet(base / str(y) / "candidates.parquet") for y in years], ignore_index=True)
        o = pd.concat([pd.read_parquet(base / str(y) / "observations.parquet") for y in years], ignore_index=True)
        frame = c.merge(o[list(KEY) + [label, "disposition"]], on=list(KEY), how="inner")
        summary: Dict[str, Any] = {"rows": int(len(frame)), "dispositions": frame["disposition"].value_counts().to_dict()}
        models = _read(self.artifacts / "experiment_models.json")
        # WARN-1: OOS scoring must be bound to the model bytes the TRAIN freeze committed to,
        # not merely to the (lineage-derived) model_id -- a post-freeze estimator substitution
        # that refreshes its own canonical/golden bytes under the unchanged model_id would
        # otherwise re-authenticate and score silently. Read the freeze's own recorded
        # canonical shas and pass them as `expect.canonical_sha256`.
        freeze_path = self.artifacts / "train_experiment_freeze.json"
        if not freeze_path.is_file():
            raise LifecycleV2Error(f"FREEZE_CANONICAL_SHA_MISSING: no TRAIN freeze found for study '{plan['study']['id']}'")
        freeze_canonical = _read(freeze_path).get("model_canonical_sha256") or {}
        if models.get("mode") == "score":
            bound_models = []
            for m in models["models"]:
                csha = freeze_canonical.get(m["name"])
                if not csha:
                    raise LifecycleV2Error(f"FREEZE_CANONICAL_SHA_MISSING: model '{m['name']}' has no TRAIN freeze canonical sha")
                expect = dict(m.get("expect") or {})
                expect["canonical_sha256"] = csha
                bound_models.append({**m, "expect": expect})
            summary["frozen_models_oos"] = self._score_models(self._train_frame_all_labels(plan, base, [int(y) for y in years]), bound_models)
            summary["train_metrics"] = [{k: m[k] for k in ("name", "id", "metrics_by_year")} for m in models["models"]]
        elif models.get("model_id"):
            from research.analysis.metrics import brier, pr_auc, roc_auc
            from research_workflow.model_store import authenticate_model, score
            csha = freeze_canonical.get("primary")
            if not csha:
                raise LifecycleV2Error("FREEZE_CANONICAL_SHA_MISSING: no primary canonical sha in TRAIN freeze")
            authentication = authenticate_model(models["model_id"], expect={"study_id": plan["study"]["id"], "canonical_sha256": csha}, model_root=self.opts.model_root)
            binary = frame[frame[label].isin([0, 1, 0.0, 1.0])]
            s = score(models["model_id"], binary[models["features"]], model_root=self.opts.model_root)
            summary["oos_metrics"] = {"n": int(len(binary)), "roc_auc": roc_auc(binary[label], s).to_dict().get("value"),
                                      "pr_auc": pr_auc(binary[label], s).to_dict().get("value"), "brier": brier(binary[label], s).to_dict().get("value")}
            summary["train_metrics"] = models.get("metrics")
            summary["model_authentication"] = {k: authentication[k] for k in ("model_id", "identity_rule", "canonical_sha256", "feature_contract_sha256", "golden", "tier", "selection_status")}
        elif models.get("models"):
            # A multi-arm/multi-cell frozen fit. Score every trained cell on its OWN declared subset,
            # each bound to the canonical bytes the TRAIN freeze committed to (WARN-1), so a post-freeze
            # estimator substitution cannot re-authenticate under the unchanged model_id. Without this
            # branch the stage fell through every case and wrote an analysis carrying no OOS metric at
            # all -- a deliverable that reads as PASS while vouching for nothing.
            bound_models = self._freeze_bound_fitted_models(plan, models, label)
            summary["frozen_models_oos"] = self._score_models(self._train_frame_all_labels(plan, base, [int(y) for y in years]), bound_models)
            summary["train_metrics"] = [{"name": _model_record_name(m), "id": _model_record_id(m),
                                         "direction": m.get("direction"), "subset": _model_record_subset(m),
                                         "metrics": m.get("metrics")} for m in models["models"]]
        elif models:
            # An experiment_models.json that exists but matches no scorable shape must fail loudly:
            # falling through silently is what produced an OOS deliverable with no metrics.
            raise LifecycleV2Error(
                f"OOS_MODEL_RECORDS_UNRECOGNISED: experiment_models.json (mode={models.get('mode')!r}) carries no scorable models")
        analyze_name = Path(DELIVERABLES["analyze"][0]).name
        path = _write(self.artifacts / analyze_name, {"schema_version": 2, "contract": plan["outcome"]["contract"], "plan_sha256": plan["plan_sha256"],
                                                                        "oos_years": list(years), "authority": "plan.chronology.dev", **summary, "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)]}

    def close(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("close")
        closure = self.opts.closure or {}
        if not closure.get("outcome") or not closure.get("terminal_decision"):
            raise LifecycleV2Error("CLOSURE_DECISION_REQUIRED: --closure-outcome and --closure-decision")
        seal_path = self.artifacts / "preexec_audit_seal.json"
        seal = _read(seal_path)
        bound: Dict[str, Any] = {"preexec_seal_artifact_sha256": _sha(seal_path), "preexec_seal_composite_sha256": seal.get("composite_seal_hash")}
        freeze = self.artifacts / "train_experiment_freeze.json"
        if freeze.is_file():
            bound["train_freeze_sha256"] = _read(freeze).get("freeze_sha256") or _sha(freeze)
        from research_workflow.study_closure import V2_FINAL_EVIDENCE
        for key, rel in V2_FINAL_EVIDENCE.items():
            evidence = self.study / rel
            if evidence.is_file():
                binding: Dict[str, Any] = {"path": rel, "artifact_file_sha256": _sha(evidence)}
                if key == "v2_analysis":
                    # Fresh means produced from THIS plan and THIS TRAIN freeze (study_closure
                    # verifies it against the artifact's own plan_sha256 and the freeze's models).
                    binding["plan_sha256"] = (_read(evidence) or {}).get("plan_sha256")
                    if "train_freeze_sha256" in bound:
                        binding["train_freeze_sha256"] = bound["train_freeze_sha256"]
                bound[key] = binding
        body = {"schema_version": 1, "study_id": self.study.name, "status": "CLOSED", "outcome": str(closure["outcome"]), "terminal_decision": str(closure["terminal_decision"]),
                "platform": "v2", "plan_sha256": load_plan(self.study).get("plan_sha256"), "closed_at_utc": _now(), "bound_evidence": bound}
        # DEV-08: validate BEFORE the closure persists, and never leave a rejected closure on disk -- a rejected
        # closure that remained was later honoured as the study's terminal authority.
        from research_workflow.study_closure import _validate_terminal_decision, load_study_closure
        _validate_terminal_decision(self.study, body["terminal_decision"])
        target = self.artifacts / "study_closure.json"
        path = _write(target, body)
        try:
            load_study_closure(self.study)
        except Exception:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        return {"status": "PASS", "outputs": [str(path)]}


# --------------------------------------------------------------------------- #
# audit ingestion (v2)
# --------------------------------------------------------------------------- #
def ingest_audit_report(study: Path, audit_type: str, report: Path, author: Optional[str] = None) -> Dict[str, Any]:
    from scripts.run_preexec_audits import _extract_v2_summary
    study = Path(study).resolve(); report = Path(report).resolve()
    text = report.read_text(encoding="utf-8")
    summary = _extract_v2_summary(text, report, expected_audit_type=audit_type)
    frozen = _read(study / "audit" / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
    if summary.get("study") != study.name:
        raise LifecycleV2Error(f"AUDIT_STUDY_MISMATCH: {summary.get('study')} != {study.name}")
    if summary.get("audited_execution_composite_sha256") != frozen:
        raise LifecycleV2Error("AUDIT_COMPOSITE_STALE: the report names a composite that is not the frozen plan closure")
    auditor = summary.get("auditor") or author
    if not auditor:
        raise LifecycleV2Error("AUDITOR_REQUIRED")
    other = _read(study / "audit" / ("contract_status.json" if audit_type == "causal" else "status.json"))
    if other.get("auditor") and other.get("auditor") == auditor:
        raise LifecycleV2Error("AUDITOR_ROLE_REUSE: causal and contract auditors must be distinct identities")
    name = "status.json" if audit_type == "causal" else "contract_status.json"
    counts = {k: int(summary.get(k, 0) or 0) for k in ("critical", "warning", "note")}
    verdict = summary["verdict"]
    if verdict == "CLEAR" and counts["critical"] > 0:
        verdict = "BLOCKED"
    body = {"audit_type": audit_type, "auditor": auditor, "verdict": verdict, **counts, "audited_execution_composite_sha256": frozen,
            "audit_report_sha256": _sha(report), "audit_report_path": str(report.relative_to(study)) if study in report.parents else str(report),
            "derived_by_parser": "research_workflow.lifecycle_v2.ingest_audit_report", "platform": "v2", "issued_at_utc": _now()}
    path = _write(study / "audit" / name, body)
    return {"STATUS": "OK" if verdict == "CLEAR" else "BLOCKED", "status_path": str(path), **{k: body[k] for k in ("audit_type", "auditor", "verdict", "critical", "warning", "note")}}


# --------------------------------------------------------------------------- #
# child entry point (partitions)
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("partition")
    p.add_argument("--study", required=True); p.add_argument("--period", required=True); p.add_argument("--year", type=int, required=True)
    p.add_argument("--out-dir", required=True); p.add_argument("--progress"); p.add_argument("--repo-root"); p.add_argument("--studies-root")
    p.add_argument("--windows", help="comma-separated declared window ids/ranges this child may execute")
    p.add_argument("--chunked-batch-rows", type=int, default=0, help="see V2Options.chunked_batch_rows")
    p.add_argument("--chunked-batch-bytes", type=int, default=None, help="see V2Options.chunked_batch_bytes")
    ns = ap.parse_args(argv)
    if ns.cmd == "partition":
        child_kwargs = dict(studies_root=Path(ns.studies_root) if ns.studies_root else None,
                            windows=[w for w in (ns.windows or "").split(",") if w.strip()] or None,
                            chunked_batch_rows=ns.chunked_batch_rows)
        if ns.chunked_batch_bytes is not None:
            child_kwargs["chunked_batch_bytes"] = ns.chunked_batch_bytes
        opts = V2Options(**child_kwargs)
        lc = V2Lifecycle(Path(ns.study), repo_root=Path(ns.repo_root) if ns.repo_root else REPO_ROOT, options=opts)
        manifest = lc.run_partition(ns.year, ns.period, Path(ns.out_dir), progress=Path(ns.progress) if ns.progress else None)
        print(json.dumps({"STATUS": "OK", "partition": manifest.get("id"), "rows": manifest.get("rows")}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
