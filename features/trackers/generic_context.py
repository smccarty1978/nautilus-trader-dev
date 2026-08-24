"""Canonical stateless/current-state context feature building blocks."""
from __future__ import annotations

from datetime import datetime
from typing import Mapping

import pytz

from utils.session_boundaries import is_in_session


CT = pytz.timezone("America/Chicago")


class GenericContextProvider:
    """Compute context metrics from supplied already-causal state.

    EMA period/role, session, and unit are instance parameters.  This class
    does not own an EMA or regime state machine and cannot observe a forming
    bar; callers pass completed-bar values and their explicit timestamps.
    """

    @staticmethod
    def ema_slope(*, values: list[float], lookback: int, atr: float) -> float:
        if lookback <= 0 or atr <= 0 or len(values) < lookback + 1:
            return 0.0
        return (float(values[-1]) - float(values[-(lookback + 1)])) / (lookback * atr)

    @staticmethod
    def regime_age(*, bars: int, unit: str = "bars") -> float:
        if unit != "bars":
            raise ValueError("UNSUPPORTED_REGIME_AGE_UNIT")
        return float(bars)

    @staticmethod
    def session_membership(*, ts_avail: int, session: str) -> float:
        if session != "RTH":
            raise ValueError("UNSUPPORTED_SESSION")
        return 1.0 if is_in_session(int(ts_avail), session) else 0.0

    @staticmethod
    def session_elapsed(*, ts_avail: int, session: str, unit: str = "minutes") -> float:
        if session != "RTH" or unit != "minutes":
            raise ValueError("UNSUPPORTED_SESSION_ELAPSED_PARAMETER")
        current = datetime.fromtimestamp(ts_avail / 1e9, tz=pytz.utc).astimezone(CT)
        return float((current.hour - 8) * 60 + (current.minute - 30))
