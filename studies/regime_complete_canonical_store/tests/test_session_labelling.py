"""Regression tests for session labelling.

The first build wrote `session = "ETH"` on all 61,543,945 path rows. `dt.hour()`
returns Int8, so `hour * 60` overflowed: 8 * 60 = 480 wraps to -32, and the RTH
window test `-32 + 30 in [510, 900)` was never true.

The column was present, correctly typed, and fully non-null, so every schema,
provenance, and row-count check passed. Both audit gates passed. Only the value
distribution reveals it — which is what these tests assert.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from studies.regime_complete_canonical_store.implementation.writer import (
    _chicago_minute,
    _session_expr,
)

CT = ZoneInfo("America/Chicago")
NS = 1_000_000_000


def _ns(year, month, day, hour, minute) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=CT).timestamp()) * NS


def _session_of(ts_ns: int) -> str | None:
    return (
        pl.DataFrame({"t": [ts_ns]}).select(_session_expr("t").alias("s"))["s"].item()
    )


def _minute_of(ts_ns: int) -> int:
    return (
        pl.DataFrame({"t": [ts_ns]}).select(_chicago_minute("t").alias("m"))["m"].item()
    )


@pytest.mark.parametrize(
    "hour,minute,expected_minutes",
    [(0, 0, 0), (8, 29, 509), (8, 30, 510), (12, 0, 720), (14, 59, 899), (23, 59, 1439)],
)
def test_chicago_minute_does_not_overflow(hour, minute, expected_minutes):
    """Any hour >= 3 overflows Int8 once multiplied by 60."""
    assert _minute_of(_ns(2025, 3, 3, hour, minute)) == expected_minutes


def test_minutes_since_midnight_are_never_negative():
    for hour in range(24):
        assert _minute_of(_ns(2025, 3, 3, hour, 0)) >= 0


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (8, 29, "ETH"),   # one minute before the open
        (8, 30, "RTH"),   # inclusive open
        (12, 0, "RTH"),
        (14, 59, "RTH"),
        (15, 0, "ETH"),   # exclusive close
        (17, 0, "ETH"),
        (3, 0, "ETH"),
    ],
)
def test_rth_window_boundaries(hour, minute, expected):
    assert _session_of(_ns(2025, 3, 3, hour, minute)) == expected


def test_session_expression_agrees_with_the_python_predicate():
    """`is_rth_decision` is the Python authority used by the collector; the
    vectorized expression must agree with it, since the two were the reason
    scores were labelled correctly while paths were not."""
    from studies.full_trade_path_builder.implementation.phase_a_strategy import (
        is_rth_decision,
    )

    for month in (1, 3, 7, 11):          # spans both DST transitions
        for hour in range(24):
            for minute in (0, 29, 30, 59):
                ts = _ns(2025, month, 3, hour, minute)
                expected = "RTH" if is_rth_decision(ts) else "ETH"
                assert _session_of(ts) == expected, (
                    f"disagreement at 2025-{month:02d}-03 {hour:02d}:{minute:02d}"
                )


def test_session_survives_dst_transitions():
    """US DST starts 2025-03-09 and ends 2025-11-02. 08:30 local is RTH on both
    sides even though the UTC offset differs."""
    assert _session_of(_ns(2025, 3, 8, 8, 30)) == "RTH"   # CST
    assert _session_of(_ns(2025, 3, 10, 8, 30)) == "RTH"  # CDT
    assert _session_of(_ns(2025, 11, 1, 8, 30)) == "RTH"  # CDT
    assert _session_of(_ns(2025, 11, 3, 8, 30)) == "RTH"  # CST


def test_a_degenerate_session_column_is_detectable():
    """The property the build lacked: both labels must actually occur."""
    day = [_ns(2025, 3, 3, h, 0) for h in range(24)]
    labels = set(
        pl.DataFrame({"t": day}).select(_session_expr("t").alias("s"))["s"].to_list()
    )
    assert labels == {"RTH", "ETH"}, f"session column is degenerate: {labels}"
