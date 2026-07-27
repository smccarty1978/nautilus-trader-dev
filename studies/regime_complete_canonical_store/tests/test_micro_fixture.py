"""Phase 1 micro fixture.

Drives the collector's regime/path/score bookkeeping directly with a synthetic
bar stream, so every branch is exercised deterministically and without market
data: both directions, established and never-established regimes, domain
transitions, multiple checkpoints, the opposing flip, and terminal censoring.

The frozen adapters and models are not loaded. What is under test here is the
collection contract -- what gets retained and how it is keyed -- not the model
arithmetic, which is covered by the Phase 2 byte-identity check against the
accepted artifact.
"""
from __future__ import annotations

import polars as pl
import pytest

from studies.regime_complete_canonical_store.implementation import writer
from studies.regime_complete_canonical_store.implementation.collector import (
    REGIME_END_CENSORED,
    REGIME_END_OPPOSING_FLIP,
    RegimeCompleteCollector,
)
from studies.regime_complete_canonical_store.implementation.identity import (
    regime_id as make_regime_id,
)

NS = 1_000_000_000
# 2025-03-03 08:30:00 America/Chicago (CST, UTC-6) == 14:30:00 UTC.
RTH_OPEN_NS = 1_741_012_200 * NS
INSTRUMENT = "NQ.XCME"


class _StubRegimeEngine:
    """Stands in for `RegimeEngine` so ATR reads resolve without market data."""

    atr = 10.0


class FakeCollector(RegimeCompleteCollector):
    """Collector with the frozen model stack replaced by a recorder.

    Only `__init__` is bypassed; every method under test is the real one.
    """

    def __init__(self):  # noqa: D107 - deliberately skips Strategy.__init__
        self.instrument_id = INSTRUMENT
        self._regime = _StubRegimeEngine()
        self._domain = None
        self.collector_version = "fixture"
        self.regime_engine_version = "fixture-engine"
        self.regimes, self.paths, self.rows, self.flips, self.missing = [], [], [], [], []
        self._open_regime = None
        self._regime_sequence = 0
        self._warmup_flips_skipped = 0
        self._last_score_ns = self._last_bull_p = self._last_bear_p = None
        self._last_close = None
        self._last_1s_event = None

    def emit_checkpoint(
        self, decision_ns: int, established: bool, atr: float = 10.0, direction: int = 1
    ):
        """Stand in for the inherited scoring half, then run the real augmentation.

        `*_in_domain` is seeded with the inherited predicate -- which has no
        session conjunct -- so the augmentation's session correction is exercised.
        """
        self.rows.append({
            "checkpoint_decision_ns": decision_ns,
            "established_regime_gate": established,
            "atr_at_checkpoint": atr,
            "bullish_probability": 0.4,
            "bearish_probability": 0.6,
            "bullish_in_domain": direction == 1 and established,
            "bearish_in_domain": direction == -1 and established,
        })
        self._augment_score_row(decision_ns)


def open_regime(collector: FakeCollector, start_ns: int, direction: int, atr=10.0):
    collector._open_new_regime(
        {"new_direction": direction, "atr_at_regime_start": atr},
        start_ns,
        start_ns - NS,
        anchor=20000.0,
    )


def feed_seconds(collector: FakeCollector, first_ns: int, count: int, atr=10.0):
    for i in range(count):
        ti = first_ns + i * NS
        collector._append_path_row(ti - NS, ti, 1.0, 2.0, 0.5, 1.5, 7.0, atr)


@pytest.fixture
def collector() -> FakeCollector:
    return FakeCollector()


# --------------------------------------------------------------- regimes


def test_regime_id_is_deterministic_and_order_independent():
    a = make_regime_id(INSTRUMENT, RTH_OPEN_NS, 1)
    b = make_regime_id(INSTRUMENT, RTH_OPEN_NS, 1)
    assert a == b and a.startswith("RGM_") and len(a) == 28
    assert make_regime_id(INSTRUMENT, RTH_OPEN_NS, -1) != a, "direction must matter"
    assert make_regime_id(INSTRUMENT, RTH_OPEN_NS + NS, 1) != a, "start must matter"


def test_regime_id_rejects_a_neutral_direction():
    with pytest.raises(ValueError):
        make_regime_id(INSTRUMENT, RTH_OPEN_NS, 0)


def test_both_directions_are_retained(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    collector._close_open_regime(
        RTH_OPEN_NS + 600 * NS, RTH_OPEN_NS + 599 * NS, 20010.0,
        REGIME_END_OPPOSING_FLIP,
    )
    open_regime(collector, RTH_OPEN_NS + 600 * NS, -1)
    collector._close_open_regime(
        RTH_OPEN_NS + 900 * NS, RTH_OPEN_NS + 899 * NS, 19990.0,
        REGIME_END_OPPOSING_FLIP,
    )
    assert [r["regime_direction"] for r in collector.regimes] == [1, -1]
    assert [r["regime_sequence_number"] for r in collector.regimes] == [1, 2]


def test_a_censored_regime_never_invents_terminal_values(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    feed_seconds(collector, RTH_OPEN_NS + NS, 10)
    collector.finalize()

    regime = collector.regimes[0]
    assert regime["regime_end_reason"] == REGIME_END_CENSORED
    for field in ("regime_end_decision_ns", "regime_end_event_ns", "regime_end_price"):
        assert regime[field] is None, f"{field} was invented for a censored regime"

    frame = writer.build_regimes(collector.regimes, "fixture")
    assert frame["path_is_complete"].to_list() == [False]
    assert frame["path_censor_reason"].to_list() == [REGIME_END_CENSORED]
    assert frame["duration_seconds"].to_list() == [None]


def test_a_regime_that_never_establishes_is_still_retained(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    for i in range(1, 4):
        collector.emit_checkpoint(RTH_OPEN_NS + i * 5 * NS, established=False)
    collector._close_open_regime(
        RTH_OPEN_NS + 20 * NS, RTH_OPEN_NS + 19 * NS, 20005.0, REGIME_END_OPPOSING_FLIP
    )
    regime = collector.regimes[0]
    assert regime["established_reached"] is False
    assert regime["regime_established_decision_ns"] is None
    assert regime["atr_at_established"] is None
    assert len(collector.rows) == 3, "checkpoints retained without establishment"


def test_established_onset_is_recorded_once_at_first_true(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    collector.emit_checkpoint(RTH_OPEN_NS + 5 * NS, established=False)
    collector.emit_checkpoint(RTH_OPEN_NS + 125 * NS, established=True, atr=11.0)
    collector.emit_checkpoint(RTH_OPEN_NS + 130 * NS, established=True, atr=12.0)

    regime = collector._open_regime
    assert regime["regime_established_decision_ns"] == RTH_OPEN_NS + 125 * NS
    assert regime["atr_at_established"] == 11.0, "onset must not be overwritten"
    assert regime["session_at_established"] == "RTH"
    assert [r["seconds_from_established"] for r in collector.rows] == [None, 0.0, 5.0]


# ----------------------------------------------------------------- scores


def test_score_rows_carry_exact_regime_linkage(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    for i in range(1, 4):
        collector.emit_checkpoint(RTH_OPEN_NS + i * 5 * NS, established=False)
    expected = make_regime_id(INSTRUMENT, RTH_OPEN_NS, 1)
    assert {r["regime_id"] for r in collector.rows} == {expected}
    assert [r["score_sequence_in_regime"] for r in collector.rows] == [0, 1, 2]
    assert [r["seconds_from_regime_start"] for r in collector.rows] == [5.0, 10.0, 15.0]


def test_score_observation_ids_are_unique(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    for i in range(1, 25):
        collector.emit_checkpoint(RTH_OPEN_NS + i * 5 * NS, established=False)
    ids = [r["score_observation_id"] for r in collector.rows]
    assert len(set(ids)) == len(ids)


def test_eth_checkpoints_are_retained_and_flagged(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS - 3600 * NS, 1)
    collector.emit_checkpoint(RTH_OPEN_NS - 3600 * NS, established=False)  # 07:30 CT
    collector.emit_checkpoint(RTH_OPEN_NS + 60 * NS, established=False)  # 08:31 CT

    eth, rth = collector.rows
    assert eth["session"] == "ETH"
    assert eth["session_contract_status"] == "OUT_OF_FROZEN_SESSION_CONTRACT"
    assert rth["session"] == "RTH"
    assert rth["session_contract_status"] == "IN_FROZEN_SESSION_CONTRACT"


def test_no_eth_row_can_ever_be_in_domain(collector: FakeCollector):
    """Negative test. Both frozen model contracts specify session
    [08:30,15:00) America/Chicago, so a mature ETH regime is still out of
    domain. The inherited predicate omits the session conjunct."""
    open_regime(collector, RTH_OPEN_NS - 7200 * NS, 1)
    collector.emit_checkpoint(
        RTH_OPEN_NS - 7200 * NS, established=True, direction=1
    )  # 06:30 CT, mature
    collector.emit_checkpoint(RTH_OPEN_NS + 600 * NS, established=True, direction=1)

    eth, rth = collector.rows
    assert eth["session"] == "ETH"
    assert eth["bullish_in_domain"] is False
    assert eth["bearish_in_domain"] is False
    assert eth["bullish_out_of_domain_reason"] == "OUT_OF_FROZEN_SESSION_CONTRACT"
    assert rth["session"] == "RTH"
    assert rth["bullish_in_domain"] is True, "RTH must be unaffected by the correction"
    assert rth["bullish_out_of_domain_reason"] is None


def test_established_eth_regimes_are_retained_despite_being_out_of_domain(
    collector: FakeCollector,
):
    """Out-of-domain must suppress eligibility, never retention."""
    open_regime(collector, RTH_OPEN_NS - 7200 * NS, 1)
    for i in range(5):
        collector.emit_checkpoint(
            RTH_OPEN_NS - 7200 * NS + i * 5 * NS, established=True
        )
    assert len(collector.rows) == 5
    assert collector._open_regime["established_reached"] is True
    assert all(r["bullish_probability"] is not None for r in collector.rows)


def test_every_score_row_is_a_true_scoring_event(collector: FakeCollector):
    """Carry-forward must never appear as a row in the score table."""
    open_regime(collector, RTH_OPEN_NS, 1)
    for i in range(1, 10):
        collector.emit_checkpoint(RTH_OPEN_NS + i * 5 * NS, established=False)
    assert all(r["bullish_score_is_new"] for r in collector.rows)
    assert all(r["bearish_score_is_new"] for r in collector.rows)
    decisions = [r["score_decision_ns"] for r in collector.rows]
    assert all(d % (5 * NS) == 0 for d in decisions), "off-grid dispatch"
    assert len(set(decisions)) == len(decisions)


def test_score_availability_never_precedes_its_decision(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    for i in range(1, 6):
        collector.emit_checkpoint(RTH_OPEN_NS + i * 5 * NS, established=False)
    for row in collector.rows:
        assert row["score_available_ns"] == row["score_decision_ns"]
        assert row["bullish_score_available_ns"] == row["score_decision_ns"]
        assert row["bearish_score_available_ns"] == row["score_decision_ns"]


# ------------------------------------------------------------------ paths


def test_path_capture_starts_at_the_regime_not_at_a_signal(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    feed_seconds(collector, RTH_OPEN_NS + NS, 300)
    regime = collector._open_regime
    assert regime["path_row_count"] == 300
    assert regime["path_start_ns"] == RTH_OPEN_NS + NS
    assert len(collector.rows) == 0, "paths must not require a score to exist"


def test_path_continues_past_the_first_qualifying_score(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    feed_seconds(collector, RTH_OPEN_NS + NS, 100)
    collector.emit_checkpoint(RTH_OPEN_NS + 50 * NS, established=True)
    feed_seconds(collector, RTH_OPEN_NS + 101 * NS, 200)
    after = [p for p in collector.paths if p[2] > RTH_OPEN_NS + 50 * NS]
    assert len(after) == 250, "a qualifying score must not terminate collection"


def test_no_open_regime_means_no_path_rows(collector: FakeCollector):
    feed_seconds(collector, RTH_OPEN_NS, 50)
    assert collector.paths == []


def test_path_expansion_is_dense_and_correctly_flagged(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    collector.emit_checkpoint(RTH_OPEN_NS + 125 * NS, established=True)
    feed_seconds(collector, RTH_OPEN_NS + NS, 600)
    end_ns = RTH_OPEN_NS + 600 * NS
    collector._close_open_regime(
        end_ns, end_ns - NS, 20010.0, REGIME_END_OPPOSING_FLIP
    )

    regimes = writer.build_regimes(collector.regimes, "fixture")
    paths = writer.build_paths(collector.paths, regimes, "fixture")

    assert paths.height == 600
    assert paths["path_sequence_in_regime"].to_list() == list(range(600))
    assert paths["is_regime_start_row"].sum() == 1
    assert paths["is_terminal_row"].sum() == 1
    assert paths["is_opposing_flip_row"].sum() == 1
    assert paths["is_established_row"].sum() == 1
    assert paths.filter(pl.col("is_opposing_flip_row"))["path_init_ns"].item() == end_ns
    assert paths["regime_id"].n_unique() == 1
    assert paths["seconds_from_regime_start"].to_list()[:3] == [1.0, 2.0, 3.0]
    established = paths.filter(pl.col("is_established_row"))
    assert established["seconds_from_established"].item() == 0.0


def test_path_table_contains_no_entry_dependent_columns(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    feed_seconds(collector, RTH_OPEN_NS + NS, 30)
    collector._close_open_regime(
        RTH_OPEN_NS + 30 * NS, RTH_OPEN_NS + 29 * NS, 1.0, REGIME_END_OPPOSING_FLIP
    )
    regimes = writer.build_regimes(collector.regimes, "fixture")
    columns = set(writer.build_paths(collector.paths, regimes, "fixture").columns)
    forbidden = {
        "mfe_from_entry", "mae_from_entry", "trade_return", "stop_hit",
        "target_hit", "entry_price", "trade_id", "fallback_exit_mark_return_atr",
    }
    assert not (columns & forbidden), f"entry-dependent columns present: {columns & forbidden}"


def test_carried_forward_scores_are_visible_with_their_age(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    collector.emit_checkpoint(RTH_OPEN_NS + 5 * NS, established=False)
    feed_seconds(collector, RTH_OPEN_NS + 6 * NS, 4)
    collector._close_open_regime(
        RTH_OPEN_NS + 9 * NS, RTH_OPEN_NS + 8 * NS, 1.0, REGIME_END_OPPOSING_FLIP
    )
    regimes = writer.build_regimes(collector.regimes, "fixture")
    paths = writer.build_paths(collector.paths, regimes, "fixture")
    assert paths["score_age_seconds"].to_list() == [1.0, 2.0, 3.0, 4.0]
    assert paths["is_carried_forward"].all()
    assert paths["last_score_decision_ns"].unique().to_list() == [RTH_OPEN_NS + 5 * NS]


def test_path_rows_before_any_score_carry_no_score(collector: FakeCollector):
    open_regime(collector, RTH_OPEN_NS, 1)
    feed_seconds(collector, RTH_OPEN_NS + NS, 3)
    assert all(p[11] is None for p in collector.paths)


# -------------------------------------------------------------- lifecycle


def test_warmup_flips_are_counted_not_silently_dropped(collector: FakeCollector):
    collector._domain = None
    assert collector._warmup_flips_skipped == 0


def test_sequence_numbers_are_dense_across_many_regimes(collector: FakeCollector):
    for i in range(20):
        start = RTH_OPEN_NS + i * 300 * NS
        open_regime(collector, start, 1 if i % 2 == 0 else -1)
        feed_seconds(collector, start + NS, 299)
        collector._close_open_regime(
            start + 300 * NS, start + 299 * NS, 1.0, REGIME_END_OPPOSING_FLIP
        )
    numbers = [r["regime_sequence_number"] for r in collector.regimes]
    assert numbers == list(range(1, 21))
    directions = [r["regime_direction"] for r in collector.regimes]
    assert all(a != b for a, b in zip(directions, directions[1:])), "must alternate"

    regimes = writer.build_regimes(collector.regimes, "fixture")
    paths = writer.build_paths(collector.paths, regimes, "fixture")
    assert paths["regime_id"].n_unique() == 20
    assert paths.group_by("regime_id").len()["len"].unique().to_list() == [299]
