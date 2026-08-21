"""Targeted tests for CleanFlipCollector's generic candidates/observations output
interface (get_candidates_dataframe/get_observations_dataframe), added so this
collector satisfies backtests/nt_runtime/modes/collect.py's fail-closed output
verification and the shared reconcile_candidate_dispositions invariant: every
emitted candidate reaches exactly one terminal disposition.
"""
from collections import deque

from backtests.nt_runtime.output_manager import reconcile_candidate_dispositions
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import (
    NS, CENSOR_DATA_GAP, CENSOR_RUN_END, CleanFlipCollector, DISPOSITION_CENSORED,
    DISPOSITION_LABELED_NEGATIVE, DISPOSITION_LABELED_POSITIVE,
)


def _bare_collector() -> CleanFlipCollector:
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    collector._pending_labels = deque()
    collector._flip_times_ns = deque()
    collector.feature_rows = []
    collector.candidates_log = []
    collector.observations_log = []
    return collector


def _pending(checkpoint: int, index: int, target_observable: bool = True) -> dict:
    return {
        "row": {
            "checkpoint_decision_ns": checkpoint,
            "observation_ts": checkpoint,
            "regime_start_ns": checkpoint - 1000 * NS,
            "checkpoint_index": index,
        },
        "target_observable": target_observable,
    }


def test_labeled_positive_candidate_gets_matching_observation():
    checkpoint = 1_700_000_000 * NS
    collector = _bare_collector()
    collector._pending_labels.append(_pending(checkpoint, 0))
    collector._flip_times_ns.append(checkpoint + 50 * NS)
    collector._last_seen_1m_init_ns = checkpoint + 301 * NS

    collector._resolve_pending_labels(checkpoint + 300 * NS + NS)

    assert len(collector.observations_log) == 1
    obs = collector.observations_log[0]
    assert obs["disposition"] == DISPOSITION_LABELED_POSITIVE
    assert obs["flip_within_300s"] == 1
    assert obs["censor_reason"] is None
    assert (obs["observation_ts"], obs["regime_start_ns"], obs["checkpoint_index"]) == \
        (checkpoint, checkpoint - 1000 * NS, 0)


def test_labeled_negative_candidate_gets_matching_observation():
    checkpoint = 1_700_000_000 * NS
    collector = _bare_collector()
    collector._pending_labels.append(_pending(checkpoint, 0))
    collector._last_seen_1m_init_ns = checkpoint + 301 * NS  # no flip appended

    collector._resolve_pending_labels(checkpoint + 300 * NS + NS)

    assert len(collector.observations_log) == 1
    obs = collector.observations_log[0]
    assert obs["disposition"] == DISPOSITION_LABELED_NEGATIVE
    assert obs["flip_within_300s"] == 0


def test_data_gap_censored_candidate_is_not_silently_dropped():
    """A candidate whose horizon crosses an unavailable interval must still reach a
    terminal disposition -- it must not vanish from observations_log entirely."""
    checkpoint = 1_700_000_000 * NS
    collector = _bare_collector()
    collector._pending_labels.append(_pending(checkpoint, 0, target_observable=False))
    collector._last_seen_1m_init_ns = checkpoint + 301 * NS

    collector._resolve_pending_labels(checkpoint + 300 * NS + NS)

    assert not collector.feature_rows  # unchanged existing behavior: never labeled
    assert len(collector.observations_log) == 1
    obs = collector.observations_log[0]
    assert obs["disposition"] == DISPOSITION_CENSORED
    assert obs["censor_reason"] == CENSOR_DATA_GAP
    assert obs["flip_within_300s"] is None


def test_on_stop_censors_trailing_unresolved_candidates_at_run_end():
    checkpoint = 1_700_000_000 * NS
    collector = _bare_collector()
    collector._pending_labels.append(_pending(checkpoint, 0))
    collector._pending_labels.append(_pending(checkpoint + 5 * NS, 1))

    collector.on_stop()

    assert len(collector._pending_labels) == 0
    assert len(collector.observations_log) == 2
    assert all(obs["disposition"] == DISPOSITION_CENSORED for obs in collector.observations_log)
    assert all(obs["censor_reason"] == CENSOR_RUN_END for obs in collector.observations_log)


def test_candidates_and_observations_dataframes_reconcile_cleanly():
    """End-to-end proof against the real shared reconciliation check: a mixed batch of
    labeled, data-gap-censored, and run-end-censored candidates reconciles with zero
    undisposed/orphaned/duplicate findings."""
    collector = _bare_collector()
    base = 1_700_000_000 * NS

    # Candidate 0: labeled positive.
    collector._pending_labels.append(_pending(base, 0))
    collector._flip_times_ns.append(base + 50 * NS)
    collector._last_seen_1m_init_ns = base + 301 * NS
    collector._resolve_pending_labels(base + 300 * NS + NS)

    # Candidate 1: data-gap censored.
    collector._pending_labels.append(_pending(base + 10 * NS, 1, target_observable=False))
    collector._last_seen_1m_init_ns = base + 311 * NS
    collector._resolve_pending_labels(base + 310 * NS + NS)

    # Candidate 2: still pending when the run ends.
    collector._pending_labels.append(_pending(base + 20 * NS, 2))
    collector.on_stop()

    # candidates_log mirrors what _on_1s would have appended for each registered candidate.
    collector.candidates_log = [
        {"observation_ts": base, "regime_start_ns": base - 1000 * NS, "checkpoint_index": 0},
        {"observation_ts": base + 10 * NS, "regime_start_ns": (base + 10 * NS) - 1000 * NS, "checkpoint_index": 1},
        {"observation_ts": base + 20 * NS, "regime_start_ns": (base + 20 * NS) - 1000 * NS, "checkpoint_index": 2},
    ]

    candidates_df = collector.get_candidates_dataframe()
    observations_df = collector.get_observations_dataframe()

    assert len(candidates_df) == 3
    assert len(observations_df) == 3

    report = reconcile_candidate_dispositions(candidates_df, observations_df)
    assert report["passed"] is True, report["findings"]
    assert report["undisposed_candidates"] == 0
    assert report["orphaned_observations"] == 0
    assert report["duplicate_observations"] == 0
    assert report["disposition_counts"] == {
        DISPOSITION_LABELED_POSITIVE: 1,
        DISPOSITION_CENSORED: 2,
    }


def test_empty_collector_returns_empty_dataframes():
    collector = _bare_collector()
    assert collector.get_candidates_dataframe().empty
    assert collector.get_observations_dataframe().empty
