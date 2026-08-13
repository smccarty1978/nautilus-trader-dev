"""Deterministic tests for the walk primitive, on synthetic bars.

Synthetic rather than sampled: the properties under test (tie resolution,
overnight containment, censored-vs-uncensored divergence) are exactly the ones
that occur rarely in real data and therefore hide from spot checks.
"""
from __future__ import annotations

import numpy as np
import pytest

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    MarketData,
    RegimeIndex,
)
from studies.armed_fade_score_path_progression.implementation.walks import (
    CONFIRMED,
    SESSION_CLOSE_UNRESOLVED,
    STOPPED_BEFORE_CONFIRM,
    measure_to_confirm,
)

NS = 1_000_000_000
DAY = 24 * 3600 * NS


def make_market(highs, lows, start_ns=0, session_close_ns=None, opens=None, closes=None):
    n = len(highs)
    ts = np.arange(n, dtype=np.int64) * NS + start_ns
    close = np.asarray(closes if closes is not None else lows, dtype=float)
    open_ = np.asarray(opens if opens is not None else highs, dtype=float)
    day_close = np.full(n, session_close_ns if session_close_ns is not None
                        else ts[-1], dtype=np.int64)
    return MarketData(
        ts=ts, open_=open_, high=np.asarray(highs, dtype=float),
        low=np.asarray(lows, dtype=float), close=close, day_close_ns=day_close,
    )


def make_regimes(pairs):
    return RegimeIndex(
        start_ns=np.asarray([p[0] for p in pairs], dtype=np.int64),
        direction=np.asarray([p[1] for p in pairs], dtype=np.int64),
    )


def test_confirm_before_stop_is_confirmed_in_both_populations():
    # Short fade at 100. Price drifts down, so adverse excursion stays tiny.
    market = make_market(highs=[100.2] * 6, lows=[99.0] * 6)
    regimes = make_regimes([(3 * NS, -1)])
    r = measure_to_confirm(market, regimes, 0, -1, 100.0, 1.0)

    assert r["terminal_label"] == CONFIRMED
    assert r["confirm_reached_uncensored"] and r["confirm_reached_censored"]
    assert not r["stop_before_confirm"]
    assert r["mae_to_confirm_atr"] == pytest.approx(0.2)


def test_stop_before_confirm_splits_the_two_populations():
    # Adverse excursion reaches 1 ATR at bar 1; the flip only arrives at bar 4.
    # Uncensored still records the MAE-to-confirm; censored does not.
    market = make_market(highs=[100.2, 101.5, 101.5, 101.5, 101.5], lows=[99.0] * 5)
    regimes = make_regimes([(4 * NS, -1)])
    r = measure_to_confirm(market, regimes, 0, -1, 100.0, 1.0)

    assert r["terminal_label"] == STOPPED_BEFORE_CONFIRM
    assert r["stop_before_confirm"]
    assert r["confirm_reached_uncensored"] is True
    assert r["confirm_reached_censored"] is False
    # The honest stop-room number exceeds the stop that would have killed it.
    assert r["mae_to_confirm_atr"] == pytest.approx(1.5)


def test_same_bar_stop_and_confirm_resolves_adversely_and_flags_ambiguous():
    market = make_market(highs=[100.2, 101.5, 101.5], lows=[99.0] * 3)
    regimes = make_regimes([(1 * NS, -1)])
    r = measure_to_confirm(market, regimes, 0, -1, 100.0, 1.0)

    assert r["ambiguous"] is True
    assert r["terminal_label"] == STOPPED_BEFORE_CONFIRM
    assert r["confirm_reached_censored"] is False
    assert r["confirm_reached_censored_optimistic"] is True


def test_window_never_traverses_the_overnight_gap():
    # Two RTH sessions stitched together; index i+1 after the last bar of day 1
    # is day 2's first bar. A confirming flip on day 2 must not be reachable.
    ts = np.array([0, NS, 2 * NS, DAY, DAY + NS], dtype=np.int64)
    day_close = np.array([2 * NS, 2 * NS, 2 * NS, DAY + NS, DAY + NS], dtype=np.int64)
    market = MarketData(
        ts=ts,
        open_=np.array([100.0, 100.0, 100.0, 80.0, 80.0]),
        high=np.array([100.2, 100.2, 100.2, 80.0, 80.0]),
        low=np.array([99.9, 99.9, 99.9, 80.0, 80.0]),
        close=np.array([100.0, 100.0, 100.0, 80.0, 80.0]),
        day_close_ns=day_close,
    )
    regimes = make_regimes([(DAY, -1)])
    r = measure_to_confirm(market, regimes, 0, -1, 100.0, 1.0)

    assert r["terminal_label"] == SESSION_CLOSE_UNRESOLVED
    assert r["confirm_reached_uncensored"] is False
    # Day 1 alone offers 0.1 points of favorable excursion. The 20-point
    # overnight gain from the 100 -> 80 gap must not appear anywhere.
    assert r["mfe_at_terminal_atr"] == pytest.approx(0.1)
    assert r["gross_atr"] == pytest.approx(0.0)
    assert r["terminal_ns"] <= 2 * NS


def test_stop_fills_at_the_following_bar_open_not_the_trigger():
    market = make_market(
        highs=[100.2, 101.5, 101.5],
        lows=[99.9, 99.9, 99.9],
        opens=[100.0, 101.0, 102.0],
        closes=[100.0, 101.0, 102.0],
    )
    regimes = make_regimes([(9 * NS, -1)])
    r = measure_to_confirm(market, regimes, 0, -1, 100.0, 1.0)

    assert r["terminal_label"] == STOPPED_BEFORE_CONFIRM
    # Trigger on bar 1 (index 1 of the slice starting at bar 1 -> market idx 2),
    # so the fill is market bar 2's open of 102.0, never the 101.5 trigger.
    assert r["gross_atr"] == pytest.approx(-2.0)


def test_confirming_flip_stamped_at_the_entry_second_is_in_the_future():
    # The inclusive resolver is mandatory: a flip stamped at T is knowable only
    # after a decision made at T, under the 1s-before-1m dispatch convention.
    market = make_market(highs=[100.2] * 4, lows=[99.0] * 4)
    regimes = make_regimes([(0, -1), (2 * NS, -1)])
    r = measure_to_confirm(market, regimes, 0, -1, 100.0, 1.0)

    assert r["confirm_ns"] == 0
    # The window still opens at the first bar strictly after the decision.
    assert r["terminal_label"] == CONFIRMED


def test_invalid_atr_is_censored_not_silently_zero():
    market = make_market(highs=[100.2] * 3, lows=[99.0] * 3)
    regimes = make_regimes([(1 * NS, -1)])
    for atr in (0.0, -1.0, float("nan")):
        r = measure_to_confirm(market, regimes, 0, -1, 100.0, atr)
        assert r["valid"] is False
