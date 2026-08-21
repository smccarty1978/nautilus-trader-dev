from collections import deque

from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import CleanFlipCollector, NS


def _collector_with_pending(checkpoint: int) -> CleanFlipCollector:
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    collector._pending_labels = deque([{
        "row": {
            "checkpoint_decision_ns": checkpoint,
            "observation_ts": checkpoint,
            "regime_start_ns": checkpoint,
            "checkpoint_index": 0,
        },
        "target_observable": True,
    }])
    collector._flip_times_ns = deque()
    collector._last_seen_1m_init_ns = checkpoint
    collector.feature_rows = []
    collector.observations_log = []
    return collector


def test_target_horizon_includes_flip_at_t_plus_300_seconds_only_after_it_is_known():
    checkpoint = 1_700_000_000 * NS
    collector = _collector_with_pending(checkpoint)
    collector._flip_times_ns.append(checkpoint + 300 * NS)

    collector._resolve_pending_labels(checkpoint + 300 * NS)
    assert not collector.feature_rows

    collector._last_seen_1m_init_ns = checkpoint + 301 * NS
    collector._resolve_pending_labels(checkpoint + 300 * NS + NS)
    assert collector.feature_rows[0]["flip_within_300s"] == 1


def test_rejected_boundary_second_invalidates_pending_target_window():
    checkpoint = 1_700_000_000 * NS
    collector = _collector_with_pending(checkpoint)

    collector._invalidate_pending_horizons(checkpoint, checkpoint)
    collector._resolve_pending_labels(checkpoint + 301 * NS)
    assert not collector.feature_rows
