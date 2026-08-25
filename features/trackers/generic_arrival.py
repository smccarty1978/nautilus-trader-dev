"""Parameterized arrival velocity and volume building blocks.

These providers make the legacy completed-1s formulas queryable by their
completed-observation lookbacks.  The legacy trackers retain observations, not
timestamps, so a sparse stream is intentionally measured in completed bars;
calling those values a clock-time window would be false.  They retain the old
trackers for legacy aliases and expose generic calculations for new supported
lookbacks without a per-lookback registry definition.
"""
from __future__ import annotations

from collections import deque
from typing import Mapping

import numpy as np


class GenericArrivalVelocityProvider:
    def __init__(self, *, max_lookback_bars: int = 60) -> None:
        if max_lookback_bars <= 0:
            raise ValueError("max_lookback_bars must be positive")
        self._prices: deque[float] = deque(maxlen=max_lookback_bars + 1)

    def update_completed_bar(self, *, close: float) -> None:
        self._prices.append(float(close))

    def velocity(self, *, lookback: int, atr: float) -> float | None:
        if lookback <= 0 or lookback > self._prices.maxlen - 1:
            raise ValueError("UNSUPPORTED_HISTORY_LOOKBACK")
        if atr <= 0 or len(self._prices) < lookback + 1:
            return None
        prices = list(self._prices)
        return (prices[-1] - prices[-(lookback + 1)]) / (lookback * atr)

    def max_absolute_velocity(self, *, lookback: int, velocity_lookback: int, atr: float) -> float | None:
        if lookback > self._prices.maxlen - 1 or velocity_lookback > self._prices.maxlen - 1:
            raise ValueError("UNSUPPORTED_HISTORY_LOOKBACK")
        if lookback <= velocity_lookback or velocity_lookback <= 0 or atr <= 0:
            return None
        prices = list(self._prices)
        if len(prices) < lookback:
            return None
        # Preserve the legacy sampling convention exactly: each historical
        # velocity is expressed with negative offsets from the current
        # completed observation. ``lookback=30, velocity_lookback=5`` is the
        # historical ``max_vel_30s`` formula; other positive windows use the
        # same algorithm rather than a separate route.
        return max(
            abs((prices[-offset + velocity_lookback - 1] - prices[-offset - 1]) / (velocity_lookback * atr))
            for offset in range(velocity_lookback, min(lookback, len(prices)))
        )

    def metric(self, *, kind: str, atr: float, lookback: int | None = None,
               short_lookback: int | None = None, long_lookback: int | None = None) -> float | None:
        """Semantic arrival queries; unsupported combinations fail closed."""
        if kind == "velocity" and lookback is not None:
            return self.velocity(lookback=lookback, atr=atr)
        if kind == "acceleration" and short_lookback and long_lookback:
            short = self.velocity(lookback=short_lookback, atr=atr)
            long = self.velocity(lookback=long_lookback, atr=atr)
            return None if short is None or long is None else short - long
        if kind == "velocity_ratio" and short_lookback and long_lookback:
            denominator = self.velocity(lookback=long_lookback, atr=atr)
            short = self.velocity(lookback=short_lookback, atr=atr)
            return short / denominator if short is not None and denominator is not None and abs(denominator) > 0.001 else None
        raise ValueError("UNSUPPORTED_ARRIVAL_PARAMETER_COMBINATION")

    def snapshot(self, *, atr: float) -> Mapping[str, float]:
        """Legacy-alias compatibility projection of the generic operations."""
        prices = list(self._prices)
        if len(prices) < 30 or atr <= 0:
            return {
                "arrival_vel_5s": 0.0, "arrival_vel_10s": 0.0, "arrival_vel_20s": 0.0,
                "arrival_vel_30s": 0.0, "arrival_accel_5s": 0.0, "arrival_accel_10s": 0.0,
                "arrival_jerk": 0.0, "max_vel_30s": 0.0, "vel_ratio_5_20": 0.0,
                "is_decelerating": 0.0,
            }
        vel_5 = self.velocity(lookback=5, atr=atr) or 0.0
        vel_10 = self.velocity(lookback=10, atr=atr) or 0.0
        vel_20 = self.velocity(lookback=20, atr=atr) or 0.0
        # The historical 30-second alias retained only 60 observations and
        # uses ``p[-30]`` rather than the usual ``p[-31]`` boundary.  Preserve
        # that established alias exactly; arbitrary new ``velocity(lookback=…)``
        # instances use the mathematically regular completed-observation form.
        vel_30 = (prices[-1] - prices[-30]) / (30 * atr)
        accel_5 = vel_5 - vel_10
        accel_10 = vel_10 - vel_20
        return {
            "arrival_vel_5s": vel_5, "arrival_vel_10s": vel_10,
            "arrival_vel_20s": vel_20, "arrival_vel_30s": vel_30,
            "arrival_accel_5s": accel_5, "arrival_accel_10s": accel_10,
            "arrival_jerk": accel_5 - accel_10,
            "max_vel_30s": self.max_absolute_velocity(lookback=30, velocity_lookback=5, atr=atr) or 0.0,
            "vel_ratio_5_20": vel_5 / vel_20 if abs(vel_20) > 0.001 else 0.0,
            "is_decelerating": 1.0 if accel_5 > 0.0 else 0.0,
        }


class GenericArrivalVolumeProvider:
    def __init__(self, *, max_lookback_bars: int = 60) -> None:
        if max_lookback_bars <= 0:
            raise ValueError("max_lookback_bars must be positive")
        self._volumes: deque[float] = deque(maxlen=max_lookback_bars)
        self._opens: deque[float] = deque(maxlen=max_lookback_bars)
        self._closes: deque[float] = deque(maxlen=max_lookback_bars)

    def update_completed_bar(self, *, volume: float, open_px: float, close_px: float) -> None:
        self._volumes.append(float(volume))
        self._opens.append(float(open_px))
        self._closes.append(float(close_px))

    def relative_volume(self, *, aggregation_lookback: int, baseline_lookback: int) -> float | None:
        values = list(self._volumes)
        if (aggregation_lookback <= 0 or baseline_lookback <= 0
                or aggregation_lookback + baseline_lookback > self._volumes.maxlen):
            raise ValueError("UNSUPPORTED_HISTORY_LOOKBACK")
        if len(values) < aggregation_lookback + baseline_lookback:
            return None
        recent = sum(values[-aggregation_lookback:])
        if len(values) < aggregation_lookback + baseline_lookback:
            return None
        prior = sum(values[-(aggregation_lookback + baseline_lookback):-aggregation_lookback])
        return recent / prior if prior > 0 else None

    def volume_price_correlation(self, *, lookback: int) -> float | None:
        values, opens, closes = list(self._volumes), list(self._opens), list(self._closes)
        if lookback <= 1 or lookback > self._volumes.maxlen:
            raise ValueError("UNSUPPORTED_HISTORY_LOOKBACK")
        if len(values) < lookback:
            return None
        returns = np.asarray([close - open_ for open_, close in zip(opens[-lookback:], closes[-lookback:])])
        volume = np.asarray(values[-lookback:])
        if np.std(returns) == 0 or np.std(volume) == 0:
            return None
        result = float(np.corrcoef(returns, volume)[0, 1])
        return None if np.isnan(result) else result

    def snapshot(self) -> Mapping[str, float]:
        """Compatibility projection, implemented from parameterized windows."""
        values, opens, closes = list(self._volumes), list(self._opens), list(self._closes)
        if len(values) < 20:
            return {
                "rvol_1s": 1.0, "rvol_5s": 1.0, "rvol_10s": 1.0, "vol_trend_10s": 1.0,
                "vol_spike": 0.0, "vol_climax": 0.0, "vol_accel": 0.0,
                "up_vol_ratio_10s": 0.5, "down_vol_ratio_10s": 0.5, "vol_price_corr_10s": 0.0,
            }
        mean_10 = float(np.mean(values[-11:-1]))
        rvol_1 = values[-1] / mean_10 if mean_10 > 0 else 1.0
        rvol_5_value = self.relative_volume(aggregation_lookback=5, baseline_lookback=5)
        rvol_10_value = self.relative_volume(aggregation_lookback=10, baseline_lookback=10)
        rvol_5 = 1.0 if rvol_5_value is None else rvol_5_value
        rvol_10 = 1.0 if rvol_10_value is None else rvol_10_value
        recent_5 = float(np.mean(values[-5:]))
        prior_5 = float(np.mean(values[-10:-5]))
        accel = recent_5 / prior_5 if prior_5 > 0 else 1.0
        std_10 = float(np.std(values[-11:-1]))
        spike = (values[-1] - mean_10) / std_10 if std_10 > 0 else 0.0
        up = sum(values[-index] for index in range(1, min(11, len(values) + 1)) if closes[-index] >= opens[-index])
        down = sum(values[-index] for index in range(1, min(11, len(values) + 1)) if closes[-index] < opens[-index])
        total = up + down
        return {
            "rvol_1s": rvol_1, "rvol_5s": rvol_5, "rvol_10s": rvol_10,
            "vol_trend_10s": 1.0 if rvol_5 > 1.2 else (-1.0 if rvol_5 < 0.8 else 0.0),
            "vol_spike": spike, "vol_climax": 1.0 if rvol_1 > 3.0 and spike > 2.0 else 0.0,
            "vol_accel": accel, "up_vol_ratio_10s": up / total if total > 0 else 0.5,
            "down_vol_ratio_10s": down / total if total > 0 else 0.5,
            "vol_price_corr_10s": (lambda value: 0.0 if value is None else value)(
                self.volume_price_correlation(lookback=10)),
        }
