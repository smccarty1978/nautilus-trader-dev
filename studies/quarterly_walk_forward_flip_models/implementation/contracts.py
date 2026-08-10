"""Pure, auditable temporal and selection contracts for the study."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

NS = 1_000_000_000
HORIZON_NS = 300 * NS


@dataclass(frozen=True)
class Quarter:
    year: int
    number: int

    @property
    def start(self) -> int:
        return int(datetime(self.year, (self.number - 1) * 3 + 1, 1, tzinfo=UTC).timestamp() * NS)

    @property
    def end(self) -> int:
        return (
            Quarter(self.year + 1, 1).start
            if self.number == 4
            else Quarter(self.year, self.number + 1).start
        )

    @property
    def label(self) -> str:
        return f"{self.year}Q{self.number}"


def quarters(start_year: int, end_year: int) -> list[Quarter]:
    return [Quarter(year, number) for year in range(start_year, end_year + 1) for number in range(1, 5)]


def resolved_train_mask(times: np.ndarray, quarter_start_ns: int) -> np.ndarray:
    """Rows whose entire future 300s label window was knowable before Q."""
    return times + HORIZON_NS < quarter_start_ns


def evaluation_mask(times: np.ndarray, quarter: Quarter, visible_end_ns: int) -> np.ndarray:
    """Quarter rows with labels resolved without crossing a sealed boundary."""
    return (times >= quarter.start) & (times < quarter.end) & (times + HORIZON_NS <= visible_end_ns)


def threshold(values: np.ndarray, quantile: float) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        raise ValueError("threshold population has no finite scores")
    return float(np.quantile(finite, quantile, method="linear"))


def first_crossings(
    regime_start_ns: np.ndarray,
    decision_ns: np.ndarray,
    age_seconds: np.ndarray,
    score: np.ndarray,
    value: float,
    minimum_age_seconds: int = 600,
) -> np.ndarray:
    """First true upward crossing after the age gate, one per regime.

    The caller supplies chronological true NT dispatches only. No carry-forward
    score can create a crossing. A score already above threshold at the gate is
    deliberately not a crossing: it crossed before the allowed entry window.
    """
    if not (len(regime_start_ns) == len(decision_ns) == len(age_seconds) == len(score)):
        raise ValueError("crossing arrays have unequal lengths")
    chosen = np.zeros(len(score), dtype=bool)
    previous: dict[int, bool] = {}
    selected: set[int] = set()
    for i, (rid, _, age, probability) in enumerate(
        zip(regime_start_ns, decision_ns, age_seconds, score, strict=True)
    ):
        key = int(rid)
        current = bool(np.isfinite(probability) and probability >= value)
        crossed = current and not previous.get(key, False)
        if key not in selected and age > minimum_age_seconds and crossed:
            chosen[i] = True
            selected.add(key)
        previous[key] = current
    return chosen


def monotonicity_violation(event_rates: dict[str, float]) -> bool:
    """Top-1 >= Top-2.5 >= Top-5 >= Top-10 must hold when all are defined."""
    levels = ("top_1", "top_2_5", "top_5", "top_10")
    values = [event_rates.get(level) for level in levels]
    values = [value for value in values if value is not None and np.isfinite(value)]
    return any(left < right for left, right in zip(values, values[1:], strict=False))
