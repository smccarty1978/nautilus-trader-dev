"""Negative tests for SPEC 10.2 properties that were previously argued from
architecture rather than exercised.

"The collector has no exit concept, so an exit cannot truncate a path" is a
design claim, not evidence. Each test here drives the behavior and would fail if
the property were violated, so a future refactor that introduces a policy
predicate breaks a test rather than silently shrinking the store.
"""
from __future__ import annotations

import polars as pl
import pytest

from studies.regime_complete_canonical_store.implementation import writer
from studies.regime_complete_canonical_store.implementation.collector import (
    REGIME_END_OPPOSING_FLIP,
)

from .test_micro_fixture import (
    INSTRUMENT,
    NS,
    RTH_OPEN_NS,
    FakeCollector,
    feed_seconds,
    open_regime,
)

# A long candidate anchored at 20000 with ATR 10, stopped 1.0 ATR below.
ANCHOR = 20000.0
HYPOTHETICAL_STOP_PRICE = ANCHOR - 10.0


@pytest.fixture
def collector() -> FakeCollector:
    return FakeCollector()


def feed_priced_seconds(
    collector: FakeCollector, first_ns: int, count: int, low: float, high: float
) -> None:
    """Feed 1s bars at a realistic price level.

    `feed_seconds` in the shared fixture emits toy single-digit prices, which
    would sit below any stop expressed in index points.
    """
    for i in range(count):
        ti = first_ns + i * NS
        mid = (low + high) / 2
        collector._append_path_row(ti - NS, ti, mid, high, low, mid, 7.0, 10.0)


def test_a_hypothetical_stop_cannot_terminate_the_regime_path(
    collector: FakeCollector,
):
    """SPEC 10.2: a selected-trade exit cannot terminate a regime path.

    Simulates a long candidate whose stop is breached mid-regime, then asserts
    the path continues to the regime's own terminal boundary. Re-entry research
    depends on those later rows existing.
    """
    open_regime(collector, RTH_OPEN_NS, 1)
    collector.emit_checkpoint(RTH_OPEN_NS + 125 * NS, established=True)

    # 200s comfortably above the stop, then one bar that breaches it, then 400s
    # after the breach.
    feed_priced_seconds(
        collector, RTH_OPEN_NS + NS, 200, low=ANCHOR + 1.0, high=ANCHOR + 6.0
    )
    stop_ns = RTH_OPEN_NS + 201 * NS
    collector._append_path_row(
        stop_ns - NS, stop_ns, ANCHOR, ANCHOR,
        HYPOTHETICAL_STOP_PRICE - 5.0, HYPOTHETICAL_STOP_PRICE - 5.0, 7.0, 10.0,
    )
    feed_priced_seconds(
        collector, stop_ns + NS, 400, low=ANCHOR + 1.0, high=ANCHOR + 6.0
    )

    end_ns = RTH_OPEN_NS + 601 * NS
    collector._close_open_regime(
        end_ns, end_ns - NS, 20010.0, REGIME_END_OPPOSING_FLIP
    )

    regimes = writer.build_regimes(collector.regimes, "fixture")
    paths = writer.build_paths(collector.paths, regimes, "fixture")

    breached = paths.filter(pl.col("low") <= HYPOTHETICAL_STOP_PRICE)
    assert breached.height >= 1, "fixture must actually breach the stop"

    first_breach_ns = breached["path_init_ns"].min()
    after = paths.filter(pl.col("path_init_ns") > first_breach_ns)
    assert after.height == 400, (
        "path must continue past a hypothetical stop; "
        f"only {after.height} rows survived"
    )
    assert paths["path_init_ns"].max() == end_ns, (
        "path must reach the regime terminal boundary, not the stop"
    )
    assert paths.filter(pl.col("is_terminal_row"))["path_init_ns"].item() == end_ns


def test_a_regime_whose_scores_never_qualify_is_still_retained(
    collector: FakeCollector,
):
    """SPEC 10.2: a Top-2.5% filter cannot remove low-score regimes.

    Every checkpoint scores far below any frozen threshold. The regime, its
    score rows, and its full path must all still be present.
    """
    lowest_frozen_threshold = 0.34374423771129053  # bullish Top-20%
    open_regime(collector, RTH_OPEN_NS, 1)
    for i in range(1, 13):
        collector.emit_checkpoint(RTH_OPEN_NS + i * 5 * NS, established=True)
        collector.rows[-1]["bullish_probability"] = 0.01
        collector.rows[-1]["bearish_probability"] = 0.02
    feed_seconds(collector, RTH_OPEN_NS + NS, 120)
    end_ns = RTH_OPEN_NS + 121 * NS
    collector._close_open_regime(
        end_ns, end_ns - NS, 20001.0, REGIME_END_OPPOSING_FLIP
    )

    assert all(
        r["bullish_probability"] < lowest_frozen_threshold for r in collector.rows
    ), "fixture must sit below every frozen threshold"

    regimes = writer.build_regimes(collector.regimes, "fixture")
    assert regimes.height == 1, "an all-low-score regime was dropped"
    assert len(collector.rows) == 12, "low-score checkpoints were dropped"

    paths = writer.build_paths(collector.paths, regimes, "fixture")
    assert paths.height == 120, "an all-low-score regime lost its path"


def test_a_later_bar_cannot_alter_an_earlier_score_row(collector: FakeCollector):
    """SPEC 10.2: a future bar cannot alter a prior score row.

    Snapshots every emitted score row, feeds 300 further seconds and two later
    checkpoints, then asserts the earlier rows are byte-identical. Catches any
    retro-fill that back-writes a resolved value onto a prior observation.
    """
    import copy

    open_regime(collector, RTH_OPEN_NS, 1)
    for i in range(1, 6):
        collector.emit_checkpoint(RTH_OPEN_NS + i * 5 * NS, established=False)
    feed_seconds(collector, RTH_OPEN_NS + NS, 30)

    snapshot = copy.deepcopy(collector.rows)
    assert len(snapshot) == 5

    feed_seconds(collector, RTH_OPEN_NS + 31 * NS, 300)
    collector.emit_checkpoint(RTH_OPEN_NS + 335 * NS, established=True)
    collector.emit_checkpoint(RTH_OPEN_NS + 340 * NS, established=True)

    for index, (before, after) in enumerate(zip(snapshot, collector.rows)):
        assert before == after, (
            f"score row {index} at {before['score_decision_ns']} was mutated "
            f"by later bars"
        )
    assert len(collector.rows) == 7, "later checkpoints must append, not replace"


def test_establishment_does_not_backfill_earlier_score_rows(
    collector: FakeCollector,
):
    """A regime establishing later must not retroactively mark earlier
    checkpoints as established -- that would leak future state into a past row."""
    open_regime(collector, RTH_OPEN_NS, 1)
    collector.emit_checkpoint(RTH_OPEN_NS + 5 * NS, established=False)
    collector.emit_checkpoint(RTH_OPEN_NS + 10 * NS, established=False)
    early = [dict(r) for r in collector.rows]

    collector.emit_checkpoint(RTH_OPEN_NS + 125 * NS, established=True)

    for before, after in zip(early, collector.rows):
        assert after["seconds_from_established"] is None, (
            "an earlier checkpoint gained an establishment offset after the fact"
        )
        assert before == after
    assert collector.rows[-1]["seconds_from_established"] == 0.0


def test_path_rows_never_carry_a_score_from_the_future(collector: FakeCollector):
    """Carried-forward score fields must reference a past checkpoint only."""
    open_regime(collector, RTH_OPEN_NS, 1)
    collector.emit_checkpoint(RTH_OPEN_NS + 5 * NS, established=False)
    feed_seconds(collector, RTH_OPEN_NS + 6 * NS, 10)
    collector.emit_checkpoint(RTH_OPEN_NS + 20 * NS, established=False)
    feed_seconds(collector, RTH_OPEN_NS + 21 * NS, 10)
    end_ns = RTH_OPEN_NS + 31 * NS
    collector._close_open_regime(
        end_ns, end_ns - NS, 20001.0, REGIME_END_OPPOSING_FLIP
    )

    regimes = writer.build_regimes(collector.regimes, "fixture")
    paths = writer.build_paths(collector.paths, regimes, "fixture")

    future = paths.filter(
        pl.col("last_score_decision_ns") > pl.col("path_init_ns")
    )
    assert future.height == 0, "a path row referenced a future score checkpoint"
    assert (paths["score_age_seconds"] >= 0).all()
