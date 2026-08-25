"""Causal reference aggregation for forming calendar-bar feature instances."""
from __future__ import annotations

from typing import Iterable, Mapping, Optional


def forming_calendar_bar_from_completed_seconds(
    bars: Iterable[Mapping[str, float]], *, timeframe_seconds: int, as_of_ns: int,
) -> Optional[dict]:
    """Return the current bucket using only completed 1s inputs available by as_of_ns.

    ``ts_init`` is the availability timestamp, so any later completed second is excluded.
    This is intentionally distinct from a trailing rolling window: the bucket start is
    calendar aligned and no prior-bucket bars are admitted.
    """
    if timeframe_seconds <= 0:
        raise ValueError("INVALID_TIMEFRAME")
    ns = 1_000_000_000
    bucket_ns = timeframe_seconds * ns
    bucket_start = (as_of_ns // bucket_ns) * bucket_ns
    usable = [bar for bar in bars if bucket_start <= int(bar["ts_event"]) < as_of_ns and int(bar["ts_init"]) <= as_of_ns]
    if not usable:
        return None
    usable.sort(key=lambda bar: int(bar["ts_event"]))
    return {
        "open": float(usable[0]["open"]), "high": max(float(bar["high"]) for bar in usable),
        "low": min(float(bar["low"]) for bar in usable), "close": float(usable[-1]["close"]),
        "volume": sum(float(bar["volume"]) for bar in usable),
        "bucket_start_ns": bucket_start, "as_of_ns": as_of_ns,
    }
