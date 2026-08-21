"""Canonical Causal Registration and Callback Ordering Helper for NautilusTrader.
=============================================================================

Invariant:
----------
When registering coincident multi-timeframe bar streams (e.g. 1s and 1m bars):
  - 1s bars closing at T MUST be delivered before the coincident parent 1m bar closing at T.
  - Adding bar streams in reverse or without explicit temporal interleaving causes the 1m bar
    to trigger signals before the 1s sub-bars at that second have executed, creating the
    MFE/MAE blind-spot anomaly.

Use `add_bars_causal_order` to register multiple bar collections with strict causal precedence.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple
import numpy as np


class MixedTimeframeOrderError(ValueError):
    """Raised when coincident bar streams are registered in non-causal order."""
    pass


def sort_coincident_bars_causal(bars: Sequence[Any]) -> List[Any]:
    """Sorts a mixed collection of NautilusTrader bars causally.

    Sorting Key:
      1. ts_init (close timestamp ascending)
      2. timeframe duration (shorter timeframe first: 1s < 5s < 1m < 5m)
    """
    def bar_key(b: Any) -> Tuple[int, int]:
        ts = getattr(b, "ts_init", 0)
        # Extract bar duration in nanoseconds if available
        bar_type = getattr(b, "bar_type", None)
        spec = getattr(bar_type, "spec", None) if bar_type else None
        step = getattr(spec, "step", 1) if spec else 1
        unit = getattr(spec, "unit", "") if spec else ""
        
        duration_ns = step
        if "MINUTE" in str(unit) or "1m" in str(b):
            duration_ns = step * 60_000_000_000
        elif "SECOND" in str(unit) or "1s" in str(b):
            duration_ns = step * 1_000_000_000

        return (ts, duration_ns)

    return sorted(bars, key=bar_key)


def add_bars_causal_order(engine: Any, bars_1s: Sequence[Any], bars_1m: Sequence[Any]) -> None:
    """The ONLY safe way to load coincident 1s+1m data into a BacktestEngine.
    add_data()'s tie-break at equal ts_init is determined purely by call order.
    Always add 1s bars before 1m bars."""
    if not hasattr(engine, "add_data"):
        raise AttributeError("Engine missing 'add_data' method")

    engine.add_data(list(bars_1s))
    engine.add_data(list(bars_1m))


def verify_callback_causal_order(event_stream: Sequence[Tuple[int, str]]) -> Tuple[bool, List[str]]:
    """Verifies that for any coincident close timestamp T, 1s events precede 1m events.

    Parameters
    ----------
    event_stream : list of (ts_init, timeframe_str)

    Returns
    -------
    (bool, list of error messages)
    """
    errors = []
    seen_1m_at_ts = set()

    for idx, (ts_init, tf) in enumerate(event_stream):
        if tf == "1m":
            seen_1m_at_ts.add(ts_init)
        elif tf == "1s":
            if ts_init in seen_1m_at_ts:
                errors.append(
                    f"Callback order inversion at index {idx}, ts_init={ts_init}: "
                    f"1s bar processed AFTER coincident parent 1m bar"
                )

    return (len(errors) == 0), errors
