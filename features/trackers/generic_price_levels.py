"""Parameterized completed-bar price-level building blocks.

Level kind, rolling duration, normalization, and observation context are
instance parameters.  Legacy names are rendered only at the compatibility
edge; all session and availability behavior remains in PriceLevelTracker.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from features.trackers.price_levels import PriceLevelTracker


NS = 1_000_000_000


class GenericPriceLevelProvider:
    """One causal level provider with parameterized rolling durations."""

    def __init__(self, *, rolling_windows_min: Iterable[int] = (5, 15, 30, 60),
                 tick_size: float = 0.25, touch_tolerance_ticks: float = 1.0) -> None:
        self._tracker = PriceLevelTracker(
            tick_size=tick_size,
            touch_tolerance_ticks=touch_tolerance_ticks,
            rolling_windows_min=rolling_windows_min,
        )
        self._last_completed_ts: int | None = None

    def update_completed_bar(self, *, ts_avail: int, open_px: float, high: float,
                             low: float, close: float, is_rth: bool) -> None:
        if self._last_completed_ts is not None and ts_avail <= self._last_completed_ts:
            raise ValueError("NON_MONOTONIC_COMPLETED_BAR")
        self._tracker.update_1m(ts_avail, open_px, high, low, close, is_rth)
        self._last_completed_ts = int(ts_avail)

    def snapshot(self, *, observation_ts: int, reference_price: float, atr: float,
                 direction: int = -1) -> Mapping[str, object]:
        if self._last_completed_ts is None:
            raise ValueError("NO_COMPLETED_BAR_AVAILABLE")
        if observation_ts < self._last_completed_ts:
            raise ValueError("CAUSAL_SNAPSHOT_ORDER_VIOLATION")
        # This provider consumes a completed 1m stream. A request at or after
        # the next expected close means that stream is missing an input bar;
        # do not present stale rolling levels as a current observation.
        if observation_ts - self._last_completed_ts >= 60 * NS:
            raise ValueError("STALE_COMPLETED_INPUT_STREAM")
        return self._tracker.calculate(observation_ts, reference_price, atr, direction)

    def level_metric(self, *, level: str, metric: str, observation_ts: int,
                     reference_price: float, atr: float, direction: int = -1) -> object:
        """Resolve ``distance_to_level(level=..., normalization=...)`` output."""
        return self.snapshot(
            observation_ts=observation_ts, reference_price=reference_price, atr=atr, direction=direction,
        ).get(f"{level}_{metric}")
