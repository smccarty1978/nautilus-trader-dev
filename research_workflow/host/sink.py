"""Columnar output buffers.  No pandas on the event path: rows land as per-column lists
and become frames only at flush (partition end / run end)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence


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
    """Candidate and observation buffers plus an optional event ledger."""

    def __init__(self, candidate_columns: Sequence[str], observation_columns: Sequence[str], *, ledger: Optional[List[Dict[str, Any]]] = None) -> None:
        self.candidates = ColumnarBuffer(candidate_columns)
        self.observations = ColumnarBuffer(observation_columns)
        self.ledger = ledger

    def record(self, stage: str, ts: int, key: Any, payload: Mapping[str, Any]) -> None:
        if self.ledger is not None:
            self.ledger.append({"timestamp": int(ts), "stage": stage, "key": key, "payload": dict(payload)})

    def frames(self):
        return self.candidates.to_frame(), self.observations.to_frame()


__all__ = ["ColumnarBuffer", "CollectionSink"]
