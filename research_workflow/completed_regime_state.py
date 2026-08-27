"""Reusable completed-bar regime state sourced from the accepted collector_v2 engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from collectors.collector_v2.aggregator import TIMEFRAME_TO_BUCKET_NS, TimeframeAggregator
from collectors.collector_v2.regime_engine import RegimeStateEngine
from collectors.collector_v2.registry import CompletedBarRegistry, CompletedBarState

NS = 1_000_000_000


@dataclass(frozen=True)
class CompletedRegimeTransition:
    timeframe: str
    available_ts: int
    previous: Optional[CompletedBarState]
    current: CompletedBarState

    @property
    def regime_changed(self) -> bool:
        return self.previous is not None and self.previous.regime != self.current.regime


class CompletedRegimeStateFeed:
    """Aggregate completed 1s bars and expose only causally available frozen states.

    This class deliberately delegates the calculation to the already accepted
    ``TimeframeAggregator`` and ``RegimeStateEngine``. It is an owning-layer adapter,
    not another regime definition.
    """

    def __init__(self, timeframes: Iterable[str], *, atr_period: int = 14) -> None:
        requested = tuple(dict.fromkeys(str(tf) for tf in timeframes))
        if not requested:
            raise ValueError("CompletedRegimeStateFeed requires at least one timeframe")
        unknown = [tf for tf in requested if tf not in TIMEFRAME_TO_BUCKET_NS]
        if unknown:
            raise ValueError(f"unsupported completed regime timeframe(s): {unknown}")
        self.timeframes: Tuple[str, ...] = requested
        self.registry = CompletedBarRegistry(supported_timeframes=requested)
        self.engines = {
            tf: RegimeStateEngine(tf, self.registry, atr_period=atr_period)
            for tf in requested
        }
        self._available_ts = 0
        self._transitions: list[CompletedRegimeTransition] = []
        self.aggregator = TimeframeAggregator(self._on_bucket_closed, timeframes=requested)

    def _on_bucket_closed(self, timeframe, completed) -> None:
        previous = self.registry.get(timeframe)
        self.engines[timeframe].on_bar_closed(completed)
        current = self.registry.get(timeframe)
        if current is None:  # pragma: no cover - engine contract defense
            raise RuntimeError(f"regime engine failed to publish {timeframe!r}")
        self._transitions.append(
            CompletedRegimeTransition(timeframe, self._available_ts, previous, current)
        )

    def on_completed_1s_bar(
        self,
        *,
        ts_event: int,
        ts_init: int,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> Tuple[CompletedRegimeTransition, ...]:
        """Consume one fully completed OPEN-stamped 1s bar.

        ``ts_init`` is its causal availability timestamp and must be exactly one second
        after ``ts_event``. Completed parent buckets are published through that boundary.
        """
        ts_event, ts_init = int(ts_event), int(ts_init)
        if ts_init != ts_event + NS:
            raise ValueError(
                "completed 1s bar requires ts_init = ts_event + 1 second"
            )
        if ts_init < self._available_ts:
            raise ValueError("completed 1s bars must arrive in non-decreasing availability order")
        self._available_ts = ts_init
        start = len(self._transitions)
        self.aggregator.on_1s_bar(ts_event, open, high, low, close, volume)
        self.aggregator.finalize_through(ts_init)
        self.registry.audit_provenance(ts_init)
        return tuple(self._transitions[start:])

    def state(self, timeframe: str, *, decision_ts: int) -> Optional[CompletedBarState]:
        if timeframe not in self.timeframes:
            raise ValueError(f"timeframe {timeframe!r} was not declared for this feed")
        self.registry.audit_provenance(int(decision_ts))
        return self.registry.get(timeframe)

    def consume_incomplete_close_ts(self, timeframe: str) -> Tuple[int, ...]:
        if timeframe not in self.timeframes:
            raise ValueError(f"timeframe {timeframe!r} was not declared for this feed")
        return tuple(self.aggregator.consume_incomplete_close_ts(timeframe))


__all__ = ["CompletedRegimeStateFeed", "CompletedRegimeTransition"]
