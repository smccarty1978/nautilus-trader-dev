"""Regression tests for attach_features.py's bucket/replay helpers.

Covers CRIT-1 (1s->1m bucket construction was off by one) and CRIT-4
(regime-relative warmup for the validation-smoke padding), per the
lookahead audit's specific recommendations (audit/audit.md).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from attach_features import minute_bucket_key  # noqa: E402
from features.engine import FeatureEngine  # noqa: E402
from features.trackers.ohlcv_delta import OHLCVDeltaTracker  # noqa: E402
from test_feature_library import MockBar, MockRegime  # noqa: E402

NS = 1_000_000_000


def test_minute_bucket_key_exact_boundary_bar_completes_current_minute():
    """The bar with ts an exact multiple of 60s is the TRUE last second of
    the minute ENDING at that ts (it covers `(ts-1s, ts]`) -- it must bucket
    with the 59 seconds BEFORE it, not the 59 seconds after."""
    minute0_bars = [1, 2, 3, 58, 59, 60]  # all true members of minute [0,60]
    keys = {minute_bucket_key(ts * NS) for ts in minute0_bars}
    assert keys == {0}

    minute1_bars = [61, 62, 119, 120]  # true members of minute (60,120]
    keys1 = {minute_bucket_key(ts * NS) for ts in minute1_bars}
    assert keys1 == {1}

    # ts=60 and ts=61 must NOT share a bucket (they are the last second of
    # minute 0 and the first second of minute 1, respectively).
    assert minute_bucket_key(60 * NS) != minute_bucket_key(61 * NS)


def test_minute_bucket_key_hand_computed_ohlc_reference():
    """Feed a hand-built sequence of 1s bars spanning an exact minute
    boundary through the same bucketing key attach_features.py uses, and
    verify the resulting 1-minute OHLC (computed by hand) matches what the
    bucketing would produce -- i.e. minute 0 = bars ts=1..60, NOT ts=0..59."""
    # bars: (ts_seconds, open, high, low, close)
    bars = [(0, 100.0, 100.0, 100.0, 100.0)]  # true last second of the PRIOR minute
    bars += [(t, 100.0 + t * 0.01, 100.5 + t * 0.01, 99.5 + t * 0.01, 100.2 + t * 0.01)
            for t in range(1, 61)]  # true minute-0 members, ts=1..60
    bars += [(61, 200.0, 200.0, 200.0, 200.0)]  # first second of the NEXT minute

    minute0 = [b for b in bars if minute_bucket_key(b[0] * NS) == 0]
    assert len(minute0) == 60  # ts=1..60, NOT including ts=0 or ts=61
    assert min(b[0] for b in minute0) == 1
    assert max(b[0] for b in minute0) == 60
    hand_open = minute0[0][1]  # open of ts=1
    hand_high = max(b[2] for b in minute0)
    hand_low = min(b[3] for b in minute0)
    hand_close = minute0[-1][4]  # close of ts=60
    assert hand_open == pytest.approx(100.01)
    assert hand_close == pytest.approx(100.8)
    # The bar at ts=0 (which a naive `bar_ts // 60s` bucketing would have
    # wrongly included) must not affect the computed OHLC.
    assert hand_open != 100.0


def _offline_style_regime_replay(bars_1s, regime_starts):
    """Minimal replica of attach_features.py's FIXED (post-CRIT-5) regime/RTH
    resolution: buffer each forming minute's bars and resolve/replay them
    only at minute completion, using that minute's own open as anchor --
    matching FeatureEngine's granularity exactly. `bars_1s` is a list of
    (ts_ns, open, high, low, close, volume), already sorted, spanning
    whole minutes with no gaps (test fixture, not raw data)."""
    tracker = OHLCVDeltaTracker()
    reg_idx = -1
    current_minute = None
    minute_o = None
    minute_buffer = []

    for ts_ns, o, h, l, c, v in bars_1s:
        b_est = tracker.update(ts_ns, o, h, l, c, v)
        minute_key = minute_bucket_key(ts_ns)
        if current_minute is None:
            current_minute = minute_key
            minute_o = o
            minute_buffer = [(ts_ns, h, l, v, b_est["bar_est_delta"])]
        elif minute_key != current_minute:
            m_close_ts = int((current_minute + 1) * 60 * NS)
            while reg_idx + 1 < len(regime_starts) and m_close_ts >= regime_starts[reg_idx + 1]:
                reg_idx += 1
                tracker.reset_regime(int(regime_starts[reg_idx]), float(minute_o))
            for buf_ts, buf_h, buf_l, buf_v, buf_d in minute_buffer:
                tracker.accumulate_regime_rth(buf_ts, buf_h, buf_l, buf_v, buf_d)
            current_minute = minute_key
            minute_o = o
            minute_buffer = [(ts_ns, h, l, v, b_est["bar_est_delta"])]
        else:
            minute_buffer.append((ts_ns, h, l, v, b_est["bar_est_delta"]))
    return tracker


def test_offline_and_live_regime_transition_attribution_match():
    """Cross-pipeline parity: feed the SAME synthetic bar sequence (two
    clean minutes of an established old regime, then a third minute that
    CONFIRMS a new regime at its own close) through both
    attach_features.py's offline replay style and FeatureEngine's live
    buffer-and-replay, and assert they agree exactly on regime_vol_sum and
    the anchor price at the checkpoint immediately after the transition.

    This is the specific regression the CRIT-5 fix targets: before the fix,
    offline attributed only the LAST second of the transitioning (3rd)
    minute to the new regime while live (already fixed for CRIT-2)
    attributed the whole confirming minute -- a silent disagreement between
    the two paths this project's registry contract requires to be a single
    source of truth. Old-regime minutes 0-1 exist so the test can prove the
    new regime's total does NOT carry over the old regime's accumulated
    1200 -- it must be exactly the confirming minute's own 600."""
    # ts0 must be exactly 1 second past a minute boundary, so bar i=0 starts
    # a fresh 60-bar minute bucket (minute_bucket_key(60K*NS) is the LAST
    # bar of minute K-1, not the first of minute K). All minute-close
    # timestamps are then derived from minute_bucket_key() itself (not
    # hand-computed offsets) so this test's own arithmetic cannot silently
    # drift from what the code under test actually does.
    base_s = 1_700_000_000
    ts0 = ((base_s // 60) * 60 + 1) * NS
    bucket_a = minute_bucket_key(ts0)

    def minute_close_ts(bucket_key: int) -> int:
        return (bucket_key + 1) * 60 * NS

    close_a, close_b, close_c = (minute_close_ts(bucket_a + k) for k in range(3))

    bars = []
    for i in range(120):  # minutes 0-1: established old regime, price ~100
        bars.append((ts0 + i * NS, 100.0, 101.0, 99.0, 100.5, 10.0))
    for i in range(120, 180):  # minute 2: CONFIRMS the new regime at its close
        bars.append((ts0 + i * NS, 105.0, 106.0, 104.0, 105.5, 10.0))
    bars.append((close_c + NS, 999.0, 999.0, 999.0, 999.0, 10.0))  # one bar into
    # minute 3, purely to trigger the offline replica's finalization of
    # minute 2 (it only replays a minute once the FOLLOWING minute's first
    # bar arrives) -- its own distinctive price/volume must NOT appear in
    # minute 2's regime_vol_sum below.

    # Old regime already active at ts0 (matches the pre-loop init path);
    # new regime confirmed by minute 2's own true close.
    regime_starts = np.array([ts0, close_c], dtype=np.int64)

    offline_tracker = _offline_style_regime_replay(bars, regime_starts)
    offline_result = offline_tracker.calculate(atr=2.0)

    engine = FeatureEngine(buffer_size_1s=200, buffer_size_1m=50)
    old_regime = MockRegime(regime_id=1, regime=1, has_breached=False, atr=2.0, short_ema=100, long_ema=99)
    new_regime = MockRegime(regime_id=2, regime=-1, has_breached=False, atr=2.0, short_ema=99, long_ema=100)
    for i in range(60):
        engine.update_1s(MockBar(100.0, 101.0, 99.0, 100.5, 10.0, ts0 + i * NS))
    # First-ever regime confirmation (id 0 -> 1) at minute 0's own close --
    # matches offline's pre-loop init of the already-active old regime.
    engine.update_1m(MockBar(100.0, 101.0, 99.0, 100.5, 600.0, close_a, ts_init=close_a), old_regime)
    for i in range(60, 120):
        engine.update_1s(MockBar(100.0, 101.0, 99.0, 100.5, 10.0, ts0 + i * NS))
    engine.update_1m(MockBar(100.0, 101.0, 99.0, 100.5, 600.0, close_b, ts_init=close_b), old_regime)
    for i in range(120, 180):
        engine.update_1s(MockBar(105.0, 106.0, 104.0, 105.5, 10.0, ts0 + i * NS))
    # The transition: id 1 -> 2, confirmed by minute 2's own bar (open=105).
    engine.update_1m(MockBar(105.0, 106.0, 104.0, 105.5, 600.0, close_c, ts_init=close_c), new_regime)
    live_result = engine._ohlcv_delta_tracker.calculate(atr=2.0)

    assert offline_result["regime_vol_sum"] == pytest.approx(600.0)
    assert live_result["regime_vol_sum"] == pytest.approx(600.0)
    assert offline_result["regime_vol_sum"] == pytest.approx(live_result["regime_vol_sum"])
    assert offline_tracker._regime_anchor_price == pytest.approx(105.0)
    assert offline_tracker._regime_anchor_price == pytest.approx(engine._ohlcv_delta_tracker._regime_anchor_price)
