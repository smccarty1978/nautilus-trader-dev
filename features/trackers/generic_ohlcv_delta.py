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

    def __init__(self, *, windows_seconds: Iterable[int], maxlen: int | None = None,
                 window_pairs: Mapping[str, Iterable[tuple[int, int]]] | None = None) -> None:
        windows = tuple(sorted({int(window) for window in windows_seconds}))
        if not windows or any(window <= 0 for window in windows):
            raise ValueError("window must be a positive completed-bar duration")
        retained = maxlen if maxlen is not None else max(1900, max(windows))
        self._tracker = OHLCVDeltaTracker(maxlen=retained, windows_seconds=windows,
                                          window_pairs=window_pairs)
        self._windows = windows
        self._last_completed_ts: int | None = None

    @property
    def windows_seconds(self) -> tuple[int, ...]:
        return self._windows

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

    def trend_normalized_est_delta_sum(
        self, *, window: str, prevailing_direction: int, atr: float,
    ) -> float | None:
        """Return estimated delta with positive meaning prevailing-trend pressure."""
        if prevailing_direction not in (-1, 1):
            raise ValueError("prevailing_direction must be -1 or +1")
        value = self.metric(name="est_delta_sum", window=window, atr=atr)
        return None if value is None else prevailing_direction * float(value)

    def trend_normalized_est_delta_scale_ratio(
        self, *, numerator_window: str, denominator_window: str,
        prevailing_direction: int, atr: float,
    ) -> float | None:
        """Compare directional pressure against a non-signed long-window scale.

        Unlike the historical volume ratios (which use EPS because zero volume
        is an observed neutral value), a zero estimated-delta scale has no
        directional interpretation.  It therefore follows this feature's
        declared null contract and returns ``None`` rather than manufacturing
        an infinite or arbitrary neutral ratio.
        """
        numerator = self.trend_normalized_est_delta_sum(
            window=numerator_window, prevailing_direction=prevailing_direction, atr=atr,
        )
        denominator = self.metric(name="est_delta_sum", window=denominator_window, atr=atr)
        if numerator is None or denominator is None or float(denominator) == 0.0:
            return None
        return numerator / abs(float(denominator))

    def trend_normalized_est_delta_acceleration(
        self, *, short_window: str, prevailing_direction: int, atr: float,
    ) -> float | None:
        """Directional pressure in the last ``w`` seconds MINUS the directional pressure
        in the ``w`` seconds immediately before that.

        With ``D(x)`` the estimated delta accumulated over the trailing ``x`` seconds, the
        immediately preceding comparable window is ``[t-2w, t-w]``, whose delta is
        ``D(2w) - D(w)`` exactly (the windows are contiguous and disjoint and the
        underlying quantity is a plain sum over completed bars). So

            value = dir * ( D(w) - (D(2w) - D(w)) ) = dir * ( 2*D(w) - D(2w) )

        Positive means directional pressure ALONG the prevailing regime is stronger now
        than it was over the preceding equal-length window; negative means it is fading.
        Both ``w`` and ``2w`` must be constructed windows of this provider -- the caller
        (the runtime adapter) derives that from the declared instances.

        This is the quantity ``est_delta_sum_minus_scaled`` is often mistaken for. That
        historical feature is ``D(a) - D(b)`` for a fixed (a, b), which is minus the delta
        over ``[t-b, t-a]``, not a comparison of two equal-length adjacent windows.
        """
        if prevailing_direction not in (-1, 1):
            raise ValueError("prevailing_direction must be -1 or +1")
        short_s = int(str(short_window).strip().lower().removesuffix("s"))
        long_s = 2 * short_s
        if short_s not in self._windows or long_s not in self._windows:
            raise ValueError(
                f"trend_normalized_est_delta_acceleration({short_window}) needs windows "
                f"{short_s}s and {long_s}s; provider has {list(self._windows)}")
        near = self.metric(name="est_delta_sum", window=f"{short_s}s", atr=atr)
        far = self.metric(name="est_delta_sum", window=f"{long_s}s", atr=atr)
        if near is None or far is None:
            return None
        return prevailing_direction * (2.0 * float(near) - float(far))
