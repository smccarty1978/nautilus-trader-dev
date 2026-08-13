from datetime import datetime, timezone

from studies.full_trade_path_builder.implementation.phase_a_strategy import (
    is_rth_decision,
    is_rth_minute_bar,
    minute_bucket_from_close,
)
from studies.full_trade_path_builder.implementation.phase_a_core import NS


def _ns(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * NS)


def test_rth_half_open_normal_day():
    # July is CDT (UTC-5).
    assert not is_rth_decision(_ns("2025-07-01T13:29:55"))
    assert is_rth_decision(_ns("2025-07-01T13:30:00"))
    assert is_rth_decision(_ns("2025-07-01T19:59:59"))
    assert not is_rth_decision(_ns("2025-07-01T20:00:00"))


def test_rth_dst_offsets():
    # January is CST (UTC-6); July is CDT (UTC-5).
    assert is_rth_decision(_ns("2025-01-15T14:30:00"))
    assert not is_rth_decision(_ns("2025-01-15T14:29:59"))
    assert is_rth_decision(_ns("2025-07-15T13:30:00"))
    assert not is_rth_decision(_ns("2025-07-15T13:29:59"))
    # First sessions immediately after the spring/fall transitions.
    assert is_rth_decision(_ns("2025-03-10T13:30:00"))
    assert not is_rth_decision(_ns("2025-03-10T13:29:59"))
    assert is_rth_decision(_ns("2025-11-03T14:30:00"))
    assert not is_rth_decision(_ns("2025-11-03T14:29:59"))


def test_minute_bucket_uses_close_boundary():
    close_ns = 60 * NS
    assert minute_bucket_from_close(close_ns) == 0


def test_minute_interval_rth_edges():
    open_boundary = _ns("2025-07-01T13:30:00")
    close_boundary = _ns("2025-07-01T20:00:00")
    assert is_rth_decision(open_boundary) and not is_rth_minute_bar(open_boundary)
    assert is_rth_minute_bar(_ns("2025-07-01T13:31:00"))
    assert not is_rth_decision(close_boundary) and is_rth_minute_bar(close_boundary)
    assert not is_rth_minute_bar(_ns("2025-07-01T20:01:00"))
