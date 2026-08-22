"""Targeted tests for CleanFlipCollector's generic candidates/observations output
interface (get_candidates_dataframe/get_observations_dataframe), added so this
collector satisfies backtests/nt_runtime/modes/collect.py's fail-closed output
verification and the shared reconcile_candidate_dispositions invariant: every
emitted candidate reaches exactly one terminal disposition.
"""
from collections import deque

from backtests.nt_runtime.output_manager import reconcile_candidate_dispositions
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation import collector as collector_module
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import (
    NS, CENSOR_RUN_END, CleanFlipCollector, CleanFlipCollectorConfig,
    DISPOSITION_CENSORED, DISPOSITION_LABELED_NEGATIVE, DISPOSITION_LABELED_POSITIVE,
)


def _bare_collector() -> CleanFlipCollector:
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    # D2.3: get_candidates_dataframe() now reads its metadata column list from
    # self._metadata_columns (the single canonical authority, sourced from
    # CleanFlipCollectorConfig.metadata_columns) rather than a hardcoded literal.
    collector._metadata_columns = CleanFlipCollectorConfig().metadata_columns
    collector._pending_labels = deque()
    collector._flip_times_ns = deque()
    collector.feature_rows = []
    collector.candidates_log = []
    collector.observations_log = []
    return collector


def _pending(checkpoint: int, index: int) -> dict:
    return {
        "row": {
            "checkpoint_decision_ns": checkpoint,
            "observation_ts": checkpoint,
            "regime_start_ns": checkpoint - 1000 * NS,
            "checkpoint_index": index,
        },
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


def test_data_gap_disposition_removed_from_declared_contract():
    """CENSOR_DATA_GAP was removed as a stale, production-unreachable contract member
    (see research_decision.yaml): its only setter, _invalidate_pending_horizons, had no
    production caller -- unexpected 1s/1m gaps during expected trading time hard-fail
    the run instead of censoring a candidate. It must not be reintroduced as an
    importable symbol, and _invalidate_pending_horizons must not exist to be rewired."""
    assert not hasattr(collector_module, "CENSOR_DATA_GAP")
    assert not hasattr(CleanFlipCollector, "_invalidate_pending_horizons")


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
    labeled-positive, labeled-negative, and run-end-censored candidates reconciles with
    zero undisposed/orphaned/duplicate findings."""
    collector = _bare_collector()
    base = 1_700_000_000 * NS

    # Candidate 0: labeled positive.
    collector._pending_labels.append(_pending(base, 0))
    collector._flip_times_ns.append(base + 50 * NS)
    collector._last_seen_1m_init_ns = base + 301 * NS
    collector._resolve_pending_labels(base + 300 * NS + NS)

    # Candidate 1: labeled negative -- checkpoint chosen so its (T, T+300s] horizon does
    # not overlap the flip already consumed by candidate 0 above (flip_times_ns is only
    # trimmed relative to the *next* pending checkpoint, so an in-range choice here would
    # spuriously re-match that same historical flip).
    collector._pending_labels.append(_pending(base + 400 * NS, 1))
    collector._last_seen_1m_init_ns = base + 701 * NS
    collector._resolve_pending_labels(base + 700 * NS + NS)

    # Candidate 2: still pending when the run ends.
    collector._pending_labels.append(_pending(base + 20 * NS, 2))
    collector.on_stop()

    # candidates_log mirrors what _on_1s would have appended for each registered candidate.
    collector.candidates_log = [
        {"observation_ts": base, "regime_start_ns": base - 1000 * NS, "checkpoint_index": 0},
        {"observation_ts": base + 400 * NS, "regime_start_ns": (base + 400 * NS) - 1000 * NS, "checkpoint_index": 1},
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
        DISPOSITION_LABELED_NEGATIVE: 1,
        DISPOSITION_CENSORED: 1,
    }


def test_empty_collector_returns_empty_dataframes():
    collector = _bare_collector()
    assert collector.get_candidates_dataframe().empty
    assert collector.get_observations_dataframe().empty
