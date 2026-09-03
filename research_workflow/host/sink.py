"""Columnar output buffers.  No pandas on the event path: rows land as per-column lists
and become frames only at flush (partition end / run end)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class ColumnarBuffer:
    def __init__(self, columns: Sequence[str]) -> None:
        self.columns: List[str] = list(columns)
        self._cols: Dict[str, List[Any]] = {c: [] for c in self.columns}
        self.n = 0

    def append(self, row: Mapping[str, Any]) -> None:
        cols = self._cols
        for c in self.columns:
            cols[c].append(row.get(c))
        self.n += 1

    def append_values(self, values: Sequence[Any]) -> None:
        for c, v in zip(self.columns, values):
            self._cols[c].append(v)
        self.n += 1

    def __len__(self) -> int:
        return self.n

    def to_frame(self):
        import pandas as pd  # flush-time only
        return pd.DataFrame({c: self._cols[c] for c in self.columns}, columns=self.columns)

    def clear(self) -> None:
        for c in self.columns:
            self._cols[c] = []
        self.n = 0


class CollectionSink:
    """Candidate and observation buffers plus an optional event ledger.

    Primary-interval retention happens HERE (rows whose ``observation_ts`` falls outside the
    interval are dropped at append), never by suppressing state transitions: warmup and
    lookahead bars must drive trackers, trigger graphs and pending outcomes exactly as
    primary bars do.
    """

    def __init__(self, candidate_columns: Sequence[str], observation_columns: Sequence[str], *, ledger: Optional[List[Dict[str, Any]]] = None,
                 primary_interval: Optional[Tuple[Optional[int], Optional[int]]] = None) -> None:
        self.candidates = ColumnarBuffer(candidate_columns)
        self.observations = ColumnarBuffer(observation_columns)
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


__all__ = ["ColumnarBuffer", "CollectionSink"]
