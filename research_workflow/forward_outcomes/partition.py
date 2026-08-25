"""Partition-safe forward observation.

A partitioned run and a monolithic run must produce byte-identical outcome tables. Two
properties get that:

* **Emit-once.** An entry belongs to exactly one partition -- the one whose *primary*
  interval contains its ``entry_ts``. Neighbouring partitions may read the same bars,
  but they never emit the same entry.
* **Resolve-fully.** A partition reads far enough past its primary end that its own
  boundary entries reach their full tracking budget inside the partition. Anything less
  turns a partition boundary into a censoring event, which is a data-layout artifact
  masquerading as a market fact.

:func:`required_lookahead_seconds` is the contract between those two properties, and
:func:`assert_partition_parity` is the check that they held.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

import pandas as pd

from research_workflow.forward_outcomes.contracts import (
    NS,
    ForwardOutcomeError,
    ForwardOutcomeSpec,
)


class PartitionParityError(ForwardOutcomeError):
    """Raised when partitioned and monolithic observation disagree."""


@dataclass(frozen=True)
class OutcomePartition:
    """One bounded observation window: what it emits, and what it must read."""

    partition_id: str
    primary_start_ns: int
    primary_end_ns: int
    lookahead_end_ns: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def primary_interval(self) -> tuple[int, int]:
        return (int(self.primary_start_ns), int(self.primary_end_ns))


def required_lookahead_seconds(spec: ForwardOutcomeSpec) -> int:
    """Seconds of bar data a partition must read past its primary end.

    The budget is the entry tracking window plus, when a confirmation is declared, the
    worst case of waiting the full confirmation window and then tracking the full
    post-confirmation window from there.
    """
    budget = int(spec.max_tracking_seconds)
    if spec.confirmation is not None:
        budget = max(
            budget,
            int(spec.confirmation.max_wait_seconds) + int(spec.confirmation.post_max_tracking_seconds),
        )
    return budget


def build_outcome_partitions(
    boundaries: Sequence[tuple[str, int, int]], spec: ForwardOutcomeSpec
) -> list[OutcomePartition]:
    """Build partitions from ``(partition_id, primary_start_ns, primary_end_ns)`` triples."""
    lookahead_ns = required_lookahead_seconds(spec) * NS
    parts = [
        OutcomePartition(
            partition_id=str(pid),
            primary_start_ns=int(start),
            primary_end_ns=int(end),
            lookahead_end_ns=int(end) + lookahead_ns,
        )
        for pid, start, end in boundaries
    ]
    ordered = sorted(parts, key=lambda p: p.primary_start_ns)
    for left, right in zip(ordered, ordered[1:]):
        if left.primary_end_ns >= right.primary_start_ns:
            raise PartitionParityError(
                f"overlapping primary intervals: {left.partition_id} / {right.partition_id}"
            )
    return ordered


def partitions_from_specs(
    partition_specs: Iterable[Any], spec: ForwardOutcomeSpec
) -> list[OutcomePartition]:
    """Adapt ``research_workflow.partitioning.PartitionSpec`` calendar partitions."""
    boundaries: list[tuple[str, int, int]] = []
    for part in partition_specs:
        start = pd.Timestamp(part.primary_start, tz="UTC").value
        end = (
            pd.Timestamp(part.primary_end, tz="UTC")
            + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        ).value
        boundaries.append((str(part.partition_id), int(start), int(end)))
    return build_outcome_partitions(boundaries, spec)


def merge_outcome_partitions(
    frames: Sequence[pd.DataFrame],
    partitions: Optional[Sequence[OutcomePartition]] = None,
) -> pd.DataFrame:
    """Concatenate partition outcome tables, rejecting duplication and schema drift."""
    frames = [f for f in frames]
    if partitions is not None and len(frames) != len(partitions):
        raise PartitionParityError("one outcome frame is required for each partition")
    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return pd.DataFrame()
    columns = list(non_empty[0].columns)
    for frame in non_empty[1:]:
        if list(frame.columns) != columns:
            raise PartitionParityError("partition outcome schema mismatch")

    if partitions is not None:
        for frame, part in zip(frames, partitions):
            if frame.empty:
                continue
            ts = frame["entry_ts"].astype("int64")
            outside = frame.loc[(ts < part.primary_start_ns) | (ts > part.primary_end_ns)]
            if not outside.empty:
                raise PartitionParityError(
                    f"partition {part.partition_id} emitted {len(outside)} entries outside "
                    f"its primary interval; an entry must be emitted by exactly one partition"
                )

    merged = pd.concat(non_empty, ignore_index=True)
    if merged["entry_id"].duplicated().any():
        dupes = sorted(merged.loc[merged["entry_id"].duplicated(), "entry_id"].unique())
        raise PartitionParityError(
            f"entry emitted by more than one partition: {dupes[:5]}"
        )
    return merged.sort_values(["entry_ts", "entry_id"], kind="mergesort").reset_index(drop=True)


def normalize_outcome_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame.sort_values(["entry_ts", "entry_id"], kind="mergesort").reset_index(drop=True)


def assert_partition_parity(
    monolithic: pd.DataFrame, partitioned: pd.DataFrame, *, context: str = "forward outcomes"
) -> dict[str, Any]:
    """Exact equality between a single-pass run and a merged partitioned run."""
    left = normalize_outcome_frame(monolithic)
    right = normalize_outcome_frame(partitioned)
    if list(left.columns) != list(right.columns):
        raise PartitionParityError(
            f"{context}: column mismatch\n  monolithic: {list(left.columns)[:8]}\n"
            f"  partitioned: {list(right.columns)[:8]}"
        )
    if len(left) != len(right):
        raise PartitionParityError(
            f"{context}: row count mismatch ({len(left)} vs {len(right)})"
        )
    mismatched: list[str] = []
    for column in left.columns:
        a, b = left[column], right[column]
        if a.equals(b):
            continue
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            import numpy as np

            if np.allclose(a.to_numpy(dtype="float64"), b.to_numpy(dtype="float64"),
                           rtol=0.0, atol=0.0, equal_nan=True):
                continue
        mismatched.append(column)
    if mismatched:
        raise PartitionParityError(f"{context}: columns differ: {mismatched[:10]}")
    return {"passed": True, "rows": int(len(left)), "columns": int(len(left.columns))}
