"""Applies the frozen R5/R2.5 thresholds only -- never computes its own
quantiles, never touches March data to derive a cutoff."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdPolicy:
    top_5pct_threshold: float
    top_2_5pct_threshold: float

    def r5_trigger(self, score: float) -> bool:
        return score >= self.top_5pct_threshold

    def r2_5_trigger(self, score: float) -> bool:
        return score >= self.top_2_5pct_threshold

    @classmethod
    def from_frozen_file(cls, path) -> "ThresholdPolicy":
        import json
        d = json.loads(path.read_text())
        return cls(top_5pct_threshold=d["top_5pct_threshold"],
                   top_2_5pct_threshold=d["top_2_5pct_threshold"])
