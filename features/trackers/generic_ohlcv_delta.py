"""Parameterized completed-bar OHLCV/delta building blocks.

This is the V2 surface for the existing causal estimator.  It deliberately
delegates state ownership to :class:`OHLCVDeltaTracker`, whose completed-bar,
regime replay, RTH-reset, gap, and null semantics are the legacy authority.
The only new API is selection by semantic parameters rather than physical
``*_5s`` / ``*_300s`` aliases.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from features.trackers.ohlcv_delta import OHLCVDeltaTracker


class GenericOHLCVDeltaProvider:
    """One estimator with parameterized rolling windows and contexts."""

    def __init__(self, *, windows_seconds: Iterable[int], maxlen: int | None = None) -> None:
        windows = tuple(sorted({int(window) for window in windows_seconds}))
        if not windows or any(window <= 0 for window in windows):
            raise ValueError("window must be a positive completed-bar duration")
        retained = maxlen if maxlen is not None else max(1900, max(windows))
        self._tracker = OHLCVDeltaTracker(maxlen=retained, windows_seconds=windows)
        self._last_completed_ts: int | None = None

    def update_completed_bar(self, *, close_ts: int, open_px: float, high: float,
                             low: float, close: float, volume: float) -> Mapping[str, object]:
        """Forward a completed bar at its close/availability timestamp.

        Raw Nautilus/Databento bars carry open-stamped ``ts_event``. This V2
        API deliberately does not accept that field: rolling cutoffs and
        elapsed regime state are defined at completed-bar availability.
        Callers must provide ``close_ts`` (normally NT ``ts_init`` for a
        catalog 1s bar), so an open-stamped call fails at the boundary.
        """
        if self._last_completed_ts is not None and close_ts <= self._last_completed_ts:
            raise ValueError("NON_MONOTONIC_COMPLETED_BAR")
        result = self._tracker.update(int(close_ts), open_px, high, low, close, volume)
        self._last_completed_ts = int(close_ts)
        return result

    def reset_regime(self, *, ts_avail: int, anchor_price: float) -> None:
        self._tracker.reset_regime(ts_avail, anchor_price)

    def accumulate_regime(self, *, close_ts: int, high: float, low: float,
                          volume: float, est_delta: float) -> None:
        self._tracker.accumulate_regime(close_ts, high, low, volume, est_delta)

    def reset_rth(self, *, ts_avail: int) -> None:
        self._tracker.reset_rth(ts_avail)

    def end_rth(self) -> None:
        self._tracker.end_rth()

    def snapshot(self, *, atr: float) -> Mapping[str, object]:
        return self._tracker.calculate(atr)

    def metric(self, *, name: str, window: str | None = None, atr: float) -> object:
        """Read a semantic metric from the single canonical calculation.

        ``window`` is rendered in the historical suffix only at this adapter
        boundary, preserving legacy output aliases without making it part of
        the provider or canonical feature identity.
        """
        key = name if window is None else f"{name}_{window}"
        return self.snapshot(atr=atr).get(key)
