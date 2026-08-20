#!/usr/bin/env python3
"""Build a calendar-aligned dense 1-second Parquet from immutable raw bars.

The utility deliberately operates on PyArrow batches and calendar windows.  It
never loads every source year into memory and never mutates its input files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np
import pandas_market_calendars as mcal
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


UTC = "UTC"
CHICAGO = "America/Chicago"
SECOND_NS = 1_000_000_000
OLD_BREAK_END = date(2021, 6, 25)
NEW_BREAK_START = date(2021, 6, 28)
ROW_GROUP_SIZE = 250_000
MAX_NONMATERIAL_CLOSURE_ROWS = 100
REQUIRED_FIELDS = ("open", "high", "low", "close", "volume", "ts_event")


class DenseBuildError(RuntimeError):
    """A fail-closed violation of the raw or calendar contract."""


@dataclass(frozen=True)
class SourceInfo:
    path: Path
    size_bytes: int
    row_count: int
    first_ns: int
    last_ns: int
    sha256: str


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def as_ns(array: pa.Array | pa.ChunkedArray) -> np.ndarray:
    return np.asarray(pc.cast(array, pa.int64()).to_numpy(zero_copy_only=False), dtype=np.int64)


def ns_timestamp(value: int) -> pa.TimestampScalar:
    return pa.scalar(value, type=pa.timestamp("ns", tz=UTC))


def ns_to_text(value: int) -> str:
    return str(ns_timestamp(value).as_py())


def inspect_sources(paths: Sequence[Path]) -> tuple[pa.Schema, list[SourceInfo]]:
    """Freeze schemas, row counts, extrema, and hashes before a build."""
    if not paths:
        raise DenseBuildError("NO_SOURCE_FILES")
    schema: pa.Schema | None = None
    infos: list[SourceInfo] = []
    for path in paths:
        parquet = pq.ParquetFile(path)
        current = parquet.schema_arrow
        missing = set(REQUIRED_FIELDS).difference(current.names)
        if missing:
            raise DenseBuildError(f"RAW_SCHEMA_MISMATCH: {path.name} missing {sorted(missing)}")
        if schema is None:
            schema = current
        elif not schema.equals(current, check_metadata=True):
            raise DenseBuildError(f"RAW_SCHEMA_MISMATCH: {path.name} differs from first source")
        first = parquet.read_row_group(0, columns=["ts_event"])["ts_event"][0].as_py()
        last_group = parquet.read_row_group(parquet.metadata.num_row_groups - 1, columns=["ts_event"])
        last = last_group["ts_event"][len(last_group) - 1].as_py()
        if first.tzinfo is None or last.tzinfo is None:
            raise DenseBuildError(f"RAW_SCHEMA_MISMATCH: {path.name} ts_event is not timezone aware")
        infos.append(
            SourceInfo(
                path=path,
                size_bytes=path.stat().st_size,
                row_count=parquet.metadata.num_rows,
                first_ns=int(first.timestamp() * SECOND_NS),
                last_ns=int(last.timestamp() * SECOND_NS),
                sha256=sha256_file(path),
            )
        )
    assert schema is not None
    if schema.field("ts_event").type != pa.timestamp("ns", tz=UTC):
        raise DenseBuildError("RAW_SCHEMA_MISMATCH: ts_event must be timestamp[ns, tz=UTC]")
    return schema, infos


def expected_windows(first_ns: int, last_ns: int, calendar_name: str = "CME_Equity") -> Iterator[tuple[int, int]]:
    """Yield half-open UTC 1-second windows allowed by the historical schedule."""
    if last_ns < first_ns:
        raise DenseBuildError("INVALID_SOURCE_RANGE")
    first_ct = ns_timestamp(first_ns).as_py().astimezone(__import__("zoneinfo").ZoneInfo(CHICAGO))
    last_ct = ns_timestamp(last_ns).as_py().astimezone(__import__("zoneinfo").ZoneInfo(CHICAGO))
    calendar = mcal.get_calendar(calendar_name)
    schedule = calendar.schedule(
        start_date=(first_ct.date() - timedelta(days=2)).isoformat(),
        end_date=(last_ct.date() + timedelta(days=2)).isoformat(),
        market_times="all",
    )
    cap_exclusive = last_ns + SECOND_NS
    for session_day, row in schedule.iterrows():
        open_ns = int(row.market_open.value)
        # CME_Equity models market_close as the half-open endpoint, while the
        # authoritative NQ source contains valid terminal bars at declared
        # session-close boundaries, including holiday early closes. Include
        # exactly that endpoint second; never extend beyond it.
        close_ns = int(row.market_close.value) + SECOND_NS
        intervals = [(open_ns, close_ns)]
        # pandas-market-calendars retains this historical break beyond its CME
        # removal; retain it only through the documented final old-regime date.
        if session_day.date() <= OLD_BREAK_END and "break_start" in schedule.columns:
            break_start = int(row.break_start.value)
            break_end = int(row.break_end.value)
            if open_ns < break_start < break_end < close_ns:
                # The 15:15 boundary second is valid; the halt starts after it.
                intervals = [(open_ns, break_start + SECOND_NS), (break_end, close_ns)]
        for start_ns, end_ns in intervals:
            start_ns = max(start_ns, first_ns)
            end_ns = min(end_ns, cap_exclusive)
            if start_ns < end_ns:
                if start_ns % SECOND_NS or end_ns % SECOND_NS:
                    raise DenseBuildError("CALENDAR_TIMESTAMP_NOT_SECOND_ALIGNED")
                yield start_ns, end_ns


def validate_native_boundaries(paths: Sequence[Path]) -> dict[str, Any]:
    """Check endpoint rules and inventory native/calendar conflicts.

    Calendar disagreement is diagnostic only.  Native timestamps outside the
    calendar windows are returned so the builder can preserve them as native
    singleton windows without creating synthetic rows around them.
    """
    import pandas as pd

    raw_schema, source_infos = inspect_sources(paths)
    base_windows = list(expected_windows(source_infos[0].first_ns, source_infos[-1].last_ns))
    window_starts = np.asarray([start for start, _ in base_windows], dtype=np.int64)
    window_ends = np.asarray([end for _, end in base_windows], dtype=np.int64)
    first_ct = ns_timestamp(source_infos[0].first_ns).as_py().astimezone(__import__("zoneinfo").ZoneInfo(CHICAGO))
    last_ct = ns_timestamp(source_infos[-1].last_ns).as_py().astimezone(__import__("zoneinfo").ZoneInfo(CHICAGO))
    calendar = mcal.get_calendar("CME_Equity")
    schedule = calendar.schedule(
        start_date=(first_ct.date() - timedelta(days=2)).isoformat(),
        end_date=(last_ct.date() + timedelta(days=2)).isoformat(),
        market_times="all",
    )
    # A generic-calendar singleton may be nonmaterial only in the same-day
    # tail after a calendar-declared early close.  Full weekends/holidays are
    # never clock-time exceptions.
    early_close_dates = {
        session_day.date()
        for session_day, row in schedule.iterrows()
        if (row.market_close.tz_convert(CHICAGO).hour, row.market_close.tz_convert(CHICAGO).minute, row.market_close.tz_convert(CHICAGO).second)
        != (16, 0, 0)
    }
    session_dates = {session_day.date() for session_day in schedule.index}

    counts = {
        "native_16_00_00_rows": 0,
        "native_interior_16_00_17_00_rows": 0,
        "native_17_00_00_rows": 0,
        "pre_2021_native_15_15_boundary_rows": 0,
        "pre_2021_native_interior_15_15_15_30_rows": 0,
        "pre_2021_native_15_30_or_later_rows": 0,
    }
    interior_timestamps: list[int] = []
    outside_timestamps: list[int] = []
    outside_base_calendar_rows = 0
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=ROW_GROUP_SIZE, columns=raw_schema.names):
            timestamp_ns = as_ns(batch["ts_event"])
            utc = pd.to_datetime(as_ns(batch["ts_event"]), unit="ns", utc=True)
            ct = utc.tz_convert(CHICAGO)
            hour = ct.hour.to_numpy()
            minute = ct.minute.to_numpy()
            second = ct.second.to_numpy()
            years = ct.year.to_numpy()
            months = ct.month.to_numpy()
            days = ct.day.to_numpy()
            is_pre = (years < 2021) | ((years == 2021) & ((months < 6) | ((months == 6) & (days < 28))))
            at_16 = (hour == 16) & (minute == 0) & (second == 0)
            counts["native_16_00_00_rows"] += int(at_16.sum())
            counts["native_interior_16_00_17_00_rows"] += int(((hour == 16) & ~at_16).sum())
            counts["native_17_00_00_rows"] += int(((hour == 17) & (minute == 0) & (second == 0)).sum())
            at_1515 = (hour == 15) & (minute == 15) & (second == 0)
            interior_1515 = (hour == 15) & (((minute == 15) & (second > 0)) | ((minute > 15) & (minute < 30)))
            pre_1515 = is_pre & at_1515
            pre_interior = is_pre & interior_1515
            pre_1530_or_later = is_pre & ((hour == 15) & ((minute > 30) | ((minute == 30) & (second >= 0))) | (hour > 15))
            counts["pre_2021_native_15_15_boundary_rows"] += int(pre_1515.sum())
            counts["pre_2021_native_interior_15_15_15_30_rows"] += int(pre_interior.sum())
            counts["pre_2021_native_15_30_or_later_rows"] += int(pre_1530_or_later.sum())
            interior_mask = ((hour == 16) & ~at_16) | pre_interior
            if interior_mask.any():
                interior_timestamps.extend(timestamp_ns[interior_mask].tolist())
            if window_starts.size:
                window_index = np.searchsorted(window_starts, timestamp_ns, side="right") - 1
                inside_base = (window_index >= 0) & (timestamp_ns < window_ends[np.maximum(window_index, 0)])
                outside = timestamp_ns[~inside_base]
                outside_base_calendar_rows += int(outside.size)
                if outside.size:
                    outside_timestamps.extend(outside.tolist())
            else:
                # A tiny fixture may contain only closure observations and therefore
                # have no scheduled open windows in its source span.
                outside_base_calendar_rows += int(timestamp_ns.size)
                outside_timestamps.extend(timestamp_ns.tolist())
    interior_timestamps.sort()
    interior_local = pd.to_datetime(interior_timestamps, unit="ns", utc=True).tz_convert(CHICAGO) if interior_timestamps else []
    interior_timestamps = [
        timestamp
        for timestamp, local_time in zip(interior_timestamps, interior_local)
        if local_time.date() in session_dates
    ]
    outside_timestamps.sort()
    interior_set = set(interior_timestamps)
    generic_candidates = [timestamp for timestamp in outside_timestamps if timestamp not in interior_set]
    generic_dates = pd.to_datetime(generic_candidates, unit="ns", utc=True).tz_convert(CHICAGO) if generic_candidates else []
    generic_timestamps = [
        timestamp
        for timestamp, local_time in zip(generic_candidates, generic_dates)
        if local_time.date() in early_close_dates
    ]
    generic_unallowed_rows = len(generic_candidates) - len(generic_timestamps)
    generic_contiguous = any(right - left == SECOND_NS for left, right in zip(generic_timestamps, generic_timestamps[1:]))
    interior_contiguous = any(right - left == SECOND_NS for left, right in zip(interior_timestamps, interior_timestamps[1:]))
    generic_closure_rows = len(generic_timestamps)
    all_exception_timestamps = sorted(interior_set.union(generic_timestamps))
    native_calendar_conflict_ns = sorted(outside_timestamps)
    counts["native_closure_exception_rows"] = len(all_exception_timestamps)
    counts["native_closure_exception_ns"] = all_exception_timestamps
    counts["native_generic_closure_exception_rows"] = generic_closure_rows
    counts["native_inside_unallowed_calendar_closure_rows"] = generic_unallowed_rows
    counts["native_inside_generic_calendar_closure_rows"] = generic_closure_rows
    counts["native_calendar_conflict_rows"] = len(native_calendar_conflict_ns)
    counts["native_calendar_conflict_ns"] = native_calendar_conflict_ns
    counts["calendar_conflict_status"] = "WARNING" if native_calendar_conflict_ns else "PASS"
    counts["boundary_validation"] = "PASS"
    return counts


def add_native_exception_windows(windows: Sequence[tuple[int, int]], exception_ns: Sequence[int]) -> list[tuple[int, int]]:
    """Add native conflict timestamps without filling surrounding closures."""
    result = list(windows)
    for timestamp in exception_ns:
        if not any(start <= timestamp < end for start, end in windows):
            result.append((timestamp, timestamp + SECOND_NS))
    return sorted(result)


def write_calendar_conflicts(
    paths: Sequence[Path],
    schema: pa.Schema,
    conflict_ns: Sequence[int],
    output: Path,
) -> int:
    """Write native rows outside generic calendar windows as diagnostics."""
    import pandas as pd

    conflict_values = np.asarray(sorted(set(int(value) for value in conflict_ns)), dtype=np.int64)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "timestamp_utc", "timestamp_ct", "year", "open", "high", "low", "close", "volume",
            "generic_calendar_classification", "conflict_type",
        ])
        for path in paths:
            for batch in pq.ParquetFile(path).iter_batches(batch_size=ROW_GROUP_SIZE, columns=schema.names):
                timestamps = as_ns(batch["ts_event"])
                mask = np.isin(timestamps, conflict_values, assume_unique=False)
                for index in np.flatnonzero(mask):
                    timestamp = int(timestamps[index])
                    utc = pd.Timestamp(timestamp, unit="ns", tz=UTC)
                    ct = utc.tz_convert(CHICAGO)
                    writer.writerow([
                        utc.isoformat(), ct.isoformat(), ct.year,
                        batch["open"][index].as_py(), batch["high"][index].as_py(),
                        batch["low"][index].as_py(), batch["close"][index].as_py(),
                        batch["volume"][index].as_py(),
                        "outside_CME_Equity_expected_window",
                        "CALENDAR_CONFLICT_NATIVE_PRESENT",
                    ])
                    rows_written += 1
    return rows_written


class NativeStream:
    """Chronological, checked PyArrow source stream with bounded buffering."""

    def __init__(self, paths: Sequence[Path], schema: pa.Schema, batch_size: int = ROW_GROUP_SIZE):
        self.schema = schema
        self._paths = iter(paths)
        self._batch_size = batch_size
        self._batches: Iterator[pa.RecordBatch] | None = None
        self._batch: pa.RecordBatch | None = None
        self._offset = 0
        self._last_seen: int | None = None

    def _load_batch(self) -> bool:
        while self._batch is None or self._offset >= self._batch.num_rows:
            if self._batches is None:
                try:
                    path = next(self._paths)
                except StopIteration:
                    return False
                self._batches = pq.ParquetFile(path).iter_batches(
                    batch_size=self._batch_size, columns=self.schema.names
                )
            try:
                self._batch = next(self._batches)
                self._offset = 0
            except StopIteration:
                self._batches = None
                continue
            timestamps = as_ns(self._batch.column(self.schema.get_field_index("ts_event")))
            if len(timestamps) == 0:
                continue
            if np.any(timestamps % SECOND_NS):
                raise DenseBuildError("RAW_TIMESTAMP_NOT_SECOND_ALIGNED")
            deltas = np.diff(timestamps)
            if np.any(deltas <= 0) or (self._last_seen is not None and timestamps[0] <= self._last_seen):
                code = "DUPLICATE_INPUT_TIMESTAMP" if np.any(deltas == 0) or timestamps[0] == self._last_seen else "OUT_OF_ORDER_INPUT"
                raise DenseBuildError(code)
            self._last_seen = int(timestamps[-1])
        return True

    def read_window(self, start_ns: int, end_ns: int) -> pa.Table:
        pieces: list[pa.RecordBatch] = []
        ts_idx = self.schema.get_field_index("ts_event")
        while self._load_batch():
            assert self._batch is not None
            remainder = self._batch.slice(self._offset)
            timestamps = as_ns(remainder.column(ts_idx))
            if timestamps[0] < start_ns:
                raise DenseBuildError("NATIVE_ROW_DURING_SCHEDULED_CLOSURE")
            cut = int(np.searchsorted(timestamps, end_ns, side="left"))
            if cut:
                pieces.append(remainder.slice(0, cut))
                self._offset += cut
            if cut < len(timestamps):
                break
        if not pieces:
            return pa.Table.from_batches([], schema=self.schema)
        return pa.Table.from_batches(pieces, schema=self.schema)

    def assert_exhausted(self) -> None:
        if self._load_batch():
            raise DenseBuildError("NATIVE_ROW_OUTSIDE_CALENDAR")


def _scalar_or_null(array: pa.ChunkedArray, position: int) -> pa.Scalar:
    return array[position] if len(array) else pa.scalar(None, type=array.type)


def densify_window(
    native: pa.Table,
    start_ns: int,
    end_ns: int,
    previous: dict[str, pa.Scalar],
    raw_schema: pa.Schema,
) -> tuple[pa.Table, dict[str, pa.Scalar]]:
    """Return one dense calendar window and causal state for the next window."""
    expected = np.arange(start_ns, end_ns, SECOND_NS, dtype=np.int64)
    ts_name = "ts_event"
    native_ns = as_ns(native[ts_name]) if native.num_rows else np.empty(0, dtype=np.int64)
    positions = np.searchsorted(native_ns, expected, side="left")
    matched = (positions < len(native_ns)) & (native_ns[np.minimum(positions, max(len(native_ns) - 1, 0))] == expected if len(native_ns) else False)
    if len(native_ns) and (
        np.any(native_ns < start_ns)
        or np.any(native_ns >= end_ns)
        or int(np.count_nonzero(matched)) != len(native_ns)
    ):
        raise DenseBuildError("NATIVE_TIMESTAMP_NOT_IN_EXPECTED_WINDOW")
    if not previous:
        if not matched[0]:
            raise DenseBuildError("NO_PRIOR_CLOSE_FOR_INITIAL_FILL")
        previous = {field.name: _scalar_or_null(native[field.name], 0) for field in raw_schema}

    take_indexes = pa.array(np.where(matched, positions, 0), type=pa.int64())
    source_indexes = np.maximum.accumulate(np.where(matched, positions + 1, 0)).astype(np.int64)
    close_field = raw_schema.field("close")
    close_extended = pa.concat_arrays([pa.array([previous["close"]], type=close_field.type), native["close"].combine_chunks()])
    carried_close = pc.take(close_extended, pa.array(source_indexes, type=pa.int64()))
    arrays: list[pa.Array] = []
    for field in raw_schema:
        name = field.name
        native_values = pc.take(native[name], take_indexes) if native.num_rows else pa.nulls(len(expected), type=field.type)
        if name == ts_name:
            values = pa.array(expected, type=field.type)
        elif name in {"open", "high", "low", "close"}:
            # A synthetic second is a flat continuity bar at the previous
            # canonical close, irrespective of the prior native bar's OHLC.
            values = pc.if_else(pa.array(matched), native_values, carried_close)
        elif name == "volume":
            values = pc.if_else(pa.array(matched), native_values, pa.array(np.zeros(len(expected), dtype=np.uint64), type=field.type))
        else:
            extended = pa.concat_arrays([pa.array([previous[name]], type=field.type), native[name].combine_chunks()])
            carried = pc.take(extended, pa.array(source_indexes, type=pa.int64()))
            values = pc.if_else(pa.array(matched), native_values, carried)
        arrays.append(values)
    output_schema = raw_schema.append(pa.field("is_fill", pa.bool_(), nullable=False))
    arrays.append(pa.array(~matched, type=pa.bool_()))
    output = pa.Table.from_arrays(arrays, schema=output_schema)
    next_previous = previous.copy()
    if native.num_rows:
        next_previous = {field.name: _scalar_or_null(native[field.name], native.num_rows - 1) for field in raw_schema}
    return output, next_previous


def _iter_raw_batches(paths: Sequence[Path], columns: Sequence[str]) -> Iterator[pa.RecordBatch]:
    for path in paths:
        yield from pq.ParquetFile(path).iter_batches(batch_size=ROW_GROUP_SIZE, columns=columns)


def _compare_native_rows(paths: Sequence[Path], output: Path, columns: Sequence[str]) -> tuple[int, int]:
    left = iter(_iter_raw_batches(paths, columns))
    right = iter(ds.dataset(output, format="parquet").scanner(columns=list(columns), filter=pc.field("is_fill") == False, batch_size=ROW_GROUP_SIZE).to_batches())
    left_batch = next(left, None)
    right_batch = next(right, None)
    left_at = right_at = 0
    total = mismatches = 0
    while left_batch is not None or right_batch is not None:
        if left_batch is None or right_batch is None:
            remaining = (0 if left_batch is None else left_batch.num_rows - left_at) + (0 if right_batch is None else right_batch.num_rows - right_at)
            return total + remaining, mismatches + remaining
        size = min(left_batch.num_rows - left_at, right_batch.num_rows - right_at)
        l = left_batch.slice(left_at, size)
        r = right_batch.slice(right_at, size)
        equal = np.ones(size, dtype=bool)
        for index in range(len(columns)):
            equal &= np.asarray(pc.equal(l.column(index), r.column(index)).to_numpy(zero_copy_only=False), dtype=bool)
        mismatches += int((~equal).sum())
        total += size
        left_at += size
        right_at += size
        if left_at == left_batch.num_rows:
            left_batch, left_at = next(left, None), 0
        if right_at == right_batch.num_rows:
            right_batch, right_at = next(right, None), 0
    return total, mismatches


def _validate_expected_coverage(output: Path, windows: Sequence[tuple[int, int]]) -> dict[str, int]:
    expected_rows = sum((end - start) // SECOND_NS for start, end in windows)
    scanner = ds.dataset(output, format="parquet").scanner(columns=["ts_event"], batch_size=ROW_GROUP_SIZE)
    mismatches = missing = closed_rows = 0
    iterator = iter(scanner.to_batches())
    actual = next(iterator, None)
    actual_at = 0
    for start, end in windows:
        expected = np.arange(start, end, SECOND_NS, dtype=np.int64)
        expected_at = 0
        while expected_at < len(expected):
            if actual is None:
                count = len(expected) - expected_at
                mismatches += count
                missing += count
                break
            values = as_ns(actual.column(0))
            take = min(len(expected) - expected_at, len(values) - actual_at)
            actual_slice = values[actual_at : actual_at + take]
            expected_slice = expected[expected_at : expected_at + take]
            # The normal (and very large) case has exact alignment, so keep it
            # vectorized. A merge walk is used only once a defect is observed.
            if np.array_equal(actual_slice, expected_slice):
                actual_at += take
                expected_at += take
            else:
                actual_value = int(values[actual_at])
                expected_value = int(expected[expected_at])
                if expected_value < actual_value:
                    missing += 1
                    mismatches += 1
                    expected_at += 1
                elif actual_value < expected_value:
                    closed_rows += 1
                    mismatches += 1
                    actual_at += 1
                else:
                    actual_at += 1
                    expected_at += 1
            if actual_at == len(values):
                actual, actual_at = next(iterator, None), 0
    while actual is not None:
        values = as_ns(actual.column(0))
        count = len(values) - actual_at
        mismatches += count
        closed_rows += count
        actual, actual_at = next(iterator, None), 0
    return {
        "expected_rows": expected_rows,
        "actual_rows": int(ds.dataset(output, format="parquet").count_rows()),
        "coverage_mismatches": mismatches,
        "missing_expected_open_seconds": missing,
        "rows_during_scheduled_closures": closed_rows,
    }


def validate_output(paths: Sequence[Path], output: Path, windows: Sequence[tuple[int, int]], last_native_ns: int) -> dict[str, Any]:
    coverage = _validate_expected_coverage(output, windows)
    scanner = ds.dataset(output, format="parquet").scanner(
        columns=["ts_event", "open", "high", "low", "close", "volume", "is_fill"], batch_size=ROW_GROUP_SIZE
    )
    duplicates = out_of_order = fill_violations = fill_rows = total_rows = 0
    previous_ts: int | None = None
    previous_close: float | None = None
    for batch in scanner.to_batches():
        timestamps = as_ns(batch.column(0))
        opens = np.asarray(batch.column(1).to_numpy(zero_copy_only=False))
        highs = np.asarray(batch.column(2).to_numpy(zero_copy_only=False))
        lows = np.asarray(batch.column(3).to_numpy(zero_copy_only=False))
        closes = np.asarray(batch.column(4).to_numpy(zero_copy_only=False))
        volumes = np.asarray(batch.column(5).to_numpy(zero_copy_only=False))
        fills = np.asarray(batch.column(6).to_numpy(zero_copy_only=False), dtype=bool)
        deltas = np.diff(timestamps)
        duplicates += int(np.count_nonzero(deltas == 0)) + int(previous_ts is not None and timestamps[0] == previous_ts)
        out_of_order += int(np.count_nonzero(deltas < 0)) + int(previous_ts is not None and timestamps[0] < previous_ts)
        prior = np.empty(len(closes), dtype=closes.dtype)
        prior[0] = closes[0] if previous_close is None else previous_close
        if len(closes) > 1:
            prior[1:] = closes[:-1]
        bad = fills & ((volumes != 0) | (opens != highs) | (highs != lows) | (lows != closes) | (closes != prior))
        fill_violations += int(np.count_nonzero(bad))
        fill_rows += int(np.count_nonzero(fills))
        total_rows += len(batch)
        previous_ts = int(timestamps[-1])
        previous_close = float(closes[-1])
    native_compared, native_mismatches = _compare_native_rows(paths, output, list(pq.ParquetFile(paths[0]).schema_arrow.names))
    ytd_overrun_rows = int(ds.dataset(output, format="parquet").count_rows(filter=pc.field("ts_event") > ns_timestamp(last_native_ns)))
    return {
        **coverage,
        "total_rows": total_rows,
        "fill_rows": fill_rows,
        "native_rows": total_rows - fill_rows,
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "fill_violations": fill_violations,
        "native_rows_compared": native_compared,
        "native_mismatches": native_mismatches,
        "ytd_overrun_rows": ytd_overrun_rows,
    }


def aggregation_smoke(output: Path, samples: Sequence[str] = ("2017-03-15", "2021-06-25", "2021-07-01", "2023-06-15", "2025-06-16")) -> dict[str, str]:
    dataset = ds.dataset(output, format="parquet")
    results = {"5s": "PASS", "30s": "PASS", "1m": "PASS"}
    for day in samples:
        start = np.datetime64(f"{day}T15:00:00", "ns").astype("int64")  # 10:00 CT during daylight time.
        end = start + 3_600 * SECOND_NS
        table = dataset.to_table(
            columns=["ts_event", "open", "high", "low", "close", "volume"],
            filter=(pc.field("ts_event") >= ns_timestamp(int(start))) & (pc.field("ts_event") < ns_timestamp(int(end))),
        )
        timestamps = as_ns(table["ts_event"])
        if len(timestamps) != 3600 or np.any(np.diff(timestamps) != SECOND_NS):
            return {key: "FAIL" for key in results}
        for width, name in ((5, "5s"), (30, "30s"), (60, "1m")):
            # This computes normal first/max/min/last/sum aggregation; the
            # cardinality assertion prevents sparse-input clock compression.
            arrays = [np.asarray(table[col].to_numpy(zero_copy_only=False)) for col in ("open", "high", "low", "close", "volume")]
            bars = len(arrays[0]) // width
            aggregated = (arrays[0][::width], arrays[1].reshape(bars, width).max(1), arrays[2].reshape(bars, width).min(1), arrays[3][width - 1 :: width], arrays[4].reshape(bars, width).sum(1))
            if len(aggregated[0]) != bars or any(len(value) != bars for value in aggregated):
                results[name] = "FAIL"
    return results


def _write_candidate(
    paths: Sequence[Path], raw_schema: pa.Schema, windows: Sequence[tuple[int, int]], target: Path, partitioned: bool
) -> tuple[int, int]:
    """Materialize an unpublished candidate; callers alone decide publication."""
    output_schema = raw_schema.append(pa.field("is_fill", pa.bool_(), nullable=False))
    stream = NativeStream(paths, raw_schema)
    previous: dict[str, pa.Scalar] = {}
    native_rows = fill_rows = 0
    writer: pq.ParquetWriter | None = None
    active_year: int | None = None
    try:
        if not partitioned:
            writer = pq.ParquetWriter(target, output_schema, compression="zstd", version="2.6")
        for start_ns, end_ns in windows:
            native = stream.read_window(start_ns, end_ns)
            dense, previous = densify_window(native, start_ns, end_ns, previous, raw_schema)
            if partitioned:
                year = ns_timestamp(start_ns).as_py().year
                if active_year != year:
                    if writer is not None:
                        writer.close()
                    part_dir = target / f"year={year}"
                    part_dir.mkdir(parents=True, exist_ok=True)
                    writer = pq.ParquetWriter(part_dir / "data.parquet", output_schema, compression="zstd", version="2.6")
                    active_year = year
            assert writer is not None
            writer.write_table(dense, row_group_size=ROW_GROUP_SIZE)
            native_rows += native.num_rows
            fill_rows += dense.num_rows - native.num_rows
        stream.assert_exhausted()
    finally:
        if writer is not None:
            writer.close()
    return native_rows, fill_rows


def _parquet_details(path: Path) -> dict[str, Any]:
    files = [path] if path.is_file() else sorted(path.rglob("*.parquet"))
    metadata = [pq.ParquetFile(file).metadata for file in files]
    hashes = {str(file.relative_to(path)): sha256_file(file) for file in files} if path.is_dir() else None
    logical_hash = None
    if hashes is not None:
        payload = "".join(f"{name}:{value}\n" for name, value in sorted(hashes.items()))
        logical_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "file_size_bytes": sum(file.stat().st_size for file in files),
        "row_groups": sum(item.num_row_groups for item in metadata),
        "file_count": len(files),
        "output_sha256": sha256_file(path) if path.is_file() else logical_hash,
        "partition_sha256": hashes,
    }


def _write_failed_manifest(manifest: Path, result: dict[str, Any]) -> None:
    failed = manifest.with_name(manifest.stem + ".failed" + manifest.suffix)
    failed.parent.mkdir(parents=True, exist_ok=True)
    failed.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def build_dense(symbol: str, input_dir: Path, output: Path, manifest: Path, calendar_name: str = "CME_Equity") -> dict[str, Any]:
    paths = sorted(input_dir.glob(f"{symbol}_v0_1s_*.parquet"))
    raw_schema, sources = inspect_sources(paths)
    fallback = output.parent / f"{symbol}_dense_1s"
    if output.exists() or fallback.exists():
        raise DenseBuildError(f"OUTPUT_ALREADY_EXISTS: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    boundary = validate_native_boundaries(paths)
    boundary_report = output.with_name(output.stem + ".boundary_validation.json")
    boundary_report.write_text(json.dumps(boundary, indent=2) + "\n", encoding="utf-8")
    conflict_report = output.with_name(output.stem + "_calendar_conflicts.csv")
    conflict_rows = write_calendar_conflicts(paths, raw_schema, boundary["native_calendar_conflict_ns"], conflict_report)
    windows = add_native_exception_windows(
        list(expected_windows(sources[0].first_ns, sources[-1].last_ns, calendar_name)),
        boundary["native_calendar_conflict_ns"],
    )
    if not windows:
        raise DenseBuildError("NO_EXPECTED_CALENDAR_WINDOWS")
    temporary = output.with_suffix(output.suffix + ".partial")
    fallback_temporary = fallback.with_name(fallback.name + ".partial")
    if temporary.exists() or fallback_temporary.exists():
        raise DenseBuildError(f"PARTIAL_OUTPUT_EXISTS: {temporary}")
    fallback_reason: str | None = None
    try:
        native_rows, fill_rows = _write_candidate(paths, raw_schema, windows, temporary, partitioned=False)
        candidate, format_name = temporary, "SINGLE_PARQUET"
    except (OSError, pa.ArrowException) as exc:
        # A writer/filesystem failure is the only reason to take the permitted
        # fallback; semantic/input failures remain fail-closed.
        try:
            native_rows, fill_rows = _write_candidate(paths, raw_schema, windows, fallback_temporary, partitioned=True)
        except Exception as fallback_exc:
            raise DenseBuildError(f"SINGLE_AND_PARTITIONED_WRITE_FAILED: {exc}; fallback: {fallback_exc}") from fallback_exc
        candidate, format_name = fallback_temporary, "PARTITIONED_FALLBACK"
        fallback_reason = f"{type(exc).__name__}: {exc}"
    validations = validate_output(paths, candidate, windows, sources[-1].last_ns)
    after_hashes = {source.path.name: sha256_file(source.path) for source in sources}
    source_hashes_unchanged = all(after_hashes[source.path.name] == source.sha256 for source in sources)
    smoke = aggregation_smoke(candidate)
    details = _parquet_details(candidate)
    overall = (
        source_hashes_unchanged
        and validations["native_mismatches"] == 0
        and validations["fill_violations"] == 0
        and validations["duplicates"] == 0
        and validations["out_of_order"] == 0
        and validations["coverage_mismatches"] == 0
        and validations["missing_expected_open_seconds"] == 0
        and validations["rows_during_scheduled_closures"] == 0
        and validations["ytd_overrun_rows"] == 0
        and all(value == "PASS" for value in smoke.values())
    )
    result: dict[str, Any] = {
        "build_timestamp_utc": str(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
        "symbol": symbol,
        "format": format_name,
        "fallback_reason": fallback_reason,
        "output_path": str(output if format_name == "SINGLE_PARQUET" else fallback),
        "calendar_conflict_artifact": str(conflict_report),
        "calendar_conflict_rows": conflict_rows,
        "output_sha256": details["output_sha256"],
        "cleaner_script_sha256": sha256_file(Path(__file__).resolve()),
        "source_files": [
            {"path": str(source.path), "size_bytes": source.size_bytes, "row_count": source.row_count, "first_timestamp": ns_to_text(source.first_ns), "last_timestamp": ns_to_text(source.last_ns), "sha256_before": source.sha256, "sha256_after": after_hashes[source.path.name]}
            for source in sources
        ],
        "source_hashes_unchanged": source_hashes_unchanged,
        "first_timestamp": ns_to_text(windows[0][0]),
        "last_timestamp": ns_to_text(windows[-1][1] - SECOND_NS),
        "native_rows": native_rows,
        "fill_rows": fill_rows,
        "total_rows": native_rows + fill_rows,
        "fill_percentage": 100 * fill_rows / (native_rows + fill_rows),
        "calendar": {"name": calendar_name, "package_version": importlib.metadata.version("pandas_market_calendars"), "timezone": CHICAGO},
        "project_nq_endpoint_override": "Native rows take precedence over generic calendar endpoint conventions; exact declared session-close boundary seconds (normal 16:00:00 CT and calendar-provided early closes) and pre-regime 15:15:00 CT are valid, with closure beginning afterward.",
        "boundary_validation": boundary,
        "historical_schedule_regimes": [
            {"start": "2016-01-03", "end": "2021-06-25", "daily_15_15_to_15_30_halt": True, "daily_16_00_to_17_00_closure": True},
            {"start": "2021-06-28", "end": "available_data_end", "daily_15_15_to_15_30_halt": False, "daily_16_00_to_17_00_closure": True},
        ],
        "parquet": {"compression": "zstd", "row_group_size": ROW_GROUP_SIZE, "row_groups": details["row_groups"], "file_size_bytes": details["file_size_bytes"], "file_count": details["file_count"], "partition_sha256": details["partition_sha256"], "schema": str(raw_schema.append(pa.field("is_fill", pa.bool_(), nullable=False)))},
        "validations": {**validations, "source_hashes": "PASS" if source_hashes_unchanged else "FAIL", "aggregation_smoke": smoke, "overall": "PASS" if overall else "FAIL"},
    }
    if not overall:
        _write_failed_manifest(manifest, result)
        raise DenseBuildError("VALIDATION_FAILED: canonical candidate was not published")
    # The required manifest is committed before the canonical dataset. A
    # manifest write failure therefore cannot leave a ready-named data file.
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    os.replace(candidate, output if format_name == "SINGLE_PARQUET" else fallback)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="NQ")
    parser.add_argument("--input", type=Path, default=Path("data/raw"), dest="input_dir")
    parser.add_argument("--output", type=Path, default=Path("data/canonical/NQ_dense_1s_2016_2026.parquet"))
    parser.add_argument("--manifest", type=Path, default=Path("data/canonical/NQ_dense_1s_2016_2026.manifest.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build_dense(args.symbol, args.input_dir, args.output, args.manifest)
    except Exception as exc:
        print(f"CANONICAL_DENSE_1S_BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "CANONICAL_DENSE_1S_READY" if result["validations"]["overall"] == "PASS" else "CANONICAL_DENSE_1S_BLOCKED", "manifest": result["output_path"]}, indent=2))
    return 0 if result["validations"]["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
