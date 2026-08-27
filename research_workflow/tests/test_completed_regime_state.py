from __future__ import annotations

import pytest

from research_workflow.completed_regime_state import CompletedRegimeStateFeed

NS = 1_000_000_000


def emit(feed, second, *, high=101.0, low=99.0, close=100.0):
    return feed.on_completed_1s_bar(
        ts_event=second * NS,
        ts_init=(second + 1) * NS,
        open=100.0,
        high=high,
        low=low,
        close=close,
        volume=1.0,
    )


def test_completed_5s_state_is_available_at_exact_close_not_before():
    feed = CompletedRegimeStateFeed(("5s",), atr_period=2)
    for second in range(4):
        assert emit(feed, second) == ()
        assert feed.state("5s", decision_ts=(second + 1) * NS) is None
    transitions = emit(feed, 4)
    assert len(transitions) == 1
    state = feed.state("5s", decision_ts=5 * NS)
    assert state is not None and state.open_ts == 0 and state.close_ts == 5 * NS
    assert transitions[0].available_ts == 5 * NS


def test_forming_5s_bucket_is_never_published():
    feed = CompletedRegimeStateFeed(("5s",))
    emit(feed, 0)
    assert feed.state("5s", decision_ts=NS) is None
    assert feed.aggregator.current_bucket("5s") is not None


def test_incomplete_bucket_is_rejected_instead_of_published():
    feed = CompletedRegimeStateFeed(("5s",))
    for second in (0, 1, 3, 4):
        emit(feed, second)
    emit(feed, 5)
    assert feed.state("5s", decision_ts=6 * NS) is None
    assert feed.consume_incomplete_close_ts("5s") == (5 * NS,)


def test_feed_rejects_forming_or_misstamped_1s_input():
    feed = CompletedRegimeStateFeed(("5s",))
    with pytest.raises(ValueError, match="ts_init"):
        feed.on_completed_1s_bar(
            ts_event=0, ts_init=0, open=1, high=1, low=1, close=1, volume=1
        )


def test_same_close_callbacks_are_macro_to_micro():
    feed = CompletedRegimeStateFeed(("1m", "5s"), atr_period=2)
    transitions = ()
    for second in range(60):
        transitions = emit(feed, second)
    assert [t.timeframe for t in transitions] == ["1m", "5s"]
