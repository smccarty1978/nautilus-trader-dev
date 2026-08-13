"""Regression coverage for the RTH-cumulative flush-boundary audit.

Root cause (see strategy.py's _on_1s "delayed boundary bar" branch comment
for the full derivation): offline's minute_bucket_key((bar_ts-1)//60s) puts
bar_ts values {60k+1,...,60(k+1)} in bucket k, so bucket k's own LAST bar is
the 1s bar whose ts_event is an exact multiple of 60s. attach_features.py
flushes bucket k when it encounters the first bar of bucket k+1, so that
boundary bar IS included in bucket k's flush there. NT structurally cannot
match that: the 1-MINUTE bar closing minute k (ts_init=60(k+1)s) is
dispatched strictly BEFORE the 1s bar with ts_event=60(k+1)s exists (that
bar's own ts_init is one second later). The old _on_1s/_on_1m state machine
treated this late-arriving bar as "start a fresh buffer" (since its own
bucket number, by the same formula, coincidentally equals the bucket that
was JUST flushed), and the bar immediately after it then discarded that
phantom buffer entirely via the "gap" warning branch -- silently dropping
one bar's volume/delta from accumulate_regime_rth every single minute.

These tests drive the REAL production ReducedModelSmokeStrategy._on_1s /
_on_1m (unbound, on a lightweight fake self -- avoids needing a live
BacktestEngine) with synthetic bar sequences built to match NT's actual
dispatch order (established in nt_live_scoring_infra_prereqs's coincident-
ts_init tie-break tests: at equal ts_init the 1s bar fires before the 1m
bar; a 1s bar whose ts_event is an exact minute multiple has ts_init ONE
SECOND LATER than that minute's own 1m-bar close, so it is not even
coincident -- it arrives strictly after).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

IMPL = Path(__file__).resolve().parents[1] / "implementation"
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))

import strategy  # noqa: E402
from reduced_feature_engine import ReducedFeatureEngine  # noqa: E402

NS = 1_000_000_000


class FakeBar:
    def __init__(self, ts_event, ts_init, o=100.0, h=100.5, l=99.5, c=100.0, v=1.0):
        self.ts_event = ts_event
        self.ts_init = ts_init
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v


class FakeLog:
    def __init__(self):
        self.warnings = []

    def warning(self, msg):
        self.warnings.append(msg)


class FakeCandidateTracker:
    def on_1s_bar(self, ts_ns, high, low, close, minute_of_day):
        pass

    def on_regime_flip(self, ts, direction, anchor, atr):
        pass


class FakeRegimeEngine:
    """Direction flips exactly once, at `flip_after_1m_calls`-th update() call
    (1-indexed); otherwise holds steady. Lets tests exercise the regime-reset
    interaction without needing the real (much heavier) RegimeEngine."""

    def __init__(self, atr=10.0, flip_after_1m_calls=None):
        self._direction = 1
        self.atr = atr
        self._calls = 0
        self._flip_after = flip_after_1m_calls

    def update(self, h, l, c):
        self._calls += 1
        if self._flip_after is not None and self._calls == self._flip_after:
            self._direction = -self._direction
        return self._direction


def make_fake_self(flip_after_1m_calls=None, rth_always=True):
    fs = types.SimpleNamespace()
    fs._bars_processed_1s = 0
    fs._bars_processed_1m = 0
    fs._maybe_report_and_checkpoint = lambda ts: None
    fs._prev_close = None
    fs._feature_engine = ReducedFeatureEngine(["dummy"])
    fs._current_minute = None
    fs._last_flushed_minute = None
    fs._minute_o = fs._minute_h = fs._minute_l = None
    fs._minute_buf = []
    fs._trade = None
    fs._state = None
    fs._exit_retry = False
    fs._exit_order_id = None
    fs._exit_reason_pending = None
    fs._candidate_tracker = FakeCandidateTracker()
    fs._engine = FakeRegimeEngine(flip_after_1m_calls=flip_after_1m_calls)
    fs._regime_dir = 0
    fs._was_rth = False
    fs._in_rth = (lambda ts: True) if rth_always else (lambda ts: False)
    fs._last_1m_close_ts = None
    fs.flips = []
    fs.log = FakeLog()
    return fs


def feed_1m(fs, minute_close_s, o=100.0, h=100.5, l=99.5, c=100.0):
    """minute_close_s is the minute boundary in whole seconds (e.g. 60, 120)."""
    ts_init = minute_close_s * NS
    bar = FakeBar(ts_event=ts_init - 60 * NS, ts_init=ts_init, o=o, h=h, l=l, c=c)
    strategy.ReducedModelSmokeStrategy._on_1m(fs, bar)


def feed_1s(fs, second_s, o=100.0, h=100.5, l=99.5, c=100.0, v=1.0):
    ts_event = second_s * NS
    bar = FakeBar(ts_event=ts_event, ts_init=ts_event + NS, o=o, h=h, l=l, c=c, v=v)
    strategy.ReducedModelSmokeStrategy._on_1s(fs, bar)


def run_minutes(fs, n_minutes, seconds_into_next=0, v=1.0):
    """Feeds bars 1..n_minutes*60 (+ seconds_into_next extra), inserting each
    1m close bar in NT's real dispatch position (immediately before the 1s
    bar whose ts_event is that same minute boundary)."""
    total = n_minutes * 60 + seconds_into_next
    for i in range(1, total + 1):
        if i % 60 == 0:
            feed_1m(fs, i)
        feed_1s(fs, i, v=v)


# ---------------------------------------------------------------------------


def test_boundary_bar_is_accumulated_not_dropped():
    """The core reproduction. Fails on the pre-fix implementation (177.0,
    3 warnings); passes after the fix (180.0, 0 warnings). See module
    docstring for the full mechanism."""
    fs = make_fake_self()
    run_minutes(fs, n_minutes=3, seconds_into_next=3, v=1.0)
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(180.0)
    assert fs.log.warnings == []


def test_minute_flush_occurs_exactly_once():
    """No bar's volume is counted twice: with distinct per-bar volumes, the
    cumulative sum after N settled minutes equals the exact analytic sum of
    those bars' volumes, not more."""
    fs = make_fake_self()
    total = 120  # 2 full minutes
    for i in range(1, total + 1):
        if i % 60 == 0:
            feed_1m(fs, i)
        feed_1s(fs, i, v=float(i))
    # Only bars 1..120 have been dispatched; both minutes (1-60, 61-120) are
    # fully settled once bar 120 itself is fed (it's the delayed boundary bar
    # for minute 2, accumulated immediately per the fix).
    expected = sum(range(1, 121))
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(float(expected))


def test_rth_reset_at_session_start():
    """reset_rth zeroes cumulative state, and the very first minute after a
    reset still correctly includes its own boundary bar (the fix's branch
    must not depend on _last_flushed_minute having been set by a PRIOR
    session -- first-ever minute takes the normal fresh-buffer path)."""
    fs = make_fake_self()
    run_minutes(fs, n_minutes=1, seconds_into_next=1, v=2.0)
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(120.0)  # 60 bars * 2.0


def test_multiple_consecutive_minutes():
    """Extends the core reproduction to 10 consecutive minutes -- the fix
    must not merely patch the first occurrence."""
    fs = make_fake_self()
    run_minutes(fs, n_minutes=10, seconds_into_next=0, v=1.0)
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(600.0)
    assert fs.log.warnings == []


def test_checkpoint_immediately_before_minute_close():
    """A feature snapshot taken on the last-but-one bar of a minute (before
    the boundary bar even exists) must reflect only the PRIOR minute's fully
    settled RTH volume -- this is the same causal lag offline itself has
    (attach_features.py cannot see a bucket's own last bar until the next
    bucket's first bar arrives either), not a defect."""
    fs = make_fake_self()
    run_minutes(fs, n_minutes=1)
    # One bar into minute 2, not yet its boundary bar.
    feed_1s(fs, 61, v=1.0)
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(60.0)


def test_checkpoint_exactly_on_minute_close_and_immediately_after():
    """The boundary bar itself (ts_event == a 60s multiple) is accumulated
    the instant it arrives -- the row immediately after should already
    reflect it."""
    fs = make_fake_self()
    run_minutes(fs, n_minutes=1)  # ends having just fed bar 60 (the boundary bar)
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(60.0)
    feed_1s(fs, 61, v=5.0)
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(60.0)  # bar 61 itself buffers, not yet flushed


def test_genuine_gap_still_warns_and_does_not_misattribute():
    """A REAL gap (an entire minute with zero buffered 1s bars, distinct
    from the routine single-bar boundary case) must still hit the warning
    branch in _on_1m's own mismatch handler and must not silently fabricate
    RTH volume for the missing minute."""
    fs = make_fake_self()
    run_minutes(fs, n_minutes=1)  # minute 1 settled normally (60.0), bar 60 just consumed
    # Skip straight to minute 3's close with NO 1s bars for minute 2 at all
    # (current_minute is None from minute 1's own flush, so this exercises
    # _on_1m's OWN buffer_matches_this_minute fallback, not _on_1s's branch).
    feed_1m(fs, 180)
    assert "no matching buffered 1s bars" in " ".join(fs.log.warnings)
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(60.0)  # unchanged, nothing fabricated


def test_flip_at_minute_boundary_attributes_delayed_bar_to_new_regime():
    """When a regime flip is confirmed exactly at a minute's close, the
    delayed boundary bar (structurally bucket k, but processed after
    _on_1m already called reset_regime for the flip) must attribute to the
    NEW regime -- matching attach_features.py's own order (reset regime/RTH
    for m_close_ts FIRST, then accumulate the whole buffer including the
    boundary bar) exactly, not a look-ahead or a stale-context bug."""
    fs = make_fake_self(flip_after_1m_calls=2)  # flips on the 2nd _on_1m call (minute 2's close)
    run_minutes(fs, n_minutes=1)  # minute 1: no flip yet (direction starts at 1, first update call)
    for i in range(61, 121):  # minute 2, including its own boundary bar (120)
        if i == 120:
            feed_1m(fs, 120)  # flip fires here (2nd update() call), reset_regime called
        feed_1s(fs, i, v=1.0)
    regime_sum_after_flip_minute = fs._feature_engine.ohlcv._regime_vol_sum
    # reset_regime() fires BEFORE the buffered minute-2 bars (61..119, 59 of
    # them) are accumulated -- matching attach_features.py's own order
    # exactly -- so all of them attribute to the NEW regime, not the old
    # one. Bar 120 (the delayed boundary bar) is processed right after,
    # also via the new regime's context, adding one more: 59 + 1 = 60, the
    # bucket's full 60 bars, none lost and none double-counted across the
    # flip.
    assert regime_sum_after_flip_minute == pytest.approx(60.0)


def test_session_close_end_rth_stops_further_accumulation():
    """A boundary bar arriving after RTH has ended (end_rth called) must not
    be accumulated into rth_vol_cum -- the delayed-boundary-bar branch must
    respect the current RTH state, not blindly accumulate."""
    fs = make_fake_self(rth_always=False)
    fs._in_rth = lambda ts: True
    run_minutes(fs, n_minutes=1)  # RTH active, minute 1 settled + boundary bar (60.0)
    fs._in_rth = lambda ts: False  # session ends
    feed_1m(fs, 120)  # end_rth() fires inside _on_1m
    feed_1s(fs, 121, v=99.0)  # this is the delayed boundary bar for minute 2, post-RTH
    assert fs._feature_engine.ohlcv._rth_vol_cum == pytest.approx(60.0)  # unchanged -- RTH already ended
