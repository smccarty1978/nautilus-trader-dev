"""Columnar output buffers.  No pandas on the event path: rows land as per-column lists
and become frames only at flush (partition end / run end)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class ColumnarBuffer:
    """Rows land as per-column lists and become a frame only at flush -- UNLESS a
    ``writer`` (``research_workflow.host.chunked_writer.ChunkedParquetWriter``) is attached,
    in which case rows are forwarded to it in ``flush_every``-row batches and dropped from
    this buffer immediately, so the one-partition replay never holds more than
    ``flush_every`` rows of this column in Python memory at once. ``writer=None`` (the
    default) is byte-for-byte the pre-existing behaviour."""

    def __init__(self, columns: Sequence[str], *, writer: Any = None, flush_every: int = 0) -> None:
        self.columns: List[str] = list(columns)
        self._cols: Dict[str, List[Any]] = {c: [] for c in self.columns}
        self.n = 0
        self.writer = writer
        self.flush_every = int(flush_every)
        self._pending_rows = 0  # rows currently buffered in self._cols, not yet forwarded

    def _maybe_flush(self) -> None:
        if self.writer is None or self.flush_every <= 0:
            return
        if self._pending_rows < self.flush_every:
            return
        rows = [{c: self._cols[c][i] for c in self.columns} for i in range(self._pending_rows)]
        self.writer.write_rows(rows)
        for c in self.columns:
            del self._cols[c][:self._pending_rows]
        self._pending_rows = 0

    def append(self, row: Mapping[str, Any]) -> None:
        cols = self._cols
        for c in self.columns:
            cols[c].append(row.get(c))
        self.n += 1
        self._pending_rows += 1
        self._maybe_flush()

    def append_values(self, values: Sequence[Any]) -> None:
        for c, v in zip(self.columns, values):
            self._cols[c].append(v)
        self.n += 1
        self._pending_rows += 1
        self._maybe_flush()

    def __len__(self) -> int:
        return self.n

    def to_frame(self):
        if self.writer is not None:
            raise RuntimeError("CHUNKED_BUFFER_HAS_NO_FRAME: this buffer streams to a "
                               "ChunkedParquetWriter; read its finalize() manifest instead "
                               "of materializing a DataFrame")
        import pandas as pd  # flush-time only
        return pd.DataFrame({c: self._cols[c] for c in self.columns}, columns=self.columns)

    def flush_to_writer(self) -> None:
        """Forward any still-buffered rows to the attached writer WITHOUT finalizing it (the
        writer may still receive more rows from a later window of the same partition). A
        no-op when no writer is attached. The writer's owner calls ``writer.finalize()``
        itself once, after the LAST window of the partition."""
        if self.writer is None or not self._pending_rows:
            return
        rows = [{c: self._cols[c][i] for c in self.columns} for i in range(self._pending_rows)]
        self.writer.write_rows(rows)
        for c in self.columns:
            del self._cols[c][:self._pending_rows]
        self._pending_rows = 0

    def clear(self) -> None:
        for c in self.columns:
            self._cols[c] = []
        self.n = 0
        self._pending_rows = 0


class CollectionSink:
    """Candidate and observation buffers plus an optional event ledger.

    Primary-interval retention happens HERE (rows whose ``observation_ts`` falls outside the
    interval are dropped at append), never by suppressing state transitions: warmup and
    lookahead bars must drive trackers, trigger graphs and pending outcomes exactly as
    primary bars do.
    """

    def __init__(self, candidate_columns: Sequence[str], observation_columns: Sequence[str], *, ledger: Optional[List[Dict[str, Any]]] = None,
                 primary_interval: Optional[Tuple[Optional[int], Optional[int]]] = None,
                 candidate_writer: Any = None, observation_writer: Any = None, flush_every: int = 0) -> None:
        self.candidates = ColumnarBuffer(candidate_columns, writer=candidate_writer, flush_every=flush_every)
        self.observations = ColumnarBuffer(observation_columns, writer=observation_writer, flush_every=flush_every)
        self.ledger = ledger
        self.primary_start, self.primary_end = (primary_interval if primary_interval else (None, None))
        self.dropped_candidates = 0
        self.dropped_observations = 0

    def in_primary(self, ts: int) -> bool:
        if self.primary_start is not None and ts < self.primary_start:
            return False
        if self.primary_end is not None and ts > self.primary_end:
            return False
        return True

    def add_candidate(self, row: Mapping[str, Any]) -> bool:
        if not self.in_primary(int(row["observation_ts"])):
            self.dropped_candidates += 1
            return False
        self.candidates.append(row)
        return True

    def add_observation(self, row: Mapping[str, Any]) -> bool:
        if not self.in_primary(int(row["observation_ts"])):
            self.dropped_observations += 1
            return False
        self.observations.append(row)
        return True

    def record(self, stage: str, ts: int, key: Any, payload: Mapping[str, Any]) -> None:
        if self.ledger is not None:
            self.ledger.append({"timestamp": int(ts), "stage": stage, "key": key, "payload": dict(payload)})

    def frames(self):
        return self.candidates.to_frame(), self.observations.to_frame()

    def chunked(self) -> bool:
        return self.candidates.writer is not None or self.observations.writer is not None

    def flush_writers(self) -> None:
        """Push any still-buffered rows to both attached writers, WITHOUT finalizing them --
        a later window of the same partition may still write more rows to the same writer.
        The writers' owner calls ``writer.finalize()`` itself once, after the last window."""
        self.candidates.flush_to_writer()
        self.observations.flush_to_writer()


__all__ = ["ColumnarBuffer", "CollectionSink"]
