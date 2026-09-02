"""Semantics-preserving hot-path fixes (platform-v2 item 07) are equivalent to their references."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from utils import session_boundaries as sb

NS = 1_000_000_000


def _year_samples() -> np.ndarray:
    """Every 7 minutes + 1s through 2023 (DST transitions 2023-03-12 and 2023-11-05), plus exact boundaries."""
    start = pd.Timestamp("2023-01-01", tz="UTC").value
    end = pd.Timestamp("2024-01-02", tz="UTC").value
    grid = np.arange(start, end, 7 * 60 * NS + NS, dtype=np.int64)
    edges = []
    for day in pd.date_range("2023-03-10", "2023-03-14", tz="America/Chicago").union(pd.date_range("2023-11-03", "2023-11-07", tz="America/Chicago")):
        for hms in ((8, 30, 0), (8, 30, 1), (8, 29, 59), (15, 15, 0), (15, 15, 1), (15, 14, 59), (0, 0, 0), (23, 59, 59)):
            edges.append(pd.Timestamp(day.year, day.month, day.day, *hms, tz="America/Chicago").tz_convert("UTC").value)
    return np.concatenate([grid, np.asarray(edges, dtype=np.int64)])


def test_is_in_session_matches_reference_across_a_year_with_dst():
    for session in ("RTH", "ETH", "ALL"):
        for ts in _year_samples():
            assert sb.is_in_session(int(ts), session) == sb.is_in_session_reference(int(ts), session), (session, int(ts))


def test_session_close_ns_matches_reference_across_a_year_with_dst():
    for ts in _year_samples():
        assert sb.session_close_ns(int(ts), "RTH") == sb.session_close_ns_reference(int(ts), "RTH"), int(ts)


def test_unknown_session_still_fails_closed():
    with pytest.raises(sb.UnknownSessionError):
        sb.is_in_session(pd.Timestamp("2023-06-01 15:00", tz="UTC").value, "GLOBEX")


def test_five_minute_boundary_integer_rule_matches_chicago_minute_of_day():
    from research_workflow.generic_collector import is_five_minute_boundary_ns, minutes_since_rth_open_ns
    for ts in _year_samples():
        ct = pd.Timestamp(int(ts), tz="UTC").tz_convert("America/Chicago")
        minute_of_day = ct.hour * 60 + ct.minute
        assert is_five_minute_boundary_ns(int(ts)) == (minute_of_day % 5 == 0 and ct.second == 0), int(ts)
        assert minutes_since_rth_open_ns(int(ts)) == (ct.hour - 8) * 60 + (ct.minute - 30), int(ts)


def test_provider_host_routes_data_streams_only_to_declared_subscribers():
    from research_workflow import provider_host as ph

    class _A:
        def __init__(self, streams): self._s = frozenset(streams); self.seen = []
        def required_streams(self): return self._s
        def on_event(self, t, e): self.seen.append(t)
        canonical_provider = "x"
    a1, a2 = _A({ph.STREAM_COMPLETED_1S}), _A({ph.STREAM_COMPLETED_5M})
    host = ph.ProviderHost(instances=(), adapters=(a1, a2))
    host.dispatch(ph.STREAM_COMPLETED_1S, {"close_ts": 10 * NS, "avail_ts": 10 * NS})
    host.dispatch(ph.STREAM_COMPLETED_5M, {"close_ts": 300 * NS, "avail_ts": 300 * NS})
    host.dispatch(ph.EVENT_REGIME_TRANSITION_1M, {"avail_ts": 301 * NS})
    assert a1.seen == [ph.STREAM_COMPLETED_1S, ph.EVENT_REGIME_TRANSITION_1M]
    assert a2.seen == [ph.STREAM_COMPLETED_5M, ph.EVENT_REGIME_TRANSITION_1M]
